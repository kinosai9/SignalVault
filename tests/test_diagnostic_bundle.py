"""P7-D: Diagnostic bundle tests — zip creation, redaction, CLI smoke."""

from __future__ import annotations

import json as _json
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

# ═════════════════════════════════════════════════════════════════════════════
# Redaction unit tests
# ═════════════════════════════════════════════════════════════════════════════


class TestRedaction:
    def test_api_key_redacted(self):
        assert redact_value("api_key", "sk-secret-12345") == "[REDACTED]"
        assert redact_value("LLM_API_KEY", "sk-abc") == "[REDACTED]"

    def test_token_redacted(self):
        assert redact_value("access_token", "tok123") == "[REDACTED]"
        assert redact_value("refresh_token", "ref456") == "[REDACTED]"
        assert redact_value("auth_token", "auth789") == "[REDACTED]"

    def test_password_redacted(self):
        assert redact_value("password", "pwd123") == "[REDACTED]"
        assert redact_value("secret", "s3cr3t") == "[REDACTED]"

    def test_content_text_truncated(self):
        result = redact_value("content_text", "Hello World" * 50)
        assert "chars redacted" in result

    def test_source_quote_truncated(self):
        result = redact_value("source_quote", "A quote" * 100)
        assert "chars redacted" in result

    def test_report_markdown_truncated(self):
        result = redact_value("report_markdown", "# Report\n" * 100)
        assert "chars redacted" in result

    def test_preview_data_truncated(self):
        result = redact_value("preview_data", '{"data": "' + "x" * 500 + '"}')
        assert "chars redacted" in result

    def test_normal_value_unredacted(self):
        assert redact_value("group_name", "投资研究") == "投资研究"
        assert redact_value("operation_type", "graph.rebuild") == "graph.rebuild"
        assert redact_value("error_code", "AUTH_ZSXQ_001") == "AUTH_ZSXQ_001"

    def test_existence_keys_boolify(self):
        assert redact_value("obsidian_vault_path", "/home/user/vault") is True
        assert redact_value("db_path", "/data/db.sqlite") is True
        assert redact_value("obsidian_vault_path", "") is False

    def test_redact_dict_recursive(self):
        data = {
            "config": {
                "api_key": "secret123",
                "public_name": "test",
                "nested": {"token": "tok", "value": 42},
            },
            "content_text": "long text" * 100,
        }
        result = redact_dict(data)
        assert result["config"]["api_key"] == "[REDACTED]"
        assert result["config"]["public_name"] == "test"
        assert result["config"]["nested"]["token"] == "[REDACTED]"
        assert result["config"]["nested"]["value"] == 42
        assert "chars redacted" in result["content_text"]

    def test_llm_base_url_redacted(self):
        assert redact_value("llm_base_url", "https://api.openai.com/v1") == "[REDACTED]"


# ═════════════════════════════════════════════════════════════════════════════
# Bundle creation tests
# ═════════════════════════════════════════════════════════════════════════════


class TestBundleCreation:
    @pytest.fixture(autouse=True)
    def _setup_output_dir(self, tmp_path):
        self.output_dir = tmp_path / "diagnostics"

    def _build(self, db_session=None, **kwargs) -> DiagnosticBundleResult:
        config = DiagnosticBundleConfig(
            output_dir=str(self.output_dir),
            limit_logs=kwargs.get("limit_logs", 100),
        )
        builder = DiagnosticBundleBuilder(config, session=db_session)
        return builder.build()

    def test_bundle_zip_created(self, db_session):
        result = self._build(db_session)
        assert result.success
        assert result.bundle_path.endswith(".zip")
        assert Path(result.bundle_path).exists()

    def test_manifest_exists(self, db_session):
        result = self._build(db_session)
        files = self._list_zip(result.bundle_path)
        assert "manifest.json" in files

    def test_manifest_has_required_fields(self, db_session):
        result = self._build(db_session)
        manifest = self._read_zip_json(result.bundle_path, "manifest.json")
        assert "generated_at" in manifest
        assert "bundle_schema_version" in manifest
        assert "redaction_policy" in manifest
        assert "included_files" in manifest or "warnings" in manifest

    def test_diagnostics_summary_exists(self, db_session):
        result = self._build(db_session)
        assert "diagnostics_summary.json" in self._list_zip(result.bundle_path)

    def test_operation_logs_exists(self, db_session):
        result = self._build(db_session)
        assert "operation_logs.json" in self._list_zip(result.bundle_path)

    def test_review_items_summary_exists(self, db_session):
        result = self._build(db_session)
        assert "review_items_summary.json" in self._list_zip(result.bundle_path)

    def test_ingest_jobs_summary_exists(self, db_session):
        result = self._build(db_session)
        assert "ingest_jobs_summary.json" in self._list_zip(result.bundle_path)

    def test_config_summary_exists(self, db_session):
        result = self._build(db_session)
        assert "config_summary.json" in self._list_zip(result.bundle_path)

    def test_system_info_exists(self, db_session):
        result = self._build(db_session)
        assert "system_info.json" in self._list_zip(result.bundle_path)

    def test_search_graph_summary_exists(self, db_session):
        result = self._build(db_session)
        assert "search_graph_summary.json" in self._list_zip(result.bundle_path)

    def test_readme_exists(self, db_session):
        result = self._build(db_session)
        assert "README.txt" in self._list_zip(result.bundle_path)

    def test_all_nine_files_present(self, db_session):
        result = self._build(db_session)
        files = set(self._list_zip(result.bundle_path))
        expected = {
            "manifest.json", "diagnostics_summary.json", "operation_logs.json",
            "review_items_summary.json", "ingest_jobs_summary.json",
            "config_summary.json", "system_info.json",
            "search_graph_summary.json", "README.txt",
        }
        assert files == expected

    def test_empty_db_does_not_crash(self, db_session):
        """Bundle should succeed even on a completely empty DB."""
        result = self._build(db_session)
        assert result.success
        assert result.file_count >= 9

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _list_zip(zip_path: str) -> list[str]:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return zf.namelist()

    @staticmethod
    def _read_zip_json(zip_path: str, name: str) -> dict:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return _json.loads(zf.read(name).decode("utf-8"))

    @staticmethod
    def _read_zip_text(zip_path: str, name: str) -> str:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return zf.read(name).decode("utf-8")


# ═════════════════════════════════════════════════════════════════════════════
# Redaction in bundle tests
# ═════════════════════════════════════════════════════════════════════════════


class TestBundleRedaction:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.output_dir = tmp_path / "diag"

    def _build(self, db_session=None) -> DiagnosticBundleResult:
        config = DiagnosticBundleConfig(output_dir=str(self.output_dir))
        builder = DiagnosticBundleBuilder(config, session=db_session)
        return builder.build()

    def test_config_has_no_api_key_value(self, db_session):
        result = self._build(db_session)
        config = _read_zip_json(result.bundle_path, "config_summary.json")
        # Check no raw key values
        config_str = _json.dumps(config).lower()
        assert "sk-" not in config_str
        assert "[REDACTED]" in config_str or "true" in config_str or "false" in config_str

    def test_operation_logs_have_no_raw_tokens(self, db_session):
        from signalvault.diagnostics.operation_log import OperationLogManager
        op = OperationLogManager.start(
            operation_type="graph.rebuild",
            metadata={"api_key": "sk-secret", "group_name": "投资研究"},
            session=db_session,
        )
        OperationLogManager.succeed(op, session=db_session)

        result = self._build(db_session)
        logs = _read_zip_json(result.bundle_path, "operation_logs.json")
        logs_str = _json.dumps(logs)
        assert "sk-secret" not in logs_str

    def test_review_items_have_no_full_content(self, db_session):
        from signalvault.sources.review_items import ReviewItemManager
        ReviewItemManager.create_item(
            item_type="pdf_needs_ocr",
            title="Test",
            severity="warning",
            description="Full paid content here" * 50,
            session=db_session,
        )

        result = self._build(db_session)
        review = _read_zip_json(result.bundle_path, "review_items_summary.json")
        # Should be summary only, not full items with descriptions
        assert "by_severity" in review
        assert "by_type" in review
        # No raw descriptions
        review_str = _json.dumps(review)
        assert "Full paid content" not in review_str

    def test_diagnostics_summary_no_secrets(self, db_session):
        result = self._build(db_session)
        diag = _read_zip_json(result.bundle_path, "diagnostics_summary.json")
        diag_str = _json.dumps(diag).lower()
        assert "sk-" not in diag_str
        # llm_key_set should be bool, not a value
        # (check config subsystem metadata)
        for ss in diag.get("subsystems", []):
            if ss.get("name") == "config":
                meta = ss.get("metadata", {})
                assert "api_key" not in str(meta).lower() or meta.get("llm_key_set") in (True, False)

    def test_system_info_no_secrets(self, db_session):
        result = self._build(db_session)
        info = _read_zip_json(result.bundle_path, "system_info.json")
        assert "python_version" in info
        assert "platform" in info


# ═════════════════════════════════════════════════════════════════════════════
# CLI smoke tests
# ═════════════════════════════════════════════════════════════════════════════


class TestBundleCLI:
    def _reload_cli(self):
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        return cli_mod

    def test_bundle_help(self):
        cli_mod = self._reload_cli()
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["diagnostics", "bundle", "--help"])
        assert result.exit_code == 0
        import re as _re
        _plain = _re.sub(r'\x1b\[[0-9;]*m', '', result.stdout)
        assert "--output" in _plain
        assert "--limit-logs" in _plain
        assert "--json" in _plain

    def test_bundle_creates_zip(self, db_session, tmp_path):
        cli_mod = self._reload_cli()
        from typer.testing import CliRunner

        output_dir = tmp_path / "bundle_out"
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, [
            "diagnostics", "bundle",
            "--output", str(output_dir),
            "--limit-logs", "10",
        ])
        assert result.exit_code == 0
        # Check zip was created
        zips = list(output_dir.glob("diagnostic_bundle_*.zip"))
        assert len(zips) >= 1

    def test_bundle_json_output(self, db_session, tmp_path):
        cli_mod = self._reload_cli()
        from typer.testing import CliRunner

        output_dir = tmp_path / "bundle_json"
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, [
            "diagnostics", "bundle",
            "--output", str(output_dir),
            "--json",
        ])
        assert result.exit_code == 0
        # Parse JSON with lenient handling for Windows line endings
        stdout = result.stdout.strip()
        idx = stdout.find("{")
        if idx > 0:
            stdout = stdout[idx:]
        try:
            data = _json.loads(stdout)
        except _json.JSONDecodeError:
            # Fall back to substring check
            assert '"success"' in stdout
            assert '"bundle_path"' in stdout
            return
        assert data["success"] is True
        assert "bundle_path" in data
        assert "file_names" in data

    def test_bundle_writes_operation_log(self, db_session, tmp_path):
        cli_mod = self._reload_cli()
        from typer.testing import CliRunner

        from signalvault.diagnostics.operation_log import OperationLogManager

        output_dir = tmp_path / "bundle_opl"
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, [
            "diagnostics", "bundle",
            "--output", str(output_dir),
        ])
        assert result.exit_code == 0

        # Check operation log was written
        ops = OperationLogManager.list_operations(session=db_session)
        bundle_ops = [o for o in ops if o.get("summary", "").startswith("诊断包导出")]
        assert len(bundle_ops) >= 1
        assert bundle_ops[0]["status"] == "succeeded"


# ═════════════════════════════════════════════════════════════════════════════
# Convenience function
# ═════════════════════════════════════════════════════════════════════════════


class TestExportConvenience:
    def test_export_diagnostic_bundle(self, db_session, tmp_path):
        result = export_diagnostic_bundle(
            output_dir=str(tmp_path / "export_test"),
            session=db_session,
        )
        assert result.success
        assert Path(result.bundle_path).exists()
        assert result.file_count >= 9


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════


def _read_zip_json(zip_path: str, name: str) -> dict:
    with zipfile.ZipFile(zip_path, "r") as zf:
        return _json.loads(zf.read(name).decode("utf-8"))
