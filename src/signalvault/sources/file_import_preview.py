"""P2-S.3.3: File import preview — eligibility evaluation, conflict detection, confirm execution."""

from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from signalvault.sources.file_content_extractor import ExtractedFileContent
from signalvault.sources.models import (
    ActionEnum,
    ConflictInfo,
    FileArchiveType,
    FileImportEligibility,
    FileImportPreview,
    UploadedFileProfile,
)

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# Preview builder
# ═════════════════════════════════════════════════════════════════════════════


def build_file_import_preview(
    profile: UploadedFileProfile,
    content: ExtractedFileContent,
    vault_path: Path,
) -> FileImportPreview:
    """Build a FileImportPreview without writing anything.

    1. Evaluate import eligibility
    2. Detect conflicts in vault
    3. Compute recommendation
    4. Return preview (NO writes)
    """
    # ── Eligibility ─────────────────────────────────────────────────────
    eligibility = evaluate_file_import_eligibility(profile, content)

    # ── Conflict detection ──────────────────────────────────────────────
    conflicts: list[ConflictInfo] = []
    if profile.content_hash:
        from signalvault.sources.conflict_detector import ConflictDetector
        detector = ConflictDetector(vault_path)
        conflicts = detector.detect_for_file(
            content_hash=profile.content_hash,
            filename=profile.original_filename,
            title=content.title,
        )

    # ── Recommendation ──────────────────────────────────────────────────
    recommended_action, available_actions, warnings = _compute_file_recommendation(
        eligibility=eligibility,
        conflicts=conflicts,
        parse_quality=profile.parse_quality,
    )

    # ── Recommended path ────────────────────────────────────────────────
    recommended_path = ""
    if recommended_action != ActionEnum.skip:
        recommended_path = _build_recommended_path(
            content.title or profile.original_filename,
            profile.content_hash or "",
            vault_path,
        )

    # Collect all warnings
    all_warnings = list(profile.quality_warnings)
    all_warnings.extend(content.quality_warnings)
    all_warnings.extend(eligibility.warning_messages)
    all_warnings.extend(warnings)

    return FileImportPreview(
        filename=profile.original_filename,
        extension=profile.extension,
        file_size_bytes=profile.file_size_bytes,
        content_hash=profile.content_hash or "",
        title=content.title,
        extracted_text_excerpt=content.excerpt,
        extracted_text_length=profile.extracted_text_length,
        parse_quality=profile.parse_quality,
        import_eligible=eligibility.import_eligible,
        ineligible_reason=eligibility.ineligible_reason,
        conflicts=conflicts,
        recommended_action=recommended_action,
        recommended_path=recommended_path,
        available_actions=available_actions,
        warning_messages=all_warnings,
        _extracted_text=content.text,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Eligibility evaluation
# ═════════════════════════════════════════════════════════════════════════════


def evaluate_file_import_eligibility(
    profile: UploadedFileProfile,
    content: ExtractedFileContent,
) -> FileImportEligibility:
    """Determine whether a file meets minimum requirements for archive import.

    Minimum conditions:
      - supported = True
      - extracted_text_length >= 200
      - content_hash exists
      - parse_quality != "minimal"
    """
    warnings: list[str] = []

    if not profile.supported:
        return FileImportEligibility(
            import_eligible=False,
            ineligible_reason=profile.unsupported_reason or "文件类型不支持。",
            recommended_archive_type=FileArchiveType.skip,
        )

    if not profile.content_hash:
        return FileImportEligibility(
            import_eligible=False,
            ineligible_reason="无法计算文件内容哈希。",
            recommended_archive_type=FileArchiveType.skip,
        )

    if profile.extracted_text_length < 200:
        return FileImportEligibility(
            import_eligible=False,
            ineligible_reason="提取文本过短（不足 200 字），不适合归档。",
            recommended_archive_type=FileArchiveType.skip,
        )

    if profile.parse_quality == "minimal":
        return FileImportEligibility(
            import_eligible=False,
            ineligible_reason="文件解析质量过低，无法提取有效内容。",
            recommended_archive_type=FileArchiveType.skip,
        )

    if profile.parse_quality == "degraded":
        warnings.append("文件解析质量一般，部分内容可能未提取完整。")

    return FileImportEligibility(
        import_eligible=True,
        ineligible_reason=None,
        recommended_archive_type=FileArchiveType.source_archive,
        warning_messages=warnings,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Recommendation engine
# ═════════════════════════════════════════════════════════════════════════════


def _compute_file_recommendation(
    eligibility: FileImportEligibility,
    conflicts: list[ConflictInfo],
    parse_quality: str,
) -> tuple[ActionEnum, list[ActionEnum], list[str]]:
    """Compute recommended action + available actions + additional warnings.

    Returns:
        (recommended_action, available_actions, additional_warnings)
    """
    conflict_types = {c.conflict_type for c in conflicts}
    has_content_hash_conflict = "same_content_hash" in conflict_types
    has_filename_conflict = "same_filename" in conflict_types

    additional_warnings: list[str] = []
    available: list[ActionEnum] = [ActionEnum.skip]

    # ── Content hash duplicate is a hard block ──────────────────────────
    if has_content_hash_conflict:
        additional_warnings.append(
            "内容完全相同的文件已存在于归档中。建议跳过，避免重复。"
        )
        available = [ActionEnum.skip]
        return ActionEnum.skip, available, additional_warnings

    # ── Not eligible ────────────────────────────────────────────────────
    if not eligibility.import_eligible:
        additional_warnings.append(
            eligibility.ineligible_reason or "文件不符合入库条件。"
        )
        available = [ActionEnum.skip]
        return ActionEnum.skip, available, additional_warnings

    # ── Eligible ────────────────────────────────────────────────────────
    available = [ActionEnum.confirm_archive, ActionEnum.skip]

    if has_filename_conflict:
        additional_warnings.append(
            "相同文件名的资料已存在。导入后文件名将自动追加哈希以避免覆盖。"
        )

    if parse_quality == "degraded":
        additional_warnings.append(
            "文件解析质量一般。归档后建议人工检查内容完整性。"
        )

    return ActionEnum.confirm_archive, available, additional_warnings


# ═════════════════════════════════════════════════════════════════════════════
# Confirm execution — THIS is where writes happen
# ═════════════════════════════════════════════════════════════════════════════


def confirm_file_import(
    preview: FileImportPreview,
    vault_path: Path,
) -> dict:
    """Write the uploaded file content into the SourceArchive.

    This is the ONLY function that writes to the vault during file import.
    All validation, eligibility, and conflict checks must have passed before
    calling this.

    Returns:
        dict with "success" (bool), "message" (str), "path" (str), "filename" (str)
    """
    from signalvault.exporters.markdown_utils import (
        build_frontmatter,
        sanitize_filename,
    )

    archive_dir = vault_path / "01_Reports" / "SourceArchive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    imported_at = now.strftime("%Y-%m-%d %H:%M")

    safe_title = sanitize_filename(
        preview.title or "untitled",
        fallback="uploaded_file",
    )
    filename = f"{date_str}_uploaded_{safe_title}.md"

    # Avoid overwrite: append hash suffix if file exists
    filepath = archive_dir / filename
    if filepath.exists() and preview.content_hash:
        hash_suffix = preview.content_hash[:6]
        filename = f"{date_str}_uploaded_{safe_title}_{hash_suffix}.md"
        filepath = archive_dir / filename

    # Build frontmatter
    fm = OrderedDict([
        ("type", "source_archive"),
        ("source_type", "uploaded_text_file"),
        ("archive_type", "source_archive"),
        ("original_filename", preview.filename),
        ("file_extension", preview.extension),
        ("file_size_bytes", preview.file_size_bytes),
        ("content_hash", preview.content_hash),
        ("imported_at", imported_at),
        ("parse_quality", preview.parse_quality),
        ("source_confidence", "secondary"),
        ("tags", ["source-archive", "uploaded-file"]),
    ])

    body = _build_file_archive_body(preview, imported_at)
    content = build_frontmatter(fm) + "\n\n" + body
    filepath.write_text(content, encoding="utf-8")

    return {
        "success": True,
        "message": f"文件已归档: {filename}",
        "path": str(filepath),
        "filename": filename,
    }


def _build_file_archive_body(
    preview: FileImportPreview,
    imported_at: str,
) -> str:
    """Build the Markdown body for an uploaded file archive."""
    sections = [
        f"# {preview.title or preview.filename}",
        "",
        "## 导入信息",
        "",
        f"- **原始文件名**: {preview.filename}",
        f"- **文件类型**: {preview.extension}",
        f"- **导入时间**: {imported_at}",
        f"- **内容哈希**: `{preview.content_hash}`",
        f"- **解析质量**: {preview.parse_quality}",
        f"- **文件大小**: {_format_size(preview.file_size_bytes)}",
        "",
        "## 提取内容",
        "",
        preview._extracted_text or "*无内容*",
        "",
        "---",
        "",
        f"*此归档由 signalvault P2-S.3.3 自动生成，"
        f"来源于用户上传文件 `{preview.filename}`。*",
        "",
    ]
    return "\n".join(sections)


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════


def _build_recommended_path(
    title: str,
    content_hash: str,
    vault_path: Path,
) -> str:
    """Build the recommended save path for display."""
    from signalvault.exporters.markdown_utils import sanitize_filename

    safe_title = sanitize_filename(title or "untitled", fallback="uploaded_file")
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{date_str}_uploaded_{safe_title}.md"
    archive_dir = vault_path / "01_Reports" / "SourceArchive"
    return str(archive_dir / filename)


def _format_size(bytes_count: int) -> str:
    """Format byte count to human-readable string."""
    if bytes_count < 1024:
        return f"{bytes_count} B"
    elif bytes_count < 1024 * 1024:
        return f"{bytes_count / 1024:.1f} KB"
    else:
        return f"{bytes_count / (1024 * 1024):.1f} MB"
