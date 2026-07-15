"""SignalVault global configuration (compatibility facade).

C1-A: Path constants resolved via ``AppPaths``.
C1-B: LLM, Obsidian, logging values delegated to ``ConfigService``.

Module-level names are resolved via ConfigService at access time so there is
a single source of truth.  ``from config import LLM_PROVIDER`` still works
(import caches the snapshot, same as before).
"""

from pathlib import Path

from dotenv import load_dotenv

from signalvault.settings.app_paths import AppPaths

load_dotenv()

# ── AppPaths singleton ────────────────────────────────────────────────────
_paths = AppPaths.resolve()

# ── Source-root anchor (templates, static files — NOT user data) ──────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ── Path constants (delegated to AppPaths; stable after import) ───────────
DATA_DIR = _paths.data_dir
LOG_DIR = _paths.log_dir
DB_PATH = _paths.db_path
SUBTITLE_DIR = _paths.subtitle_dir
REPORT_DIR = _paths.report_dir
TRANSCRIPT_CACHE_DIR = _paths.transcript_cache_dir


# ── ConfigService-backed names ────────────────────────────────────────────
# These are resolved through __getattr__ so they always come from
# ConfigService (single source of truth).  ``from config import LLM_PROVIDER``
# snapshots the value at import time as it always did.

_CONFIG_NAME_MAP: dict[str, str] = {
    "LLM_PROVIDER":           "llm.provider",
    "LLM_MODEL":              "llm.model",
    "LLM_BASE_URL":           "llm.base_url",
    "LLM_API_KEY":            "llm.api_key",
    "LOG_LEVEL":              "logging.level",
    "OBSIDIAN_VAULT_PATH":    "obsidian.vault_path",
    "OBSIDIAN_EXPORT_ENABLED": "obsidian.export_enabled",
}


def __getattr__(name: str):
    """Resolve legacy config names via ConfigService."""
    if name in _CONFIG_NAME_MAP:
        from signalvault.settings.service import get_config_service
        svc = get_config_service()
        key = _CONFIG_NAME_MAP[name]
        if key in ("llm.api_key",):
            return svc.get_secret(key) or ""
        return svc.get(key)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def ensure_dirs() -> None:
    """Create all data directories.  Idempotent."""
    _paths.ensure_dirs()


def get_app_paths() -> AppPaths:
    """Return the resolved AppPaths instance."""
    return _paths
