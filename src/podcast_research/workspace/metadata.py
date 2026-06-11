"""Report metadata polish: backfill title, published_at, and fix display names.

Queries SQLite channel_videos for metadata, updates report frontmatter,
fixes H1 headings, and refreshes Source Reports display text across all cards.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from podcast_research.claim_signal.review import (
    _ensure_frontmatter_field,
    _parse_frontmatter,
)
from podcast_research.utils.file_io import read_text_safe

logger = logging.getLogger(__name__)


def polish_report_metadata(
    vault_path: Path,
    *,
    dry_run: bool = True,
    apply: bool = False,
    overwrite_title: bool = False,
) -> dict:
    """Backfill report metadata from DB and fix display names.

    Args:
        vault_path: Path to Obsidian vault root.
        dry_run: Preview changes without writing.
        apply: Actually write changes.
        overwrite_title: Overwrite existing non-empty title fields.

    Returns:
        dict with 'results' list and 'stats' summary.
    """
    if not dry_run and not apply:
        raise ValueError("Must specify --dry-run or --apply")

    # Load DB metadata
    cv_meta = _load_db_metadata()

    results: list[dict] = []
    stats = {"reports_scanned": 0, "titles_updated": 0, "published_dates_updated": 0,
             "h1_fixed": 0, "display_names_updated": 0}

    reports_dir = vault_path / "01_Reports"
    if not reports_dir.exists():
        return {"results": results, "stats": stats}

    # Phase 1: Polish report files themselves
    for p in sorted(reports_dir.glob("*.md")):
        try:
            content = read_text_safe(p)
        except Exception:
            logger.warning(f"Cannot read report: {p}")
            continue
        stats["reports_scanned"] += 1

        fm = _parse_frontmatter(content)
        video_id = fm.get("video_id", "")
        channel = fm.get("channel", "")
        current_title = fm.get("title", "")
        current_published = fm.get("published_at", "")

        result = {
            "filename": p.stem,
            "video_id": video_id,
            "channel": channel,
            "current_title": current_title,
            "suggested_title": current_title,
            "current_published": current_published,
            "suggested_published": current_published,
            "h1_fixed": False,
            "action": "skip",
            "reason": "no changes needed",
        }

        updated = content

        # Determine best title
        db_title = ""
        db_published = ""
        if video_id and video_id in cv_meta:
            db_title = cv_meta[video_id].get("video_title", "") or ""
            db_published = cv_meta[video_id].get("published_at", "") or ""

        suggested_title = _determine_title(content, current_title, db_title, overwrite_title)
        if suggested_title and suggested_title != current_title:
            result["suggested_title"] = suggested_title
            result["action"] = "update_metadata"

        # Backfill published_at
        suggested_published = current_published or db_published
        if suggested_published and suggested_published != current_published:
            result["suggested_published"] = suggested_published
            result["action"] = "update_metadata"

        # Apply
        if apply and result["action"] == "update_metadata":
            if suggested_title and suggested_title != current_title:
                updated = _ensure_frontmatter_field(updated, "title", f'"{suggested_title}"')
                stats["titles_updated"] += 1
            if suggested_published and suggested_published != current_published:
                updated = _ensure_frontmatter_field(updated, "published_at", f'"{suggested_published}"')
                stats["published_dates_updated"] += 1
            # Fix H1 if it's a bare video_id
            if suggested_title and _h1_is_video_id(content):
                updated = _fix_h1(updated, suggested_title)
                result["h1_fixed"] = True
                stats["h1_fixed"] += 1
            # Update updated_at
            now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            updated = _ensure_frontmatter_field(updated, "updated_at", f'"{now_iso}"')
            p.write_text(updated, encoding="utf-8")

        results.append(result)

    # Phase 2: Refresh display names in source report references
    # Build a title map from reports
    title_map: dict[str, str] = {}
    for p in sorted(reports_dir.glob("*.md")):
        try:
            content = read_text_safe(p)
        except Exception:
            continue
        fm = _parse_frontmatter(content)
        fm.get("video_id", "")
        ch = fm.get("channel", "")
        t = fm.get("title", "")
        if not t:
            # Try H1
            for line in content.split("\n"):
                if line.startswith("# ") and not line.startswith("## "):
                    h1 = line[2:].strip()
                    if not _is_video_id_string(h1):
                        t = h1
                    break
        title_map[p.stem] = f"{ch} — {t}" if ch and t else (t or p.stem)

    # Refresh display names in other cards
    for card_dir_name in ["02_Topics", "03_Companies", "05_Channels", "06_Claims", "07_Signals"]:
        card_dir = vault_path / card_dir_name
        if not card_dir.exists():
            continue
        for p in sorted(card_dir.glob("*.md")):
            try:
                content = read_text_safe(p)
            except Exception:
                continue
            updated_content = _refresh_source_report_display(content, title_map)
            if updated_content != content:
                if apply:
                    p.write_text(updated_content, encoding="utf-8")
                stats["display_names_updated"] += 1

    # Write log
    if apply and (stats["titles_updated"] > 0 or stats["h1_fixed"] > 0 or stats["display_names_updated"] > 0):
        _write_metadata_log(vault_path, stats, results)

    return {"results": results, "stats": stats}


# ── DB metadata loading ───────────────────────────────────────────


def _load_db_metadata() -> dict[str, dict]:
    """Load channel_videos metadata from SQLite DB, keyed by video_id."""
    try:

        from podcast_research.db.models import Channel, ChannelVideo
        from podcast_research.db.session import SessionLocal

        session = SessionLocal()
        try:
            all_cv = session.query(ChannelVideo).all()
            all_ch = {ch.id: ch for ch in session.query(Channel).all()}
            result = {}
            for cv in all_cv:
                ch = all_ch.get(cv.channel_id)
                result[cv.video_id] = {
                    "video_title": cv.title or "",
                    "published_at": str(cv.published_at)[:10] if cv.published_at else "",
                    "channel_name": ch.name if ch else "",
                }
            return result
        finally:
            session.close()
    except Exception:
        logger.warning("Cannot load DB metadata, using empty map")
        return {}


# ── Title determination ───────────────────────────────────────────


def _determine_title(
    content: str,
    current_title: str,
    db_title: str,
    overwrite_title: bool,
) -> str:
    """Determine the best title for a report."""
    # If title exists and we're not overwriting
    if current_title and not overwrite_title:
        return current_title

    # Priority: DB title > H1 > empty
    if db_title:
        return db_title

    # Try H1
    for line in content.split("\n"):
        if line.startswith("# ") and not line.startswith("## "):
            h1 = line[2:].strip()
            if not _is_video_id_string(h1) and h1:
                return h1
            break

    return current_title  # keep existing


def _is_video_id_string(text: str) -> bool:
    """Check if a string looks like a bare YouTube video ID."""
    # YouTube video IDs are 11 chars, alphanumeric + -_
    return bool(re.match(r'^[A-Za-z0-9_-]{11}$', text.strip()))


def _h1_is_video_id(content: str) -> bool:
    """Check if the H1 heading is a bare video ID."""
    for line in content.split("\n"):
        if line.startswith("# ") and not line.startswith("## "):
            return _is_video_id_string(line[2:].strip())
    return False


def _fix_h1(content: str, new_title: str) -> str:
    """Replace video_id H1 with a human-readable title."""
    lines = content.split("\n")
    result = []
    for line in lines:
        if line.startswith("# ") and not line.startswith("## "):
            if _is_video_id_string(line[2:].strip()):
                result.append(f"# {new_title}")
                continue
        result.append(line)
    return "\n".join(result)


# ── Source report display name refresh ────────────────────────────


def _refresh_source_report_display(content: str, title_map: dict[str, str]) -> str:
    """Update source report display names in card body text.

    Changes: [[filename]] — video_id → [[filename]] — Channel — Title
    Does NOT modify wiki link targets.
    """
    updated = content

    # Pattern: - [[filename]] — something (captures the display part after —)
    # We want to replace the display text without changing the [[link]]
    def _replace_display(match):
        full = match.group(0)
        link_target = match.group(1)
        # Remove .md extension for matching
        clean_target = link_target.replace(".md", "")
        display_part = match.group(2) if match.group(2) else ""

        if clean_target in title_map:
            new_display = title_map[clean_target]
            # Only replace if display is different (i.e., old display was just video_id)
            old_display_clean = display_part.strip()
            if old_display_clean != new_display and old_display_clean:
                return f"- [[{link_target}]] — {new_display}"
        return full

    # Match lines like: "- [[2026-05-29_Latent Space_CSYWbbP_OkY]] — CSYWbbP_OkY"
    pattern = re.compile(r'- \[\[([^\]]+)\]\]\s*—\s*(.+)$', re.MULTILINE)
    updated = pattern.sub(_replace_display, updated)

    return updated


# ── Logging ───────────────────────────────────────────────────────


def _write_metadata_log(
    vault_path: Path,
    stats: dict,
    results: list[dict],
) -> None:
    """Write Report_Metadata_Polish_Log.md."""
    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    log_path = system_dir / "Report_Metadata_Polish_Log.md"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# Report Metadata Polish Log",
        "",
        f"## {now}",
        "",
        f"- Reports scanned: {stats['reports_scanned']}",
        f"- Titles updated: {stats['titles_updated']}",
        f"- Published dates updated: {stats['published_dates_updated']}",
        f"- H1 headings fixed: {stats['h1_fixed']}",
        f"- Display names updated: {stats['display_names_updated']}",
        "",
    ]

    updated_reports = [r for r in results if r.get("action") == "update_metadata"]
    if updated_reports:
        lines.append("### Updated Reports")
        lines.append("")
        for r in updated_reports:
            parts = []
            if r.get("suggested_title") != r.get("current_title"):
                parts.append(f"title: '{r['current_title']}' → '{r['suggested_title']}'")
            if r.get("suggested_published") != r.get("current_published"):
                parts.append(f"published: '{r['current_published']}' → '{r['suggested_published']}'")
            if r.get("h1_fixed"):
                parts.append("H1 fixed")
            lines.append(f"- **{r['filename']}**: {'; '.join(parts)}")
        lines.append("")

    # Append to existing log
    if log_path.exists():
        existing = read_text_safe(log_path)
        header_end = existing.find("\n\n", existing.find("# Report Metadata Polish Log"))
        if header_end > 0:
            new_entry = "\n".join(lines[2:])
            log_path.write_text(existing[:header_end + 2] + new_entry + "\n" + existing[header_end + 2:])
            return

    log_path.write_text("\n".join(lines), encoding="utf-8")
