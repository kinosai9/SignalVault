"""P2-S.2: Deep Notes Export — 将外部衍生信息源导出为 Obsidian Deep Notes。

将 P2-S.1 的 NormalizedSourceDocument 导出为 Obsidian 可读笔记：
- 01_Reports/DeepNotes/  → 深度精读笔记
- 与现有 YouTube Report 双向链接
- derived-only 文档自动标记
- parser health check (degraded flag)
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from signalvault.adapters.external_html_notes import (
    NormalizedSourceDocument,
)
from signalvault.exporters.markdown_utils import (
    build_frontmatter,
    sanitize_filename,
)

logger = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════════
# Health check
# ═════════════════════════════════════════════════════════════════════════════


def check_document_health(doc: NormalizedSourceDocument) -> dict:
    """Check if a NormalizedSourceDocument has minimum viable content.

    Returns a dict with:
        - healthy: bool — True if at least one content section has data
        - degraded: bool — True if ALL of key_points/timeline/speaker_turns are empty
        - reasons: list[str] — human-readable reasons for degradation
        - content_sections_populated: int — how many of the 5 main sections have data
    """
    sections = {
        "key_points": len(doc.key_points) > 0,
        "timeline": len(doc.timeline) > 0,
        "speaker_viewpoints": len(doc.speaker_viewpoints) > 0,
        "bilingual_quotes": len(doc.bilingual_quotes) > 0,
        "summary": bool(doc.summary and doc.summary.strip()),
    }

    populated = sum(1 for v in sections.values() if v)
    core_empty = (
        len(doc.key_points) == 0
        and len(doc.timeline) == 0
    )
    # Check speaker turns within timeline segments
    has_speaker_turns = any(
        len(seg.speaker_turns) > 0 for seg in doc.timeline
    )

    reasons: list[str] = []
    degraded = False

    if len(doc.key_points) == 0:
        reasons.append("key_points is empty")
    if len(doc.timeline) == 0:
        reasons.append("timeline is empty")
    if not has_speaker_turns and len(doc.timeline) > 0:
        reasons.append("timeline has segments but no speaker turns")
    if len(doc.speaker_viewpoints) == 0:
        reasons.append("speaker_viewpoints is empty")
    if len(doc.bilingual_quotes) == 0:
        reasons.append("bilingual_quotes is empty")

    # Degraded = ALL three core content sections are effectively empty
    if core_empty and not has_speaker_turns and len(doc.speaker_viewpoints) == 0:
        degraded = True
        if not reasons:
            reasons.append("all core content sections are empty")

    # Edge case: has summary but nothing else → still degraded
    if degraded and doc.summary:
        reasons.append("only summary is present, all structured sections are empty")

    return {
        "healthy": not degraded and populated >= 1,
        "degraded": degraded,
        "reasons": reasons,
        "content_sections_populated": populated,
    }


# ═════════════════════════════════════════════════════════════════════════════
# Deep Notes Markdown generation
# ═════════════════════════════════════════════════════════════════════════════


def _build_deep_notes_frontmatter(
    doc: NormalizedSourceDocument,
    linked_report_id: int | None = None,
    linked_report_path: str = "",
    derived_only: bool = False,
    degraded: bool = False,
    imported_at: str = "",
) -> OrderedDict:
    """Build YAML frontmatter for a Deep Notes file."""
    tags = ["deep-notes", "derived-source"]
    if derived_only:
        tags.append("derived-only")
    if degraded:
        tags.append("degraded")

    fm = OrderedDict([
        ("type", "deep_notes"),
        ("source_type", "derived"),
        ("source_confidence", "secondary"),
        ("provider", doc.provider),
        ("source_url", doc.source_url),
        ("original_source_url", doc.original_source_url),
        ("youtube_video_id", doc.youtube_video_id),
        ("title", doc.title),
        ("slug", doc.slug),
        ("generated_at", doc.generated_at),
        ("reading_time", doc.reading_time),
        ("imported_at", imported_at or datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("linked_report_id", linked_report_id or ""),
        ("linked_report_path", linked_report_path),
        ("derived_only", derived_only),
        ("degraded", degraded),
        ("tags", tags),
    ])
    return fm


def _format_key_points(key_points: list[str]) -> str:
    """Format key points as numbered list."""
    if not key_points:
        return "*（无核心要点）*"

    lines = []
    for i, pt in enumerate(key_points, 1):
        lines.append(f"{i}. {pt}")
    return "\n".join(lines)


def _format_timeline(timeline) -> str:
    """Format timeline segments as structured Markdown."""
    if not timeline:
        return "*（无时间线分段）*"

    sections = []
    for seg in timeline:
        # Segment header
        time_str = f" `{seg.time_range}`" if seg.time_range else ""
        sections.append(f"### {seg.index:02d}. {seg.title}{time_str}")
        sections.append("")

        # Core points
        if seg.core_points:
            sections.append("**核心内容**")
            sections.append("")
            for cp in seg.core_points:
                sections.append(f"- {cp}")
            sections.append("")

        # Background terms
        if seg.background_terms:
            sections.append("**背景术语**")
            sections.append("")
            for term in seg.background_terms:
                term_name = term.get("term", "")
                term_def = term.get("definition", "")
                if term_def:
                    sections.append(f"- **{term_name}**：{term_def}")
                else:
                    sections.append(f"- **{term_name}**")
            sections.append("")

        # Speaker turns
        if seg.speaker_turns:
            sections.append("**逐段发言**")
            sections.append("")
            for turn in seg.speaker_turns:
                speaker = turn.speaker_name
                text = turn.text
                sections.append(f"> **{speaker}**：{text}")
                sections.append("")

        sections.append("---")
        sections.append("")

    return "\n".join(sections)


def _format_speaker_viewpoints(viewpoints) -> str:
    """Format speaker viewpoints as cards."""
    if not viewpoints:
        return "*（无人物观点）*"

    sections = []
    for vp in viewpoints:
        role_str = f"（{vp.role}）" if vp.role else ""
        sections.append(f"### {vp.name} {role_str}")
        sections.append("")
        if vp.viewpoint:
            sections.append(vp.viewpoint)
        sections.append("")

    return "\n".join(sections)


def _format_bilingual_quotes(quotes) -> str:
    """Format bilingual quotes as blockquotes."""
    if not quotes:
        return "*（无双语引语）*"

    sections = []
    for i, q in enumerate(quotes, 1):
        sections.append(f"**{i}.**")
        sections.append("")
        if q.text_en:
            sections.append(f"> {q.text_en}")
            sections.append("")
        if q.text_zh:
            sections.append(f"> {q.text_zh}")
            sections.append("")
        if q.context_note:
            sections.append(f"*{q.context_note}*")
            sections.append("")
        sections.append("")

    return "\n".join(sections)


def _format_background_terms(timeline) -> str:
    """Extract and deduplicate all background terms across timeline segments."""
    seen: set[str] = set()
    all_terms: list[dict] = []

    for seg in timeline:
        for term in seg.background_terms:
            term_name = term.get("term", "")
            if term_name and term_name not in seen:
                seen.add(term_name)
                all_terms.append(term)

    if not all_terms:
        return "*（无背景术语）*"

    lines = []
    for term in all_terms:
        term_name = term.get("term", "")
        term_def = term.get("definition", "")
        if term_def:
            lines.append(f"- **{term_name}**：{term_def}")
        else:
            lines.append(f"- **{term_name}**")

    return "\n".join(lines)


def build_deep_notes_body(
    doc: NormalizedSourceDocument,
    linked_report_path: str = "",
    derived_only: bool = False,
    degraded: bool = False,
) -> str:
    """Build the full Markdown body for a Deep Notes file.

    Args:
        doc: NormalizedSourceDocument from adapter.
        linked_report_path: Wiki link path to the existing YouTube report (if any).
        derived_only: True if no existing YouTube report exists for this video_id.
        degraded: True if parser health check indicates degraded content.
    """
    sections: list[str] = []

    # ── Title ────────────────────────────────────────────────────────────
    sections.append(f"# {doc.title}")
    sections.append("")

    # ── Health warning ───────────────────────────────────────────────────
    if degraded:
        sections.append("> [!warning] 解析状态：内容不完整")
        sections.append("> 此 Deep Notes 的关键内容部分（核心要点 / 时间线 / 人物观点）为空或严重不全。")
        sections.append("> 原始页面可能结构异常或解析器需要更新。")
        sections.append("")

    # ── Status badges ────────────────────────────────────────────────────
    if derived_only:
        sections.append("> [!info] 独立深度笔记（Derived Only）")
        sections.append("> 此笔记对应的 YouTube 视频尚未生成投资分析报告。")
        sections.append("> 内容仅来源于外部精读页面，不包含 AI 投资观点抽取。")
        sections.append("")

    # ── Source attribution ───────────────────────────────────────────────
    sections.append("## 来源信息")
    sections.append("")
    sections.append(f"- **提供方**：{doc.provider}")
    sections.append("- **来源类型**：衍生信息源（derived / secondary）")
    sections.append(f"- **精读页面**：{doc.source_url}")
    if doc.original_source_url:
        sections.append(f"- **原始来源**：{doc.original_source_url}")
    if doc.generated_at:
        sections.append(f"- **页面生成时间**：{doc.generated_at}")
    if doc.reading_time:
        sections.append(f"- **预计阅读**：{doc.reading_time}")
    if doc.youtube_video_id:
        sections.append(f"- **YouTube ID**：`{doc.youtube_video_id}`")
    sections.append("")

    # ── Linked report ────────────────────────────────────────────────────
    if linked_report_path:
        sections.append("## 关联报告")
        sections.append("")
        sections.append(f"- 投资分析报告：[[{linked_report_path}]]")
        sections.append("")
    elif derived_only:
        sections.append("## 关联报告")
        sections.append("")
        sections.append("- *暂无关联的投资分析报告*")
        sections.append("")

    # ── Summary ──────────────────────────────────────────────────────────
    if doc.summary:
        sections.append("## 摘要")
        sections.append("")
        sections.append(doc.summary)
        sections.append("")

    # ── Key points ───────────────────────────────────────────────────────
    sections.append("## 核心要点")
    sections.append("")
    sections.append(_format_key_points(doc.key_points))
    sections.append("")

    # ── Timeline ─────────────────────────────────────────────────────────
    sections.append("## 时间线精读")
    sections.append("")
    sections.append(_format_timeline(doc.timeline))
    sections.append("")

    # ── Background terms ─────────────────────────────────────────────────
    sections.append("## 背景术语")
    sections.append("")
    sections.append(_format_background_terms(doc.timeline))
    sections.append("")

    # ── Speaker viewpoints ───────────────────────────────────────────────
    sections.append("## 人物观点")
    sections.append("")
    sections.append(_format_speaker_viewpoints(doc.speaker_viewpoints))
    sections.append("")

    # ── Bilingual quotes ─────────────────────────────────────────────────
    sections.append("## 双语引语")
    sections.append("")
    sections.append(_format_bilingual_quotes(doc.bilingual_quotes))
    sections.append("")

    # ── Attribution footer ───────────────────────────────────────────────
    sections.append("---")
    sections.append("")
    sections.append(
        f"*此笔记由 signalvault P2-S.2 Deep Notes Export 自动生成，"
        f"内容来源于 [{doc.provider}]({doc.source_url})。*"
    )
    sections.append(
        "*外部衍生信息源，不作为投资决策的唯一依据。原始内容版权归原作者所有。*"
    )
    sections.append("")

    return "\n".join(sections)


# ═════════════════════════════════════════════════════════════════════════════
# Export orchestrator
# ═════════════════════════════════════════════════════════════════════════════


def _ensure_deep_notes_dir(vault_path: Path) -> Path:
    """Ensure 01_Reports/DeepNotes/ exists."""
    deep_notes_dir = vault_path / "01_Reports" / "DeepNotes"
    deep_notes_dir.mkdir(parents=True, exist_ok=True)
    return deep_notes_dir


def _generate_filename(doc: NormalizedSourceDocument) -> str:
    """Generate a safe filename for a Deep Notes file.

    Pattern: {date}_{provider}_{slug}.md
    Falls back to video_id if slug is empty.
    """
    date_str = ""
    if doc.generated_at:
        # Extract date part: "2026-04-30 15:59" → "2026-04-30"
        date_str = doc.generated_at[:10] if len(doc.generated_at) >= 10 else doc.generated_at

    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    provider_safe = sanitize_filename(doc.provider, fallback="external")

    # Use slug for uniqueness, fall back to video_id
    identifier = doc.slug or doc.youtube_video_id or "untitled"
    id_safe = sanitize_filename(identifier, fallback="untitled")

    return f"{date_str}_{provider_safe}_{id_safe}.md"


def _find_existing_report(video_id: str) -> dict | None:
    """Find existing report by YouTube video_id in the database.

    Returns dict with report_id, episode_id, report_path etc., or None.
    """
    if not video_id:
        return None

    try:
        from signalvault.db.repository import find_report_by_video_id
        from signalvault.db.session import get_session, init_db

        init_db()
        session = get_session()
        try:
            return find_report_by_video_id(session, video_id)
        finally:
            session.close()
    except Exception as e:
        logger.warning("Failed to query DB for video_id '%s': %s", video_id, e)
        return None


def _infer_linked_report_path(
    report_info: dict | None,
    vault_path: Path,
) -> str:
    """Infer the wiki link path for the linked report.

    Returns the filename (without extension) for wiki linking, or empty string.
    """
    if not report_info:
        return ""

    # Try to find report file in 01_Reports/
    reports_dir = vault_path / "01_Reports"
    if reports_dir.exists():
        vid = report_info.get("video_id", "")
        if vid:
            for rf in reports_dir.glob("*.md"):
                # Check frontmatter for video_id match
                try:
                    content = rf.read_text(encoding="utf-8")
                    if f"video_id: {vid}" in content or f"video_id:{vid}" in content:
                        return rf.stem
                except Exception:
                    pass

    # Fallback: return empty (no wiki link)
    return ""


def export_deep_note(
    vault_path: Path,
    doc: NormalizedSourceDocument,
    overwrite: bool = False,
) -> dict:
    """Export a NormalizedSourceDocument as a Deep Notes markdown file.

    Orchestrates:
    1. Health check → degraded flag
    2. DB lookup by video_id → linked report info
    3. Frontmatter + body generation
    4. Write to 01_Reports/DeepNotes/

    Args:
        vault_path: Root of the Obsidian vault.
        doc: NormalizedSourceDocument from adapter.
        overwrite: If True, overwrite existing Deep Notes file.

    Returns:
        dict with:
            - status: "created" | "skipped" | "degraded"
            - path: str (file path)
            - deep_notes_filename: str
            - linked_report_id: int | None
            - linked_report_path: str
            - derived_only: bool
            - degraded: bool
            - health: dict (from check_document_health)
    """
    # 1. Health check
    health = check_document_health(doc)

    # 2. Find existing report
    report_info = _find_existing_report(doc.youtube_video_id) if doc.youtube_video_id else None
    derived_only = report_info is None

    # 3. Infer linked report path for wiki linking
    linked_report_path = _infer_linked_report_path(report_info, vault_path)

    # 4. Generate filename and path
    deep_notes_dir = _ensure_deep_notes_dir(vault_path)
    filename = _generate_filename(doc)
    filepath = deep_notes_dir / filename

    # 5. Check if already exists
    if filepath.exists() and not overwrite:
        logger.info("Deep Notes already exists: %s", filepath)
        return {
            "status": "skipped",
            "path": str(filepath),
            "deep_notes_filename": filename,
            "linked_report_id": report_info["id"] if report_info else None,
            "linked_report_path": linked_report_path,
            "derived_only": derived_only,
            "degraded": health["degraded"],
            "health": health,
        }

    # 6. Build frontmatter
    imported_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    fm = _build_deep_notes_frontmatter(
        doc,
        linked_report_id=report_info["id"] if report_info else None,
        linked_report_path=linked_report_path,
        derived_only=derived_only,
        degraded=health["degraded"],
        imported_at=imported_at,
    )

    # 7. Build body
    body = build_deep_notes_body(
        doc,
        linked_report_path=linked_report_path,
        derived_only=derived_only,
        degraded=health["degraded"],
    )

    # 8. Write file
    content = build_frontmatter(fm) + "\n\n" + body
    filepath.write_text(content, encoding="utf-8")
    logger.info(
        "Deep Notes exported: %s (derived_only=%s, degraded=%s)",
        filepath, derived_only, health["degraded"],
    )

    # 9. If linked to existing report, update the report's derived_sources
    if report_info and not derived_only:
        _update_report_derived_sources(
            vault_path, report_info, filename, linked_report_path,
        )

    return {
        "status": "degraded" if health["degraded"] else "created",
        "path": str(filepath),
        "deep_notes_filename": filename,
        "linked_report_id": report_info["id"] if report_info else None,
        "linked_report_path": linked_report_path,
        "derived_only": derived_only,
        "degraded": health["degraded"],
        "health": health,
    }


def _update_report_derived_sources(
    vault_path: Path,
    report_info: dict,
    deep_notes_filename: str,
    linked_report_path: str = "",
) -> None:
    """Update the existing report's Obsidian file to include derived_sources link.

    Adds a `derived_sources` field to the frontmatter and a "Deep Notes" section
    if not already present.
    """
    if not report_info:
        return

    reports_dir = vault_path / "01_Reports"
    if not reports_dir.exists():
        return

    vid = report_info.get("video_id", "")
    if not vid:
        return

    # Find the report file
    target_file = None
    for rf in reports_dir.glob("*.md"):
        try:
            content = rf.read_text(encoding="utf-8")
            if f"video_id: {vid}" in content or f"video_id:{vid}" in content:
                target_file = rf
                break
        except Exception:
            pass

    if not target_file:
        logger.debug("No Obsidian report file found for video_id=%s", vid)
        return

    try:
        content = target_file.read_text(encoding="utf-8")

        # Check if deep_notes link already present
        deep_notes_stem = Path(deep_notes_filename).stem
        if f"[[{deep_notes_stem}]]" in content:
            logger.debug("Deep Notes link already present in report %s", target_file)
            return

        # Add derived_sources to frontmatter
        if "derived_sources:" not in content:
            # Insert after the first tag or after source_url
            if "\ntags:" in content:
                content = content.replace(
                    "\ntags:",
                    f"\nderived_sources:\n  - \"[[{deep_notes_stem}]]\"\ntags:",
                    1,
                )
            elif "\nsource_url:" in content:
                content = content.replace(
                    "\nsource_url:",
                    f"\nderived_sources:\n  - \"[[{deep_notes_stem}]]\"\nsource_url:",
                    1,
                )
            else:
                # Insert after the first frontmatter line
                first_line_end = content.find("\n", content.find("---") + 3)
                if first_line_end > 0:
                    content = (
                        content[:first_line_end + 1]
                        + f"derived_sources:\n  - \"[[{deep_notes_stem}]]\"\n"
                        + content[first_line_end + 1:]
                    )

        # Add Deep Notes section before Notes section (or at end)
        if "## Deep Notes" not in content:
            deep_notes_section = (
                "\n## Deep Notes\n\n"
                f"- [[{deep_notes_stem}]] — 外部中文精读笔记\n"
            )
            if "## Notes" in content:
                content = content.replace("## Notes", deep_notes_section + "## Notes", 1)
            else:
                content = content.rstrip() + "\n" + deep_notes_section + "\n"

        target_file.write_text(content, encoding="utf-8")
        logger.info("Updated report %s with derived_sources link", target_file)

    except Exception as e:
        logger.warning("Failed to update report derived_sources: %s", e)


# ═════════════════════════════════════════════════════════════════════════════
# Batch export
# ═════════════════════════════════════════════════════════════════════════════


def export_deep_notes_batch(
    vault_path: Path,
    documents: list[NormalizedSourceDocument],
    overwrite: bool = False,
    skip_degraded: bool = False,
) -> dict:
    """Export multiple NormalizedSourceDocuments as Deep Notes.

    Args:
        vault_path: Root of the Obsidian vault.
        documents: List of NormalizedSourceDocument from adapter.
        overwrite: If True, overwrite existing files.
        skip_degraded: If True, skip documents that fail health check.

    Returns:
        dict with created, skipped, degraded, results list.
    """
    created = 0
    skipped = 0
    degraded_count = 0
    results = []

    for doc in documents:
        result = export_deep_note(vault_path, doc, overwrite=overwrite)

        if result["degraded"] and skip_degraded:
            degraded_count += 1
            result["status"] = "skipped_degraded"
            results.append(result)
            continue

        if result["degraded"]:
            degraded_count += 1

        if result["status"] == "created" or result["status"] == "degraded":
            created += 1
        elif result["status"] == "skipped":
            skipped += 1

        results.append(result)

    return {
        "created": created,
        "skipped": skipped,
        "degraded": degraded_count,
        "results": results,
    }
