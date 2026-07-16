"""C1-C: Obsidian Validator — vault path validation backend.

Wraps ``workspace/setup.py:validate_vault()`` with additional filesystem
checks.  Does NOT require Obsidian to be installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ObsidianValidationResult:
    """Result of vault path validation.

    ``path_valid`` means the directory exists, is absolute, readable, and
    writable — regardless of Obsidian or SignalVault metadata.
    ``has_obsidian_metadata`` (``.obsidian/``) is informational only
    and does NOT make a valid path invalid.
    """

    path: str = ""
    path_valid: bool = False                 # passes basic filesystem checks
    exists: bool = False
    is_directory: bool = False
    is_absolute: bool = False
    is_readable: bool = False
    is_writable: bool = False
    has_obsidian_metadata: bool = False      # .obsidian/ directory present (informational)
    is_signalvault_initialized: bool = False  # manifest exists
    missing_dirs: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    test_write_ok: bool = False
    error_message: str = ""


def validate_obsidian_vault_path(vault_path: str) -> ObsidianValidationResult:
    """Validate a candidate vault path.

    Checks in order:
    1. Non-empty
    2. Absolute path
    3. Exists
    4. Is a directory
    5. Readable
    6. Writable (test write)
    7. Contains .obsidian/ (optional — informational)
    8. SignalVault initialized (manifest check)
    9. Vault structure validation (delegates to workspace/setup.py)
    """
    result = ObsidianValidationResult(path=vault_path)

    # 1. Non-empty
    if not vault_path or not vault_path.strip():
        result.error_message = "路径不能为空"
        return result

    vault_path = vault_path.strip()
    result.path = vault_path
    p = Path(vault_path)

    # 2. Absolute
    result.is_absolute = p.is_absolute()
    if not result.is_absolute:
        result.error_message = "请输入完整的绝对路径"
        return result

    # 3. Exists
    result.exists = p.exists()
    if not result.exists:
        result.error_message = f"路径不存在: {vault_path}"
        return result

    # 4. Is directory
    result.is_directory = p.is_dir()
    if not result.is_directory:
        result.error_message = "路径不是一个目录"
        return result

    # 5. Readable
    result.is_readable = _check_readable(p)
    if not result.is_readable:
        result.error_message = "目录不可读，请检查权限"
        return result

    # 6. Writable
    result.test_write_ok = _check_writable(p)
    result.is_writable = result.test_write_ok
    if not result.is_writable:
        result.error_message = "目录不可写，请检查权限"
        return result

    # All basic checks passed — path is valid for use
    result.path_valid = True

    # 7. .obsidian/ directory (informational only — does not affect path_valid)
    result.has_obsidian_metadata = (p / ".obsidian").is_dir()

    # 8. SignalVault manifest
    manifest_path = p / "99_System" / "signalvault_manifest.json"
    result.is_signalvault_initialized = manifest_path.is_file()

    # 9. Vault structure validation
    try:
        from signalvault.workspace.setup import validate_vault
        vault_result = validate_vault(p)
        result.missing_dirs = list(vault_result.missing_dirs)
        result.missing_files = list(vault_result.missing_files)
    except Exception:
        # Structure check failure is non-fatal for path_valid
        pass

    return result


def _check_readable(p: Path) -> bool:
    """Check if the directory is readable."""
    try:
        list(p.iterdir())
        return True
    except (PermissionError, OSError):
        return False


def _check_writable(p: Path) -> bool:
    """Check if the directory is writable by creating a temp file."""
    test_file = p / ".signalvault_test_write"
    try:
        test_file.write_text("", encoding="utf-8")
        test_file.unlink()
        return True
    except (PermissionError, OSError):
        return False
