"""C1-C: Vault Manifest — metadata file for SignalVault-managed Obsidian vaults.

Writes ``99_System/signalvault_manifest.json`` with atomic (tmp+replace) I/O.
Supports idempotent init, safe backfill for pre-manifest vaults, and repair.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "signalvault_manifest.json"
MANAGED_BY = "signalvault"
CURRENT_SCHEMA_VERSION = 1


@dataclass
class VaultManifest:
    managed_by: str = MANAGED_BY
    vault_schema_version: int = CURRENT_SCHEMA_VERSION
    initialized_at: str = ""       # ISO 8601 UTC
    last_repaired_at: str = ""     # ISO 8601 UTC
    app_version: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# Read
# ═══════════════════════════════════════════════════════════════════════════════


def read_manifest(vault_path: str | Path) -> VaultManifest | None:
    """Read an existing manifest.  Returns None if missing or corrupt."""
    manifest_path = _manifest_path(vault_path)
    if not manifest_path.is_file():
        return None
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        return VaultManifest(
            managed_by=raw.get("managed_by", MANAGED_BY),
            vault_schema_version=raw.get("vault_schema_version", CURRENT_SCHEMA_VERSION),
            initialized_at=raw.get("initialized_at", ""),
            last_repaired_at=raw.get("last_repaired_at", ""),
            app_version=raw.get("app_version", ""),
        )
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Vault manifest corrupt at %s: %s", manifest_path, e)
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Write / Ensure / Repair
# ═══════════════════════════════════════════════════════════════════════════════


def ensure_manifest(
    vault_path: str | Path,
    *,
    app_version: str = "",
) -> VaultManifest:
    """Idempotent: create manifest if missing, otherwise leave unchanged.

    For existing vaults that predate manifest support, backfill safely.
    Returns the (new or existing) manifest.
    """
    manifest_path = _manifest_path(vault_path)
    existing = read_manifest(vault_path)

    if existing is not None:
        # Conflict check: refuse to overwrite a manifest from another tool
        if existing.managed_by != MANAGED_BY:
            raise ManifestConflictError(
                f"Vault at {vault_path} is managed by '{existing.managed_by}', "
                f"not '{MANAGED_BY}'. Refusing to overwrite."
            )
        # Already exists and is ours — leave unchanged
        return existing

    # Create new manifest
    now = _utcnow_iso()
    manifest = VaultManifest(
        managed_by=MANAGED_BY,
        vault_schema_version=CURRENT_SCHEMA_VERSION,
        initialized_at=now,
        app_version=app_version,
    )
    _write(manifest_path, manifest)
    logger.info("Created vault manifest at %s", manifest_path)
    return manifest


def repair_manifest(vault_path: str | Path) -> VaultManifest | None:
    """Update last_repaired_at on an existing manifest.

    Creates the manifest if it doesn't exist (backfill).
    Returns None if the manifest is owned by another tool (conflict).
    """
    manifest_path = _manifest_path(vault_path)

    existing = read_manifest(vault_path)
    if existing is not None:
        if existing.managed_by != MANAGED_BY:
            logger.warning(
                "Vault at %s managed by '%s' — skipping repair",
                vault_path, existing.managed_by,
            )
            return None
        # Update last_repaired_at
        now = _utcnow_iso()
        manifest = VaultManifest(
            managed_by=existing.managed_by,
            vault_schema_version=existing.vault_schema_version,
            initialized_at=existing.initialized_at,
            last_repaired_at=now,
            app_version=existing.app_version,
        )
        _write(manifest_path, manifest)
        return manifest

    # Backfill: vault predates manifest support
    return ensure_manifest(vault_path)


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _manifest_path(vault_path: str | Path) -> Path:
    return Path(vault_path) / "99_System" / MANIFEST_FILENAME


def _write(path: Path, manifest: VaultManifest) -> None:
    """Atomic write via temp + replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "managed_by": manifest.managed_by,
            "vault_schema_version": manifest.vault_schema_version,
            "initialized_at": manifest.initialized_at,
            "last_repaired_at": manifest.last_repaired_at,
            "app_version": manifest.app_version,
        },
        ensure_ascii=False,
        indent=2,
    )
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ═══════════════════════════════════════════════════════════════════════════════
# Errors
# ═══════════════════════════════════════════════════════════════════════════════


class ManifestConflictError(Exception):
    """Raised when attempting to overwrite a manifest owned by another tool."""
