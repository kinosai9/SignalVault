"""Apply reviewed patch proposals to Topic Cards.

Safety: Single-file explicit apply only. No batch mode. No auto-apply.
Uses LLM-WIKI markers to prevent duplicate application.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from podcast_research.llm_wiki.validator import (
    validate_patch_file,
    PatchValidationResult,
)
from podcast_research.utils.file_io import read_text_safe
from podcast_research.llm_wiki.taxonomy import (
    SECTION_ORDER,
    get_section_position,
    normalize_topic_name,
    classify_entity,
)

logger = logging.getLogger(__name__)

# Mapping: patch section → target card section (topic)
SECTION_MAP = {
    "## Proposed Current Understanding": "## Current Understanding",
    "## Proposed Key Claims": "## Key Claims",
    "## Proposed Related Companies": "## Related Companies",
    "## Proposed Related Topics": "## Related Topics",
    "## Proposed Open Questions": "## Open Questions",
    "## Proposed Timeline": "## Timeline",
}

# Mapping: patch section → target card section (company)
COMPANY_SECTION_MAP = {
    "## Proposed Current Thesis": "## Current Thesis",
    "## Proposed Key Claims": "## Key Claims",
    "## Proposed Related Topics": "## Related Topics",
    "## Proposed Related Companies": "## Related Companies",
    "## Proposed Risks": "## Risks",
    "## Proposed Open Questions": "## Open Questions",
    "## Proposed Timeline": "## Timeline",
}


@dataclass
class ApplyResult:
    """Result of applying a patch to a target card."""
    patch_path: Path
    patch_id: str = ""
    target_name: str = ""
    target_card_path: Path | None = None
    applied: bool = False
    sections_applied: list[str] = field(default_factory=list)
    sections_skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False


def _extract_patch_id(patch_path: Path) -> str:
    """Extract patch_id from filename.

    e.g. topic_AI_Agents_20260530_151319.md → topic_AI_Agents_20260530_151319
    """
    return patch_path.stem


def _make_marker(patch_id: str, marker_type: str = "BEGIN") -> str:
    """Generate LLM-WIKI marker comment."""
    return f"<!-- LLM-WIKI:{marker_type} {patch_id} -->"


def _parse_patch_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from patch content into a flat dict."""
    from podcast_research.llm_wiki.validator import _parse_patch_frontmatter
    return _parse_patch_frontmatter(content)


def _has_marker_in_file(content: str, patch_id: str) -> bool:
    """Check if patch marker already exists in file content."""
    begin_marker = _make_marker(patch_id, "BEGIN")
    return begin_marker in content


def _extract_patch_sections(patch_content: str, section_map: dict[str, str] | None = None) -> dict[str, str]:
    """Extract proposed sections from patch markdown.

    Args:
        patch_content: Full patch markdown
        section_map: Section mapping dict (defaults to SECTION_MAP for topics)

    Returns:
        Dict mapping target section name → section content
    """
    if section_map is None:
        section_map = SECTION_MAP
    result = {}
    lines = patch_content.split("\n")
    current_patch_section = None
    current_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped in section_map:
            if current_patch_section:
                result[section_map[current_patch_section]] = "\n".join(current_lines).strip()
            current_patch_section = stripped
            current_lines = []
            continue

        if current_patch_section and stripped.startswith("## ") and stripped not in section_map:
            result[section_map[current_patch_section]] = "\n".join(current_lines).strip()
            current_patch_section = None
            current_lines = []
            continue

        if current_patch_section:
            current_lines.append(line)

    if current_patch_section and current_lines:
        result[section_map[current_patch_section]] = "\n".join(current_lines).strip()

    return result


def _normalize_topic_links(content: str) -> str:
    """Apply topic canonical mapping to [[Topic]] links in content."""
    def _replace_topic(match):
        name = match.group(1)
        canonical = normalize_topic_name(name)
        if canonical != name:
            return f"[[{canonical}]]"
        return match.group(0)
    return re.sub(r"\[\[([^\]]+)\]\]", _replace_topic, content)


def _annotate_entity_types(content: str) -> str:
    """Add entity type annotations to non-company [[Entity]] links."""
    def _replace_entity(match):
        name = match.group(1)
        etype = classify_entity(name)
        if etype:
            return f"[[{name}]] *({etype})*"
        return match.group(0)
    return re.sub(r"\[\[([^\]]+)\]\]", _replace_entity, content)


def _apply_section_content(
    target_content: str,
    section_name: str,
    patch_content: str,
    patch_id: str,
) -> str:
    """Append patch content to target section with markers.

    If the section doesn't exist, it's inserted at the correct position
    according to SECTION_ORDER, not appended to the end of the file.

    Args:
        target_content: Full content of target card
        section_name: Section header (e.g. "## Current Understanding")
        patch_content: Content to append (from patch section)
        patch_id: Unique patch identifier

    Returns:
        Updated target card content
    """
    begin_marker = _make_marker(patch_id, "BEGIN")
    end_marker = _make_marker(patch_id, "END")
    block = f"\n\n{begin_marker}\n\n{patch_content}\n\n{end_marker}"

    lines = target_content.split("\n")
    in_section = False
    section_found = False
    result_lines = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        if stripped == section_name and not in_section:
            # Entering target section
            in_section = True
            section_found = True
            result_lines.append(line)
            continue

        if in_section:
            if stripped.startswith("## ") and stripped != section_name:
                # Next section reached → append block before it
                result_lines.append(block)
                result_lines.append("")
                result_lines.append(line)
                in_section = False
                continue
            result_lines.append(line)
            continue

        result_lines.append(line)

    # If section was found and is the last section, append at end
    if in_section:
        result_lines.append(block)

    # If section was never found, insert at correct position
    if not section_found:
        target_pos = get_section_position(section_name)
        # Strategy: find the latest section (by file line number) whose
        # canonical position is BEFORE target_pos. Insert right after its
        # content block ends (next ## header, or EOF).
        insert_idx = len(result_lines)
        best_after_line = 0  # last line of the best preceding section

        for i, line in enumerate(result_lines):
            stripped = line.strip()
            if stripped.startswith("## "):
                pos = get_section_position(stripped)
                if pos < target_pos:
                    # This section comes before us canonically — find where it ends
                    k = i + 1
                    while k < len(result_lines) and not result_lines[k].strip().startswith("## "):
                        k += 1
                    if k > best_after_line:
                        best_after_line = k

        if best_after_line > 0:
            insert_idx = best_after_line

        new_section_lines = [f"\n{section_name}", block, ""]
        result_lines = result_lines[:insert_idx] + new_section_lines + result_lines[insert_idx:]

    return "\n".join(result_lines)


def apply_patch(
    vault_path: Path,
    patch_rel_path: str,
    dry_run: bool = True,
    confirm_reviewed: bool = False,
    force: bool = False,
) -> ApplyResult:
    """Apply a single patch to its target topic card.

    Args:
        vault_path: Path to vault root
        patch_rel_path: Relative path to patch file from vault root
        dry_run: If True, validate but don't write
        confirm_reviewed: Required when patch status is pending_review
        force: Skip pending_review requirement (but still require valid)

    Returns:
        ApplyResult with details of what was done
    """
    patch_path = vault_path / patch_rel_path
    patch_id = _extract_patch_id(patch_path)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    result = ApplyResult(
        patch_path=patch_path,
        patch_id=patch_id,
        dry_run=dry_run,
    )

    # --- 1. Validate patch ---
    validation = validate_patch_file(patch_path, vault_path)
    if not validation.is_valid:
        result.errors = validation.issues
        logger.warning("Patch validation failed: %s", validation.issues)
        return result

    result.target_name = validation.target

    # --- 2. Check frontmatter fields ---
    fm = _parse_patch_frontmatter(read_text_safe(patch_path))
    if not fm:
        result.errors.append("Missing YAML frontmatter")
        return result

    patch_type = fm.get("type", "")
    target_type = fm.get("target_type", "")
    status = fm.get("status", "")
    auto_apply = fm.get("auto_apply", "")
    target_card_rel = fm.get("target_card", "")

    if patch_type != "llm_wiki_patch":
        result.errors.append(f"Invalid type: {patch_type} (expected llm_wiki_patch)")
        return result
    if target_type not in ("topic", "company"):
        result.errors.append(f"Invalid target_type: {target_type} (expected topic or company)")
        return result
    if str(auto_apply).lower() != "false":
        result.errors.append("auto_apply must be false, refusing to apply")
        return result

    # --- 3. Status check ---
    if status == "applied":
        result.errors.append("Patch already applied, refusing duplicate apply")
        return result
    if status == "rejected":
        result.errors.append("Patch is rejected, refusing to apply")
        return result
    if status == "rolled_back":
        result.errors.append("Patch was rolled back, refusing to apply")
        return result
    if status == "pending_review" and not confirm_reviewed and not force:
        result.errors.append(
            "Patch status is 'pending_review'. Use --confirm-reviewed to confirm "
            "you have reviewed the patch content, or --force to skip."
        )
        return result

    # --- 4. Check target card ---
    target_card_path = vault_path / target_card_rel
    if not target_card_path.exists():
        result.errors.append(f"Target card not found: {target_card_rel}")
        return result
    result.target_card_path = target_card_path

    # --- 5. Parse patch sections ---
    patch_content = read_text_safe(patch_path)
    # Use company or topic section map based on target_type
    use_company_map = target_type == "company"
    active_section_map = COMPANY_SECTION_MAP if use_company_map else SECTION_MAP
    sections = _extract_patch_sections(patch_content, active_section_map)

    if not sections:
        result.errors.append("No proposed sections found in patch")
        return result

    # --- 5a. Normalize topics (apply canonical mapping) ---
    if "## Related Topics" in sections and sections["## Related Topics"]:
        sections["## Related Topics"] = _normalize_topic_links(
            sections["## Related Topics"]
        )

    # --- 5b. Annotate entity types (flag known non-companies) ---
    if "## Related Companies" in sections and sections["## Related Companies"]:
        sections["## Related Companies"] = _annotate_entity_types(
            sections["## Related Companies"]
        )

    # --- 6. Check for duplicate markers ---
    target_content = read_text_safe(target_card_path)
    if _has_marker_in_file(target_content, patch_id):
        result.errors.append(
            f"Patch '{patch_id}' already applied to target card (marker found)"
        )
        return result

    # --- 7. Determine sections to apply ---
    if use_company_map:
        apply_order = [
            "## Current Thesis",
            "## Key Claims",
            "## Related Topics",
            "## Related Companies",
            "## Risks",
            "## Open Questions",
            "## Timeline",
        ]
    else:
        apply_order = [
            "## Current Understanding",
            "## Key Claims",
            "## Related Companies",
            "## Related Topics",
            "## Open Questions",
            "## Timeline",
        ]
    for target_section in apply_order:
        if target_section in sections and sections[target_section]:
            result.sections_applied.append(target_section)
        else:
            result.sections_skipped.append(target_section)

    # --- 8. Dry-run: stop here ---
    if dry_run:
        result.sections_applied = [s for s in result.sections_applied]  # already populated
        return result

    # --- 9. Apply sections (sorted by canonical order so new sections land in place) ---
    new_content = target_content
    # Sort sections by their canonical position to ensure correct insertion order
    sorted_sections = sorted(
        result.sections_applied,
        key=lambda s: get_section_position(s),
    )
    for target_section in sorted_sections:
        new_content = _apply_section_content(
            new_content,
            target_section,
            sections[target_section],
            patch_id,
        )

    # --- 10. Write target card ---
    target_card_path.write_text(new_content, encoding="utf-8")
    logger.info("Applied patch '%s' to %s", patch_id, target_card_rel)

    # --- 11. Update patch frontmatter status ---
    updated_patch = patch_content.replace(
        f"status: {status}", "status: applied"
    )
    # Insert applied_at and applied_to before the closing ---
    closing_fm = updated_patch.find("---", 3)  # Skip opening ---
    if closing_fm > 0:
        new_fields = f"applied_at: \"{now_utc}\"\napplied_to: \"{target_card_rel}\"\n"
        updated_patch = updated_patch[:closing_fm] + new_fields + updated_patch[closing_fm:]

    patch_path.write_text(updated_patch, encoding="utf-8")
    logger.info("Updated patch status to 'applied' in %s", patch_path.name)

    # --- 12. Write apply log ---
    log_dir = vault_path / "99_System"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "Patch_Apply_Log.md"

    log_entry = f"""## {now_local}

- **Patch**: [[{patch_id}]]
- **Target**: [[{result.target_name}]]
- **Status**: applied
- **Sections applied**:
"""
    for s in result.sections_applied:
        log_entry += f"  - {s.replace('## ', '')}\n"

    if log_path.exists():
        existing_log = read_text_safe(log_path)
        # Insert after header
        if "# Patch Apply Log" in existing_log:
            existing_log = existing_log.replace("# Patch Apply Log\n\n", "# Patch Apply Log\n\n" + log_entry)
        else:
            existing_log = "# Patch Apply Log\n\n" + log_entry + "\n---\n\n" + existing_log
        log_path.write_text(existing_log, encoding="utf-8")
    else:
        log_path.write_text("# Patch Apply Log\n\n" + log_entry, encoding="utf-8")

    logger.info("Apply log written to %s", log_path)
    result.applied = True
    return result
