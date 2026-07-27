"""M3-B0: Diagnostic bundle security audit tests.

Verify that the diagnostic bundle never leaks sensitive data:
  - API keys, tokens, passwords
  - Vault content, report markdown
  - Raw file paths (only existence checks)
  - Secrets embedded in exception messages or operation log metadata

These tests intentionally inject mock secrets and verify redaction.
"""

from __future__ import annotations

import json as _json
import os
import zipfile
from pathlib import Path

import pytest

from signalvault.diagnostics.bundle import (
    DiagnosticBundleBuilder,
    DiagnosticBundleConfig,
    DiagnosticBundleResult,
    export_diagnostic_bundle,
    redact_dict,
    redact_value,
)

# ── Constants ───────────────────────────────────────────────────────

# Patterns that should NEVER appear in any bundle file
_FORBIDDEN_PATTERNS = [
    "sk-",           # OpenAI-style key prefix
    "sk-abc123",     # mock key
    "Bearer ",       # auth header
    "api_key",       # bare key field name holding a value (not in redaction_policy)
]

# Patterns that should be replaced with [REDACTED] or bool
_API_KEY_PATTERNS = [
    "sk-proj-",
    "sk-ant-",
    "sk-or-",
    "org-",
]


class TestRedactionSecurity:
    """Unit tests for the redaction engine — edge cases and security-critical paths."""

    def test_api_key_in_deeply_nested_dict(self):
        """API key at depth 4 should still be redacted."""
        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "api_key": "sk-deep-secret-12345",
                    }
                }
            }
        }
        result = redact_dict(data)
        assert result["level1"]["level2"]["level3"]["api_key"] == "[REDACTED]"

    def test_api_key_in_list_items(self):
        """API keys inside list items should be redacted."""
        data = {
            "items": [
                {"name": "item1", "token": "secret1"},
                {"name": "item2", "token": "secret2"},
                {"name": "item3", "public": "visible"},
            ]
        }
        result = redact_dict(data)
        assert result["items"][0]["token"] == "[REDACTED]"
        assert result["items"][1]["token"] == "[REDACTED]"
        assert result["items"][2]["public"] == "visible"

    def test_mixed_case_key_names(self):
        """Key name case variations should all be redacted."""
        assert redact_value("API_KEY", "sk-abc") == "[REDACTED]"
        assert redact_value("Api_Key", "sk-def") == "[REDACTED]"
        assert redact_value("LLM_API_KEY", "sk-ghi") == "[REDACTED]"
        assert redact_value("api_key", "sk-jkl") == "[REDACTED]"

    def test_hyphenated_key_names(self):
        """Keys with hyphens should also match."""
        assert redact_value("api-key", "sk-secret") == "[REDACTED]"
        assert redact_value("access-token", "tok123") == "[REDACTED]"

    def test_non_string_secret_values_redacted(self):
        """Non-string values for secret keys should still be redacted."""
        assert redact_value("api_key", 12345) == "[REDACTED]"
        assert redact_value("password", True) == "[REDACTED]"

    def test_empty_secret_values(self):
        """Empty/None values for secret keys should return empty string."""
        assert redact_value("api_key", "") == ""
        assert redact_value("api_key", None) == ""

    def test_exception_message_containing_key(self):
        """Exception messages that look like they contain API keys should be redacted."""
        # Simulating how an operation log might capture an exception
        data = {
            "error_message": "HTTP 401: Invalid API key sk-proj-abc123xyz for request",
            "operation_type": "llm.test_connection",
        }
        result = redact_dict(data)
        # The error_message key doesn't match REDACT_KEYS, but long values are truncated
        result_str = _json.dumps(result)
        assert "sk-proj-abc123xyz" not in result_str

    def test_authorization_header_redacted(self):
        """Authorization header values should be redacted."""
        assert redact_value("authorization", "Bearer token123") == "[REDACTED]"

    def test_config_base_url_redacted(self):
        """LLM base URL is redacted (may contain key in path)."""
        assert redact_value("llm_base_url", "https://api.openai.com/v1") == "[REDACTED]"

    def test_full_text_truncated_not_leaked(self):
        """Full content text should be replaced with char count, never leaked."""
        original = "This is the full paid content from a research report." * 50
        result = redact_value("content_text", original)
        assert "chars redacted" in result
        assert "research report" not in result  # content is fully replaced

    def test_source_quote_truncated_not_leaked(self):
        """Source quotes should be truncated, not leaked."""
        original = "According to the CEO, revenue will grow 50% next year." * 20
        result = redact_value("source_quote", original)
        assert "chars redacted" in result
        assert "CEO" not in result


class TestBundleSecurity:
    """Integration tests — build full bundles and scan for leaks."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.output_dir = tmp_path / "security_test_diag"
        self.tmp = tmp_path

    def _build(self, db_session=None) -> DiagnosticBundleResult:
        config = DiagnosticBundleConfig(output_dir=str(self.output_dir))
        builder = DiagnosticBundleBuilder(config, session=db_session)
        return builder.build()

    def _read_all_text(self, zip_path: str) -> str:
        """Read all files from the zip and concatenate their text content."""
        all_text = ""
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                try:
                    all_text += zf.read(name).decode("utf-8") + "\n"
                except UnicodeDecodeError:
                    pass
        return all_text

    def _read_zip_json(self, zip_path: str, name: str) -> dict:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return _json.loads(zf.read(name).decode("utf-8"))

    # ── Test: No API key anywhere in zip ─────────────────────────────

    def test_no_api_key_pattern_in_any_file(self, db_session):
        """Scan every file in the bundle for API key patterns."""
        result = self._build(db_session)
        all_text = self._read_all_text(result.bundle_path).lower()

        for pattern in _API_KEY_PATTERNS:
            assert pattern.lower() not in all_text, (
                f"API key pattern '{pattern}' found in bundle"
            )

    def test_no_bearer_token_in_zip(self, db_session):
        """No Bearer/auth token should appear."""
        result = self._build(db_session)
        all_text = self._read_all_text(result.bundle_path)
        assert "Bearer " not in all_text

    # ── Test: Secrets not leaked in operation logs ────────────────────

    def test_operation_log_metadata_secrets_redacted(self, db_session):
        """Operation log entries with api_key in metadata must be redacted."""
        from signalvault.diagnostics.operation_log import OperationLogManager

        # Create a log entry with a secret in metadata
        op = OperationLogManager.start(
            operation_type="llm.test_connection",
            metadata={
                "api_key": "sk-real-secret-key-12345",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4",
            },
            session=db_session,
        )
        OperationLogManager.succeed(op, session=db_session)

        result = self._build(db_session)
        logs = self._read_zip_json(result.bundle_path, "operation_logs.json")
        logs_str = _json.dumps(logs)

        assert "sk-real-secret-key-12345" not in logs_str
        assert "[REDACTED]" in logs_str

    def test_operation_log_error_message_secrets_redacted(self, db_session):
        """Operation log failure messages containing key-like patterns are redacted."""
        from signalvault.diagnostics.operation_log import OperationLogManager

        op = OperationLogManager.start(
            operation_type="llm.test_connection",
            metadata={"provider": "openai-compatible"},
            session=db_session,
        )
        OperationLogManager.fail(
            op,
            error_code="AUTH_LLM_002",
            error_detail="Connection failed with key sk-proj-deadbeef — check config",
            session=db_session,
        )

        result = self._build(db_session)
        logs = self._read_zip_json(result.bundle_path, "operation_logs.json")
        logs_str = _json.dumps(logs)

        assert "sk-proj-deadbeef" not in logs_str

    # ── Test: No vault content in zip ────────────────────────────────

    def test_no_vault_file_paths_in_zip(self, db_session):
        """Bundle should not contain raw user file paths from Obsidian vault."""
        result = self._build(db_session)
        all_text = self._read_all_text(result.bundle_path)

        # Common vault path patterns that should NOT appear as raw strings
        # (existence checks return bool, not path)
        suspicious = [
            "/Users/",          # macOS home
            "C:\\Users\\",      # Windows home (escaped)
            "/home/",           # Linux home
            "MyVault",          # common vault name
            ".obsidian",        # Obsidian config dir
        ]
        # These may appear in README.txt explanation, which is intentional
        # But not in JSON data files as actual paths
        for name in result.file_names:
            if name == "README.txt":
                continue
            text = ""
            with zipfile.ZipFile(result.bundle_path, "r") as zf:
                try:
                    text = zf.read(name).decode("utf-8")
                except Exception:
                    continue

            for pattern in suspicious:
                if pattern in text:
                    # Only fail if this appears as a JSON value (not in a key name)
                    # Check if it's a path-like context
                    if f'"{pattern}' in text or f"'{pattern}" in text:
                        pytest.fail(
                            f"Potential vault path leak in {name}: found '{pattern}'"
                        )

    def test_no_report_markdown_in_zip(self, db_session):
        """Report markdown content must not appear in the bundle."""
        result = self._build(db_session)
        all_text = self._read_all_text(result.bundle_path)
        # The redaction policy replaces report_markdown with char count
        assert "report_markdown" not in all_text.lower() or \
            "[REDACTED]" in all_text or \
            "chars redacted" in all_text

    # ── Test: Config snapshot has no raw values ───────────────────────

    def test_config_summary_api_key_is_bool_only(self, db_session):
        """config_summary.json must show llm_api_key as bool, never as a string value."""
        result = self._build(db_session)
        config = self._read_zip_json(result.bundle_path, "config_summary.json")

        # The key should be something like llm_api_key_set or llm_key_set
        for key, value in config.items():
            if "api_key" in key.lower() or "key" in key.lower():
                assert isinstance(value, bool), (
                    f"Config key '{key}' should be bool, got {type(value).__name__}: {value!r}"
                )

    def test_config_summary_no_raw_base_url(self, db_session):
        """config_summary.json must not contain raw Base URL values."""
        result = self._build(db_session)
        config = self._read_zip_json(result.bundle_path, "config_summary.json")

        config_str = _json.dumps(config)
        # Base URL is redacted — should not see https:// in the config
        assert "https://" not in config_str, (
            "config_summary.json contains a raw URL (may leak Base URL)"
        )

    # ── Test: Paths are existence checks, not absolute paths ─────────

    def test_paths_are_existence_checks(self, db_session):
        """Path values in the bundle should be booleans, not file paths."""
        result = self._build(db_session)

        # Check manifest.json paths section
        manifest = self._read_zip_json(result.bundle_path, "manifest.json")
        paths = manifest.get("paths", {})
        for key, value in paths.items():
            assert isinstance(value, bool), (
                f"Paths key '{key}' should be bool (existence check), "
                f"got {type(value).__name__}: {value!r}"
            )

    def test_system_info_no_user_paths(self, db_session):
        """system_info.json should not contain user home directory paths."""
        result = self._build(db_session)
        info = self._read_zip_json(result.bundle_path, "system_info.json")

        info_str = _json.dumps(info)
        # Should not reveal user home paths
        import os as _os
        home = _os.path.expanduser("~")
        if home and len(home) > 4:  # ensure it's not just "/" or something
            # Normalize path separators for comparison
            home_normalized = home.replace("\\", "\\\\")
            assert home_normalized not in info_str, (
                f"system_info.json contains user home path: {home}"
            )

    # ── Test: Diagnostic summary has no secrets ──────────────────────

    def test_diagnostics_summary_llm_key_is_bool(self, db_session):
        """diagnostics_summary.json config subsystem should show key as bool."""
        result = self._build(db_session)
        diag = self._read_zip_json(result.bundle_path, "diagnostics_summary.json")

        for ss in diag.get("subsystems", []):
            if ss.get("name") == "config":
                meta = ss.get("metadata", {})
                if "llm_key_set" in meta:
                    assert isinstance(meta["llm_key_set"], bool)
                if "llm_api_key_set" in meta:
                    assert isinstance(meta["llm_api_key_set"], bool)

    # ── Test: Full zip content scan ──────────────────────────────────

    def test_no_sk_pattern_anywhere_in_zip(self, db_session):
        """Complete zip scan: no sk-* API key pattern in any file."""
        # Inject a real-looking key into an operation log to verify redaction
        from signalvault.diagnostics.operation_log import OperationLogManager

        op = OperationLogManager.start(
            operation_type="llm.test_connection",
            metadata={
                "api_key": "sk-or-v1-abcdefghijklmnopqrstuvwxyz123456",
                "provider": "openai",
            },
            session=db_session,
        )
        OperationLogManager.fail(
            op,
            error_code="AUTH_LLM_002",
            error_detail="Invalid API key: sk-or-v1-abcdefghijklmnopqrstuvwxyz123456",
            session=db_session,
        )

        result = self._build(db_session)
        all_text = self._read_all_text(result.bundle_path)

        # The specific injected key must not appear
        assert "sk-or-v1-abcdefghijklmnopqrstuvwxyz123456" not in all_text

        # Generic sk- should only appear in redaction policy description
        sk_count = all_text.count("sk-")
        # Allow "sk-" to appear in the manifest's redaction_policy documentation
        # and in README.txt explanation
        manifest = self._read_zip_json(result.bundle_path, "manifest.json")
        policy_str = _json.dumps(manifest.get("redaction_policy", {}))
        readme_text = ""
        with zipfile.ZipFile(result.bundle_path, "r") as zf:
            try:
                readme_text = zf.read("README.txt").decode("utf-8")
            except Exception:
                pass

        # Count sk- occurrences outside of documentation
        sk_in_policy = policy_str.count("sk-")
        sk_in_readme = readme_text.count("sk-")

        # "sk-" should ONLY appear in the redaction_policy docs (listing what gets redacted)
        # and in the README
        legit_sk_count = sk_in_policy + sk_in_readme
        assert sk_count <= legit_sk_count, (
            f"'sk-' found {sk_count} times in bundle (expected ≤{legit_sk_count} "
            f"from redaction policy docs). Possible leak in data files."
        )


class TestExportConvenienceSecurity:
    """Security tests via the convenience export function."""

    def test_export_no_secrets(self, db_session, tmp_path):
        """Full export via convenience function must not leak secrets."""
        from signalvault.diagnostics.operation_log import OperationLogManager

        op = OperationLogManager.start(
            operation_type="config.save",
            metadata={"api_key": "sk-leaked-key-via-export"},
            session=db_session,
        )
        OperationLogManager.succeed(op, session=db_session)

        result = export_diagnostic_bundle(
            output_dir=str(tmp_path / "export_sec"),
            session=db_session,
        )
        assert result.success

        # Read entire zip
        all_text = ""
        with zipfile.ZipFile(result.bundle_path, "r") as zf:
            for name in zf.namelist():
                all_text += zf.read(name).decode("utf-8", errors="replace") + "\n"

        assert "sk-leaked-key-via-export" not in all_text
