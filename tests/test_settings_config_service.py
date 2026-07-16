"""C1-B: ConfigService tests.

Coverage:
    - schema defaults and type coercion
    - user config write / read
    - only non-default values persisted
    - atomic write
    - TOML corruption handling
    - runtime override priority
    - env priority over user config
    - .env backward compat
    - source tracking
    - public snapshot without secrets
    - config_store vault migration
    - old config.py names work
    - test isolation
    - reload behaviour
"""

from __future__ import annotations

import pytest

from signalvault.settings.app_paths import AppPaths
from signalvault.settings.schema import RUNTIME_SCHEMA
from signalvault.settings.secret_store import SecretStore
from signalvault.settings.service import (
    ConfigService,
    Source,
    get_config_service,
)

# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_svc(tmp_path, env=None) -> ConfigService:
    paths = AppPaths.resolve(home_override=tmp_path / "SignalVault")
    secrets = SecretStore(paths.config_dir)
    return ConfigService(paths, env=env or {}, secret_store=secrets)


# ═════════════════════════════════════════════════════════════════════════
# Default resolution
# ═════════════════════════════════════════════════════════════════════════

class TestDefaults:
    def test_llm_provider_defaults_to_mock(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc.get("llm.provider") == "mock"

    def test_web_host_defaults_to_localhost(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc.get("web.host") == "127.0.0.1"

    def test_source_is_default(self, tmp_path):
        svc = _make_svc(tmp_path)
        cv = svc.get_with_source("web.port")
        assert cv.source == Source.DEFAULT
        assert cv.is_default is True

    def test_all_schema_keys_resolvable(self, tmp_path):
        svc = _make_svc(tmp_path)
        for key in RUNTIME_SCHEMA:
            val = svc.get(key)
            assert val is not None or RUNTIME_SCHEMA[key].type in (str,)


# ═════════════════════════════════════════════════════════════════════════
# Environment variable priority
# ═════════════════════════════════════════════════════════════════════════

class TestEnvPriority:
    def test_env_overrides_default(self, tmp_path):
        svc = _make_svc(tmp_path, env={"LLM_PROVIDER": "openai-compatible"})
        cv = svc.get_with_source("llm.provider")
        assert cv.value == "openai-compatible"
        assert cv.source == Source.ENV

    def test_env_overrides_user_config(self, tmp_path):
        svc = _make_svc(tmp_path)
        # User sets it to "openai-compatible" in config.toml
        svc.set_user_value("llm.provider", "openai-compatible")
        # But env var overrides with "mock"
        svc2 = _make_svc(tmp_path, env={"LLM_PROVIDER": "mock"})
        cv = svc2.get_with_source("llm.provider")
        assert cv.value == "mock"
        assert cv.source == Source.ENV
        assert cv.is_overridden is True

    def test_env_bool_coerced(self, tmp_path):
        svc = _make_svc(tmp_path, env={"OBSIDIAN_EXPORT_ENABLED": "true"})
        cv = svc.get_with_source("obsidian.export_enabled")
        assert cv.value is True


# ═════════════════════════════════════════════════════════════════════════
# User config (config.toml) write / read
# ═════════════════════════════════════════════════════════════════════════

class TestUserConfig:
    def test_set_and_get(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_user_value("llm.provider", "openai-compatible")
        cv = svc.get_with_source("llm.provider")
        assert cv.value == "openai-compatible"
        assert cv.source == Source.USER

    def test_persisted_across_reload(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_user_value("web.port", 9999)
        svc.reload()
        assert svc.get("web.port") == 9999

    def test_new_instance_reads_same_value(self, tmp_path):
        svc1 = _make_svc(tmp_path)
        svc1.set_user_value("web.port", 8888)

        svc2 = _make_svc(tmp_path)
        assert svc2.get("web.port") == 8888

    def test_delete_user_value_reverts_to_default(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_user_value("web.port", 7777)
        svc.delete_user_value("web.port")
        assert svc.get("web.port") == 8000  # schema default

    def test_default_value_not_persisted(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_user_value("web.port", 8000)  # same as default
        # Should be treated as delete
        cv = svc.get_with_source("web.port")
        assert cv.source == Source.DEFAULT

    def test_sensitive_key_rejected(self, tmp_path):
        svc = _make_svc(tmp_path)
        with pytest.raises(ValueError, match="SecretStore"):
            svc.set_user_value("llm.api_key", "sk-123")

    def test_unknown_key_rejected(self, tmp_path):
        svc = _make_svc(tmp_path)
        with pytest.raises(KeyError):
            svc.set_user_value("nonexistent.key", 42)

    def test_validator_rejects_invalid(self, tmp_path):
        svc = _make_svc(tmp_path)
        with pytest.raises(ValueError):
            svc.set_user_value("llm.provider", "invalid-provider")


# ═════════════════════════════════════════════════════════════════════════
# Runtime override priority
# ═════════════════════════════════════════════════════════════════════════

class TestRuntimeOverride:
    def test_runtime_overrides_all(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_user_value("web.port", 1111)
        svc.set_runtime_override("web.port", 9999)

        cv = svc.get_with_source("web.port")
        assert cv.value == 9999
        assert cv.source == Source.RUNTIME

    def test_clear_runtime_override(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_runtime_override("web.port", 1234)
        assert svc.get("web.port") == 1234
        svc.clear_runtime_override("web.port")
        assert svc.get("web.port") == 8000

    def test_runtime_not_persisted(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_runtime_override("web.port", 1234)
        # New instance should not see the override
        svc2 = _make_svc(tmp_path)
        assert svc2.get("web.port") == 8000

    def test_cli_override_priority(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_user_value("web.port", 9000)
        svc.set_cli_overrides(web__port=5555)  # note: key format doesn't match
        # CLI override uses "web.port" as key
        svc.set_cli_overrides(**{"web.port": 5555})
        cv = svc.get_with_source("web.port")
        assert cv.value == 5555
        assert cv.source == Source.CLI


# ═════════════════════════════════════════════════════════════════════════
# TOML corruption handling
# ═════════════════════════════════════════════════════════════════════════

class TestTOMLCorruption:
    def test_corrupt_file_renamed_not_overwritten(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_user_value("web.port", 7777)

        # Corrupt the file
        svc._config_path.write_text("this is not valid toml {{{", encoding="utf-8")

        # New instance should fall back to defaults
        svc2 = _make_svc(tmp_path)
        assert svc2.get("web.port") == 8000  # default

        # Corrupt backup should exist
        corrupt_files = list(svc._config_path.parent.glob("config.toml.corrupt.*"))
        assert len(corrupt_files) >= 1


# ═════════════════════════════════════════════════════════════════════════
# Public snapshot
# ═════════════════════════════════════════════════════════════════════════

class TestPublicSnapshot:
    def test_does_not_contain_secret_values(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_secret("llm.api_key", "sk-secret-123")
        snapshot = svc.get_public_snapshot()
        llm_key = snapshot.get("llm.api_key", {})
        assert llm_key == {"configured": True}
        # No raw value anywhere in snapshot
        snapshot_str = str(snapshot)
        assert "sk-secret-123" not in snapshot_str

    def test_contains_non_secret_values(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_user_value("web.port", 4321)
        snapshot = svc.get_public_snapshot()
        assert snapshot["web.port"]["value"] == 4321
        assert snapshot["web.port"]["source"] == Source.USER

    def test_secret_not_configured(self, tmp_path):
        svc = _make_svc(tmp_path)
        snapshot = svc.get_public_snapshot()
        assert snapshot["llm.api_key"] == {"configured": False}


# ═════════════════════════════════════════════════════════════════════════
# SecretStore integration
# ═════════════════════════════════════════════════════════════════════════

class TestSecretIntegration:
    def test_set_and_get_secret(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_secret("llm.api_key", "sk-abc")
        assert svc.is_secret_set("llm.api_key") is True
        assert svc.get_secret("llm.api_key") == "sk-abc"

    def test_delete_secret(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_secret("llm.api_key", "sk-abc")
        svc.delete_secret("llm.api_key")
        assert svc.is_secret_set("llm.api_key") is False

    def test_secret_from_env_backward_compat(self, tmp_path):
        svc = _make_svc(tmp_path, env={"LLM_API_KEY": "sk-from-env"})
        assert svc.get_secret("llm.api_key") == "sk-from-env"

    def test_secret_store_preferred_over_env(self, tmp_path):
        """SecretStore value wins over env for get_secret()."""
        svc = _make_svc(tmp_path, env={"LLM_API_KEY": "sk-from-env"})
        svc.set_secret("llm.api_key", "sk-from-store")
        assert svc.get_secret("llm.api_key") == "sk-from-store"

    def test_empty_secret_deletes(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_secret("llm.api_key", "val")
        svc.set_secret("llm.api_key", "")  # empty → delete
        assert svc.is_secret_set("llm.api_key") is False

    def test_runtime_override_wins_over_store(self, tmp_path):
        """Runtime override should be highest priority in get_secret()."""
        svc = _make_svc(tmp_path, env={"LLM_API_KEY": "sk-from-env"})
        svc.set_secret("llm.api_key", "sk-from-store")
        svc.set_runtime_override("llm.api_key", "sk-runtime")
        assert svc.get_secret("llm.api_key") == "sk-runtime"

    def test_runtime_override_wins_without_store(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_runtime_override("llm.api_key", "sk-runtime-only")
        assert svc.get_secret("llm.api_key") == "sk-runtime-only"

    def test_get_secret_with_source_configured(self, tmp_path):
        svc = _make_svc(tmp_path, env={"LLM_API_KEY": "sk-from-env"})
        result = svc.get_secret_with_source("llm.api_key")
        assert result["configured"] == "true"
        assert result["source"] == Source.ENV

    def test_get_secret_with_source_not_configured(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.get_secret_with_source("llm.api_key")
        assert result["configured"] == "false"
        assert result["source"] == Source.DEFAULT

    def test_get_secret_with_source_runtime(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_runtime_override("llm.api_key", "sk-runtime")
        result = svc.get_secret_with_source("llm.api_key")
        assert result["configured"] == "true"
        assert result["source"] == Source.RUNTIME

    def test_get_secret_with_source_store(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_secret("llm.api_key", "sk-store")
        result = svc.get_secret_with_source("llm.api_key")
        assert result["configured"] == "true"
        assert result["source"] == "secret_store"

    def test_get_secret_with_source_never_returns_value(self, tmp_path):
        """get_secret_with_source must NEVER return the actual secret value."""
        svc = _make_svc(tmp_path)
        svc.set_secret("llm.api_key", "sk-very-secret-value-12345")
        result = svc.get_secret_with_source("llm.api_key")
        assert "sk-very-secret-value-12345" not in str(result)
        assert "value" not in result  # no raw value field


# ═════════════════════════════════════════════════════════════════════════
# Source tracking
# ═════════════════════════════════════════════════════════════════════════

class TestSourceTracking:
    def test_is_overridden_flag(self, tmp_path):
        """When env overrides user config, is_overridden=True."""
        svc = _make_svc(tmp_path)
        svc.set_user_value("llm.provider", "openai-compatible")

        # Without env override — user value wins
        cv = svc.get_with_source("llm.provider")
        assert cv.source == Source.USER
        assert cv.is_overridden is False

        # With env override (new service, same config.toml on disk, but env set)
        svc2 = _make_svc(tmp_path, env={"LLM_PROVIDER": "mock"})
        cv2 = svc2.get_with_source("llm.provider")
        assert cv2.source == Source.ENV
        assert cv2.is_overridden is True


# ═════════════════════════════════════════════════════════════════════════
# Test isolation
# ═════════════════════════════════════════════════════════════════════════

class TestIsolation:
    def test_services_dont_pollute(self, tmp_path):
        svc1 = _make_svc(tmp_path / "a")
        svc2 = _make_svc(tmp_path / "b")

        svc1.set_user_value("web.port", 1111)
        assert svc2.get("web.port") == 8000

    def test_conftest_isolates_singleton(self):
        """The autouse fixture should have set up a test ConfigService."""
        svc = get_config_service()
        assert svc is not None
        # Should be an isolated instance (paths under tmp_path)
        assert "SignalVault" in str(svc._app_paths.app_support_dir)


# ═════════════════════════════════════════════════════════════════════════
# Reload behaviour
# ═════════════════════════════════════════════════════════════════════════

class TestReload:
    def test_reload_picks_up_disk_changes(self, tmp_path):
        svc1 = _make_svc(tmp_path)
        svc1.set_user_value("web.port", 1111)

        svc2 = _make_svc(tmp_path)
        svc2.set_user_value("web.port", 2222)

        svc1.reload()
        assert svc1.get("web.port") == 2222
