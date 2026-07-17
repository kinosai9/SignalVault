"""C2-B: Obsidian Settings Service — unified backend for HTML pages and JSON API.

Both the HTML templates and the /api/obsidian/* JSON endpoints call the
same functions here.  No template context ever contains vault document
contents or private file listings.

Design rules:
- SQLite is the primary data source; Obsidian is optional.
- Path operations use pathlib only — no shell, no system commands.
- All write operations are CSRF-protected at the route layer.
- Template context only carries safe status/path info.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# State model
# ═══════════════════════════════════════════════════════════════════════════════

class ObsidianState:
    DISABLED = "disabled"
    NOT_CONFIGURED = "not_configured"
    PATH_INVALID = "path_invalid"
    PATH_VALID_NOT_OBSIDIAN = "path_valid_not_obsidian"
    PATH_VALID_NOT_INITIALIZED = "path_valid_not_initialized"
    INITIALIZED = "initialized"
    NEEDS_REPAIR = "needs_repair"
    MANIFEST_CONFLICT = "manifest_conflict"


# ═══════════════════════════════════════════════════════════════════════════════
# View model (safe for templates — NO document content, NO private file lists)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ObsidianSettingsView:
    """All Obsidian settings data safe for template rendering."""

    # ── State ──────────────────────────────────────────────────────────────
    state: str = ObsidianState.NOT_CONFIGURED
    state_label: str = "未配置"

    # ── Configuration ──────────────────────────────────────────────────────
    enabled: bool = False
    vault_path: str = ""
    vault_path_source: str = "default"

    # ── Path validation ────────────────────────────────────────────────────
    path_valid: bool = False
    exists: bool = False
    is_directory: bool = False
    is_absolute: bool = False
    readable: bool = False
    writable: bool = False

    # ── Metadata ───────────────────────────────────────────────────────────
    has_obsidian_metadata: bool = False   # .obsidian/ directory present (informational)
    is_signalvault_initialized: bool = False  # manifest exists
    missing_directories: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)

    # ── Manifest info ──────────────────────────────────────────────────────
    manifest_exists: bool = False
    manifest_managed_by: str = ""
    manifest_conflict: bool = False
    vault_schema_version: int = 0
    initialized_at: str = ""
    last_repaired_at: str = ""

    # ── Initialization preview ─────────────────────────────────────────────
    preview_will_create_dirs: list[str] = field(default_factory=list)
    preview_will_create_files: list[str] = field(default_factory=list)
    preview_existing_items: list[str] = field(default_factory=list)

    # ── Warnings / errors ──────────────────────────────────────────────────
    error_message: str = ""
    warnings: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# Service helpers
# ═══════════════════════════════════════════════════════════════════════════════

# Dangerous paths that should trigger a strong warning or be rejected
_DANGEROUS_ROOTS = frozenset({
    "/", "C:\\", "C:", "D:\\", "D:",
})


def _get_svc():
    from signalvault.settings.service import get_config_service
    return get_config_service()


def _is_dangerous_path(path: str) -> bool:
    """Check if the path is a system root or other dangerous location.

    Only flags paths that ARE dangerous locations, not paths that merely
    contain a dangerous component as an ancestor (e.g. a temp dir under
    AppData is fine; using AppData itself as the vault root is not).
    """
    p = Path(path).resolve()
    p_str = str(p)

    # System root
    if p_str in _DANGEROUS_ROOTS or p_str in ("/",):
        return True

    # User home root
    home = Path.home()
    if p_str == str(home):
        return True

    # Check if the vault path itself is a known dangerous directory
    # (not just that an ancestor contains it)
    dangerous_names = frozenset({
        "site-packages",
        "Application Data",
        "AppData",
        "Local",
        "Roaming",
    })
    # The vault directory name itself should not be a system dir
    if p.name in dangerous_names:
        return True

    # The parent directory name should not be site-packages
    return p.parent.name == "site-packages"


# ═══════════════════════════════════════════════════════════════════════════════
# Read: build the settings view
# ═══════════════════════════════════════════════════════════════════════════════


def get_obsidian_settings_view() -> ObsidianSettingsView:
    """Build the Obsidian settings view model from ConfigService.

    Safe for templates — never includes vault document contents.

    Obsidian integration is enabled whenever a vault path is configured.
    There is no separate enable/disable toggle — clear the path to disable.
    """
    svc = _get_svc()
    view = ObsidianSettingsView()

    # Read config
    vault_path_cv = svc.get_with_source("obsidian.vault_path")
    view.vault_path = str(vault_path_cv.value) if vault_path_cv.value else ""
    view.vault_path_source = vault_path_cv.source

    # Enabled = path is configured (automatic; no separate toggle needed)
    view.enabled = bool(view.vault_path)

    # Compute state
    if not view.vault_path:
        view.state = ObsidianState.NOT_CONFIGURED
        view.state_label = "未配置"
        return view

    # Validate the path
    from signalvault.settings.obsidian_validator import validate_obsidian_vault_path
    vr = validate_obsidian_vault_path(view.vault_path)

    view.path_valid = vr.path_valid
    view.exists = vr.exists
    view.is_directory = vr.is_directory
    view.is_absolute = vr.is_absolute
    view.readable = vr.is_readable
    view.writable = vr.is_writable
    view.has_obsidian_metadata = vr.has_obsidian_metadata
    view.is_signalvault_initialized = vr.is_signalvault_initialized
    view.missing_directories = list(vr.missing_dirs)
    view.missing_files = list(vr.missing_files)
    view.error_message = vr.error_message

    # Manifest info
    _populate_manifest(view)

    # Determine state
    view.state = _compute_state(view)
    view.state_label = _compute_state_label(view)

    # Build initialization preview
    _populate_preview(view)

    return view


def _populate_manifest(view: ObsidianSettingsView) -> None:
    """Read manifest and populate view fields."""
    if not view.vault_path or not view.exists:
        return

    from signalvault.settings.vault_manifest import (
        MANAGED_BY,
        ManifestConflictError,
        read_manifest,
    )

    try:
        manifest = read_manifest(view.vault_path)
        if manifest is not None:
            view.manifest_exists = True
            view.manifest_managed_by = manifest.managed_by
            view.manifest_conflict = manifest.managed_by != MANAGED_BY
            view.vault_schema_version = manifest.vault_schema_version
            view.initialized_at = manifest.initialized_at
            view.last_repaired_at = manifest.last_repaired_at
    except ManifestConflictError:
        view.manifest_conflict = True
    except Exception:
        pass


def _populate_preview(view: ObsidianSettingsView) -> None:
    """Compute what initialization would create."""
    if not view.vault_path or not view.path_valid:
        return

    from signalvault.workspace.setup import REQUIRED_DIRS, REQUIRED_FILES

    vault = Path(view.vault_path)
    for d in REQUIRED_DIRS:
        full = vault / d
        if not full.exists():
            view.preview_will_create_dirs.append(d)
        else:
            view.preview_existing_items.append(f"{d}/ (已存在)")

    for f in REQUIRED_FILES:
        full = vault / f
        if not full.exists():
            view.preview_will_create_files.append(f)
        else:
            view.preview_existing_items.append(f"{f} (已存在)")


def _compute_state(view: ObsidianSettingsView) -> str:
    """Compute the canonical state from view fields."""
    if view.manifest_conflict:
        return ObsidianState.MANIFEST_CONFLICT

    if not view.path_valid:
        return ObsidianState.PATH_INVALID

    if view.is_signalvault_initialized:
        # Check if repair is needed
        if view.missing_directories or view.missing_files:
            return ObsidianState.NEEDS_REPAIR
        return ObsidianState.INITIALIZED

    # Path is valid but not initialized
    if not view.has_obsidian_metadata:
        return ObsidianState.PATH_VALID_NOT_OBSIDIAN
    return ObsidianState.PATH_VALID_NOT_INITIALIZED


def _compute_state_label(view: ObsidianSettingsView) -> str:
    """Human-readable state label."""
    labels = {
        ObsidianState.DISABLED: "已禁用",
        ObsidianState.NOT_CONFIGURED: "未配置",
        ObsidianState.PATH_INVALID: "路径无效",
        ObsidianState.PATH_VALID_NOT_OBSIDIAN: "路径有效（未检测到 Obsidian）",
        ObsidianState.PATH_VALID_NOT_INITIALIZED: "路径有效（尚未初始化）",
        ObsidianState.INITIALIZED: "已初始化",
        ObsidianState.NEEDS_REPAIR: "需要修复",
        ObsidianState.MANIFEST_CONFLICT: "Manifest 冲突",
    }
    return labels.get(view.state, view.state)


# ═══════════════════════════════════════════════════════════════════════════════
# Write: update settings
# ═══════════════════════════════════════════════════════════════════════════════


def update_obsidian_settings(fields: dict[str, Any]) -> dict[str, Any]:
    """Update Obsidian configuration from a dict of field values.

    Args:
        fields: Dict with any of: vault_path, enabled

    Returns:
        {"ok": true, "updated": [...]} or {"ok": false, "error": "..."}
    """
    svc = _get_svc()
    updated: list[str] = []

    if "vault_path" in fields:
        raw_path = str(fields["vault_path"]).strip()
        if not raw_path:
            return {"ok": False, "error": "路径不能为空"}

        p = Path(raw_path)
        if not p.is_absolute():
            return {"ok": False, "error": "请输入完整的绝对路径（例如 C:\\Users\\...\\MyVault）"}

        if _is_dangerous_path(raw_path):
            return {"ok": False, "error": "不能使用系统根目录或用户主目录作为知识库路径"}

        # Normalize and save
        normalized = str(p.resolve()) if p.exists() else str(p)
        svc.set_user_value("obsidian.vault_path", normalized)
        updated.append("obsidian.vault_path")

    if "enabled" in fields:
        enabled_val = fields["enabled"]
        if isinstance(enabled_val, str):
            enabled_val = enabled_val.lower() in ("true", "1", "yes", "on")
        svc.set_user_value("obsidian.export_enabled", bool(enabled_val))
        updated.append("obsidian.export_enabled")

    return {"ok": True, "updated": updated}


# ═══════════════════════════════════════════════════════════════════════════════
# Validate path (without saving)
# ═══════════════════════════════════════════════════════════════════════════════


def validate_obsidian_path(path: str) -> dict[str, Any]:
    """Validate a candidate vault path without saving it.

    Returns a dict with validation result fields.
    """
    from signalvault.settings.obsidian_validator import validate_obsidian_vault_path

    result = validate_obsidian_vault_path(path)

    resp: dict[str, Any] = {
        "path": result.path,
        "path_valid": result.path_valid,
        "exists": result.exists,
        "is_directory": result.is_directory,
        "is_absolute": result.is_absolute,
        "is_readable": result.is_readable,
        "is_writable": result.is_writable,
        "has_obsidian_metadata": result.has_obsidian_metadata,
        "is_signalvault_initialized": result.is_signalvault_initialized,
        "missing_dirs": result.missing_dirs,
        "missing_files": result.missing_files,
        "error_message": result.error_message,
        "is_dangerous": _is_dangerous_path(path),
    }
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# Initialization preview
# ═══════════════════════════════════════════════════════════════════════════════


def preview_vault_initialization(path: str) -> dict[str, Any]:
    """Preview what initialization will create/keep at *path*.

    Does NOT modify the filesystem.
    """
    from signalvault.workspace.setup import REQUIRED_DIRS, REQUIRED_FILES

    vault = Path(path)
    will_create_dirs: list[str] = []
    will_create_files: list[str] = []
    existing: list[str] = []

    for d in REQUIRED_DIRS:
        full = vault / d
        if not full.exists():
            will_create_dirs.append(d)
        else:
            existing.append(f"{d}/")

    for f in REQUIRED_FILES:
        full = vault / f
        if not full.exists():
            will_create_files.append(f)
        else:
            existing.append(f)

    # Check manifest status
    from signalvault.settings.vault_manifest import (
        MANAGED_BY,
        ManifestConflictError,
        read_manifest,
    )

    manifest_status = "will_create"
    manifest_managed_by = ""
    try:
        m = read_manifest(vault)
        if m is not None:
            manifest_status = "exists"
            manifest_managed_by = m.managed_by
    except ManifestConflictError:
        manifest_status = "conflict"
    except Exception:
        manifest_status = "will_create"

    return {
        "path": str(vault),
        "will_create_dirs": will_create_dirs,
        "will_create_files": will_create_files,
        "existing_items": existing,
        "manifest_status": manifest_status,
        "manifest_managed_by": manifest_managed_by,
        "manifest_conflict": manifest_managed_by not in ("", MANAGED_BY),
        "is_dangerous": _is_dangerous_path(path),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Initialize vault
# ═══════════════════════════════════════════════════════════════════════════════


def initialize_obsidian_vault(path: str) -> dict[str, Any]:
    """Initialize a SignalVault structure in an Obsidian vault.

    - Idempotent: only creates missing items, never overwrites
    - Writes manifest atomically
    - Refuses on manifest conflict
    - Validates path safety
    """
    from signalvault.settings.vault_manifest import (
        ManifestConflictError,
        ensure_manifest,
    )
    from signalvault.workspace.setup import initialize_vault

    p = Path(path)

    # Safety checks
    if not p.is_absolute():
        return {"ok": False, "error": "请输入完整的绝对路径"}
    if _is_dangerous_path(str(p)):
        return {"ok": False, "error": "不能使用系统根目录或用户主目录作为知识库路径"}

    # Check manifest conflict before init
    manifest_path = p / "99_System" / "signalvault_manifest.json"
    if manifest_path.exists():
        try:
            ensure_manifest(p, app_version=_app_version())
        except ManifestConflictError as e:
            return {"ok": False, "error": str(e), "error_type": "manifest_conflict"}
    else:
        # Manifest doesn't exist yet — will be created
        pass

    # Initialize vault structure
    try:
        result = initialize_vault(p)
    except PermissionError:
        return {"ok": False, "error": "没有写入权限，请检查目录权限"}
    except OSError as e:
        return {"ok": False, "error": f"无法创建知识库结构: {e}"}

    # Ensure manifest (will be created by initialize_vault, but be explicit)
    try:
        manifest = ensure_manifest(p, app_version=_app_version())
    except ManifestConflictError as e:
        return {"ok": False, "error": str(e), "error_type": "manifest_conflict"}

    return {
        "ok": True,
        "vault_path": str(p),
        "created_dirs": result.created_dirs,
        "created_files": result.created_files,
        "skipped_existing": result.skipped_existing,
        "warnings": result.warnings,
        "manifest": {
            "vault_schema_version": manifest.vault_schema_version,
            "initialized_at": manifest.initialized_at,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Repair vault
# ═══════════════════════════════════════════════════════════════════════════════


def repair_obsidian_vault(path: str) -> dict[str, Any]:
    """Repair a vault: fill in missing dirs/files and update manifest.

    - Never overwrites existing files
    - Refuses on manifest conflict
    - Only adds missing items
    """
    from signalvault.settings.vault_manifest import (
        ManifestConflictError,
        repair_manifest,
    )
    from signalvault.workspace.setup import repair_vault

    p = Path(path)

    if not p.is_absolute():
        return {"ok": False, "error": "请输入完整的绝对路径"}

    # Repair vault structure (non-destructive)
    try:
        result = repair_vault(p)
    except PermissionError:
        return {"ok": False, "error": "没有写入权限"}
    except OSError as e:
        return {"ok": False, "error": f"修复失败: {e}"}

    # Update manifest
    try:
        manifest = repair_manifest(p)
        if manifest is None:
            return {"ok": False, "error": "Manifest 由其他工具管理，无法修复", "error_type": "manifest_conflict"}
    except ManifestConflictError:
        return {"ok": False, "error": "Manifest 由其他工具管理，无法修复", "error_type": "manifest_conflict"}

    return {
        "ok": True,
        "vault_path": str(p),
        "created_dirs": result.created_dirs,
        "created_files": result.created_files,
        "skipped_existing": result.skipped_existing,
        "warnings": result.warnings,
        "last_repaired_at": manifest.last_repaired_at if manifest else "",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Test write
# ═══════════════════════════════════════════════════════════════════════════════


def test_obsidian_write(path: str) -> dict[str, Any]:
    """Create a temporary test file, verify write, then delete it.

    Does NOT overwrite existing user files.
    """
    p = Path(path)

    if not p.is_absolute():
        return {"ok": False, "error": "请输入完整的绝对路径"}
    if not p.is_dir():
        return {"ok": False, "error": "路径不存在或不是目录"}

    test_file = p / ".signalvault_test_write"
    try:
        test_file.write_text("signalvault-write-test", encoding="utf-8")
        test_file.unlink()
        return {"ok": True, "message": "写入测试成功"}
    except PermissionError:
        return {"ok": False, "error": "写入测试失败：权限不足"}
    except OSError as e:
        return {"ok": False, "error": f"写入测试失败: {e}"}

    # Cleanup attempt if unlink failed
    if test_file.exists():
        try:
            test_file.unlink()
        except OSError:
            logger.warning("Could not clean up test file: %s", test_file)
            return {"ok": True, "message": "写入测试成功", "warning": "测试文件未能自动清理，请手动删除 .signalvault_test_write"}

    return {"ok": True, "message": "写入测试成功"}


# ═══════════════════════════════════════════════════════════════════════════════
# Disable integration
# ═══════════════════════════════════════════════════════════════════════════════


def disable_obsidian_integration() -> dict[str, Any]:
    """Disable Obsidian integration by clearing the vault path.

    - Clears vault_path (no path = integration dormant)
    - Does NOT delete vault files
    - Does NOT modify SQLite
    - Re-enable by re-configuring a vault path
    """
    svc = _get_svc()
    svc.delete_user_value("obsidian.vault_path")
    return {
        "ok": True,
        "message": "Obsidian 集成已停用（路径已清除）。知识库文件未被删除，SQLite 数据未受影响。",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Clear vault path
# ═══════════════════════════════════════════════════════════════════════════════


def clear_vault_path() -> dict[str, Any]:
    """Clear the saved vault path without deleting vault files."""
    svc = _get_svc()
    svc.delete_user_value("obsidian.vault_path")
    svc.set_user_value("obsidian.export_enabled", False)
    return {
        "ok": True,
        "message": "已清除保存的 Vault 路径。知识库文件未被删除。",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _app_version() -> str:
    """Best-effort app version for manifest."""
    try:
        from signalvault import __version__
        return __version__
    except (ImportError, AttributeError):
        return "0.0.0"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
