"""Patch lifecycle management: list, rollback, reject.

Supports:
- list-applied-patches: scan patches with status=applied, check marker existence
- rollback-patch: remove LLM-WIKI marker blocks from target card
- reject-patch: mark a pending_review/approved patch as rejected
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from podcast_research.llm_wiki.validator import _parse_patch_frontmatter

logger = logging.getLogger(__name__)


@dataclass
class AppliedPatch:
    """Info about an applied patch."""
    patch_path: Path
    patch_id: str
    target_type: str = ""
    target_name: str = ""
    applied_at: str = ""
    target_card_rel: str = ""
    marker_exists: str = "unknown"  # yes / missing / unknown


@dataclass
class RollbackResult:
    """Result of rollback operation."""
    patch_path: Path
    patch_id: str
    target_name: str = ""
    target_card_path: Path | None = None
    rolled_back: bool = False
    blocks_removed: int = 0
    errors: list[str] = field(default_factory=list)
    dry_run: bool = True


@dataclass
class RejectResult:
    """Result of reject operation."""
    patch_path: Path
    patch_id: str
    rejected: bool = False
    errors: list[str] = field(default_factory=list)


def _make_marker_begin(patch_id: str) -> str:
    return f"<!-- LLM-WIKI:BEGIN {patch_id} -->"


def _make_marker_end(patch_id: str) -> str:
    return f"<!-- LLM-WIKI:END {patch_id} -->"


def _extract_patch_id(patch_path: Path) -> str:
    return patch_path.stem


def _find_patch_by_id(vault_path: Path, patch_id: str) -> Path | None:
    """Find a patch file by its patch_id (filename stem)."""
    patches_dir = vault_path / "00_Inbox" / "LLM_Patches"
    if not patches_dir.exists():
        return None
    target_file = patches_dir / f"{patch_id}.md"
    if target_file.exists():
        return target_file
    # Try glob match
    for pf in patches_dir.glob("*.md"):
        if pf.stem == patch_id:
            return pf
    return None


def _count_marker_blocks(content: str, patch_id: str) -> int:
    """Count how many marker blocks for a given patch_id exist in content."""
    begin_marker = _make_marker_begin(patch_id)
    return content.count(begin_marker)


def _remove_marker_blocks(content: str, patch_id: str) -> str:
    """Remove all LLM-WIKI BEGIN/END blocks for a given patch_id.

    Handles the blank lines surrounding the markers cleanly.
    """
    begin_marker = _make_marker_begin(patch_id)
    end_marker = _make_marker_end(patch_id)
    pattern = re.compile(
        r'\n*' + re.escape(begin_marker) + r'.*?' + re.escape(end_marker) + r'\n*',
        re.DOTALL,
    )
    return pattern.sub('\n', content)


def list_applied_patches(vault_path: Path) -> list[AppliedPatch]:
    """Scan 00_Inbox/LLM_Patches/ for patches with status: applied.

    Returns list of AppliedPatch with marker existence check.
    """
    patches_dir = vault_path / "00_Inbox" / "LLM_Patches"
    if not patches_dir.exists():
        return []

    results = []
    for pf in sorted(patches_dir.glob("*.md")):
        content = pf.read_text(encoding="utf-8")
        fm = _parse_patch_frontmatter(content)
        if fm.get("status") != "applied":
            continue

        patch_id = _extract_patch_id(pf)
        target_card_rel = fm.get("target_card", fm.get("applied_to", ""))
        target_name = fm.get("target", "")

        # Check marker existence
        marker_exists = "unknown"
        if target_card_rel:
            target_path = vault_path / target_card_rel
            if target_path.exists():
                target_content = target_path.read_text(encoding="utf-8")
                if _make_marker_begin(patch_id) in target_content:
                    marker_exists = "yes"
                else:
                    marker_exists = "missing"

        results.append(AppliedPatch(
            patch_path=pf,
            patch_id=patch_id,
            target_type=fm.get("target_type", ""),
            target_name=target_name,
            applied_at=fm.get("applied_at", ""),
            target_card_rel=target_card_rel,
            marker_exists=marker_exists,
        ))

    return results


def rollback_patch(
    vault_path: Path,
    patch_path: Path | None = None,
    patch_id: str | None = None,
    dry_run: bool = True,
) -> RollbackResult:
    """Roll back an applied patch by removing its marker blocks.

    Args:
        vault_path: Path to vault root
        patch_path: Path to patch file (mutually exclusive with patch_id)
        patch_id: Patch ID to find by filename stem
        dry_run: If True, preview only

    Returns:
        RollbackResult
    """
    # Resolve patch file
    if patch_id and not patch_path:
        patch_path = _find_patch_by_id(vault_path, patch_id)
    if not patch_path or not patch_path.exists():
        result = RollbackResult(
            patch_path=patch_path or Path("(unknown)"),
            patch_id=patch_id or "",
            dry_run=dry_run,
        )
        result.errors.append("Patch file not found")
        return result

    pid = _extract_patch_id(patch_path)
    result = RollbackResult(
        patch_path=patch_path,
        patch_id=pid,
        dry_run=dry_run,
    )

    # Read patch frontmatter
    patch_content = patch_path.read_text(encoding="utf-8")
    fm = _parse_patch_frontmatter(patch_content)
    status = fm.get("status", "")
    target_card_rel = fm.get("target_card", fm.get("applied_to", ""))
    result.target_name = fm.get("target", "")

    # Validate status
    if status != "applied":
        result.errors.append(f"Patch status is '{status}', not 'applied'. Cannot rollback.")
        return result

    if not target_card_rel:
        result.errors.append("Patch has no target_card or applied_to in frontmatter")
        return result

    target_card_path = vault_path / target_card_rel
    result.target_card_path = target_card_path

    if not target_card_path.exists():
        result.errors.append(f"Target card not found: {target_card_rel}")
        return result

    target_content = target_card_path.read_text(encoding="utf-8")
    blocks = _count_marker_blocks(target_content, pid)
    result.blocks_removed = blocks

    if blocks == 0:
        result.errors.append("No marker blocks found in target card. Nothing to rollback.")
        return result

    if dry_run:
        return result

    # Apply: remove marker blocks
    new_content = _remove_marker_blocks(target_content, pid)
    target_card_path.write_text(new_content, encoding="utf-8")
    logger.info("Removed %d marker blocks from %s", blocks, target_card_rel)

    # Update patch status
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    updated_patch = patch_content.replace(
        f"status: {status}", "status: rolled_back"
    )
    closing_fm = updated_patch.find("---", 3)
    if closing_fm > 0:
        new_fields = (
            f"rolled_back_at: \"{now_utc}\"\n"
            f"rolled_back_from: \"{target_card_rel}\"\n"
        )
        updated_patch = updated_patch[:closing_fm] + new_fields + updated_patch[closing_fm:]

    patch_path.write_text(updated_patch, encoding="utf-8")
    logger.info("Updated patch status to 'rolled_back' in %s", pid)

    # Write log
    _write_rollback_log(vault_path, pid, result.target_name, blocks)
    result.rolled_back = True
    return result


def _write_rollback_log(vault_path: Path, patch_id: str, target_name: str, blocks: int) -> None:
    """Append to Patch_Rollback_Log.md."""
    log_dir = vault_path / "99_System"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "Patch_Rollback_Log.md"
    now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    entry = (
        f"## {now_local}\n\n"
        f"- **Patch**: [[{patch_id}]]\n"
        f"- **Target**: [[{target_name}]]\n"
        f"- **Action**: rolled_back\n"
        f"- **Removed marker blocks**: {blocks}\n\n"
    )

    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        header = "# Patch Rollback Log"
        if header in existing:
            existing = existing.replace(header + "\n\n", header + "\n\n" + entry)
            log_path.write_text(existing, encoding="utf-8")
        else:
            log_path.write_text(header + "\n\n" + entry + existing)
    else:
        log_path.write_text("# Patch Rollback Log\n\n" + entry)


def reject_patch(
    vault_path: Path,
    patch_path: Path | None,
    reason: str = "",
) -> RejectResult:
    """Reject a pending_review or approved patch.

    Args:
        vault_path: Path to vault root
        patch_path: Path to patch file
        reason: Human-readable rejection reason

    Returns:
        RejectResult
    """
    if not patch_path or not patch_path.exists():
        result = RejectResult(patch_path=patch_path or Path("(unknown)"), patch_id="")
        result.errors.append("Patch file not found")
        return result

    pid = _extract_patch_id(patch_path)
    result = RejectResult(patch_path=patch_path, patch_id=pid)

    patch_content = patch_path.read_text(encoding="utf-8")
    fm = _parse_patch_frontmatter(patch_content)
    status = fm.get("status", "")

    if status not in ("pending_review", "approved"):
        result.errors.append(
            f"Patch status is '{status}'. Only pending_review or approved patches can be rejected."
        )
        return result

    # Update frontmatter
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    reason_str = reason or "manual review rejected"

    updated_patch = patch_content.replace(
        f"status: {status}", "status: rejected"
    )
    closing_fm = updated_patch.find("---", 3)
    if closing_fm > 0:
        new_fields = (
            f"rejected_at: \"{now_utc}\"\n"
            f"reject_reason: \"{reason_str}\"\n"
        )
        updated_patch = updated_patch[:closing_fm] + new_fields + updated_patch[closing_fm:]

    patch_path.write_text(updated_patch, encoding="utf-8")
    logger.info("Rejected patch '%s': %s", pid, reason_str)

    # Write log
    _write_reject_log(vault_path, pid, fm.get("target", ""), reason_str)
    result.rejected = True
    return result


def _write_reject_log(vault_path: Path, patch_id: str, target_name: str, reason: str) -> None:
    """Append to Patch_Reject_Log.md."""
    log_dir = vault_path / "99_System"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "Patch_Reject_Log.md"
    now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    entry = (
        f"## {now_local}\n\n"
        f"- **Patch**: [[{patch_id}]]\n"
        f"- **Target**: [[{target_name}]]\n"
        f"- **Action**: rejected\n"
        f"- **Reason**: {reason}\n\n"
    )

    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        header = "# Patch Reject Log"
        if header in existing:
            existing = existing.replace(header + "\n\n", header + "\n\n" + entry)
            log_path.write_text(existing, encoding="utf-8")
        else:
            log_path.write_text(header + "\n\n" + entry + existing)
    else:
        log_path.write_text("# Patch Reject Log\n\n" + entry)
