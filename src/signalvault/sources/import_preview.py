"""P2-S.3.1: Import preview pipeline — adapter selection, preview generation, confirm execution."""

from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from signalvault.adapters.allin_zh_notes import SITE_BASE
from signalvault.adapters.external_html_notes import ExternalHTMLNotesAdapter
from signalvault.sources.conflict_detector import ConflictDetector
from signalvault.sources.models import (
    ActionEnum,
    ImportPreview,
)

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# Adapter selection
# ═════════════════════════════════════════════════════════════════════════════


def select_adapter_for_url(url: str) -> ExternalHTMLNotesAdapter:
    """Route URL to the correct adapter.

    Rules:
      - allin-podcast-zh-notes URLs → AllInZHNotesAdapter
      - everything else → GenericWebPageAdapter
    """
    url_lower = url.lower()
    is_allin = (
        SITE_BASE.lower() in url_lower
        or "allin-podcast-zh-notes" in url_lower
    )

    if is_allin:
        from signalvault.adapters.allin_zh_notes import AllInZHNotesAdapter
        return AllInZHNotesAdapter()

    from signalvault.adapters.generic_web_page import GenericWebPageAdapter
    return GenericWebPageAdapter()


# ═════════════════════════════════════════════════════════════════════════════
# Preview builder
# ═════════════════════════════════════════════════════════════════════════════


def build_import_preview(url: str, vault_path: Path) -> ImportPreview:
    """Build an ImportPreview for a URL without making any writes.

    1. select_adapter_for_url(url)
    2. fetch & parse
    3. detect conflicts
    4. compute recommended_action + available_actions
    5. return ImportPreview (NO writes)
    """
    adapter = select_adapter_for_url(url)
    adapter_name = adapter.__class__.__name__

    # ── Fetch & parse ───────────────────────────────────────────────────
    source_type = "derived"
    provider = adapter.provider_name

    # Prepare default preview fields from parse result
    is_allin = isinstance(adapter_name, str) and "AllInZH" in adapter_name
    if is_allin:
        from signalvault.adapters.allin_zh_notes import AllInZHNotesAdapter
        assert isinstance(adapter, AllInZHNotesAdapter)  # for type narrowing
    else:
        from signalvault.adapters.generic_web_page import (
            GenericWebPageAdapter,
        )
        source_type = "generic_web_page"
        assert isinstance(adapter, GenericWebPageAdapter)

    # Fetch: AllInZHNotesAdapter → NormalizedSourceDocument
    #        GenericWebPageAdapter → ParsedWebPage
    try:
        if is_allin:
            doc = adapter.fetch_episode(url)
            title = doc.title
            summary = doc.summary
            detected_video_id = doc.youtube_video_id
            original_source_url = doc.original_source_url
            content_hash = ""  # NormalizedSourceDocument has no raw HTML hash
            canonical_url = url  # no separate canonical for episode pages
            parse_quality = _infer_allin_quality(doc)
            content_blocks_count = (
                len(doc.key_points) + len(doc.timeline)
                + len(doc.speaker_viewpoints) + len(doc.bilingual_quotes)
            )
            source_confidence = "secondary"
            parsed_data: object = doc
        else:
            parsed = adapter.fetch_page(url)
            title = parsed.title or url
            summary = parsed.summary
            detected_video_id = _extract_first_video_id(parsed.detected_youtube_urls)
            original_source_url = (
                parsed.detected_youtube_urls[0] if parsed.detected_youtube_urls else ""
            )
            content_hash = parsed.content_hash
            canonical_url = parsed.canonical_url
            parse_quality = parsed.parse_quality
            content_blocks_count = parsed.content_blocks_count
            source_confidence = "secondary"
            parsed_data = parsed

    except Exception as e:
        # Fatal fetch/parse error → minimal preview
        logger.error("Preview fetch/parse failed for %s: %s", url, e)
        return ImportPreview(
            url=url,
            adapter_name=adapter_name,
            provider=provider,
            source_type=source_type,
            title=url,
            parse_quality="minimal",
            source_confidence="secondary",
            warning_messages=[f"页面抓取失败: {str(e)[:200]}"],
            recommended_action=ActionEnum.skip,
            available_actions=[ActionEnum.skip],
        )

    # ── Conflict detection ──────────────────────────────────────────────
    detector = ConflictDetector(vault_path)
    conflicts = detector.detect(
        url=url,
        canonical_url=canonical_url,
        content_hash=content_hash,
        detected_youtube_video_id=detected_video_id,
    )

    # ── Recommendation ──────────────────────────────────────────────────
    recommended, available, warnings = _compute_recommendation(
        is_allin=is_allin,
        detected_video_id=detected_video_id,
        conflicts=conflicts,
        parse_quality=parse_quality,
    )

    return ImportPreview(
        url=url,
        adapter_name=adapter_name,
        provider=provider,
        source_type=source_type,
        title=title,
        canonical_url=canonical_url,
        detected_youtube_video_id=detected_video_id,
        original_source_url=original_source_url,
        summary=summary,
        content_blocks_count=content_blocks_count,
        parse_quality=parse_quality,
        source_confidence=source_confidence,
        content_hash=content_hash,
        conflicts=conflicts,
        recommended_action=recommended,
        available_actions=available,
        warning_messages=warnings,
        _parsed_data=parsed_data,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Recommendation engine
# ═════════════════════════════════════════════════════════════════════════════


def _compute_recommendation(
    is_allin: bool,
    detected_video_id: str,
    conflicts: list,
    parse_quality: str,
) -> tuple[ActionEnum, list[ActionEnum], list[str]]:
    """Compute recommended action + available actions + warnings.

    Returns:
        (recommended_action, available_actions, warning_messages)
    """
    conflict_types = {c.conflict_type for c in conflicts}
    has_report = "same_video_id_report" in conflict_types
    has_deep_notes = "same_video_id_deep_notes" in conflict_types
    has_content_hash_conflict = "same_content_hash" in conflict_types

    warnings: list[str] = []
    available: list[ActionEnum] = [ActionEnum.skip]

    # ── Content hash duplicate is a hard block ─────────────────────────
    if has_content_hash_conflict:
        warnings.append("内容完全相同的页面已存在于归档中。建议跳过或覆盖归档。")
        available = [ActionEnum.skip, ActionEnum.archive_only]
        return ActionEnum.skip, available, warnings

    if is_allin:
        # ── All-In Podcast notes ────────────────────────────────────
        if has_report and not has_deep_notes:
            recommended = ActionEnum.import_as_deep_notes_linked
            available = [
                ActionEnum.import_as_deep_notes_linked,
                ActionEnum.import_as_deep_notes,
                ActionEnum.skip,
            ]
        elif has_deep_notes:
            recommended = ActionEnum.overwrite_deep_notes
            warnings.append("Deep Notes 已存在。覆盖将替换现有文件。")
            available = [
                ActionEnum.overwrite_deep_notes,
                ActionEnum.skip,
            ]
        elif detected_video_id and not has_report:
            recommended = ActionEnum.import_as_deep_notes_derived_only
            available = [
                ActionEnum.import_as_deep_notes_derived_only,
                ActionEnum.import_as_deep_notes,
                ActionEnum.skip,
            ]
        else:
            recommended = ActionEnum.import_as_deep_notes
            available = [
                ActionEnum.import_as_deep_notes,
                ActionEnum.import_as_deep_notes_derived_only,
                ActionEnum.skip,
            ]

    else:
        # ── Generic web page ────────────────────────────────────────
        if parse_quality == "minimal":
            warnings.append("页面解析质量极低，建议仅归档或跳过。")
            recommended = ActionEnum.archive_only
            available = [ActionEnum.archive_only, ActionEnum.skip]
        elif detected_video_id and has_report:
            recommended = ActionEnum.link_as_derived_source
            available = [
                ActionEnum.link_as_derived_source,
                ActionEnum.import_as_source_archive,
                ActionEnum.archive_only,
                ActionEnum.skip,
            ]
        else:
            recommended = ActionEnum.import_as_source_archive
            available = [
                ActionEnum.import_as_source_archive,
                ActionEnum.link_as_derived_source,
                ActionEnum.archive_only,
                ActionEnum.skip,
            ]

    return recommended, available, warnings


# ═════════════════════════════════════════════════════════════════════════════
# Confirm execution
# ═════════════════════════════════════════════════════════════════════════════


def execute_import_action(
    preview: ImportPreview,
    action: ActionEnum,
    vault_path: Path,
    overwrite: bool = False,
) -> dict:
    """Execute the confirmed import action. THIS is where writes happen.

    The parse/fetch happens AGAIN on confirm (preview stores only metadata,
    not a serialized copy of the parsed document).

    Returns:
        dict with "success" (bool), "message" (str), and optional extra fields.
    """
    if action == ActionEnum.skip:
        return {"success": True, "message": "已跳过导入"}

    # ── Deep Notes path ────────────────────────────────────────────────
    if action in (
        ActionEnum.import_as_deep_notes,
        ActionEnum.import_as_deep_notes_linked,
        ActionEnum.import_as_deep_notes_derived_only,
        ActionEnum.overwrite_deep_notes,
    ):
        return _execute_deep_notes_import(preview, action, vault_path, overwrite)

    # ── Source archive path ────────────────────────────────────────────
    if action in (
        ActionEnum.import_as_source_archive,
        ActionEnum.link_as_derived_source,
        ActionEnum.archive_only,
    ):
        return _execute_source_archive(preview, action, vault_path)

    return {"success": False, "message": f"未知操作: {action.value}"}


def _execute_deep_notes_import(
    preview: ImportPreview,
    action: ActionEnum,
    vault_path: Path,
    overwrite: bool,
) -> dict:
    """Re-fetch with AllInZHNotesAdapter and export as Deep Notes."""
    from signalvault.adapters.allin_zh_notes import AllInZHNotesAdapter
    from signalvault.exporters.deep_notes import export_deep_note

    adapter = AllInZHNotesAdapter()
    doc = adapter.fetch_episode(preview.url)
    result = export_deep_note(
        vault_path, doc,
        overwrite=(action == ActionEnum.overwrite_deep_notes or overwrite),
    )
    return {
        "success": True,
        "message": f"Deep Notes 已创建: {result['deep_notes_filename']}",
        **result,
    }


def _execute_source_archive(
    preview: ImportPreview,
    action: ActionEnum,
    vault_path: Path,
) -> dict:
    """Re-fetch with GenericWebPageAdapter and save as source archive."""
    from signalvault.adapters.generic_web_page import (
        GenericWebPageAdapter,
    )
    from signalvault.exporters.markdown_utils import (
        build_frontmatter,
        sanitize_filename,
    )

    adapter = GenericWebPageAdapter()
    parsed = adapter.fetch_page(preview.url)

    archive_dir = vault_path / "01_Reports" / "SourceArchive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    imported_at = now.strftime("%Y-%m-%d %H:%M")

    safe_title = sanitize_filename(preview.title or "untitled", fallback="web_page")
    provider_safe = sanitize_filename(preview.provider, fallback="generic")
    filename = f"{date_str}_{provider_safe}_{safe_title}.md"

    # Avoid overwrite without confirmation
    filepath = archive_dir / filename
    if filepath.exists() and action != ActionEnum.overwrite_deep_notes:
        hash_suffix = (parsed.content_hash or preview.content_hash)[:6]
        filename = f"{date_str}_{provider_safe}_{safe_title}_{hash_suffix}.md"
        filepath = archive_dir / filename

    fm = OrderedDict([
        ("type", "source_archive"),
        ("source_type", "generic_web_page"),
        ("provider", preview.provider),
        ("source_url", preview.url),
        ("canonical_url", parsed.canonical_url or preview.canonical_url),
        ("content_hash", parsed.content_hash or preview.content_hash),
        ("source_confidence", preview.source_confidence),
        ("fetched_at", imported_at),
        ("imported_at", imported_at),
        ("detected_youtube_video_id", preview.detected_youtube_video_id),
        (
            "linked_report_id",
            "" if action != ActionEnum.link_as_derived_source else "(待关联)",
        ),
        ("tags", ["source-archive"]),
    ])

    body = _build_source_archive_body(preview, parsed)
    content = build_frontmatter(fm) + "\n\n" + body
    filepath.write_text(content, encoding="utf-8")

    return {
        "success": True,
        "message": f"来源归档已创建: {filename}",
        "path": str(filepath),
        "filename": filename,
    }


def _build_source_archive_body(
    preview: ImportPreview,
    parsed: object,  # ParsedWebPage (lazy import)
) -> str:
    """Build Markdown body for a source archive file."""
    sections = [
        f"# {preview.title or preview.url}",
        "",
        "## 元数据",
        "",
        f"- **来源 URL**: {preview.url}",
        f"- **规范 URL**: {parsed.canonical_url or preview.canonical_url or '无'}",
        f"- **解析质量**: {parsed.parse_quality or preview.parse_quality}",
        f"- **内容哈希**: `{parsed.content_hash or preview.content_hash}`",
        f"- **内容块数量**: {parsed.content_blocks_count or preview.content_blocks_count}",
    ]
    if preview.detected_youtube_video_id:
        sections.append(
            f"- **YouTube Video ID**: `{preview.detected_youtube_video_id}`"
        )

    sections.extend(["", "## 摘要", "", preview.summary or parsed.summary or "*无摘要*", ""])

    if parsed.h1_texts:
        sections.extend(["## 页面标题", ""])
        for h in parsed.h1_texts[:10]:
            sections.append(f"- {h}")
        sections.append("")

    if parsed.h2_texts:
        sections.extend(["## 章节标题", ""])
        for h in parsed.h2_texts[:20]:
            sections.append(f"- {h}")
        sections.append("")

    if parsed.paragraphs:
        sections.extend(["## 正文段落", ""])
        for i, p in enumerate(parsed.paragraphs[:30], 1):
            sections.append(f"{i}. {p}")
        sections.append("")

    sections.extend([
        "---",
        "",
        f"*此归档由 signalvault P2-S.3.1 自动生成，"
        f"内容来源于 [{preview.url}]({preview.url})。*",
        "",
    ])

    return "\n".join(sections)


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════


def _extract_first_video_id(youtube_urls: list[str]) -> str:
    """Extract the first YouTube video ID from a list of URLs."""
    from signalvault.adapters.external_html_notes import (
        ExternalHTMLNotesAdapter,
    )
    for yt_url in youtube_urls:
        vid = ExternalHTMLNotesAdapter._extract_video_id_from_url(yt_url)
        if vid:
            return vid
    return ""


def _infer_allin_quality(doc) -> str:
    """Infer parse quality from a NormalizedSourceDocument."""
    from signalvault.exporters.deep_notes import check_document_health
    health = check_document_health(doc)
    if health["degraded"]:
        return "degraded"
    if health["content_sections_populated"] >= 4:
        return "good"
    if health["content_sections_populated"] >= 2:
        return "degraded"
    return "minimal"
