"""Validate LLM-WIKI patch proposals.

Checks patch files for structural completeness:
- YAML frontmatter with required fields
- Target card existence
- Source report file existence
- Required markdown sections
- Review Checklist presence
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_SECTIONS_TOPIC = [
    "## Proposed Current Understanding",
    "## Proposed Key Claims",
    "## Proposed Related Companies",
    "## Proposed Related Topics",
    "## Proposed Open Questions",
    "## Evidence Notes",
    "## Patch Safety",
    "## Review Checklist",
]

REQUIRED_SECTIONS_COMPANY = [
    "## Proposed Current Thesis",
    "## Proposed Key Claims",
    "## Proposed Related Topics",
    "## Proposed Related Companies",
    "## Proposed Risks",
    "## Proposed Open Questions",
    "## Evidence Notes",
    "## Patch Safety",
    "## Review Checklist",
]


@dataclass
class PatchValidationResult:
    """Result of validating a single patch file."""
    patch_path: Path
    patch_filename: str = ""
    target: str = ""
    source_reports: list[str] = field(default_factory=list)
    status: str = ""
    is_valid: bool = True
    issues: list[str] = field(default_factory=list)


def _parse_patch_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from patch content into a flat dict."""
    stripped = content.strip()
    if not stripped.startswith("---"):
        return {}

    end_idx = stripped.find("---", 3)
    if end_idx == -1:
        return {}

    fm_text = stripped[3:end_idx].strip()
    result = {}
    current_key = None
    list_values = []

    for line in fm_text.split("\n"):
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue

        # Check if this is a list item (  - "value")
        if line_stripped.startswith('- "') and current_key:
            val = line_stripped[3:].rstrip('"').strip()
            list_values.append(val)
            continue
        elif line_stripped.startswith("- ") and current_key:
            list_values.append(line_stripped[2:].strip().strip('"'))
            continue
        elif line_stripped == "[]" and current_key:
            list_values = []
            continue

        # If we were collecting a list, save it
        if current_key and list_values is not None:
            result[current_key] = list_values
            list_values = []
            current_key = None

        # Parse key: value
        if ":" in line_stripped and not line_stripped.startswith("-"):
            key, _, val = line_stripped.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val:
                result[key] = val
                current_key = None
                list_values = []
            else:
                # Could be start of a list
                current_key = key
                list_values = []

    # Save last list if any
    if current_key and list_values is not None:
        result[current_key] = list_values

    return result


def validate_patch_file(patch_path: Path, vault_path: Path) -> PatchValidationResult:
    """Validate a single patch file.

    Args:
        patch_path: Path to the patch .md file
        vault_path: Path to vault root (for resolving relative paths)

    Returns:
        PatchValidationResult with validity and issues
    """
    result = PatchValidationResult(
        patch_path=patch_path,
        patch_filename=patch_path.name,
    )

    if not patch_path.exists():
        result.is_valid = False
        result.issues.append("File not found")
        return result

    content = patch_path.read_text(encoding="utf-8")

    # 1. Check frontmatter
    fm = _parse_patch_frontmatter(content)
    if not fm:
        result.is_valid = False
        result.issues.append("Missing YAML frontmatter")
        return result

    # Extract frontmatter fields
    result.target = fm.get("target", "")
    result.source_reports = fm.get("source_reports", [])
    result.status = fm.get("status", "")

    # 2. Check required frontmatter fields
    required_fm_fields = ["type", "target_type", "target", "target_card", "status", "auto_apply"]
    for field in required_fm_fields:
        if field not in fm:
            result.is_valid = False
            result.issues.append(f"Missing frontmatter field: {field}")

    # 3. Check target_type is valid
    valid_target_types = {"topic", "company"}
    target_type = fm.get("target_type", "")
    if target_type and target_type not in valid_target_types:
        result.is_valid = False
        result.issues.append(f"Invalid target_type: {target_type} (must be topic or company)")

    # 4. Check status is valid
    valid_statuses = {"pending_review", "approved", "rejected", "applied", "rolled_back"}
    if result.status and result.status not in valid_statuses:
        result.is_valid = False
        result.issues.append(f"Invalid status: {result.status} (must be one of {valid_statuses})")

    # 4. Check target_card exists
    target_card = fm.get("target_card", "")
    if target_card:
        target_path = vault_path / target_card
        if not target_path.exists():
            result.is_valid = False
            result.issues.append(f"Target card not found: {target_card}")

    # 5. Check source_reports exist
    if isinstance(result.source_reports, list):
        for sr in result.source_reports:
            report_path = vault_path / "01_Reports" / f"{sr}.md"
            if not report_path.exists():
                result.is_valid = False
                result.issues.append(f"Source report not found: {sr}.md")
    elif result.source_reports:
        result.is_valid = False
        result.issues.append("source_reports must be a list")

    # 6. Check required sections (depends on target_type)
    target_type = fm.get("target_type", "topic")
    required = REQUIRED_SECTIONS_COMPANY if target_type == "company" else REQUIRED_SECTIONS_TOPIC
    for section in required:
        if section not in content:
            result.is_valid = False
            result.issues.append(f"Missing section: {section}")

    # 7. Check auto_apply is false
    auto_apply = fm.get("auto_apply", "")
    if str(auto_apply).lower() != "false":
        result.is_valid = False
        result.issues.append("auto_apply must be false")

    return result


def validate_patches(
    vault_path: Path,
    patch_path: Path | None = None,
) -> list[PatchValidationResult]:
    """Validate all patches in 00_Inbox/LLM_Patches/ or a specific patch.

    Args:
        vault_path: Path to vault root
        patch_path: Optional path to a specific patch file to validate

    Returns:
        List of PatchValidationResult objects
    """
    if patch_path:
        if patch_path.exists():
            return [validate_patch_file(patch_path, vault_path)]
        return [PatchValidationResult(
            patch_path=patch_path,
            patch_filename=patch_path.name,
            is_valid=False,
            issues=["File not found"],
        )]

    # Scan all patches
    patches_dir = vault_path / "00_Inbox" / "LLM_Patches"
    if not patches_dir.exists():
        return []

    results = []
    for pf in sorted(patches_dir.glob("*.md")):
        results.append(validate_patch_file(pf, vault_path))

    return results
