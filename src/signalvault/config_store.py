"""P2-L.1 / C1-B: User settings store — backwards-compatible facade.

C1-B: ``get_user_vault_path()`` and ``save_user_vault_path()`` now delegate
to ConfigService under ``obsidian.vault_path``.  The old ``user_settings.json``
file is migrated to config.toml on first access and never deleted.

Legacy JSON path (pre-C1-A):  ``<repo>/data/user_settings.json``
C1-A path:                     ``<AppPaths.config_dir>/user_settings.json``
C1-B path:                     ``<AppPaths.config_dir>/config.toml`` (via ConfigService)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Legacy migration helpers (kept for C1-A compatibility) ──────────────────

_SETTINGS_PATH: Path | None = None
_LEGACY_SETTINGS_PATH: Path | None = None


def _get_settings_path() -> Path:
    """Return the C1-A settings path (used during migration only)."""
    global _SETTINGS_PATH
    if _SETTINGS_PATH is not None:
        return _SETTINGS_PATH
    from signalvault.config import get_app_paths
    _SETTINGS_PATH = get_app_paths().settings_path
    return _SETTINGS_PATH


def _get_legacy_path() -> Path | None:
    """Pre-C1-A settings file location."""
    global _LEGACY_SETTINGS_PATH
    if _LEGACY_SETTINGS_PATH is not None:
        return _LEGACY_SETTINGS_PATH
    from signalvault.config import BASE_DIR
    candidate = BASE_DIR / "data" / "user_settings.json"
    if candidate.exists():
        _LEGACY_SETTINGS_PATH = candidate
        return candidate
    _LEGACY_SETTINGS_PATH = None
    return None


def _override_settings_path(path: Path) -> None:
    """Testing: override the settings file path."""
    global _SETTINGS_PATH
    _SETTINGS_PATH = path


# ── Public API (delegates to ConfigService) ─────────────────────────────────

def get_user_vault_path() -> str:
    """Return the persisted Obsidian vault path.

    Priority:
        1. ConfigService (config.toml → obsidian.vault_path)
        2. C1-A user_settings.json (migrated on first read)
        3. Legacy repo data/user_settings.json (migrated on first read)
        4. OBSIDIAN_VAULT_PATH env var (via ConfigService)
        5. "" (not configured)
    """
    from signalvault.settings.service import get_config_service

    svc = get_config_service()
    cv = svc.get_with_source("obsidian.vault_path")

    # If user hasn't set it via ConfigService, try migration sources
    if cv.source == "default" or not cv.value:
        migrated = _try_migrate_vault_path(svc)
        if migrated:
            return migrated

    return str(cv.value) if cv.value else ""


def save_user_vault_path(path: str | Path) -> None:
    """Persist vault path via ConfigService."""
    from signalvault.settings.service import get_config_service

    svc = get_config_service()
    svc.set_user_value("obsidian.vault_path", str(path))


# ── Migration ───────────────────────────────────────────────────────────────

def _try_migrate_vault_path(svc) -> str | None:
    """Attempt to migrate vault path from legacy JSON files to ConfigService.

    Returns the vault path string if found, or None.
    """
    # 1. Try C1-A settings path
    c1a_path = _get_settings_path()
    vault = _read_vault_from_json(c1a_path)
    if vault:
        logger.info("config_store: migrating vault path from %s to ConfigService", c1a_path)
        svc.set_user_value("obsidian.vault_path", vault)
        return vault

    # 2. Try legacy repo path
    legacy = _get_legacy_path()
    if legacy:
        vault = _read_vault_from_json(legacy)
        if vault:
            logger.info("config_store: migrating vault path from %s to ConfigService", legacy)
            svc.set_user_value("obsidian.vault_path", vault)
            return vault

    return None


def _read_vault_from_json(path: Path) -> str | None:
    """Read obsidian_vault_path from a JSON settings file."""
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        val = data.get("obsidian_vault_path", "")
        return val if val else None
    except (json.JSONDecodeError, OSError):
        return None
