"""C1-A: Unified, platform-aware application paths.

Resolution priority:
    1. Explicit constructor `home_override` (SIGNALVAULT_HOME)
    2. Legacy env vars: DATA_DIR, LOG_DIR, DB_PATH (individual overrides)
    3. Platform defaults (Windows/macOS/Linux)

Every path that holds user data MUST go through AppPaths so that
- tests can isolate to tmp_path,
- clean-install users never write into site-packages or the repo,
- macOS .app bundles get proper Application Support paths.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _platform_data_dir(app_name: str) -> Path:
    """Platform-default application data root.

    Windows:  %APPDATA%/<app_name>
    macOS:    ~/Library/Application Support/<app_name>
    Linux:    $XDG_DATA_HOME/<app_name>  (falls back to ~/.local/share/<app_name>)
    """
    if sys.platform == "win32":
        base = os.getenv("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(base) / app_name
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name
    # Linux / other Unix
    xdg = os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg) / app_name.lower()


def _platform_cache_dir(app_name: str) -> Path:
    """Platform-default cache directory.

    Windows:  %LOCALAPPDATA%/<app_name>/cache
    macOS:    ~/Library/Caches/<app_name>
    Linux:    $XDG_CACHE_HOME/<app_name>  (falls back to ~/.cache/<app_name>)
    """
    if sys.platform == "win32":
        base = os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return Path(base) / app_name / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / app_name
    xdg = os.getenv("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    return Path(xdg) / app_name.lower()


@dataclass(frozen=True)
class AppPaths:
    """Platform-aware application paths.

    Create via ``AppPaths.resolve()`` for production or via the constructor
    with ``home_override`` for tests.
    """

    app_name: str = "SignalVault"

    # ── internal: resolved root ──────────────────────────────────────────
    _home: Path = field(default_factory=lambda: Path("."), repr=False)

    # ── legacy overrides (None = use platform default) ───────────────────
    _data_dir_override: str | None = field(default=None, repr=False)
    _log_dir_override: str | None = field(default=None, repr=False)
    _db_path_override: str | None = field(default=None, repr=False)

    # ═════════════════════════════════════════════════════════════════════
    # Factory
    # ═════════════════════════════════════════════════════════════════════

    @classmethod
    def resolve(
        cls,
        *,
        home_override: str | Path | None = None,
        app_name: str = "SignalVault",
    ) -> "AppPaths":
        """Resolve paths from env vars, falling back to platform defaults.

        ``home_override`` acts as SIGNALVAULT_HOME — every data directory
        lives under it, organised into config/data/logs/cache/… subdirs.
        """
        # 1. SIGNALVAULT_HOME
        home_str = (
            _coerce_path_str(home_override)
            or os.getenv("SIGNALVAULT_HOME", "")
        )
        home = Path(home_str) if home_str else _platform_data_dir(app_name)

        # 2. Legacy individual overrides
        data_override = os.getenv("DATA_DIR", "")
        log_override = os.getenv("LOG_DIR", "")
        db_override = os.getenv("DB_PATH", "")

        return cls(
            app_name=app_name,
            _home=home,
            _data_dir_override=data_override or None,
            _log_dir_override=log_override or None,
            _db_path_override=db_override or None,
        )

    # ═════════════════════════════════════════════════════════════════════
    # Top-level directories
    # ═════════════════════════════════════════════════════════════════════

    @property
    def app_support_dir(self) -> Path:
        """Root for ALL user data.  Equivalent to SIGNALVAULT_HOME."""
        return self._home

    @property
    def config_dir(self) -> Path:
        """Persistent configuration (user_settings.json, future config.toml)."""
        return self.app_support_dir / "config"

    @property
    def data_dir(self) -> Path:
        """Application data: DB, reports, subtitles, transcripts, FTS."""
        if self._data_dir_override:
            return Path(self._data_dir_override)
        return self.app_support_dir / "data"

    @property
    def log_dir(self) -> Path:
        """Rotating log files."""
        if self._log_dir_override:
            return Path(self._log_dir_override)
        return self.app_support_dir / "logs"

    @property
    def cache_dir(self) -> Path:
        """Transient cache (may be cleared by OS)."""
        return _platform_cache_dir(self.app_name)

    @property
    def backup_dir(self) -> Path:
        """User-visible backups."""
        return self.app_support_dir / "backups"

    @property
    def diagnostics_dir(self) -> Path:
        """Diagnostic bundle staging area."""
        return self.app_support_dir / "diagnostics"

    @property
    def runtime_dir(self) -> Path:
        """PID files, lock files, unix sockets (not used yet)."""
        return self.app_support_dir / "runtime"

    # ═════════════════════════════════════════════════════════════════════
    # Derived data paths
    # ═════════════════════════════════════════════════════════════════════

    @property
    def db_path(self) -> Path:
        """SQLite database file."""
        if self._db_path_override:
            return Path(self._db_path_override)
        return self.data_dir / "signalvault.db"

    @property
    def report_dir(self) -> Path:
        """Rendered Markdown reports (legacy on-disk copies)."""
        return self.data_dir / "reports"

    @property
    def subtitle_dir(self) -> Path:
        """Cached subtitle files (.srt/.vtt)."""
        return self.data_dir / "subtitles"

    @property
    def transcript_cache_dir(self) -> Path:
        """Cached YouTube transcripts."""
        return self.data_dir / "transcripts" / "youtube"

    @property
    def settings_path(self) -> Path:
        """User settings persistence (config_store.py)."""
        return self.config_dir / "user_settings.json"

    # ═════════════════════════════════════════════════════════════════════
    # Helpers
    # ═════════════════════════════════════════════════════════════════════

    def ensure_dirs(self) -> None:
        """Create all data directories.  Idempotent."""
        for d in [
            self.config_dir,
            self.data_dir,
            self.log_dir,
            self.report_dir,
            self.subtitle_dir,
            self.transcript_cache_dir,
            self.diagnostics_dir,
            self.backup_dir,
            self.cache_dir,
            self.runtime_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)

    def is_using_platform_default(self) -> bool:
        """True when neither SIGNALVAULT_HOME nor legacy vars are set."""
        return (
            not os.getenv("SIGNALVAULT_HOME", "")
            and not self._data_dir_override
            and not self._log_dir_override
            and not self._db_path_override
        )


def _coerce_path_str(value: str | Path | None) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None
