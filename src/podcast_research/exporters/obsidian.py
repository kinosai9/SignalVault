"""P2-C: Obsidian Vault Export v1.

将 SQLite 中的 YouTube 报告导出为 Obsidian 笔记：
- 01_Reports/  → 单视频报告（YAML frontmatter + 结构化 Markdown）
- 05_Channels/ → 频道卡片
- 99_System/   → Report Index + Export Log
"""

from __future__ import annotations

import json
import logging
import re
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

from podcast_research.db.models import Report, Episode, InvestmentViewRecord
from podcast_research.db.repository import _parse_focus_areas, _infer_source_type
from podcast_research.db.session import get_session, init_db
from podcast_research.exporters.markdown_utils import (
    build_frontmatter,
    sanitize_filename,
    wiki_link,
    wiki_links_from_list,
    _WIKI_LINK_ENTITY_TYPES,
)

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
    for i, ins in enumerate(insights_data):
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
    ch_name = sanitize_filename(channel_name or source_info.get("channel_name", "") or "UnknownChannel")

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
        existing = filepath.read_text(encoding="utf-8")
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
        existing = filepath.read_text(encoding="utf-8")
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
) -> dict:
    """Orchestrate full vault export.

    Returns:
        {"created": int, "skipped": int, "channel_cards": int, "exported": list[dict]}
    """
    init_db()
    session = get_session()
    try:
        # Query reports
        q = session.query(Report, Episode).join(Episode, Report.episode_id == Episode.id)

        # Filter: only youtube for v1
        if source_type:
            if source_type == "youtube":
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
        return {
            "created": 0, "skipped": 0, "channel_cards": 0,
            "exported": [
                {
                    "report_id": r.id,
                    "date": r.analysis_timestamp.strftime("%Y-%m-%d") if r.analysis_timestamp else "",
                    "channel": "",
                    "title": e.video_id or e.title,
                    "video_id": e.video_id,
                    "filename": "",
                }
                for r, e in rows
            ],
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
    finally:
        session2.close()

    for report, episode in rows:
        # Get channel metadata
        extraction = _load_extraction(report)
        source_info = extraction.get("source_info", {}) or {}
        channel_name = source_info.get("channel_name", "")
        channel_url = source_info.get("channel_url", "")
        channel_tags = source_info.get("channel_tags", [])

        # Also try channel lookup from DB
        for ch_id, ch in ch_map.items():
            if ch.name == channel_name or ch.url == channel_url:
                if not channel_tags:
                    try:
                        channel_tags = json.loads(ch.tags) if ch.tags else []
                    except (json.JSONDecodeError, TypeError):
                        pass
                if not channel_url:
                    channel_url = ch.url
                break

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
        published = source_info.get("published_at", "") or ""
        date_str = published[:10] if published else report.analysis_timestamp.strftime("%Y-%m-%d") if report.analysis_timestamp else datetime.now().strftime("%Y-%m-%d")
        vid = episode.video_id or "unknown"
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

        export_entry = {
            "report_id": report.id,
            "date": date_str,
            "channel": channel_name,
            "title": source_info.get("title", "") or episode.title,
            "video_id": episode.video_id,
            "filename": filename,
        }
        exported.append(export_entry)

        if result["status"] == "created":
            created += 1
        else:
            skipped += 1

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
