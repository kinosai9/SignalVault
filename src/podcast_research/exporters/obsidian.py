"""P2-C: Obsidian Vault Export v1.

将 SQLite 中的 YouTube 报告导出为 Obsidian 笔记：
- 01_Reports/  → 单视频报告（YAML frontmatter + 结构化 Markdown）
- 05_Channels/ → 频道卡片
- 99_System/   → Report Index + Export Log
"""

from __future__ import annotations

# P2-M.3: Current system versions — written to report frontmatter
CURRENT_PIPELINE_VERSION = "p2-m3"
CURRENT_SYNC_VERSION = "p2-m3"

import contextlib
import json
import logging
import re
import shutil
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from podcast_research.db.models import Episode, InvestmentViewRecord, Report
from podcast_research.db.repository import _infer_source_type, _parse_focus_areas
from podcast_research.db.session import get_session, init_db
from podcast_research.exporters.markdown_utils import (
    _WIKI_LINK_ENTITY_TYPES,
    build_frontmatter,
    sanitize_filename,
    wiki_link,
    wiki_links_from_list,
)
from podcast_research.utils.file_io import read_text_safe

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# Vault paths
# ═════════════════════════════════════════════════════════════════════════════

def _ensure_vault_dirs(vault_path: Path) -> None:
    """Ensure subdirectories exist inside vault (vault root must exist)."""
    for subdir in ["01_Reports", "05_Channels", "99_System"]:
        (vault_path / subdir).mkdir(parents=True, exist_ok=True)


# ═════════════════════════════════════════════════════════════════════════════
# Report export
# ═════════════════════════════════════════════════════════════════════════════

def _load_extraction(report: Report) -> dict:
    """Parse extraction_json from report, returning empty dict on failure."""
    try:
        return json.loads(report.extraction_json)
    except (json.JSONDecodeError, TypeError):
        return {}


def _build_report_frontmatter(
    report: Report,
    episode: Episode,
    extraction: dict,
    channel_name: str = "",
) -> OrderedDict:
    """Build YAML frontmatter for a report note."""
    source_info = extraction.get("source_info", {}) or {}
    metadata = extraction.get("metadata", {}) or {}

    return OrderedDict([
        ("type", "report"),
        ("source_type", _infer_source_type(episode)),
        ("channel", channel_name or source_info.get("channel_name", "")),
        ("video_id", episode.video_id),
        ("video_url", source_info.get("source_url", episode.source_url)),
        ("published_at", source_info.get("published_at", "")),
        ("analyzed_at", report.analysis_timestamp.strftime("%Y-%m-%d %H:%M") if report.analysis_timestamp else ""),
        ("prompt_version", extraction.get("prompt_version", report.prompt_version)),
        ("pipeline_version", CURRENT_PIPELINE_VERSION),
        ("sync_version", CURRENT_SYNC_VERSION),
        ("model", metadata.get("model", report.llm_model)),
        ("focus_areas", _parse_focus_areas(report.focus_areas)),
        ("tags", ["podcast-report"]),
    ])


def _format_views_table(views_data: list[dict]) -> str:
    """Format investment views as Markdown table."""
    if not views_data:
        return "No investment views found."

    lines = [
        "| 标的 | 方向 | AI价值链 | 证据类型 | 证据强度 | 时间范围 | 时间戳 |",
        "|------|------|----------|----------|----------|----------|--------|",
    ]
    for v in views_data:
        lines.append(
            f"| {v.get('target_name', '')} "
            f"| {v.get('view_direction', '')} "
            f"| {v.get('ai_value_chain_layer', '') or '-'} "
            f"| {v.get('evidence_type', '')} "
            f"| {v.get('evidence_strength', '')} "
            f"| {v.get('time_horizon', '')} "
            f"| {v.get('timestamp_start', '')} |"
        )
    return "\n".join(lines)


def _format_insights_list(insights_data: list[dict]) -> str:
    """Format tech/industry insights as Markdown bullet list."""
    if not insights_data:
        return "No tech/industry insights."

    lines = []
    for _i, ins in enumerate(insights_data):
        tags = " ".join(f"#{t}" for t in ins.get("topic_tags", []))
        lines.append(f"- **{ins.get('insight', '')}** `{tags}`")
        if ins.get("source_quote"):
            lines.append(f"  > {ins['source_quote']}")
    return "\n".join(lines)


def _extract_entity_wiki_links(extraction: dict) -> list[str]:
    """Extract wiki-linkable entity names from extraction."""
    entities = extraction.get("mentioned_entities", []) or []
    links = []
    for e in entities:
        etype = e.get("entity_type", "")
        name = e.get("normalized_name") or e.get("name", "")
        if etype in _WIKI_LINK_ENTITY_TYPES and name:
            links.append(wiki_link(name))
    return links


def _extract_topic_wiki_links(views_data: list[dict]) -> list[str]:
    """Extract topic-based wiki links from investment views' topic_tags."""
    all_tags = set()
    for v in views_data:
        tags = v.get("topic_tags", [])
        if isinstance(tags, list):
            for t in tags:
                if t:
                    all_tags.add(t.title())
    return [wiki_link(t) for t in sorted(all_tags)]


def _build_report_body(
    report: Report,
    episode: Episode,
    extraction: dict,
    views_data: list[dict],
    channel_name: str = "",
) -> str:
    """Build the Markdown body for a report note."""
    source_info = extraction.get("source_info", {}) or {}
    title = source_info.get("title") or episode.video_id or episode.title

    sections = [
        f"# {title}",
        "",
        "## Summary",
        "",
        extraction.get("executive_summary", ""),
        "",
        "## Source",
        "",
        f"- **Channel**: {wiki_link(channel_name) or source_info.get('channel_name', 'Unknown')}",
        f"- **Video**: {wiki_link(title) if title else 'N/A'}",
        f"- **URL**: {source_info.get('source_url', episode.source_url)}",
        f"- **Published**: {source_info.get('published_at', '')}",
        f"- **Analyzed**: {report.analysis_timestamp.strftime('%Y-%m-%d %H:%M') if report.analysis_timestamp else ''}",
        f"- **Prompt Version**: {extraction.get('prompt_version', '')}",
        f"- **Language**: {episode.language or source_info.get('language', '')}",
        "",
        "## Core Investment Views",
        "",
        _format_views_table(views_data),
        "",
        "## Tech / Industry Insights",
        "",
        _format_insights_list(extraction.get("tech_industry_insights", []) or []),
        "",
        "## Risks",
        "",
    ]

    # Risks
    risks = extraction.get("risks", []) or []
    if risks:
        for r in risks:
            sections.append(f"- **{r.get('description', '')}**")
            if r.get("source_quote"):
                sections.append(f"  > {r['source_quote']}")
    else:
        sections.append("No risks identified.")

    sections.extend([
        "",
        "## Tracking Signals",
        "",
    ])

    # Signals
    signals = extraction.get("tracking_signals", []) or []
    if signals:
        for s in signals:
            sections.append(f"- **{s.get('signal', '')}**")
            if s.get("target_name"):
                sections.append(f"  - Target: {s['target_name']}")
            if s.get("trigger_condition"):
                sections.append(f"  - Trigger: {s['trigger_condition']}")
    else:
        sections.append("No tracking signals.")

    # Entities with wiki links
    entity_links = _extract_entity_wiki_links(extraction)
    topic_links = _extract_topic_wiki_links(views_data)

    sections.extend([
        "",
        "## Entities",
        "",
        wiki_links_from_list(list(dict.fromkeys(entity_links))) if entity_links else "No entities.",
        "",
        "## Source Quotes",
        "",
    ])

    quotes = extraction.get("key_quotes", []) or []
    for q in quotes:
        sections.append(f"> {q}")
    if not quotes:
        sections.append("No source quotes extracted.")

    # Related Links
    sections.extend([
        "",
        "## Related Links",
        "",
    ])
    related = []
    if channel_name:
        related.append(wiki_link(channel_name))
    related.extend(entity_links[:10])
    related.extend(topic_links[:10])
    deduped = list(dict.fromkeys(related))
    for link in deduped:
        if link:
            sections.append(f"- {link}")

    sections.extend([
        "",
        "## Notes",
        "",
        "*Exported by podcast-research P2-C Obsidian Export v1*",
        "",
    ])

    return "\n".join(sections)


def export_report(
    vault_path: Path,
    report: Report,
    episode: Episode,
    views_data: list[dict],
    extraction: dict,
    channel_name: str = "",
    overwrite: bool = False,
) -> dict:
    """Export a single report to the Obsidian vault.

    Returns:
        {"status": "created"|"skipped", "path": str}
    """
    _ensure_vault_dirs(vault_path)

    source_info = extraction.get("source_info", {}) or {}
    published = source_info.get("published_at", "") or ""
    date_str = published[:10] if published else report.analysis_timestamp.strftime("%Y-%m-%d") if report.analysis_timestamp else datetime.now().strftime("%Y-%m-%d")

    vid = episode.video_id or "unknown"
    # P2-L.2: Fallback priority — channel_name > source_info.channel_name > YouTube_{vid}
    # Never default to "UnknownChannel" unless all fallback data is missing
    raw_ch = channel_name or source_info.get("channel_name", "")
    if raw_ch and raw_ch.lower() not in ("unknownchannel", "unknown", "none", ""):
        ch_name = sanitize_filename(raw_ch)
    else:
        ch_name = sanitize_filename(f"YouTube_{vid}")
    filename = f"{date_str}_{ch_name}_{vid}.md"
    filepath = vault_path / "01_Reports" / filename

    if filepath.exists() and not overwrite:
        return {"status": "skipped", "path": str(filepath)}

    # Build frontmatter + body
    fm = _build_report_frontmatter(report, episode, extraction, channel_name)
    body = _build_report_body(report, episode, extraction, views_data, channel_name)

    content = build_frontmatter(fm) + "\n\n" + body + "\n"
    filepath.write_text(content, encoding="utf-8")

    return {"status": "created", "path": str(filepath)}


# ═════════════════════════════════════════════════════════════════════════════
# Channel card export
# ═════════════════════════════════════════════════════════════════════════════

def export_channel_card(
    vault_path: Path,
    channel_name: str,
    channel_url: str = "",
    channel_tags: list[str] | None = None,
    channel_priority: str = "core",
    recent_reports: list[dict] | None = None,
    overwrite: bool = False,
) -> dict:
    """Export or update a channel card note.

    Returns:
        {"status": "created"|"updated"|"skipped"|"noop", "path": str}
    """
    _ensure_vault_dirs(vault_path)

    ch_safe = sanitize_filename(channel_name) if channel_name else "UnknownChannel"
    filepath = vault_path / "05_Channels" / f"{ch_safe}.md"

    if not filepath.exists():
        # Create new channel card
        fm = OrderedDict([
            ("type", "channel"),
            ("channel", channel_name),
            ("source_type", "youtube"),
            ("url", channel_url),
            ("tags", channel_tags or []),
            ("priority", channel_priority),
            ("updated_at", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ])
        body_lines = [
            f"# {channel_name}",
            "",
            "## Positioning",
            "",
            "## Recent Reports",
            "",
        ]
        if recent_reports:
            for r in recent_reports:
                body_lines.append(f"- {wiki_link(r['filename'])}")
        else:
            body_lines.append("*No reports exported yet.*")

        body_lines.extend([
            "",
            "## Recurring Topics",
            "",
            "## Key People",
            "",
            "## Notes",
            "",
        ])
        content = build_frontmatter(fm) + "\n\n" + "\n".join(body_lines) + "\n"
        filepath.write_text(content, encoding="utf-8")
        return {"status": "created", "path": str(filepath)}

    elif overwrite:
        # Overwrite mode: replace existing file entirely (same as create)
        fm = OrderedDict([
            ("type", "channel"),
            ("channel", channel_name),
            ("source_type", "youtube"),
            ("url", channel_url),
            ("tags", channel_tags or []),
            ("priority", channel_priority),
            ("updated_at", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ])
        body_lines = [
            f"# {channel_name}",
            "",
            "## Positioning",
            "",
            "## Recent Reports",
            "",
        ]
        if recent_reports:
            for r in recent_reports:
                body_lines.append(f"- {wiki_link(r['filename'])}")
        content = build_frontmatter(fm) + "\n\n" + "\n".join(body_lines) + "\n"
        filepath.write_text(content, encoding="utf-8")
        return {"status": "created", "path": str(filepath)}  # treat overwrite as created

    else:
        # File exists and no overwrite: append recent reports only
        existing = read_text_safe(filepath)
        new_reports_block = ""
        if recent_reports:
            new_links = [wiki_link(r["filename"]) for r in recent_reports]
            existing_links = set()
            for link in new_links:
                if link and link not in existing:
                    existing_links.add(link)
                    new_reports_block += f"- {link}\n"

        if new_reports_block:
            # Update updated_at in frontmatter
            updated = re.sub(
                r"updated_at:.*",
                f"updated_at: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                existing,
            )
            # Append new reports under Recent Reports section
            if "## Recent Reports" in updated:
                updated = updated.replace(
                    "## Recent Reports\n",
                    f"## Recent Reports\n{new_reports_block}",
                )
            else:
                # File has no Recent Reports section — append one before Notes or at end
                if "## Notes" in updated:
                    updated = updated.replace(
                        "## Notes",
                        f"## Recent Reports\n{new_reports_block}\n## Notes",
                    )
                else:
                    updated = updated.rstrip() + f"\n\n## Recent Reports\n{new_reports_block}\n"
            filepath.write_text(updated, encoding="utf-8")
            return {"status": "updated", "path": str(filepath)}

        return {"status": "noop", "path": str(filepath)}


# ═════════════════════════════════════════════════════════════════════════════
# System index & log
# ═════════════════════════════════════════════════════════════════════════════

def _export_report_index(vault_path: Path, exported: list[dict]) -> Path:
    """Generate 99_System/Report Index.md."""
    filepath = vault_path / "99_System" / "Report Index.md"
    lines = [
        "# Report Index",
        "",
        f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "| Date | Channel | Title | Video ID | Report |",
        "|------|---------|-------|----------|--------|",
    ]
    for r in exported:
        lines.append(
            f"| {r.get('date', '')} "
            f"| {r.get('channel', '')} "
            f"| {r.get('title', '')[:40]} "
            f"| {r.get('video_id', '')} "
            f"| {wiki_link(r.get('filename', ''))} |"
        )
    filepath.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return filepath


def _export_log(vault_path: Path, created: int, skipped: int, updated: int = 0) -> Path:
    """Append to 99_System/Export Log.md."""
    filepath = vault_path / "99_System" / "Export Log.md"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    entry = [
        f"## {now}",
        "",
        f"- Exported reports: {created}",
        f"- Skipped existing: {skipped}",
    ]
    if updated:
        entry.append(f"- Updated channel cards: {updated}")
    entry.append(f"- Vault path: {vault_path}")
    entry.append("")

    if filepath.exists():
        existing = read_text_safe(filepath)
        content = existing.rstrip() + "\n\n" + "\n".join(entry) + "\n"
    else:
        content = "# Export Log\n\n" + "\n".join(entry) + "\n"

    filepath.write_text(content, encoding="utf-8")
    return filepath


# ═════════════════════════════════════════════════════════════════════════════
# Main export orchestrator
# ═════════════════════════════════════════════════════════════════════════════

def export_to_vault(
    vault_path: Path,
    source_type: str | None = None,
    prompt_version: str | None = None,
    report_id: int | None = None,
    limit: int | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
    channel_filter: str | None = None,
    only_with_channel: bool = False,
) -> dict:
    """Orchestrate full vault export.

    Args:
        channel_filter: 只导出 channel_name 匹配的报告（大小写不敏感，部分匹配）。
        only_with_channel: 跳过无法解析出 channel_name 的报告。

    Returns:
        {"created": int, "skipped": int, "channel_cards": int, "exported": list[dict]}
    """
    init_db()
    session = get_session()
    try:
        # Query reports
        q = session.query(Report, Episode).join(Episode, Report.episode_id == Episode.id)

        # Filter: only youtube for v1
        if source_type and source_type == "youtube":
            q = q.filter(
                (Episode.video_id != "") | (Episode.source_url.like("%youtube%"))
            )
            # "local" filter not needed for v1

        if prompt_version:
            q = q.filter(Report.prompt_version == prompt_version)

        q = q.order_by(Report.analysis_timestamp.desc())

        if report_id:
            q = q.filter(Report.id == report_id)

        if limit:
            q = q.limit(limit)

        rows = q.all()
    finally:
        session.close()

    if dry_run:
        # Load metadata for backfill in preview
        from podcast_research.db.models import Channel, ChannelVideo
        init_db()
        s_dry = get_session()
        try:
            all_ch = s_dry.query(Channel).all()
            all_cv = s_dry.query(ChannelVideo).all()
            ch_by_id = {ch.id: ch for ch in all_ch}
            # Build video_id → metadata map
            cv_ch_map_dry = {}
            for cv in all_cv:
                c = ch_by_id.get(cv.channel_id)
                if c:
                    try:
                        tags = json.loads(c.tags) if c.tags and c.tags != "[]" else []
                    except (json.JSONDecodeError, TypeError):
                        tags = []
                    cv_ch_map_dry[cv.video_id] = {
                        "channel_name": c.name,
                        "channel_url": c.url,
                        "channel_tags": tags,
                        "video_title": cv.title,
                        "video_url": cv.url or f"https://www.youtube.com/watch?v={cv.video_id}",
                        "published_at": cv.published_at,
                    }
        finally:
            s_dry.close()

        preview = []
        for r, e in rows:
            extraction = _load_extraction(r)
            source_info = extraction.get("source_info", {}) or {}
            ch_name = source_info.get("channel_name", "")
            vid_title = source_info.get("title", "") or e.title
            vid = e.video_id or "unknown"

            # Backfill
            if not ch_name and vid in cv_ch_map_dry:
                ch_name = cv_ch_map_dry[vid].get("channel_name", "")
            if not vid_title and vid in cv_ch_map_dry:
                vid_title = cv_ch_map_dry[vid].get("video_title", "")

            # Determine action/reason
            if only_with_channel and not ch_name:
                action, reason = "skip", "missing_channel"
            elif channel_filter:
                if ch_name and channel_filter.lower() in ch_name.lower():
                    action, reason = "export", "new"
                else:
                    action, reason = "skip", "filtered_by_channel"
            else:
                action, reason = "export", "new"

            preview.append({
                "report_id": r.id,
                "date": r.analysis_timestamp.strftime("%Y-%m-%d") if r.analysis_timestamp else "",
                "channel": ch_name,
                "title": vid_title,
                "video_id": vid,
                "filename": "",
                "prompt_version": extraction.get("prompt_version", r.prompt_version),
                "action": action,
                "reason": reason,
            })

        return {
            "created": 0, "skipped": 0, "channel_cards": 0,
            "exported": preview,
            "dry_run": True,
        }

    _ensure_vault_dirs(vault_path)

    created = 0
    skipped = 0
    channel_cards = 0
    exported: list[dict] = []
    channel_reports: dict[str, list[dict]] = {}
    channel_meta: dict[str, dict] = {}

    # Load channel metadata from DB once
    init_db()
    session2 = get_session()
    try:
        from podcast_research.db.models import Channel, ChannelVideo
        all_channels = session2.query(Channel).all()
        ch_map = {ch.youtube_channel_id: ch for ch in all_channels}
        ch_by_id = {ch.id: ch for ch in all_channels}
        # Build video_id → metadata map for backfill
        all_cv = session2.query(ChannelVideo).all()
        cv_ch_map = {}
        for cv in all_cv:
            c = ch_by_id.get(cv.channel_id)
            if c:
                try:
                    cv_tags = json.loads(c.tags) if c.tags and c.tags != "[]" else []
                except (json.JSONDecodeError, TypeError):
                    cv_tags = []
                cv_ch_map[cv.video_id] = {
                    "channel_name": c.name,
                    "channel_url": c.url,
                    "channel_tags": cv_tags,
                    "channel_priority": c.priority,
                    "video_title": cv.title,
                    "video_url": cv.url or f"https://www.youtube.com/watch?v={cv.video_id}",
                    "published_at": cv.published_at,
                }
    finally:
        session2.close()

    for report, episode in rows:
        # Get channel metadata
        extraction = _load_extraction(report)
        source_info = extraction.get("source_info", {}) or {}
        channel_name = source_info.get("channel_name", "")
        channel_url = source_info.get("channel_url", "")
        channel_tags = source_info.get("channel_tags", [])
        video_title = source_info.get("title", "") or episode.title
        published_at = source_info.get("published_at", "") or ""
        vid = episode.video_id or "unknown"

        # --- Metadata backfill from channel_videos + channels ---
        if vid in cv_ch_map:
            cv_meta = cv_ch_map[vid]
            if not channel_name and cv_meta.get("channel_name"):
                channel_name = cv_meta["channel_name"]
            if not channel_url and cv_meta.get("channel_url"):
                channel_url = cv_meta["channel_url"]
            if not channel_tags and cv_meta.get("channel_tags"):
                channel_tags = cv_meta["channel_tags"]
            if not video_title and cv_meta.get("video_title"):
                video_title = cv_meta["video_title"]
            if not published_at and cv_meta.get("published_at"):
                published_at = cv_meta["published_at"]

        # Also try channel lookup from DB (by name/URL match)
        for _ch_id, ch in ch_map.items():
            if ch.name == channel_name or ch.url == channel_url:
                if not channel_tags:
                    with contextlib.suppress(json.JSONDecodeError, TypeError):
                        channel_tags = json.loads(ch.tags) if ch.tags else []
                if not channel_url:
                    channel_url = ch.url
                break

        # --- Filtering ---
        action = "export"
        reason = "new"

        if only_with_channel and not channel_name:
            action = "skip"
            reason = "missing_channel"
        elif channel_filter:
            if channel_name and channel_filter.lower() in channel_name.lower():
                pass  # match, proceed with export
            else:
                action = "skip"
                reason = "filtered_by_channel"

        if action == "skip":
            skipped += 1
            exported.append({
                "report_id": report.id,
                "date": report.analysis_timestamp.strftime("%Y-%m-%d") if report.analysis_timestamp else "",
                "channel": channel_name,
                "title": video_title,
                "video_id": episode.video_id,
                "filename": "",
                "action": action,
                "reason": reason,
            })
            continue

        views_data = []
        init_db()
        session3 = get_session()
        try:
            q_views = session3.query(InvestmentViewRecord).filter_by(report_id=report.id)
            for v in q_views.all():
                tags_raw = v.topic_tags or "[]"
                try:
                    tags = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
                except (json.JSONDecodeError, TypeError):
                    tags = []
                views_data.append({
                    "target_name": v.target_name,
                    "view_direction": v.view_direction,
                    "ai_value_chain_layer": v.ai_value_chain_layer,
                    "evidence_type": v.evidence_type,
                    "evidence_strength": v.evidence_strength,
                    "time_horizon": v.time_horizon,
                    "timestamp_start": v.timestamp_start,
                    "topic_tags": tags,
                })
        finally:
            session3.close()

        # Generate filename (for index)
        date_str = published_at[:10] if published_at else report.analysis_timestamp.strftime("%Y-%m-%d") if report.analysis_timestamp else datetime.now().strftime("%Y-%m-%d")
        ch_safe = sanitize_filename(channel_name or "UnknownChannel")
        filename = f"{date_str}_{ch_safe}_{vid}"

        result = export_report(
            vault_path=vault_path,
            report=report,
            episode=episode,
            views_data=views_data,
            extraction=extraction,
            channel_name=channel_name,
            overwrite=overwrite,
        )

        # Determine action for tracking
        if result["status"] == "created":
            created += 1
            action = "export"
            reason = "new"
        else:
            skipped += 1
            action = "skip" if not overwrite else "overwrite"
            reason = "exists"

        export_entry = {
            "report_id": report.id,
            "date": date_str,
            "channel": channel_name,
            "title": video_title,
            "video_id": episode.video_id,
            "filename": filename,
            "action": action,
            "reason": reason,
        }
        exported.append(export_entry)

        # Track per-channel reports
        ch_key = channel_name or "UnknownChannel"
        channel_reports.setdefault(ch_key, []).append(export_entry)
        if channel_name and channel_name not in channel_meta:
            channel_meta[channel_name] = {
                "url": channel_url,
                "tags": channel_tags,
                "priority": "core" if channel_tags else "secondary",
            }

    # Export channel cards
    for ch_name, reports in channel_reports.items():
        meta = channel_meta.get(ch_name, {})
        ch_result = export_channel_card(
            vault_path=vault_path,
            channel_name=ch_name,
            channel_url=meta.get("url", ""),
            channel_tags=meta.get("tags", []),
            channel_priority=meta.get("priority", "core"),
            recent_reports=reports,
            overwrite=overwrite,
        )
        if ch_result["status"] in ("created", "updated"):
            channel_cards += 1

    # Generate system files
    _export_report_index(vault_path, exported)
    _export_log(vault_path, created, skipped, updated=channel_cards)

    return {
        "created": created,
        "skipped": skipped,
        "channel_cards": channel_cards,
        "exported": exported,
    }


# ═════════════════════════════════════════════════════════════════════════════
# P2-C.1: UnknownChannel cleanup
# ═════════════════════════════════════════════════════════════════════════════

def _parse_yaml_frontmatter(content: str) -> dict:
    """Parse simple YAML frontmatter from markdown content.

    Returns dict of string key-value pairs. Only handles flat key: value syntax.
    Multi-line lists and nested structures are skipped.
    """
    if not content.startswith("---"):
        return {}
    end_idx = content.find("---", 3)
    if end_idx == -1:
        return {}

    fm_text = content[3:end_idx].strip()
    result = {}
    for line in fm_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        colon_idx = line.find(":")
        if colon_idx <= 0:
            continue
        key = line[:colon_idx].strip()
        val = line[colon_idx + 1:].strip()
        # Strip quotes
        if val.startswith('"') and val.endswith('"') or val.startswith("'") and val.endswith("'"):
            val = val[1:-1]
        if key:
            result[key] = val
    return result


def find_unknown_channel_files(vault_path: Path) -> list[Path]:
    """Find all UnknownChannel files in 01_Reports and 05_Channels."""
    files = []

    reports_dir = vault_path / "01_Reports"
    if reports_dir.exists():
        for f in sorted(reports_dir.glob("*.md")):
            if "UnknownChannel" in f.name:
                files.append(f)

    channels_dir = vault_path / "05_Channels"
    if channels_dir.exists():
        card = channels_dir / "UnknownChannel.md"
        if card.exists():
            files.append(card)

    return files


def _analyze_unknown_file(filepath: Path, cv_ch_map: dict) -> dict:
    """Analyze an UnknownChannel file, determine if it can be resolved.

    Returns dict with file, video_id, channel_name, suggested_filename,
    action, reason.
    """
    content = read_text_safe(filepath)
    fm = _parse_yaml_frontmatter(content)
    video_id = fm.get("video_id", "")

    is_channel_card = filepath.parent.name == "05_Channels"

    if not video_id:
        return {
            "file": filepath,
            "video_id": "",
            "channel_name": "",
            "suggested_filename": "",
            "action": "manual_review",
            "reason": "missing_video_id" if not is_channel_card else "channel_card",
        }

    if video_id in cv_ch_map:
        meta = cv_ch_map[video_id]
        ch_name = meta.get("channel_name", "")
        date = meta.get("published_at", "")
        if not date:
            # Try to extract date from filename: YYYY-MM-DD_UnknownChannel_vid.md
            parts = filepath.stem.split("_")
            if len(parts) >= 1 and len(parts[0]) == 10:
                date = parts[0]
        ch_safe = sanitize_filename(ch_name) if ch_name else "UnknownChannel"
        suggested = f"{date}_{ch_safe}_{video_id}" if date else f"{ch_safe}_{video_id}"
        return {
            "file": filepath,
            "video_id": video_id,
            "channel_name": ch_name,
            "suggested_filename": suggested,
            "action": "rename_or_reexport",
            "reason": "backfilled",
        }

    return {
        "file": filepath,
        "video_id": video_id,
        "channel_name": "",
        "suggested_filename": "",
        "action": "manual_review",
        "reason": "no_channel_metadata",
    }


def _re_export_report(
    vault_path: Path,
    report: Report,
    episode: Episode,
    extraction: dict,
    vid: str,
    ch_map: dict,
    cv_ch_map: dict,
    overwrite: bool = False,
) -> dict:
    """Re-export a single report with backfilled metadata.

    Returns export_report() result dict.
    """
    source_info = extraction.get("source_info", {}) or {}
    channel_name = source_info.get("channel_name", "")
    channel_url = source_info.get("channel_url", "")
    channel_tags = source_info.get("channel_tags", [])

    # Backfill from channel_videos
    if vid in cv_ch_map:
        cv_meta = cv_ch_map[vid]
        if not channel_name and cv_meta.get("channel_name"):
            channel_name = cv_meta["channel_name"]
        if not channel_url and cv_meta.get("channel_url"):
            channel_url = cv_meta["channel_url"]
        if not channel_tags and cv_meta.get("channel_tags"):
            channel_tags = cv_meta["channel_tags"]

    # Backfill from channels table (by name match)
    for ch in ch_map.values():
        if ch.name == channel_name or ch.url == channel_url:
            if not channel_tags:
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    channel_tags = json.loads(ch.tags) if ch.tags else []
            if not channel_url:
                channel_url = ch.url
            break

    # Load investment views
    views_data = []
    init_db()
    session = get_session()
    try:
        q_views = session.query(InvestmentViewRecord).filter_by(report_id=report.id)
        for v in q_views.all():
            tags_raw = v.topic_tags or "[]"
            try:
                tags = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
            except (json.JSONDecodeError, TypeError):
                tags = []
            views_data.append({
                "target_name": v.target_name,
                "view_direction": v.view_direction,
                "ai_value_chain_layer": v.ai_value_chain_layer,
                "evidence_type": v.evidence_type,
                "evidence_strength": v.evidence_strength,
                "time_horizon": v.time_horizon,
                "timestamp_start": v.timestamp_start,
                "topic_tags": tags,
            })
    finally:
        session.close()

    return export_report(
        vault_path=vault_path,
        report=report,
        episode=episode,
        views_data=views_data,
        extraction=extraction,
        channel_name=channel_name,
        overwrite=overwrite,
    )


def cleanup_unknown_channel_files(
    vault_path: Path,
    dry_run: bool = False,
    apply: bool = False,
    overwrite: bool = False,
) -> dict:
    """Detect and optionally cleanup UnknownChannel files.

    dry_run: 只检测分析，返回结果列表，不修改文件。
    apply:   对可识别的文件重新导出 + 将旧文件移到 backup。
             不直接删除文件。

    Returns:
        {"results": list[dict], "renamed": int, "moved": int, "skipped": int}
    """
    # 1. Find all UnknownChannel files
    unknown_files = find_unknown_channel_files(vault_path)

    # 2. Build metadata maps from DB
    init_db()
    session = get_session()
    try:
        from podcast_research.db.models import Channel, ChannelVideo
        all_ch = session.query(Channel).all()
        ch_map = {ch.youtube_channel_id: ch for ch in all_ch}
        ch_by_id = {ch.id: ch for ch in all_ch}

        all_cv = session.query(ChannelVideo).all()
        cv_ch_map = {}
        for cv in all_cv:
            c = ch_by_id.get(cv.channel_id)
            if c:
                try:
                    tags = json.loads(c.tags) if c.tags and c.tags != "[]" else []
                except (json.JSONDecodeError, TypeError):
                    tags = []
                cv_ch_map[cv.video_id] = {
                    "channel_name": c.name,
                    "channel_url": c.url,
                    "channel_tags": tags,
                    "channel_priority": c.priority,
                    "video_title": cv.title,
                    "video_url": cv.url or f"https://www.youtube.com/watch?v={cv.video_id}",
                    "published_at": cv.published_at,
                }
    finally:
        session.close()

    # 3. Analyze each file
    results = []
    for filepath in unknown_files:
        analysis = _analyze_unknown_file(filepath, cv_ch_map)
        results.append(analysis)

    if dry_run:
        return {"results": results, "renamed": 0, "moved": 0, "skipped": 0}

    if not apply:
        return {"results": results, "renamed": 0, "moved": 0, "skipped": 0}

    # 4. Apply: re-export + move old files to backup
    renamed = 0
    moved = 0
    skipped = 0
    backup_dir = vault_path / "99_System" / "UnknownChannel_Backup"

    for analysis in results:
        filepath: Path = analysis["file"]
        video_id = analysis["video_id"]
        action = analysis["action"]

        # Handle UnknownChannel.md channel card
        if filepath.parent.name == "05_Channels":
            if apply:
                backup_dir.mkdir(parents=True, exist_ok=True)
                dest = backup_dir / filepath.name
                shutil.move(str(filepath), str(dest))
                moved += 1
            continue

        if action != "rename_or_reexport" or not video_id:
            skipped += 1
            continue

        # Find report in DB by video_id
        init_db()
        session = get_session()
        try:
            row = session.query(Report, Episode).join(
                Episode, Report.episode_id == Episode.id
            ).filter(Episode.video_id == video_id).first()
        finally:
            session.close()

        if not row:
            skipped += 1
            continue

        report, episode = row
        extraction = _load_extraction(report)

        # Re-export with correct metadata
        result = _re_export_report(
            vault_path, report, episode, extraction,
            video_id, ch_map, cv_ch_map, overwrite=overwrite,
        )

        if result["status"] == "created":
            renamed += 1
        else:
            # Target file already exists (skip mode) — still move old file
            renamed += 1  # count as resolved even if target existed

        # Move old UnknownChannel file to backup
        backup_dir.mkdir(parents=True, exist_ok=True)
        dest = backup_dir / filepath.name
        if dest.exists():
            # Avoid collision in backup
            dest = backup_dir / f"{filepath.stem}_bak{filepath.suffix}"
        shutil.move(str(filepath), str(dest))
        moved += 1

    # Log the cleanup
    if renamed or moved:
        _export_log(vault_path, renamed, 0)

    return {"results": results, "renamed": renamed, "moved": moved, "skipped": skipped}


# ═════════════════════════════════════════════════════════════════════════════
# P2-C.2: Channel Card Reconciliation
# ═════════════════════════════════════════════════════════════════════════════

def _scan_report_frontmatters(vault_path: Path) -> list[dict]:
    """Scan all report files in 01_Reports/ and parse their frontmatter.

    Returns list of dicts with: file, channel, video_id, video_url,
    published_at, title (from H1 heading).
    """
    reports_dir = vault_path / "01_Reports"
    if not reports_dir.exists():
        return []

    results = []
    for filepath in sorted(reports_dir.glob("*.md")):
        content = read_text_safe(filepath)
        fm = _parse_yaml_frontmatter(content)

        # Extract title from first H1 heading
        title = ""
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("## "):
                title = stripped[2:].strip()
                break

        results.append({
            "file": filepath,
            "channel": fm.get("channel", "").strip(),
            "video_id": fm.get("video_id", "").strip(),
            "video_url": fm.get("video_url", "").strip(),
            "published_at": fm.get("published_at", "").strip(),
            "title": title,
            "filename": filepath.stem,
        })

    return results


def _group_reports_by_channel(reports: list[dict]) -> dict[str, list[dict]]:
    """Group reports by channel name. Skip empty/unknown channels."""
    groups = {}
    skip_channels = {"", "unknownchannel", "unknown", "none"}

    for r in reports:
        ch = r.get("channel", "").strip()
        if ch.lower() in skip_channels:
            continue
        groups.setdefault(ch, []).append(r)

    return groups


def sync_channel_cards(
    vault_path: Path,
    dry_run: bool = False,
    channel_filter: str | None = None,
    overwrite: bool = False,
) -> dict:
    """Scan 01_Reports/ and sync 05_Channels/ channel cards.

    For each channel found in reports:
    - If card doesn't exist → create it
    - If card exists → append new report links to Recent Reports section
    - If --overwrite → rewrite the entire card

    Returns:
        {"results": list[dict], "created": int, "updated": int, "skipped": int}
    """
    # 1. Scan report frontmatters
    all_reports = _scan_report_frontmatters(vault_path)

    # 2. Group by channel
    groups = _group_reports_by_channel(all_reports)

    # 3. Apply channel filter
    if channel_filter:
        groups = {
            ch: reps for ch, reps in groups.items()
            if channel_filter.lower() in ch.lower()
        }

    # 4. Load DB channel metadata for URL/tags enrichment
    ch_db_meta = {}
    try:
        init_db()
        session = get_session()
        try:
            from podcast_research.db.models import Channel
            for ch in session.query(Channel).all():
                ch_db_meta[ch.name.lower()] = {
                    "url": ch.url,
                    "tags": json.loads(ch.tags) if ch.tags and ch.tags != "[]" else [],
                    "priority": ch.priority,
                }
        finally:
            session.close()
    except Exception:
        pass  # DB might not be initialized in test contexts

    channels_dir = vault_path / "05_Channels"
    channels_dir.mkdir(parents=True, exist_ok=True)

    results = []
    created = 0
    updated = 0
    skipped = 0

    for ch_name, ch_reports in sorted(groups.items()):
        ch_safe = sanitize_filename(ch_name) if ch_name else "UnknownChannel"
        card_path = channels_dir / f"{ch_safe}.md"

        # Determine action
        card_exists = card_path.exists()
        if not card_exists:
            action, reason = "create", "missing_card"
        elif overwrite:
            action, reason = "create", "overwrite"
        else:
            action, reason = "update", "append_recent_reports"

        # Build report links for Recent Reports
        report_links = []
        for r in ch_reports:
            link = f"[[{r['filename']}]]"
            desc = r["title"] or f"Video ID: {r['video_id']}"
            report_links.append(f"- {link} — {desc}")

        # Enrich from DB if available
        db_meta = ch_db_meta.get(ch_name.lower(), {})
        ch_url = db_meta.get("url", "")
        ch_tags = db_meta.get("tags", [])
        ch_priority = db_meta.get("priority", "core")

        # Also try to get URL from first report's video_url
        if not ch_url:
            for r in ch_reports:
                vid_url = r.get("video_url", "")
                if vid_url and "youtube.com" in vid_url:
                    # Extract channel URL from video URL (best effort)
                    ch_url = ""  # Can't reliably infer channel URL from video URL
                    break

        if dry_run:
            # Check if card already has all links
            if card_exists and not overwrite:
                existing_content = read_text_safe(card_path)
                new_links = [
                    f"[[{r['filename']}]]" for r in ch_reports
                    if f"[[{r['filename']}]]" not in existing_content
                ]
                if not new_links:
                    action, reason = "skip", "already_synced"

            results.append({
                "channel": ch_name,
                "reports_count": len(ch_reports),
                "card_exists": card_exists,
                "action": action,
                "reason": reason,
                "report_links": report_links,
            })
            if action == "create":
                created += 1
            elif action == "update":
                updated += 1
            else:
                skipped += 1
            continue

        # Execute
        if action == "create":
            # Create or overwrite channel card
            fm = OrderedDict([
                ("type", "channel"),
                ("channel", ch_name),
                ("source_type", "youtube"),
                ("url", ch_url),
                ("tags", ch_tags),
                ("priority", ch_priority),
                ("updated_at", datetime.now().strftime("%Y-%m-%d %H:%M")),
            ])
            body_lines = [
                f"# {ch_name}",
                "",
                "## Positioning",
                "",
                "## Recent Reports",
                "",
            ]
            body_lines.extend(report_links)
            body_lines.extend([
                "",
                "## Recurring Topics",
                "",
                "## Key People",
                "",
                "## Notes",
                "",
            ])
            content = build_frontmatter(fm) + "\n\n" + "\n".join(body_lines) + "\n"
            card_path.write_text(content, encoding="utf-8")
            created += 1

        elif action == "update":
            # Append only new report links
            existing_content = read_text_safe(card_path)
            new_links = []
            for link_line in report_links:
                # Extract the [[filename]] part
                match = re.search(r"\[\[([^\]]+)\]\]", link_line)
                if match and f"[[{match.group(1)}]]" not in existing_content:
                    new_links.append(link_line)

            if new_links:
                block = "\n".join(new_links) + "\n"
                if "## Recent Reports" in existing_content:
                    # Append after "## Recent Reports\n"
                    existing_content = existing_content.replace(
                        "## Recent Reports\n",
                        f"## Recent Reports\n{block}",
                    )
                elif "## Notes" in existing_content:
                    existing_content = existing_content.replace(
                        "## Notes",
                        f"## Recent Reports\n{block}\n## Notes",
                    )
                else:
                    existing_content = existing_content.rstrip() + f"\n\n## Recent Reports\n{block}\n"

                # Update timestamp
                existing_content = re.sub(
                    r"updated_at:.*",
                    f"updated_at: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    existing_content,
                )
                card_path.write_text(existing_content, encoding="utf-8")
                updated += 1
            else:
                action, reason = "skip", "already_synced"
                skipped += 1

        results.append({
            "channel": ch_name,
            "reports_count": len(ch_reports),
            "card_exists": card_exists,
            "action": action,
            "reason": reason,
            "report_links": report_links,
        })

    return {"results": results, "created": created, "updated": updated, "skipped": skipped}


# ═════════════════════════════════════════════════════════════════════════════
# P2-D: Topic / Company Card Generation
# ═════════════════════════════════════════════════════════════════════════════

# Topic name normalization map
_TOPIC_NAME_MAP = {
    "ai-infra": "AI Infra",
    "ai-capex": "AI Capex",
    "ai-agents": "AI Agents",
    "agents": "AI Agents",
    "inference": "Inference",
    "enterprise-ai": "Enterprise AI",
    "developer-tools": "Developer Tools",
    "semiconductor": "Semiconductor",
    "cloud": "Cloud",
    "compute": "Compute",
    "enterprise": "Enterprise",
    "capital_market": "Capital Market",
    "capital-market": "Capital Market",
    "financial_metric": "Financial Metric",
    "growth_metric": "Growth Metric",
    "market_structure": "Market Structure",
    "workload-patterns": "Workload Patterns",
    "rl": "RL",
    "evals": "Evals",
    "mcp": "MCP",
    "cli": "CLI",
    "agent-tools": "Agent Tools",
    "macos": "macOS",
    "licensing": "Licensing",
    "computer-use": "Computer Use",
    "agentic-infrastructure": "Agentic Infrastructure",
    "ai-gateway": "AI Gateway",
    "competition": "Competition",
    "corporate-structure": "Corporate Structure",
    "customer-service": "Customer Service",
    "etf": "ETF",
    "expense-ratio": "Expense Ratio",
    "client-relationship": "Client Relationship",
}

# Company name normalization map (alias → canonical)
_COMPANY_NAME_MAP = {
    "nvidia": "NVIDIA",
    "alphabet": "Alphabet",
    "google": "Alphabet",
    "google cloud": "Google Cloud",
    "microsoft": "Microsoft",
    "azure": "Microsoft",
    "meta": "Meta",
    "meta platforms": "Meta",
    "taiwan semiconductor": "TSMC",
    "tsmc": "TSMC",
    "openai": "OpenAI",
    "open ai": "OpenAI",
    "anthropic": "Anthropic",
    "coreweave": "CoreWeave",
    "perplexity": "Perplexity",
    "mistral": "Mistral",
    "blackrock": "BlackRock",
    "vanguard": "Vanguard",
    "vercel": "Vercel",
    "stripe": "Stripe",
    "apple": "Apple",
    "amazon": "Amazon",
    "costco": "Costco",
    "jp morgan": "JPMorgan Chase",
    "jpmorgan chase": "JPMorgan Chase",
    "jpmorgan": "JPMorgan Chase",
    "fidelity": "Fidelity Investments",
    "fidelity investments": "Fidelity Investments",
    "state street": "State Street",
    "wellington management": "Wellington Management",
    "capital group": "Capital Group",
    "blackstone": "Blackstone",
    "renaissance technologies": "Renaissance Technologies",
    "morningstar": "Morningstar",
    "s&p global": "S&P Global",
    "polymarket": "Polymarket",
    "poke": "Poke",
    "primerica": "Primerica",
    "citigroup": "Citigroup",
    "american can company": "American Can Company",
    "massachusetts investors trust": "Massachusetts Investors Trust",
}


def _normalize_topic_name(raw: str) -> str:
    """Normalize a topic tag to display name."""
    key = raw.lower().strip()
    if key in _TOPIC_NAME_MAP:
        return _TOPIC_NAME_MAP[key]
    # Default: title case with hyphens replaced by spaces
    return raw.replace("-", " ").replace("_", " ").title()


def _normalize_company_name(raw: str) -> str:
    """Normalize a company name using alias map."""
    key = raw.lower().strip()
    if key in _COMPANY_NAME_MAP:
        return _COMPANY_NAME_MAP[key]
    # Default: return as-is
    return raw


def _extract_topics_from_report_md(content: str) -> list[str]:
    """Extract topic tags from report markdown.

    Sources:
    1. Tech/Industry Insights section: `#tag` patterns
    2. Core Investment Views table: AI value chain column (3rd data column)
    """
    topics = set()

    # 1. Extract hashtags from Tech/Industry Insights
    # Find all backtick-enclosed sections, then extract #tag within them
    for backtick_match in re.finditer(r"`([^`]+)`", content):
        section = backtick_match.group(1)
        for tag_match in re.finditer(r"#([a-zA-Z0-9_-]+)", section):
            topics.add(tag_match.group(1))

    # 2. Extract AI value chain from Core Investment Views table
    # Table rows: | target | direction | ai_value_chain | ...
    lines = content.split("\n")
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("| ") and "标的" in stripped:
            in_table = True
            continue
        if in_table and stripped.startswith("|---"):
            continue
        if in_table and stripped.startswith("|"):
            cols = [c.strip() for c in stripped.split("|")]
            # cols[0] is empty (before first |), cols[1]=target, cols[2]=direction, cols[3]=ai_value_chain
            if len(cols) >= 4 and cols[3] and cols[3] != "-" and cols[3] != "AI价值链":
                topics.add(cols[3])
        elif in_table and not stripped.startswith("|"):
            in_table = False

    return sorted(topics)


def _extract_companies_from_report_md(content: str) -> list[str]:
    """Extract company names from report markdown.

    Sources:
    1. Entities section: [[Company]] wiki links
    2. Core Investment Views table: target names (1st data column)
    """
    companies = set()

    # 1. Extract from Entities section
    lines = content.split("\n")
    in_entities = False
    for line in lines:
        stripped = line.strip()
        if stripped == "## Entities":
            in_entities = True
            continue
        if in_entities and stripped.startswith("## "):
            break
        if in_entities:
            # Match [[Company]] patterns (handle nested [[[[Company]]]])
            for match in re.finditer(r"\[\[([^\[\]]+)\]\]", stripped):
                name = match.group(1).strip()
                # Filter out obvious non-companies (topics, etc.)
                if name and not name.startswith("#") and len(name) > 1:
                    companies.add(name)

    # 2. Extract target names from Core Investment Views table
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("| ") and "标的" in stripped:
            in_table = True
            continue
        if in_table and stripped.startswith("|---"):
            continue
        if in_table and stripped.startswith("|"):
            cols = [c.strip() for c in stripped.split("|")]
            # cols[0] is empty, cols[1] = target name
            if len(cols) >= 2 and cols[1] and cols[1] != "标的":
                companies.add(cols[1])
        elif in_table and not stripped.startswith("|"):
            in_table = False

    # Normalize company names
    normalized = set()
    for c in companies:
        normalized.add(_normalize_company_name(c))

    return sorted(normalized)


def _write_topic_card(path: Path, topic_name: str, source_reports: list[dict]) -> None:
    """Create a new topic card."""
    tag_slug = topic_name.lower().replace(" ", "-")
    fm = OrderedDict([
        ("type", "topic"),
        ("topic", topic_name),
        ("aliases", []),
        ("tags", [f"topic/{tag_slug}"]),
        ("updated_at", datetime.now().strftime("%Y-%m-%d %H:%M")),
    ])

    body_lines = [
        f"# {topic_name}",
        "",
        "## Current Understanding",
        "",
        "> 待后续 LLM-WIKI 维护。当前卡片由报告索引自动生成。",
        "",
        "## Source Reports",
        "",
    ]
    for r in source_reports:
        link = f"[[{r['filename']}]]"
        desc = r["title"] or r["channel"] or r["video_id"]
        body_lines.append(f"- {link} — {desc}")

    body_lines.extend([
        "",
        "## Related Companies",
        "",
        "## Related Topics",
        "",
        "## Open Questions",
        "",
        "## Timeline",
        "",
    ])

    content = build_frontmatter(fm) + "\n\n" + "\n".join(body_lines) + "\n"
    path.write_text(content, encoding="utf-8")


def _write_company_card(path: Path, company_name: str, source_reports: list[dict]) -> None:
    """Create a new company card."""
    tag_slug = company_name.lower().replace(" ", "-")
    fm = OrderedDict([
        ("type", "company"),
        ("company", company_name),
        ("aliases", []),
        ("ticker", ""),
        ("sector", ""),
        ("tags", [f"company/{tag_slug}"]),
        ("updated_at", datetime.now().strftime("%Y-%m-%d %H:%M")),
    ])

    body_lines = [
        f"# {company_name}",
        "",
        "## Current Thesis",
        "",
        "> 待后续 LLM-WIKI 维护。当前卡片由报告索引自动生成。",
        "",
        "## Related Investment Views",
        "",
        "## Risks",
        "",
        "## Related Topics",
        "",
        "## Source Reports",
        "",
    ]
    for r in source_reports:
        link = f"[[{r['filename']}]]"
        desc = r["title"] or r["channel"] or r["video_id"]
        body_lines.append(f"- {link} — {desc}")

    body_lines.extend([
        "",
        "## Timeline",
        "",
    ])

    content = build_frontmatter(fm) + "\n\n" + "\n".join(body_lines) + "\n"
    path.write_text(content, encoding="utf-8")


def _append_source_reports(path: Path, new_links: list[str]) -> bool:
    """Append new source report links to existing card.

    Returns True if any new links were added.
    """
    existing_content = read_text_safe(path)

    # Filter out already-existing links
    to_add = []
    for link_line in new_links:
        match = re.search(r"\[\[([^\]]+)\]\]", link_line)
        if match and f"[[{match.group(1)}]]" not in existing_content:
            to_add.append(link_line)

    if not to_add:
        return False

    block = "\n".join(to_add) + "\n"

    if "## Source Reports" in existing_content:
        existing_content = existing_content.replace(
            "## Source Reports\n",
            f"## Source Reports\n{block}",
        )
    elif "## Timeline" in existing_content:
        existing_content = existing_content.replace(
            "## Timeline",
            f"## Source Reports\n{block}\n## Timeline",
        )
    else:
        existing_content = existing_content.rstrip() + f"\n\n## Source Reports\n{block}\n"

    # Update timestamp
    existing_content = re.sub(
        r"updated_at:.*",
        f"updated_at: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        existing_content,
    )
    path.write_text(existing_content, encoding="utf-8")
    return True


def _generate_topic_index(vault_path: Path, topic_data: dict[str, list[dict]]) -> None:
    """Generate 99_System/Topic Index.md."""
    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    index_path = system_dir / "Topic Index.md"

    lines = [
        "# Topic Index",
        "",
        f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "| Topic | Reports | Card |",
        "|---|---:|---|",
    ]

    for topic_name in sorted(topic_data.keys()):
        reports = topic_data[topic_name]
        count = len(reports)
        card_link = f"[[{topic_name}]]"
        lines.append(f"| {topic_name} | {count} | {card_link} |")

    lines.append("")
    index_path.write_text("\n".join(lines), encoding="utf-8")


def _generate_company_index(vault_path: Path, company_data: dict[str, list[dict]]) -> None:
    """Generate 99_System/Company Index.md."""
    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    index_path = system_dir / "Company Index.md"

    lines = [
        "# Company Index",
        "",
        f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "| Company | Reports | Card |",
        "|---|---:|---|",
    ]

    for company_name in sorted(company_data.keys()):
        reports = company_data[company_name]
        count = len(reports)
        card_link = f"[[{company_name}]]"
        lines.append(f"| {company_name} | {count} | {card_link} |")

    lines.append("")
    index_path.write_text("\n".join(lines), encoding="utf-8")


def _generate_card_log(
    vault_path: Path,
    topics_created: int,
    topics_updated: int,
    companies_created: int,
    companies_updated: int,
    skipped: int,
) -> None:
    """Append to 99_System/Card Generation Log.md."""
    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    log_path = system_dir / "Card Generation Log.md"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = [
        f"## {now}",
        "",
        f"- Topics created: {topics_created}",
        f"- Topics updated: {topics_updated}",
        f"- Companies created: {companies_created}",
        f"- Companies updated: {companies_updated}",
        f"- Skipped: {skipped}",
        f"- Vault path: {vault_path}",
        "",
    ]

    if log_path.exists():
        existing = read_text_safe(log_path)
        content = existing.rstrip() + "\n\n" + "\n".join(entry) + "\n"
    else:
        content = "# Card Generation Log\n\n" + "\n".join(entry) + "\n"

    log_path.write_text(content, encoding="utf-8")


def generate_cards(
    vault_path: Path,
    dry_run: bool = False,
    topics_only: bool = False,
    companies_only: bool = False,
    channel_filter: str | None = None,
    overwrite: bool = False,
    limit: int | None = None,
) -> dict:
    """Generate Topic and Company cards from report notes.

    Returns:
        {
            "results": list[dict],
            "topics_created": int,
            "topics_updated": int,
            "companies_created": int,
            "companies_updated": int,
            "skipped": int,
        }
    """
    reports_dir = vault_path / "01_Reports"
    if not reports_dir.exists():
        return {
            "results": [],
            "topics_created": 0,
            "topics_updated": 0,
            "companies_created": 0,
            "companies_updated": 0,
            "skipped": 0,
        }

    # Determine what to generate
    do_topics = not companies_only
    do_companies = not topics_only

    # 1. Scan reports and extract topics/companies
    topic_map: dict[str, list[dict]] = {}  # topic_name → [report_info]
    company_map: dict[str, list[dict]] = {}  # company_name → [report_info]

    report_files = sorted(reports_dir.glob("*.md"))
    if limit:
        report_files = report_files[:limit]

    for filepath in report_files:
        content = read_text_safe(filepath)
        fm = _parse_yaml_frontmatter(content)

        channel = fm.get("channel", "").strip()
        video_id = fm.get("video_id", "").strip()

        # Apply channel filter
        if channel_filter and channel_filter.lower() not in channel.lower():
            continue

        # Extract title from H1 heading
        title = ""
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("## "):
                title = stripped[2:].strip()
                break

        report_info = {
            "filename": filepath.stem,
            "channel": channel,
            "video_id": video_id,
            "title": title,
        }

        # Extract topics
        if do_topics:
            raw_topics = _extract_topics_from_report_md(content)
            for raw_tag in raw_topics:
                topic_name = _normalize_topic_name(raw_tag)
                topic_map.setdefault(topic_name, []).append(report_info)

        # Extract companies
        if do_companies:
            raw_companies = _extract_companies_from_report_md(content)
            for company_name in raw_companies:
                company_map.setdefault(company_name, []).append(report_info)

    # 2. Build results and optionally write cards
    topics_dir = vault_path / "02_Topics"
    companies_dir = vault_path / "03_Companies"

    if not dry_run:
        if do_topics:
            topics_dir.mkdir(parents=True, exist_ok=True)
        if do_companies:
            companies_dir.mkdir(parents=True, exist_ok=True)

    results = []
    topics_created = 0
    topics_updated = 0
    companies_created = 0
    companies_updated = 0
    skipped = 0

    # Process topics
    if do_topics:
        for topic_name in sorted(topic_map.keys()):
            reports = topic_map[topic_name]
            card_path = topics_dir / f"{sanitize_filename(topic_name)}.md"
            card_exists = card_path.exists()

            # Build source report links
            source_links = []
            for r in reports:
                link = f"[[{r['filename']}]]"
                desc = r["title"] or r["channel"] or r["video_id"]
                source_links.append(f"- {link} — {desc}")

            if dry_run:
                if card_exists and not overwrite:
                    existing_content = read_text_safe(card_path)
                    new_links = [
                        f"[[{r['filename']}]]" for r in reports
                        if f"[[{r['filename']}]]" not in existing_content
                    ]
                    if not new_links:
                        action, reason = "skip", "already_synced"
                        skipped += 1
                    else:
                        action, reason = "update", "append_source_reports"
                        topics_updated += 1
                elif overwrite:
                    action, reason = "create", "overwrite"
                    topics_created += 1
                else:
                    action, reason = "create", "missing_card"
                    topics_created += 1

                results.append({
                    "type": "topic",
                    "name": topic_name,
                    "reports_count": len(reports),
                    "card_exists": card_exists,
                    "action": action,
                    "reason": reason,
                })
            else:
                if not card_exists or overwrite:
                    _write_topic_card(card_path, topic_name, reports)
                    topics_created += 1
                    action, reason = "create", "missing_card" if not card_exists else "overwrite"
                else:
                    added = _append_source_reports(card_path, source_links)
                    if added:
                        topics_updated += 1
                        action, reason = "update", "append_source_reports"
                    else:
                        skipped += 1
                        action, reason = "skip", "already_synced"

                results.append({
                    "type": "topic",
                    "name": topic_name,
                    "reports_count": len(reports),
                    "card_exists": card_exists,
                    "action": action,
                    "reason": reason,
                })

    # Process companies
    if do_companies:
        for company_name in sorted(company_map.keys()):
            reports = company_map[company_name]
            card_path = companies_dir / f"{sanitize_filename(company_name)}.md"
            card_exists = card_path.exists()

            # Build source report links
            source_links = []
            for r in reports:
                link = f"[[{r['filename']}]]"
                desc = r["title"] or r["channel"] or r["video_id"]
                source_links.append(f"- {link} — {desc}")

            if dry_run:
                if card_exists and not overwrite:
                    existing_content = read_text_safe(card_path)
                    new_links = [
                        f"[[{r['filename']}]]" for r in reports
                        if f"[[{r['filename']}]]" not in existing_content
                    ]
                    if not new_links:
                        action, reason = "skip", "already_synced"
                        skipped += 1
                    else:
                        action, reason = "update", "append_source_reports"
                        companies_updated += 1
                elif overwrite:
                    action, reason = "create", "overwrite"
                    companies_created += 1
                else:
                    action, reason = "create", "missing_card"
                    companies_created += 1

                results.append({
                    "type": "company",
                    "name": company_name,
                    "reports_count": len(reports),
                    "card_exists": card_exists,
                    "action": action,
                    "reason": reason,
                })
            else:
                if not card_exists or overwrite:
                    _write_company_card(card_path, company_name, reports)
                    companies_created += 1
                    action, reason = "create", "missing_card" if not card_exists else "overwrite"
                else:
                    added = _append_source_reports(card_path, source_links)
                    if added:
                        companies_updated += 1
                        action, reason = "update", "append_source_reports"
                    else:
                        skipped += 1
                        action, reason = "skip", "already_synced"

                results.append({
                    "type": "company",
                    "name": company_name,
                    "reports_count": len(reports),
                    "card_exists": card_exists,
                    "action": action,
                    "reason": reason,
                })

    # Generate indexes and log (only if not dry_run)
    if not dry_run:
        if do_topics and topic_map:
            _generate_topic_index(vault_path, topic_map)
        if do_companies and company_map:
            _generate_company_index(vault_path, company_map)
        if topics_created or topics_updated or companies_created or companies_updated:
            _generate_card_log(
                vault_path,
                topics_created, topics_updated,
                companies_created, companies_updated,
                skipped,
            )

    return {
        "results": results,
        "topics_created": topics_created,
        "topics_updated": topics_updated,
        "companies_created": companies_created,
        "companies_updated": companies_updated,
        "skipped": skipped,
    }


# ═════════════════════════════════════════════════════════════════════════════
# P2-D.1: Topic / Company Card Cleanup & Classification
# ═════════════════════════════════════════════════════════════════════════════

# Company whitelist: names that are definitely companies
_COMPANY_WHITELIST = {
    "nvidia", "openai", "anthropic", "microsoft", "alphabet", "google",
    "meta", "tsmc", "coreweave", "perplexity", "mistral", "blackrock",
    "vanguard", "vercel", "shopify", "amazon", "apple", "amd", "broadcom",
    "oracle", "salesforce", "servicenow", "spacex", "tesla",
    "stripe", "fidelity", "jpmorgan", "jpmorgan chase",
    "state street", "wellington management", "capital group",
    "blackstone", "costco", "morningstar", "s&p global",
    "renaissance technologies", "polymarket", "poke",
    "primerica", "citigroup", "american can company",
    "massachusetts investors trust", "fidelity investments",
    "deepseek", "moonshot ai", "cloudflare", "github",
    "langchain", "workos", "zendesk", "pinecone", "cursor", "e2b", "daytona", "axiom",
    "chatbase",
}

# Topic patterns: names containing these should be topics, not companies
_TOPIC_PATTERNS = [
    "ai agent", "ai infra", "ai capex", "inference", "compute",
    "data center", "cpu supply", "gpu supply", "enterprise saas",
    "kubernetes", "etf", "semiconductor", "cloud", "robotics",
    "developer tools", "formal verification", "企业级", "ai安全",
    "商业模式", "护城河", "长期竞争力", "index fund", "passive",
    "drawdown", "resolution rate", "saas pricing", "gtm strategy",
    "customer service", "attention economy", "consumer tech",
    "b2b saas", "plg", "private equity", "product launch",
    "research workflow", "scientific discovery", "corporate governance",
    "client ownership", "compliance", "distribution", "licensing",
    "long horizon reasoning", "outcome based", "usage based",
    "tech stock", "tech giants", "alternative assets",
    "audio platform", "e commerce", "interactive ai",
    "conversational ui", "coding agents", "academic publishing",
    "chief customer officer", "harness", "model context protocol",
    "reinforcement learning", "seven powers", "lean",
    # Product/model names that aren't companies
    "chatgpt", "gpt-5", "gpt-4", "claude", "codex", "cicd",
    "apple silicon", "macbook", "m5 max", "mac os",
    # Person names that aren't companies
    "alex lubyansky", "ben gilbert", "david rosenthal",
    "hamilton helmer", "ivan burin", "mark chen", "michael lewis",
    "terry tao", "yasser al saeid",
    # Fund names
    "wellington fund", "windsor fund", "manhattan fund",
    "exeter fund", "fidelity capital fund", "ivest fund",
    # Misc
    "spdr", "berkshire hathaway", "arxiv", "formal verification tools",
]

# Topic alias map: variant → canonical
_TOPIC_ALIAS_MAP = {
    "ai agent": "AI Agents",
    "ai agents": "AI Agents",
    "ai-agent": "AI Agents",
    "ai-agents": "AI Agents",
    "agent": "AI Agents",
    "agents": "AI Agents",
    "ai infrastructure": "AI Infra",
    "ai-infra": "AI Infra",
    "ai infra": "AI Infra",
    "ai capex": "AI Capex",
    "ai-capex": "AI Capex",
    "cloud-capex": "AI Capex",
    "cloud capex": "AI Capex",
    "inference compute": "Inference",
    "ai engineering": "AI Engineering",
    "ai-engineering": "AI Engineering",
    "ai coding": "AI Coding",
    "ai-coding": "AI Coding",
    "ai security": "AI Security",
    "ai-security": "AI Security",
    "ai for science": "AI For Science",
    "ai-for-science": "AI For Science",
    "developer tools": "Developer Tools",
    "developer-tools": "Developer Tools",
    "agentic infrastructure": "Agentic Infrastructure",
    "agentic-infrastructure": "Agentic Infrastructure",
    "computer use": "Computer Use",
    "computer-use": "Computer Use",
    "workload patterns": "Workload Patterns",
    "workload-patterns": "Workload Patterns",
    "agent tools": "Agent Tools",
    "agent-tools": "Agent Tools",
    "customer service": "Customer Service",
    "customer-service": "Customer Service",
    "capital market": "Capital Market",
    "capital-market": "Capital Market",
    "corporate structure": "Corporate Structure",
    "corporate-structure": "Corporate Structure",
    "client relationship": "Client Relationship",
    "client-relationship": "Client Relationship",
    "expense ratio": "Expense Ratio",
    "expense-ratio": "Expense Ratio",
}


def _classify_company_card(name: str) -> dict:
    """Classify a company card name.

    Returns:
        {"action": "keep"|"migrate_to_topic"|"manual_review",
         "suggested_type": "company"|"topic"|"unknown",
         "suggested_name": str,
         "reason": str}
    """
    name_lower = name.lower().strip()

    # Check whitelist
    if name_lower in _COMPANY_WHITELIST:
        return {
            "action": "keep",
            "suggested_type": "company",
            "suggested_name": name,
            "reason": "company_whitelist",
        }

    # Check topic patterns
    for pattern in _TOPIC_PATTERNS:
        if pattern.lower() in name_lower:
            # Use the pattern itself as the suggested topic name (title-cased)
            suggested = pattern.replace("_", " ").replace("-", " ").title()
            # Check if there's a canonical alias
            for alias_key, canonical in _TOPIC_ALIAS_MAP.items():
                if alias_key.lower() == name_lower or alias_key.lower() in name_lower:
                    suggested = canonical
                    break
            return {
                "action": "migrate_to_topic",
                "suggested_type": "topic",
                "suggested_name": suggested,
                "reason": "topic_pattern",
            }

    # Check topic alias map directly (for exact matches)
    if name_lower in _TOPIC_ALIAS_MAP:
        return {
            "action": "migrate_to_topic",
            "suggested_type": "topic",
            "suggested_name": _TOPIC_ALIAS_MAP[name_lower],
            "reason": "alias_merge",
        }

    # Uncertain
    return {
        "action": "manual_review",
        "suggested_type": "unknown",
        "suggested_name": name,
        "reason": "uncertain",
    }


def _find_topic_aliases(vault_path: Path) -> list[dict]:
    """Scan 02_Topics/ and find cards that should be merged via alias.

    Returns list of dicts: old_path, old_name, canonical_name, action, reason.
    """
    topics_dir = vault_path / "02_Topics"
    if not topics_dir.exists():
        return []

    results = []
    for card_path in sorted(topics_dir.glob("*.md")):
        card_name = card_path.stem
        card_lower = card_name.lower().strip()

        # Check if this name is an alias for something else
        if card_lower in _TOPIC_ALIAS_MAP:
            canonical = _TOPIC_ALIAS_MAP[card_lower]
            # Only suggest merge if the canonical name is different
            if canonical.lower() != card_lower:
                results.append({
                    "old_path": card_path,
                    "old_name": card_name,
                    "canonical_name": canonical,
                    "action": "merge_topic",
                    "reason": "alias_merge",
                })

    return results


def _extract_source_reports_from_card(card_path: Path) -> list[str]:
    """Extract Source Reports lines from an existing card."""
    content = read_text_safe(card_path)
    lines = content.split("\n")
    report_lines = []
    in_source_reports = False

    for line in lines:
        stripped = line.strip()
        if stripped == "## Source Reports":
            in_source_reports = True
            continue
        if in_source_reports and stripped.startswith("## "):
            break
        if in_source_reports and stripped.startswith("- [["):
            report_lines.append(line)

    return report_lines


def _cleanup_card_log(
    vault_path: Path,
    migrated: int,
    merged: int,
    kept: int,
    manual: int,
) -> None:
    """Append to 99_System/Card Cleanup Log.md."""
    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    log_path = system_dir / "Card Cleanup Log.md"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = [
        f"## {now}",
        "",
        f"- Migrated (company → topic): {migrated}",
        f"- Merged (topic aliases): {merged}",
        f"- Kept as company: {kept}",
        f"- Manual review needed: {manual}",
        f"- Vault path: {vault_path}",
        "",
    ]

    if log_path.exists():
        existing = read_text_safe(log_path)
        content = existing.rstrip() + "\n\n" + "\n".join(entry) + "\n"
    else:
        content = "# Card Cleanup Log\n\n" + "\n".join(entry) + "\n"

    log_path.write_text(content, encoding="utf-8")


def cleanup_cards(
    vault_path: Path,
    dry_run: bool = False,
    apply: bool = False,
    topics_only: bool = False,
    companies_only: bool = False,
    overwrite: bool = False,
) -> dict:
    """Clean up Topic and Company cards: classify, migrate, merge aliases.

    Returns:
        {
            "results": list[dict],
            "migrated": int,
            "merged": int,
            "kept": int,
            "manual_review": int,
        }
    """
    do_companies = not topics_only
    do_topics = not companies_only

    results = []
    migrated = 0
    merged = 0
    kept = 0
    manual_review = 0

    # 1. Classify company cards
    if do_companies:
        companies_dir = vault_path / "03_Companies"
        if companies_dir.exists():
            for card_path in sorted(companies_dir.glob("*.md")):
                card_name = card_path.stem
                classification = _classify_company_card(card_name)

                result_entry = {
                    "type": "company",
                    "name": card_name,
                    "path": card_path,
                    **classification,
                }
                results.append(result_entry)

                if classification["action"] == "keep":
                    kept += 1
                elif classification["action"] == "manual_review":
                    manual_review += 1

    # 2. Find topic aliases
    if do_topics:
        aliases = _find_topic_aliases(vault_path)
        for alias_info in aliases:
            result_entry = {
                "type": "topic",
                "name": alias_info["old_name"],
                "path": alias_info["old_path"],
                "action": "merge_topic",
                "suggested_type": "topic",
                "suggested_name": alias_info["canonical_name"],
                "reason": "alias_merge",
            }
            results.append(result_entry)

    if dry_run:
        return {
            "results": results,
            "migrated": 0,
            "merged": 0,
            "kept": kept,
            "manual_review": manual_review,
        }

    if not apply:
        return {
            "results": results,
            "migrated": 0,
            "merged": 0,
            "kept": kept,
            "manual_review": manual_review,
        }

    # 3. Apply migrations and merges
    backup_dir = vault_path / "99_System" / "Card_Cleanup_Backup"
    backup_dir.mkdir(parents=True, exist_ok=True)

    topics_dir = vault_path / "02_Topics"
    topics_dir.mkdir(parents=True, exist_ok=True)

    for r in results:
        if r["action"] == "migrate_to_topic":
            # Migrate company card to topic
            card_path = r["path"]
            target_name = r["suggested_name"]
            target_path = topics_dir / f"{sanitize_filename(target_name)}.md"

            # Extract source reports from company card
            source_reports = _extract_source_reports_from_card(card_path)

            if not target_path.exists() or overwrite:
                # Create new topic card
                _write_topic_card(target_path, target_name, [])
                # Append source reports
                if source_reports:
                    _append_source_reports(target_path, source_reports)
            else:
                # Append source reports to existing topic card
                if source_reports:
                    _append_source_reports(target_path, source_reports)

            # Move old company card to backup
            dest = backup_dir / f"company_{card_path.name}"
            if dest.exists():
                dest = backup_dir / f"company_{card_path.stem}_bak{card_path.suffix}"
            shutil.move(str(card_path), str(dest))
            migrated += 1

        elif r["action"] == "merge_topic":
            # Merge topic alias into canonical topic
            old_path = r["path"]
            canonical_name = r["suggested_name"]
            canonical_path = topics_dir / f"{sanitize_filename(canonical_name)}.md"

            # Extract source reports from alias card
            source_reports = _extract_source_reports_from_card(old_path)

            if not canonical_path.exists() or overwrite:
                _write_topic_card(canonical_path, canonical_name, [])
                if source_reports:
                    _append_source_reports(canonical_path, source_reports)
            else:
                if source_reports:
                    _append_source_reports(canonical_path, source_reports)

            # Move old alias card to backup
            dest = backup_dir / f"topic_{old_path.name}"
            if dest.exists():
                dest = backup_dir / f"topic_{old_path.stem}_bak{old_path.suffix}"
            shutil.move(str(old_path), str(dest))
            merged += 1

    # 4. Update indexes
    # Re-scan to get current state after cleanup
    if do_topics:
        topic_data = {}
        for card_path in sorted(topics_dir.glob("*.md")):
            card_name = card_path.stem
            source_reports = _extract_source_reports_from_card(card_path)
            topic_data[card_name] = [{"filename": ""}] * len(source_reports)  # dummy
        if topic_data:
            _generate_topic_index(vault_path, topic_data)

    if do_companies:
        companies_dir = vault_path / "03_Companies"
        if companies_dir.exists():
            company_data = {}
            for card_path in sorted(companies_dir.glob("*.md")):
                card_name = card_path.stem
                source_reports = _extract_source_reports_from_card(card_path)
                company_data[card_name] = [{"filename": ""}] * len(source_reports)  # dummy
            if company_data:
                _generate_company_index(vault_path, company_data)

    # 5. Log cleanup
    if migrated or merged:
        _cleanup_card_log(vault_path, migrated, merged, kept, manual_review)

    return {
        "results": results,
        "migrated": migrated,
        "merged": merged,
        "kept": kept,
        "manual_review": manual_review,
    }


# ═════════════════════════════════════════════════════════════════════════════
# P2-D.2: Topic Taxonomy Consolidation
# ═════════════════════════════════════════════════════════════════════════════

# Core Topic taxonomy: high-level themes for LLM-WIKI maintenance
_CORE_TOPICS = {
    "ai infrastructure",
    "ai capex",
    "inference",
    "ai agents",
    "enterprise ai",
    "ai models",
    "open source ai",
    "developer tools",
    "ai applications",
    "ai safety & security",
    "ai safety and security",
    "semiconductor",
    "gpu supply",
    "data center",
    "power & energy",
    "power and energy",
    "cloud",
    "robotics",
    "ai for science",
    "china ai",
    "ai regulation",
    "valuation",
    "business model",
    "moat & strategy",
    "moat and strategy",
    "venture market",
    "public markets",
    "investment framework",
}

# Extended alias map: variant → canonical
_TOPIC_ALIAS_EXTENDED = {
    # AI Agents
    "ai agent": "AI Agents",
    "ai agents": "AI Agents",
    "agentic ai": "AI Agents",
    "agents": "AI Agents",
    "agent workflow": "AI Agents",
    "agent orchestration": "AI Agents",

    # AI Infrastructure
    "ai infra": "AI Infrastructure",
    "ai infrastructure": "AI Infrastructure",
    "ai compute": "AI Infrastructure",
    "compute infrastructure": "AI Infrastructure",
    "gpu cluster": "AI Infrastructure",
    "training infrastructure": "AI Infrastructure",

    # AI Capex
    "ai capex": "AI Capex",
    "cloud capex": "AI Capex",
    "infrastructure capex": "AI Capex",
    "capital expenditure": "AI Capex",

    # Enterprise AI
    "enterprise saas": "Enterprise AI",
    "enterprise software": "Enterprise AI",
    "enterprise ai adoption": "Enterprise AI",
    "enterprise deployment": "Enterprise AI",
    "b2b ai": "Enterprise AI",

    # AI Models
    "llm": "AI Models",
    "language model": "AI Models",
    "foundation model": "AI Models",
    "model training": "AI Models",
    "model architecture": "AI Models",
    "reasoning model": "AI Models",

    # Open Source AI
    "open models": "Open Source AI",
    "open source models": "Open Source AI",
    "open-source ai": "Open Source AI",
    "open weights": "Open Source AI",
    "源码大模型": "Open Source AI",

    # AI Safety & Security
    "ai safety": "AI Safety & Security",
    "ai security": "AI Safety & Security",
    "enterprise ai security": "AI Safety & Security",
    "alignment": "AI Safety & Security",
    "ai governance": "AI Safety & Security",

    # China AI
    "china models": "China AI",
    "chinese ai": "China AI",
    "qwen": "China AI",
    "deepseek": "China AI",
    "中国ai": "China AI",

    # Business Model
    "business model": "Business Model",
    "monetization": "Business Model",
    "pricing": "Business Model",
    "商业模式": "Business Model",
    "saas pricing": "Business Model",

    # Moat & Strategy
    "moat": "Moat & Strategy",
    "competitive advantage": "Moat & Strategy",
    "seven powers": "Moat & Strategy",
    "护城河": "Moat & Strategy",
    "长期竞争力": "Moat & Strategy",

    # Valuation
    "valuation multiple": "Valuation",
    "re-rating": "Valuation",
    "ipo valuation": "Valuation",
    "估值": "Valuation",

    # Venture Market
    "vc": "Venture Market",
    "venture": "Venture Market",
    "private market": "Venture Market",
    "startup funding": "Venture Market",
    "venture capital": "Venture Market",

    # Investment Framework
    "long-term investing": "Investment Framework",
    "长期投资基业": "Investment Framework",
    "investment thesis": "Investment Framework",
    "portfolio strategy": "Investment Framework",

    # AI for Science (canonical casing: "AI for Science", not "Ai For Science")
    "ai for science": "AI for Science",
    "ai-for-science": "AI for Science",
    "ai science": "AI for Science",

    # AI Applications (generic "application" / "applications" must merge here)
    "application": "AI Applications",
    "applications": "AI Applications",
    "ai application": "AI Applications",
    "ai applications": "AI Applications",

    # AI Models (generic "model" / "models" must merge here)
    "model": "AI Models",
    "models": "AI Models",
    "ai model": "AI Models",
    "ai models": "AI Models",
    "foundation models": "AI Models",

    # Enterprise AI (generic "enterprise" and Chinese "企业级" must merge here)
    "enterprise": "Enterprise AI",
    "企业级": "Enterprise AI",
    "enterprise ai": "Enterprise AI",
    "enterprise adoption": "Enterprise AI",

    # Public Markets (generic "capital market" must merge here)
    "capital market": "Public Markets",
    "capital markets": "Public Markets",
}

# Generic topic guard: these names must NOT survive as independent topics
_GENERIC_TOPICS = {
    "application",
    "applications",
    "model",
    "models",
    "enterprise",
    "企业级",
    "capital market",
    "capital markets",
}


def _classify_topic_status(topic_name: str, report_count: int) -> tuple[str, str]:
    """Classify topic status based on core taxonomy and report count.

    Returns:
        (status, reason): status in [core, emerging, long_tail, manual_review]
    """
    topic_lower = topic_name.lower().strip()
    # Normalize: replace hyphens and underscores with spaces for matching
    topic_normalized = topic_lower.replace("-", " ").replace("_", " ")

    # Check if it's a core topic (exact or normalized)
    if topic_lower in _CORE_TOPICS or topic_normalized in _CORE_TOPICS:
        return "core", "core_taxonomy"

    # Check if it's an alias for a core topic
    for variant in [topic_lower, topic_normalized]:
        if variant in _TOPIC_ALIAS_EXTENDED:
            canonical = _TOPIC_ALIAS_EXTENDED[variant]
            if canonical.lower() in _CORE_TOPICS or canonical.lower().replace("-", " ").replace("_", " ") in _CORE_TOPICS:
                return "core", "alias_match"

    # Classify by report count
    if report_count >= 2:
        return "emerging", "report_count"
    else:
        return "long_tail", "report_count"


def _scan_topic_cards(vault_path: Path) -> list[dict]:
    """Scan 02_Topics/ and extract metadata from each card.

    Returns:
        list of dicts with: path, name, report_count, source_reports
    """
    topics_dir = vault_path / "02_Topics"
    if not topics_dir.exists():
        return []

    results = []
    for card_path in sorted(topics_dir.glob("*.md")):
        content = read_text_safe(card_path)

        # Count source reports
        source_reports = []
        in_source_reports = False
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped == "## Source Reports":
                in_source_reports = True
                continue
            if in_source_reports and stripped.startswith("## "):
                break
            if in_source_reports and stripped.startswith("- [["):
                source_reports.append(line)

        results.append({
            "path": card_path,
            "name": card_path.stem,
            "report_count": len(source_reports),
            "source_reports": source_reports,
        })

    return results


def consolidate_topics(
    vault_path: Path,
    dry_run: bool = False,
    apply: bool = False,
    core_only: bool = False,
    merge_aliases: bool = True,
    mark_status: bool = True,
    overwrite: bool = False,
) -> dict:
    """Consolidate Topic taxonomy: merge aliases, mark status, backup old files.

    Args:
        vault_path: Path to vault root
        dry_run: Preview only, no file changes
        apply: Actually perform consolidation
        core_only: Only process core topics
        merge_aliases: Merge alias topics into canonical topics
        mark_status: Mark topic status in frontmatter
        overwrite: Overwrite existing files

    Returns:
        dict with: results, core_count, emerging_count, long_tail_count,
                   manual_review_count, merged_count
    """
    # 1. Scan all topic cards
    topic_cards = _scan_topic_cards(vault_path)

    # 2. Build alias map: variant → canonical
    alias_map = {}
    for topic_info in topic_cards:
        topic_name = topic_info["name"]
        topic_lower = topic_name.lower().strip()
        topic_normalized = topic_lower.replace("-", " ").replace("_", " ")

        # Generic topic guard: force merge regardless of other conditions
        if topic_lower in _GENERIC_TOPICS or topic_normalized in _GENERIC_TOPICS:
            # Find the canonical name for this generic topic
            canonical = None
            for variant in [topic_lower, topic_normalized]:
                if variant in _TOPIC_ALIAS_EXTENDED:
                    canonical = _TOPIC_ALIAS_EXTENDED[variant]
                    break
            if canonical and canonical != topic_name:
                alias_map[topic_name] = canonical
            continue

        # Check if this topic is an alias (try both exact and normalized)
        canonical = None
        for variant in [topic_lower, topic_normalized]:
            if variant in _TOPIC_ALIAS_EXTENDED:
                canonical = _TOPIC_ALIAS_EXTENDED[variant]
                break

        # Only mark as alias if canonical name is different
        # This handles both true aliases AND casing mismatches (e.g., "Ai For Science" → "AI for Science")
        if canonical and canonical != topic_name:
            alias_map[topic_name] = canonical

    # 3. Classify each topic
    results = []
    for topic_info in topic_cards:
        topic_name = topic_info["name"]
        report_count = topic_info["report_count"]

        # Check if this is an alias that should be merged
        if merge_aliases and topic_name in alias_map:
            canonical = alias_map[topic_name]
            action = "merge_topic"
            suggested_name = canonical
            status = "merged"
            reason = "alias_match"
        else:
            # Classify status
            status, reason = _classify_topic_status(topic_name, report_count)

            # Determine action
            if core_only and status != "core":
                action = "skip"
                suggested_name = topic_name
            elif mark_status:
                if status == "core":
                    action = "mark_core"
                elif status == "emerging":
                    action = "mark_emerging"
                elif status == "long_tail":
                    action = "mark_long_tail"
                else:
                    action = "manual_review"
                suggested_name = topic_name
            else:
                action = "keep"
                suggested_name = topic_name

        results.append({
            "path": topic_info["path"],
            "name": topic_name,
            "report_count": report_count,
            "status": status,
            "action": action,
            "suggested_name": suggested_name,
            "reason": reason,
        })

    if dry_run:
        # Count by status
        core_count = sum(1 for r in results if r["status"] == "core")
        emerging_count = sum(1 for r in results if r["status"] == "emerging")
        long_tail_count = sum(1 for r in results if r["status"] == "long_tail")
        manual_review_count = sum(1 for r in results if r["status"] == "manual_review")
        merged_count = sum(1 for r in results if r["action"] == "merge_topic")

        return {
            "results": results,
            "core_count": core_count,
            "emerging_count": emerging_count,
            "long_tail_count": long_tail_count,
            "manual_review_count": manual_review_count,
            "merged_count": merged_count,
        }

    if not apply:
        return {
            "results": results,
            "core_count": 0,
            "emerging_count": 0,
            "long_tail_count": 0,
            "manual_review_count": 0,
            "merged_count": 0,
        }

    # 4. Apply consolidation
    backup_dir = vault_path / "99_System" / "Topic_Consolidation_Backup"
    backup_dir.mkdir(parents=True, exist_ok=True)

    topics_dir = vault_path / "02_Topics"
    merged_count = 0

    # Process merges first
    for r in results:
        if r["action"] == "merge_topic":
            old_path = r["path"]
            canonical_name = r["suggested_name"]
            canonical_path = topics_dir / f"{canonical_name}.md"

            # Read old card's source reports
            old_content = read_text_safe(old_path)
            old_source_reports = _extract_source_reports_from_card(old_path)

            # Check if old_path and canonical_path are the same file (case-insensitive filesystem)
            same_file = False
            try:
                same_file = old_path.resolve() == canonical_path.resolve()
            except (OSError, RuntimeError):
                # If resolve fails, fall back to name comparison (case-insensitive)
                same_file = old_path.name.lower() == canonical_path.name.lower()

            if same_file:
                # This is a casing-only fix: rename the file to canonical casing
                # First, update the content to use canonical name
                if old_content:
                    # Update frontmatter topic field
                    old_content = re.sub(
                        r"^topic:\s*.+$",
                        f"topic: {canonical_name}",
                        old_content,
                        count=1,
                        flags=re.MULTILINE,
                    )
                    # Update H1 heading
                    old_content = re.sub(
                        r"^#\s+.+$",
                        f"# {canonical_name}",
                        old_content,
                        count=1,
                        flags=re.MULTILINE,
                    )
                    # Update tags to use canonical slug
                    canonical_slug = canonical_name.lower().replace(" ", "-").replace("&", "and")
                    old_content = re.sub(
                        r"tags:\s*\n\s*-\s*topic/[^\n]+",
                        f"tags:\n  - topic/{canonical_slug}",
                        old_content,
                        count=1,
                    )
                    # Update timestamp
                    old_content = re.sub(
                        r"updated_at:.*",
                        f"updated_at: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                        old_content,
                    )
                    # Write updated content to old_path first
                    old_path.write_text(old_content, encoding="utf-8")

                # Now rename the file to canonical casing
                backup_name = f"merged_{old_path.name}"
                backup_path = backup_dir / backup_name
                old_path.rename(backup_path)
                # Move it back with canonical name
                backup_path.rename(canonical_path)
                merged_count += 1
            else:
                # Different files: merge content
                # Create or update canonical card
                if canonical_path.exists() and not overwrite:
                    # Append source reports to existing card
                    if old_source_reports:
                        _append_source_reports(canonical_path, old_source_reports)
                else:
                    # Read old card's frontmatter and content
                    # Create new canonical card with merged source reports
                    _write_topic_card(canonical_path, canonical_name, [])
                    if old_source_reports:
                        _append_source_reports(canonical_path, old_source_reports)

                # Backup old card
                backup_name = f"merged_{old_path.name}"
                backup_path = backup_dir / backup_name
                old_path.rename(backup_path)
                merged_count += 1

    # Process status marking
    if mark_status:
        for r in results:
            if r["action"] in ("mark_core", "mark_emerging", "mark_long_tail", "manual_review"):
                card_path = r["path"]
                if card_path.exists():
                    # Read existing content
                    content = read_text_safe(card_path)

                    # Update frontmatter with status
                    if "---" in content:
                        parts = content.split("---", 2)
                        if len(parts) >= 3:
                            frontmatter = parts[1]
                            body = parts[2]

                            # Add or update status field
                            if "status:" in frontmatter:
                                frontmatter = re.sub(
                                    r"status:.*",
                                    f"status: {r['status']}",
                                    frontmatter,
                                )
                            else:
                                # Insert status after type
                                frontmatter = re.sub(
                                    r"(type:.*\n)",
                                    f"\\1status: {r['status']}\n",
                                    frontmatter,
                                )

                            # Update timestamp
                            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                            if "updated_at:" in frontmatter:
                                frontmatter = re.sub(
                                    r"updated_at:.*",
                                    f"updated_at: {timestamp}",
                                    frontmatter,
                                )
                            else:
                                frontmatter += f"updated_at: {timestamp}\n"

                            content = f"---{frontmatter}---{body}"
                            card_path.write_text(content, encoding="utf-8")

    # 5. Generate taxonomy index
    _generate_topic_taxonomy(vault_path, results)

    # 6. Update topic index
    topic_data = {}
    for card_path in sorted(topics_dir.glob("*.md")):
        card_name = card_path.stem
        source_reports = _extract_source_reports_from_card(card_path)
        topic_data[card_name] = [{"filename": ""}] * len(source_reports)
    if topic_data:
        _generate_topic_index(vault_path, topic_data)

    # 7. Log consolidation
    _consolidation_log(vault_path, results, merged_count)

    # Count by status
    core_count = sum(1 for r in results if r["status"] == "core")
    emerging_count = sum(1 for r in results if r["status"] == "emerging")
    long_tail_count = sum(1 for r in results if r["status"] == "long_tail")
    manual_review_count = sum(1 for r in results if r["status"] == "manual_review")

    return {
        "results": results,
        "core_count": core_count,
        "emerging_count": emerging_count,
        "long_tail_count": long_tail_count,
        "manual_review_count": manual_review_count,
        "merged_count": merged_count,
    }


def _generate_topic_taxonomy(vault_path: Path, results: list[dict]) -> None:
    """Generate 99_System/Topic Taxonomy.md with hierarchical topic listing."""
    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)

    # Group by status
    core_topics = [r for r in results if r["status"] == "core" and r["action"] != "merge_topic"]
    emerging_topics = [r for r in results if r["status"] == "emerging"]
    long_tail_topics = [r for r in results if r["status"] == "long_tail"]
    manual_review_topics = [r for r in results if r["status"] == "manual_review"]

    # Sort each group
    core_topics.sort(key=lambda r: r["name"])
    emerging_topics.sort(key=lambda r: r["report_count"], reverse=True)
    long_tail_topics.sort(key=lambda r: r["name"])
    manual_review_topics.sort(key=lambda r: r["name"])

    lines = [
        "# Topic Taxonomy",
        "",
        f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Core Topics",
        "",
        "| Topic | Reports | Card |",
        "|---|---:|---|",
    ]
    for r in core_topics:
        lines.append(f"| {r['name']} | {r['report_count']} | [[{r['name']}]] |")

    lines.extend([
        "",
        "## Emerging Topics",
        "",
        "| Topic | Reports | Card |",
        "|---|---:|---|",
    ])
    for r in emerging_topics:
        lines.append(f"| {r['name']} | {r['report_count']} | [[{r['name']}]] |")

    lines.extend([
        "",
        "## Long-tail Topics",
        "",
        "| Topic | Reports | Card |",
        "|---|---:|---|",
    ])
    for r in long_tail_topics:
        lines.append(f"| {r['name']} | {r['report_count']} | [[{r['name']}]] |")

    lines.extend([
        "",
        "## Manual Review",
        "",
        "| Topic | Reports | Card |",
        "|---|---:|---|",
    ])
    for r in manual_review_topics:
        lines.append(f"| {r['name']} | {r['report_count']} | [[{r['name']}]] |")

    content = "\n".join(lines) + "\n"
    (system_dir / "Topic Taxonomy.md").write_text(content, encoding="utf-8")


def _consolidation_log(
    vault_path: Path,
    results: list[dict],
    merged_count: int,
) -> None:
    """Append to 99_System/Topic Consolidation Log.md."""
    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Count by action
    core_marked = sum(1 for r in results if r["action"] == "mark_core")
    emerging_marked = sum(1 for r in results if r["action"] == "mark_emerging")
    long_tail_marked = sum(1 for r in results if r["action"] == "mark_long_tail")
    manual_review_marked = sum(1 for r in results if r["action"] == "manual_review")

    log_entry = (
        f"## {now}\n\n"
        f"- Total topics processed: {len(results)}\n"
        f"- Merged (alias → canonical): {merged_count}\n"
        f"- Marked as core: {core_marked}\n"
        f"- Marked as emerging: {emerging_marked}\n"
        f"- Marked as long_tail: {long_tail_marked}\n"
        f"- Marked as manual_review: {manual_review_marked}\n"
        f"- Vault path: {vault_path}\n"
    )

    log_path = system_dir / "Topic Consolidation Log.md"
    if log_path.exists():
        existing = read_text_safe(log_path)
        content = existing + "\n" + log_entry
    else:
        content = "# Topic Consolidation Log\n\n" + log_entry

    log_path.write_text(content, encoding="utf-8")


# ═════════════════════════════════════════════════════════════════════════════
# P2-M.3: Rerun — Archive Current Video Outputs
# ═════════════════════════════════════════════════════════════════════════════


def archive_current_video_outputs(video_id: str, vault_path: Path) -> dict:
    """Archive old reports, mark old claims/signals as archived for a given video_id.

    Returns:
        {"reports_archived": int, "claims_archived": int, "signals_archived": int}
    """
    result = {"reports_archived": 0, "claims_archived": 0, "signals_archived": 0}
    archive_dir = vault_path / "99_System" / "Archive" / "Reports"
    archive_dir.mkdir(parents=True, exist_ok=True)

    reports_dir = vault_path / "01_Reports"
    matched_report_files = []

    # Step 1: Find and archive reports matching this video_id
    if reports_dir.exists():
        for rf in sorted(reports_dir.glob("*.md")):
            try:
                content = read_text_safe(rf)
                fm = _parse_yaml_frontmatter(content)
                if fm.get("video_id", "").strip() == video_id:
                    matched_report_files.append(rf)
            except Exception:
                continue

    for rf in matched_report_files:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = archive_dir / f"{rf.stem}_{ts}{rf.suffix}"
        if dest.exists():
            dest = archive_dir / f"{rf.stem}_{ts}_b{rf.suffix}"
        shutil.move(str(rf), str(dest))
        result["reports_archived"] += 1

    if not matched_report_files:
        return result

    # Step 2: Mark claims as archived if they reference any matching report
    # Note: _parse_yaml_frontmatter cannot read list-type fields like source_reports.
    # We search for the report filename directly in the raw content.
    claim_filenames = {rf.name for rf in matched_report_files}
    claims_dir = vault_path / "06_Claims"
    if claims_dir.exists():
        for cf in sorted(claims_dir.glob("*.md")):
            try:
                content = read_text_safe(cf)
                # Check if any matched report filename appears in the file
                if any(fn in content for fn in claim_filenames):
                    _update_frontmatter_fields(cf, {
                        "status": "archived",
                        "archived_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "archived_reason": "rerun_video",
                    })
                    result["claims_archived"] += 1
            except Exception:
                continue

    # Step 3: Mark signals as archived
    signals_dir = vault_path / "07_Signals"
    if signals_dir.exists():
        for sf in sorted(signals_dir.glob("*.md")):
            try:
                content = read_text_safe(sf)
                if any(fn in content for fn in claim_filenames):
                    _update_frontmatter_fields(sf, {
                        "status": "archived",
                        "archived_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "archived_reason": "rerun_video",
                    })
                    result["signals_archived"] += 1
            except Exception:
                continue

    return result


def _update_frontmatter_fields(card_path: Path, updates: dict) -> None:
    """Update frontmatter fields in an existing card file. Reads and rewrites."""
    content = read_text_safe(card_path)
    lines = content.split("\n")

    if not lines or lines[0].strip() != "---":
        return

    # Find closing ---
    end_idx = None
    for i in range(1, min(len(lines), 50)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return

    # Apply updates to existing fields
    updated_keys = set()
    new_lines = lines[:end_idx]
    for i, line in enumerate(new_lines):
        for key, val in updates.items():
            if line.startswith(f"{key}:") and key not in updated_keys:
                new_lines[i] = f"{key}: {val}"
                updated_keys.add(key)

    # Add new fields not found
    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.insert(-1, f"{key}: {val}")

    result = "\n".join(new_lines + lines[end_idx:])
    card_path.write_text(result, encoding="utf-8")
