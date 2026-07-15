"""C1-A: AppPaths unit tests.

Coverage:
    - SIGNALVAULT_HOME overrides all paths
    - Legacy env-var overrides (DATA_DIR, LOG_DIR, DB_PATH)
    - Platform defaults (Windows, macOS, Linux)
    - Path creation is idempotent
    - No dependency on cwd
    - config_store migration from legacy path
    - Test isolation (instances don't pollute each other)
    - Editable-install compatibility
    - User data never lands in site-packages
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from signalvault.settings.app_paths import (
    AppPaths,
    _platform_cache_dir,
    _platform_data_dir,
)

# ── Helpers ─────────────────────────────────────────────────────────────────

def _set_env(monkeypatch, **kwargs: str) -> None:
    """Set env vars for the duration of a test, clearing unrelated ones.

    Legacy path vars (DATA_DIR etc.) are set to empty to suppress .env values.
    Platform vars (APPDATA etc.) are deleted so os.getenv() falls through to
    the default value (matching the semantics of "not configured").
    """
    _BLANK_VARS = ("SIGNALVAULT_HOME", "DATA_DIR", "LOG_DIR", "DB_PATH")
    _DEL_VARS = ("APPDATA", "LOCALAPPDATA", "XDG_DATA_HOME", "XDG_CACHE_HOME")
    for key in _BLANK_VARS:
        monkeypatch.setenv(key, "")
    for key in _DEL_VARS:
        monkeypatch.delenv(key, raising=False)
    for k, v in kwargs.items():
        if v:
            monkeypatch.setenv(k, v)


# ═════════════════════════════════════════════════════════════════════════
# SIGNALVAULT_HOME — all paths converge
# ═════════════════════════════════════════════════════════════════════════

class TestSignalVaultHome:
    def test_home_overrides_all_paths(self, monkeypatch):
        _set_env(monkeypatch, SIGNALVAULT_HOME="/tmp/sv_test")
        p = AppPaths.resolve()
        assert p.app_support_dir == Path("/tmp/sv_test")
        assert p.data_dir == Path("/tmp/sv_test/data")
        assert p.log_dir == Path("/tmp/sv_test/logs")
        assert p.config_dir == Path("/tmp/sv_test/config")
        assert p.backup_dir == Path("/tmp/sv_test/backups")
        assert p.diagnostics_dir == Path("/tmp/sv_test/diagnostics")
        assert p.runtime_dir == Path("/tmp/sv_test/runtime")
        assert p.db_path == Path("/tmp/sv_test/data/signalvault.db")
        assert p.report_dir == Path("/tmp/sv_test/data/reports")
        assert p.subtitle_dir == Path("/tmp/sv_test/data/subtitles")
        assert p.transcript_cache_dir == Path("/tmp/sv_test/data/transcripts/youtube")
        assert p.settings_path == Path("/tmp/sv_test/config/user_settings.json")

    def test_home_override_via_constructor(self, monkeypatch):
        _set_env(monkeypatch)  # suppress .env DATA_DIR
        p = AppPaths.resolve(home_override="/tmp/ctor_test")
        assert p.app_support_dir == Path("/tmp/ctor_test")
        assert p.data_dir == Path("/tmp/ctor_test/data")

    def test_home_constructor_wins_over_env(self, monkeypatch):
        _set_env(monkeypatch, SIGNALVAULT_HOME="/tmp/env_home")
        p = AppPaths.resolve(home_override="/tmp/ctor_home")
        assert p.app_support_dir == Path("/tmp/ctor_home")

    def test_is_using_platform_default_true(self, monkeypatch):
        _set_env(monkeypatch)  # clear all
        p = AppPaths.resolve()
        assert p.is_using_platform_default() is True

    def test_is_using_platform_default_false_with_home(self, monkeypatch):
        _set_env(monkeypatch, SIGNALVAULT_HOME="/tmp/sv")
        p = AppPaths.resolve()
        assert p.is_using_platform_default() is False


# ═════════════════════════════════════════════════════════════════════════
# Legacy env-var overrides
# ═════════════════════════════════════════════════════════════════════════

class TestLegacyOverrides:
    def test_data_dir_override(self, monkeypatch):
        _set_env(monkeypatch, DATA_DIR="/custom/data")
        p = AppPaths.resolve()
        assert p.data_dir == Path("/custom/data")
        # other paths still use home default
        assert p.log_dir != Path("/custom/data")

    def test_log_dir_override(self, monkeypatch):
        _set_env(monkeypatch, LOG_DIR="/custom/logs")
        p = AppPaths.resolve()
        assert p.log_dir == Path("/custom/logs")

    def test_db_path_override(self, monkeypatch):
        _set_env(monkeypatch, DB_PATH="/custom/db.sqlite")
        p = AppPaths.resolve()
        assert p.db_path == Path("/custom/db.sqlite")

    def test_data_dir_with_home(self, monkeypatch):
        """DATA_DIR overrides only data_dir; home controls everything else."""
        _set_env(monkeypatch, SIGNALVAULT_HOME="/tmp/sv", DATA_DIR="/custom/data")
        p = AppPaths.resolve()
        assert p.app_support_dir == Path("/tmp/sv")
        assert p.data_dir == Path("/custom/data")
        assert p.log_dir == Path("/tmp/sv/logs")
        assert p.config_dir == Path("/tmp/sv/config")

    def test_db_path_with_home(self, monkeypatch):
        _set_env(monkeypatch, SIGNALVAULT_HOME="/tmp/sv", DB_PATH="/custom/db.sqlite")
        p = AppPaths.resolve()
        assert p.db_path == Path("/custom/db.sqlite")
        assert p.data_dir == Path("/tmp/sv/data")


# ═════════════════════════════════════════════════════════════════════════
# Platform defaults
# ═════════════════════════════════════════════════════════════════════════

class TestPlatformDefaults:
    def test_windows_default(self, monkeypatch):
        _set_env(monkeypatch, APPDATA="C:\\Users\\test\\AppData\\Roaming")
        with monkeypatch.context() as m:
            m.setattr(sys, "platform", "win32")
            result = _platform_data_dir("SignalVault")
        assert result == Path("C:/Users/test/AppData/Roaming/SignalVault")

    def test_macos_default(self, monkeypatch):
        _set_env(monkeypatch)
        with monkeypatch.context() as m:
            m.setattr(sys, "platform", "darwin")
            result = _platform_data_dir("SignalVault")
        assert result.name == "SignalVault"
        assert "Library" in str(result)
        assert "Application Support" in str(result)

    def test_linux_xdg(self, monkeypatch):
        _set_env(monkeypatch, XDG_DATA_HOME="/home/user/.local/share")
        with monkeypatch.context() as m:
            m.setattr(sys, "platform", "linux")
            result = _platform_data_dir("SignalVault")
        assert result == Path("/home/user/.local/share/signalvault")

    def test_linux_xdg_fallback(self, monkeypatch):
        _set_env(monkeypatch)  # no XDG
        with monkeypatch.context() as m:
            m.setattr(sys, "platform", "linux")
            home = Path.home()
            result = _platform_data_dir("SignalVault")
        assert result == home / ".local" / "share" / "signalvault"

    def test_windows_cache(self, monkeypatch):
        _set_env(monkeypatch, LOCALAPPDATA="C:\\Users\\test\\AppData\\Local")
        with monkeypatch.context() as m:
            m.setattr(sys, "platform", "win32")
            result = _platform_cache_dir("SignalVault")
        assert result == Path("C:/Users/test/AppData/Local/SignalVault/cache")

    def test_macos_cache(self, monkeypatch):
        _set_env(monkeypatch)
        with monkeypatch.context() as m:
            m.setattr(sys, "platform", "darwin")
            home = Path.home()
            result = _platform_cache_dir("SignalVault")
        assert result == home / "Library" / "Caches" / "SignalVault"

    def test_linux_cache_xdg(self, monkeypatch):
        _set_env(monkeypatch, XDG_CACHE_HOME="/home/user/.cache")
        with monkeypatch.context() as m:
            m.setattr(sys, "platform", "linux")
            result = _platform_cache_dir("SignalVault")
        assert result == Path("/home/user/.cache/signalvault")

    @pytest.mark.parametrize("platform,attr", [
        ("win32", "APPDATA"),
        ("darwin", None),
        ("linux", "XDG_DATA_HOME"),
    ])
    def test_resolve_uses_platform_default(self, monkeypatch, platform, attr):
        """AppPaths.resolve() with no env vars should produce platform paths."""
        _set_env(monkeypatch)  # clear all
        p = AppPaths.resolve()
        # On any platform, paths should exist as Path objects
        assert isinstance(p.data_dir, Path)
        assert isinstance(p.log_dir, Path)
        assert isinstance(p.db_path, Path)
        # app_support_dir should NOT be the repo root
        assert "site-packages" not in str(p.app_support_dir)
        assert "signalvault" in str(p.app_support_dir).lower()


# ═════════════════════════════════════════════════════════════════════════
# Idempotency & creation
# ═════════════════════════════════════════════════════════════════════════

class TestEnsureDirs:
    def test_ensure_dirs_creates_all(self, tmp_path):
        home = tmp_path / "sv_test"
        p = AppPaths.resolve(home_override=home)
        p.ensure_dirs()
        assert p.data_dir.is_dir()
        assert p.log_dir.is_dir()
        assert p.config_dir.is_dir()
        assert p.report_dir.is_dir()
        assert p.subtitle_dir.is_dir()
        assert p.transcript_cache_dir.is_dir()
        assert p.diagnostics_dir.is_dir()
        assert p.backup_dir.is_dir()
        assert p.cache_dir.is_dir()
        assert p.runtime_dir.is_dir()

    def test_ensure_dirs_idempotent(self, tmp_path):
        home = tmp_path / "sv_test"
        p = AppPaths.resolve(home_override=home)
        p.ensure_dirs()
        mtimes_before = {d: d.stat().st_mtime for d in [
            p.data_dir, p.log_dir, p.config_dir]}
        p.ensure_dirs()
        for d, mt in mtimes_before.items():
            assert d.stat().st_mtime == mt, f"{d} was recreated"


# ═════════════════════════════════════════════════════════════════════════
# No cwd dependency
# ═════════════════════════════════════════════════════════════════════════

class TestNoCwdDependency:
    def test_paths_independent_of_cwd(self, tmp_path, monkeypatch):
        """AppPaths should not change when cwd changes."""
        _set_env(monkeypatch, SIGNALVAULT_HOME="/tmp/sv_fixed")
        p1 = AppPaths.resolve()
        # Change cwd
        monkeypatch.chdir(str(tmp_path))
        p2 = AppPaths.resolve()
        assert p1.data_dir == p2.data_dir
        assert p1.log_dir == p2.log_dir
        assert p1.db_path == p2.db_path
        assert p1.settings_path == p2.settings_path


# ═════════════════════════════════════════════════════════════════════════
# config_store migration
# ═════════════════════════════════════════════════════════════════════════

class TestConfigStoreMigration:
    def test_new_path_used_when_no_legacy(self, tmp_path, monkeypatch):
        """C1-B: ConfigService reads from config.toml when no legacy exists."""
        import signalvault.config_store as cs
        from signalvault.settings.service import (
            ConfigService,
            _override_config_service,
        )

        home = tmp_path / "sv"
        paths = AppPaths.resolve(home_override=home)
        # Pre-populate config.toml via ConfigService
        from signalvault.settings.secret_store import SecretStore
        svc = ConfigService(paths, secret_store=SecretStore(paths.config_dir))
        svc.set_user_value("obsidian.vault_path", "/vault/new")
        _override_config_service(svc)
        monkeypatch.setattr(cs, "_get_legacy_path", lambda: None)
        monkeypatch.setattr(cs, "_get_settings_path",
                            lambda: paths.settings_path)

        result = cs.get_user_vault_path()
        assert result == "/vault/new"

    def test_legacy_migrated_on_first_read(self, tmp_path, monkeypatch):
        """When legacy JSON exists, migrate to ConfigService on first read."""
        import signalvault.config_store as cs
        from signalvault.settings.service import (
            ConfigService,
            _override_config_service,
        )

        home = tmp_path / "sv"
        paths = AppPaths.resolve(home_override=home)

        # Set up legacy JSON with vault path
        legacy = tmp_path / "legacy_data" / "user_settings.json"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(
            json.dumps({"obsidian_vault_path": "/vault/legacy"}),
            encoding="utf-8",
        )

        # Wire legacy path detection
        monkeypatch.setattr(cs, "_get_legacy_path", lambda: legacy)
        monkeypatch.setattr(cs, "_LEGACY_SETTINGS_PATH", legacy)
        monkeypatch.setattr(cs, "_get_settings_path",
                            lambda: paths.settings_path)

        # Create test ConfigService
        from signalvault.settings.secret_store import SecretStore
        svc = ConfigService(paths, secret_store=SecretStore(paths.config_dir))
        _override_config_service(svc)

        result = cs.get_user_vault_path()
        assert result == "/vault/legacy"
        # Should be stored in ConfigService now
        assert svc.get("obsidian.vault_path") == "/vault/legacy"
        # Legacy file still exists (not deleted)
        assert legacy.exists()

    def test_legacy_empty_does_not_migrate(self, tmp_path, monkeypatch):
        """Empty legacy file should not trigger migration."""
        import signalvault.config_store as cs

        home = tmp_path / "sv"
        new_path = AppPaths.resolve(home_override=home).settings_path
        new_path.parent.mkdir(parents=True, exist_ok=True)

        legacy = tmp_path / "legacy_data" / "user_settings.json"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("{}", encoding="utf-8")

        monkeypatch.setattr(cs, "_get_settings_path", lambda: new_path)
        monkeypatch.setattr(cs, "_SETTINGS_PATH", new_path)
        monkeypatch.setattr(cs, "_get_legacy_path", lambda: legacy)
        monkeypatch.setattr(cs, "_LEGACY_SETTINGS_PATH", legacy)

        result = cs.get_user_vault_path()
        # legacy was empty, so vault path should be empty
        assert result == ""

    def test_save_writes_to_new_path(self, tmp_path, monkeypatch):
        """C1-B: save_user_vault_path writes to ConfigService → config.toml."""
        import signalvault.config_store as cs
        from signalvault.settings.service import (
            ConfigService,
            _override_config_service,
        )

        home = tmp_path / "sv"
        paths = AppPaths.resolve(home_override=home)

        from signalvault.settings.secret_store import SecretStore
        svc = ConfigService(paths, secret_store=SecretStore(paths.config_dir))
        _override_config_service(svc)
        monkeypatch.setattr(cs, "_get_legacy_path", lambda: None)

        cs.save_user_vault_path("/my/vault")
        # config.toml should exist with the vault path
        config_toml = paths.config_dir / "config.toml"
        assert config_toml.exists()
        assert svc.get("obsidian.vault_path") == "/my/vault"

    def test_save_atomic(self, tmp_path, monkeypatch):
        """C1-B: ConfigService uses atomic write (tmp file then rename)."""
        import signalvault.config_store as cs
        from signalvault.settings.service import (
            ConfigService,
            _override_config_service,
        )

        home = tmp_path / "sv"
        paths = AppPaths.resolve(home_override=home)

        from signalvault.settings.secret_store import SecretStore
        svc = ConfigService(paths, secret_store=SecretStore(paths.config_dir))
        _override_config_service(svc)
        monkeypatch.setattr(cs, "_get_legacy_path", lambda: None)

        cs.save_user_vault_path("/vault/atomic")
        # No .tmp file left behind
        tmp_files = list(paths.config_dir.glob("*.tmp"))
        assert len(tmp_files) == 0
        assert svc.get("obsidian.vault_path") == "/vault/atomic"


# ═════════════════════════════════════════════════════════════════════════
# Test isolation
# ═════════════════════════════════════════════════════════════════════════

class TestTestIsolation:
    def test_app_paths_isolated_in_test(self, tmp_path):
        """The autouse fixture _isolate_app_paths should be active."""
        from signalvault import config
        # In tests, DATA_DIR should be inside tmp_path, not a real user dir
        data_dir_str = str(config.DATA_DIR)
        assert "SignalVault" in data_dir_str
        # Should NOT be in site-packages
        assert "site-packages" not in data_dir_str
        # Should NOT be in the real %APPDATA%
        real_appdata = os.getenv("APPDATA", "")
        if real_appdata:
            assert real_appdata not in data_dir_str

    def test_two_fixtures_dont_pollute(self, tmp_path):
        """Successive AppPaths.resolve() with different homes stay independent."""
        p1 = AppPaths.resolve(home_override=tmp_path / "a")
        p2 = AppPaths.resolve(home_override=tmp_path / "b")
        assert p1.data_dir != p2.data_dir
        assert p1.log_dir != p2.log_dir

    def test_editable_install_compatible(self):
        """In editable install, config._paths should work."""
        from signalvault import config
        # The module should load without error
        assert hasattr(config, "_paths")
        assert isinstance(config.DATA_DIR, Path)
        assert isinstance(config.get_app_paths(), AppPaths)


# ═════════════════════════════════════════════════════════════════════════
# config.py compatibility
# ═════════════════════════════════════════════════════════════════════════

class TestConfigCompatibility:
    def test_legacy_constants_still_work(self):
        """All legacy config constants must resolve to Path objects."""
        from signalvault import config
        for name in ("BASE_DIR", "DATA_DIR", "LOG_DIR", "DB_PATH",
                     "SUBTITLE_DIR", "REPORT_DIR", "TRANSCRIPT_CACHE_DIR"):
            val = getattr(config, name)
            assert isinstance(val, Path), f"config.{name} is not a Path: {type(val)}"

    def test_ensure_dirs_works(self, tmp_path, monkeypatch):
        """config.ensure_dirs() should create directories under the active AppPaths."""
        from signalvault import config
        from signalvault.settings.app_paths import AppPaths

        home = tmp_path / "compat_test"
        test_paths = AppPaths.resolve(home_override=home)
        monkeypatch.setattr(config, "_paths", test_paths)
        monkeypatch.setattr(config, "DATA_DIR", test_paths.data_dir)
        monkeypatch.setattr(config, "LOG_DIR", test_paths.log_dir)
        monkeypatch.setattr(config, "DB_PATH", test_paths.db_path)

        config.ensure_dirs()
        assert test_paths.data_dir.is_dir()
        assert test_paths.log_dir.is_dir()

    def test_llm_config_unchanged(self):
        """C1-A must not touch LLM config values."""
        from signalvault import config
        assert config.LLM_PROVIDER == "mock"  # test default
        assert isinstance(config.LLM_API_KEY, str)

    def test_obsidian_config_unchanged(self):
        """C1-A must not touch Obsidian config values."""
        from signalvault import config
        assert config.OBSIDIAN_VAULT_PATH == ""  # test default
        assert config.OBSIDIAN_EXPORT_ENABLED is False
