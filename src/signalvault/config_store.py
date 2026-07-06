"""P2-L.1: Lightweight user settings store.

Persists user preferences to data/user_settings.json.
Priority for each setting: user_settings.json > env var > default.

No external dependencies. Thread-safe enough for single-user local tool.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_SETTINGS_PATH: Path | None = None


def _get_settings_path() -> Path:
    global _SETTINGS_PATH
    if _SETTINGS_PATH is not None:
        return _SETTINGS_PATH
    # Resolve relative to project root (where data/ lives)
    candidate = Path(os.getcwd()) / "data" / "user_settings.json"
    _SETTINGS_PATH = candidate
    return candidate


def _override_settings_path(path: Path) -> None:
    """For testing: override the settings file path."""
    global _SETTINGS_PATH
    _SETTINGS_PATH = path


def _load() -> dict:
    path = _get_settings_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    path = _get_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_user_vault_path() -> str:
    """Return the resolved Obsidian vault path.

    Priority:
        1. data/user_settings.json -> obsidian_vault_path
        2. OBSIDIAN_VAULT_PATH env var
        3. "" (not configured)
    """
    settings = _load()
    path = settings.get("obsidian_vault_path", "")
    if path:
        return path
    return os.getenv("OBSIDIAN_VAULT_PATH", "")


def save_user_vault_path(path: str | Path) -> None:
    """Persist vault path to user_settings.json."""
    settings = _load()
    settings["obsidian_vault_path"] = str(path)
    _save(settings)
