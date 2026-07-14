"""Tests for config_store.py and logging_config.py.

Note: conftest.py has an autouse fixture _isolate_config_store that
monkeypatches config_store._SETTINGS_PATH. Tests that need to control
the settings path must use monkeypatch.setattr to match this pattern.
"""

import json
import pytest


# ── config_store.py ──────────────────────────────────────────────────────────

class TestConfigStore:
    def _set_settings_path(self, monkeypatch, path):
        """Override the settings file path for this test."""
        import signalvault.config_store as cs
        monkeypatch.setattr(cs, "_get_settings_path", lambda: path)

    def test_get_vault_path_from_settings(self, tmp_path, monkeypatch):
        from signalvault.config_store import get_user_vault_path, save_user_vault_path
        settings_file = tmp_path / "user_settings.json"
        self._set_settings_path(monkeypatch, settings_file)
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)

        save_user_vault_path(str(tmp_path / "my_vault"))
        result = get_user_vault_path()
        assert result == str(tmp_path / "my_vault")

    def test_get_vault_path_fallback_to_env(self, tmp_path, monkeypatch):
        from signalvault.config_store import get_user_vault_path
        settings_file = tmp_path / "nonexistent.json"
        self._set_settings_path(monkeypatch, settings_file)
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "env_vault"))
        result = get_user_vault_path()
        assert result == str(tmp_path / "env_vault")

    def test_get_vault_path_settings_priority_over_env(self, tmp_path, monkeypatch):
        from signalvault.config_store import get_user_vault_path, save_user_vault_path
        settings_file = tmp_path / "user_settings.json"
        self._set_settings_path(monkeypatch, settings_file)
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "env_vault"))
        save_user_vault_path(str(tmp_path / "settings_vault"))
        result = get_user_vault_path()
        assert result == str(tmp_path / "settings_vault")

    def test_get_vault_path_not_configured(self, tmp_path, monkeypatch):
        from signalvault.config_store import get_user_vault_path
        settings_file = tmp_path / "nonexistent.json"
        self._set_settings_path(monkeypatch, settings_file)
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        result = get_user_vault_path()
        assert result == ""

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        from signalvault.config_store import save_user_vault_path
        settings_file = tmp_path / "settings.json"
        self._set_settings_path(monkeypatch, settings_file)

        vault = str(tmp_path / "roundtrip_vault")
        save_user_vault_path(vault)
        assert settings_file.exists()
        raw = json.loads(settings_file.read_text(encoding="utf-8"))
        assert raw["obsidian_vault_path"] == vault

    def test_corrupt_json_returns_empty(self, tmp_path, monkeypatch):
        from signalvault.config_store import get_user_vault_path
        settings_file = tmp_path / "bad.json"
        settings_file.write_text("not valid json {{{", encoding="utf-8")
        self._set_settings_path(monkeypatch, settings_file)
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        result = get_user_vault_path()
        assert result == ""

    def test_save_creates_parent_dir(self, tmp_path, monkeypatch):
        from signalvault.config_store import save_user_vault_path
        deep = tmp_path / "deep" / "nested" / "settings.json"
        self._set_settings_path(monkeypatch, deep)
        save_user_vault_path("/some/vault")
        assert deep.exists()
        assert deep.parent.exists()


# ── logging_config.py ────────────────────────────────────────────────────────

class TestLoggingConfig:
    def test_creates_log_directory(self, tmp_path, monkeypatch):
        """Verify setup_logging creates the log directory. Does not test handler
        attachment to avoid pytest stderr capture conflicts."""
        from signalvault.logging_config import setup_logging
        import logging
        log_dir = tmp_path / "new_logs"
        monkeypatch.setattr("signalvault.logging_config.LOG_DIR", log_dir)

        root = logging.getLogger()
        root.handlers.clear()
        assert not log_dir.exists()
        setup_logging("INFO")
        assert log_dir.exists()
