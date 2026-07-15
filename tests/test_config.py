"""Tests for config_store.py and logging_config.py.

Note: conftest.py has an autouse fixture _isolate_config_store that
monkeypatches config_store._SETTINGS_PATH. Tests that need to control
the settings path must use monkeypatch.setattr to match this pattern.
"""


# ── config_store.py ──────────────────────────────────────────────────────────

class TestConfigStore:
    def _set_settings_path(self, monkeypatch, path):
        """Override the settings file path for this test."""
        import signalvault.config_store as cs
        monkeypatch.setattr(cs, "_get_settings_path", lambda: path)

    def test_get_vault_path_from_settings(self, tmp_path, monkeypatch):
        """C1-B: save_user_vault_path persists via ConfigService → config.toml."""
        from signalvault.config_store import get_user_vault_path, save_user_vault_path
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)

        vault_path = str(tmp_path / "my_vault")
        save_user_vault_path(vault_path)
        result = get_user_vault_path()
        assert result == vault_path

    def test_get_vault_path_fallback_to_env(self, tmp_path, monkeypatch):
        from signalvault.config_store import get_user_vault_path
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "env_vault"))
        result = get_user_vault_path()
        assert result == str(tmp_path / "env_vault")

    def test_get_vault_path_env_overrides_user(self, tmp_path, monkeypatch):
        """C1-B: env var has higher priority than user config (config.toml)."""
        from signalvault.config_store import get_user_vault_path, save_user_vault_path
        save_user_vault_path(str(tmp_path / "saved_vault"))
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "env_vault"))
        result = get_user_vault_path()
        # env overrides user config
        assert result == str(tmp_path / "env_vault")

    def test_get_vault_path_not_configured(self, tmp_path, monkeypatch):
        from signalvault.config_store import get_user_vault_path
        settings_file = tmp_path / "nonexistent.json"
        self._set_settings_path(monkeypatch, settings_file)
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        result = get_user_vault_path()
        assert result == ""

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        """C1-B: save and load via ConfigService."""
        from signalvault.config_store import get_user_vault_path, save_user_vault_path
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)

        vault = str(tmp_path / "roundtrip_vault")
        save_user_vault_path(vault)
        result = get_user_vault_path()
        assert result == vault
        # config.toml should exist
        from signalvault.config import get_app_paths
        config_toml = get_app_paths().config_dir / "config.toml"
        assert config_toml.exists()

    def test_corrupt_json_returns_empty(self, tmp_path, monkeypatch):
        """C1-B: corrupt TOML is handled gracefully."""
        from signalvault.config_store import get_user_vault_path
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        # Write corrupt config.toml
        from signalvault.config import get_app_paths
        config_toml = get_app_paths().config_dir / "config.toml"
        config_toml.parent.mkdir(parents=True, exist_ok=True)
        config_toml.write_text("this is not valid toml {{{", encoding="utf-8")
        result = get_user_vault_path()
        assert result == ""

    def test_save_creates_parent_dir(self, tmp_path, monkeypatch):
        """C1-B: saving creates config directory automatically."""
        from signalvault.config_store import get_user_vault_path, save_user_vault_path
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)

        from signalvault.config import get_app_paths
        config_dir = get_app_paths().config_dir
        # Dir should be auto-created by ConfigService on write
        save_user_vault_path("/some/vault")
        result = get_user_vault_path()
        assert result == "/some/vault"
        assert config_dir.exists()


# ── logging_config.py ────────────────────────────────────────────────────────

class TestLoggingConfig:
    def test_creates_log_directory(self, tmp_path, monkeypatch):
        """Verify setup_logging creates the log directory. Does not test handler
        attachment to avoid pytest stderr capture conflicts."""
        import logging

        from signalvault.logging_config import setup_logging
        log_dir = tmp_path / "new_logs"
        monkeypatch.setattr("signalvault.logging_config.LOG_DIR", log_dir)

        root = logging.getLogger()
        root.handlers.clear()
        assert not log_dir.exists()
        setup_logging("INFO")
        assert log_dir.exists()
