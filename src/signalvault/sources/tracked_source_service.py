"""P2-S.3.2: Tracked Source Service — refresh discovery & batch import orchestration.

Orchestrates the P2-S.3.1 import pipeline (adapter selection → build_import_preview
→ execute_import_action) for persistent tracked external sources.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def validate_url_for_tracking(url: str) -> tuple[bool, str, str, str]:
    """Validate a URL for tracking. Only AllIn Podcast ZH notes supported in v1.

    Returns:
        (is_valid, adapter_name, provider, message)
    """
    url_lower = url.lower()
    is_allin = (
        "allin-podcast-zh-notes" in url_lower
        or "chirs-ma.github.io/allin-podcast-zh-notes" in url_lower
    )
    if is_allin:
        return True, "AllInZHNotesAdapter", "allin-podcast-zh-notes", ""
    return (
        False, "", "",
        "当前不支持持续跟踪该站点。目前仅支持 All-In Podcast 中文笔记"
        " (allin-podcast-zh-notes)。你可以使用单网页导入功能处理其他站点。",
    )


def refresh_tracked_source(
    tracked_source_id: int,
    vault_path: Path,
    preview_store: dict,
) -> dict:
    """Execute a full refresh cycle for a tracked source.

    1. Load tracked source, select adapter
    2. adapter.fetch_homepage() → ExternalEpisodeEntry list
    3. For each entry: upsert in DB, generate ImportPreview if new
    4. Store ImportPreview in preview_store and link preview_id to entry
    5. Update tracked source stats and status

    Returns a summary dict:
        {success, message, total_on_page, new_entries, existing_entries,
         failed_entries, preview_ids}
    """
    from sqlalchemy import func

    from signalvault.db.models import TrackedSource
    from signalvault.db.models import TrackedSourceEntry as TSE
    from signalvault.db.repository import (
        get_tracked_source,
        update_tracked_source_entry_status,
        update_tracked_source_status,
        upsert_tracked_source_entry,
    )
    from signalvault.db.session import get_session, init_db
    from signalvault.sources.import_preview import (
        build_import_preview,
        select_adapter_for_url,
    )

    init_db()
    session = get_session()
    try:
        ts = get_tracked_source(session, tracked_source_id)
        if not ts:
            return {"success": False, "message": "信息源不存在"}

        # ── Eligibility gate ────────────────────────────────────────────
        # Respect profiling decision: only refresh trackable sources
        if not ts.get("enabled", True):
            return {"success": False, "message": "该信息源已禁用，无法刷新"}
        trackable_kinds = {"allin_notes_index"}
        if ts.get("source_kind", "") not in trackable_kinds:
            return {
                "success": False,
                "message": f"该来源类型 ({ts.get('source_kind', 'unknown')}) 不支持刷新",
            }

        adapter = select_adapter_for_url(ts["homepage_url"])

        # Step 1: Fetch homepage
        try:
            entries = adapter.fetch_homepage(ts["homepage_url"])
        except Exception as e:
            update_tracked_source_status(session, tracked_source_id, "failed", str(e)[:500])
            session.commit()
            return {"success": False, "message": f"首页抓取失败: {str(e)[:120]}"}

        if not entries:
            update_tracked_source_status(session, tracked_source_id, "active")
            session.commit()
            return {
                "success": True,
                "message": "首页无内容，未发现新条目",
                "total_on_page": 0,
                "new_entries": 0,
                "existing_entries": 0,
                "failed_entries": 0,
                "preview_ids": [],
            }

        # Step 2: Process each entry
        new_count = 0
        existing_count = 0
        failed_count = 0
        preview_ids: list[str] = []

        for entry in entries:
            entry_id, is_new = upsert_tracked_source_entry(
                session,
                tracked_source_id=tracked_source_id,
                url=entry.url,
                title=entry.title,
                slug=entry.slug,
                published_at=entry.date,
            )

            if not is_new:
                existing_count += 1
                # ── State machine guard ──────────────────────────────────────
                # Status flow: new → preview_ready → imported | skipped | failed
                # Only transition "new" → "existing" on re-discovery.
                # Never overwrite user decisions (skipped/imported) or machine
                # states (failed/preview_ready/existing) during refresh.
                # This keeps the status graph unidirectional and explainable.
                #
                # "existing" vs ConflictDetector semantics:
                #   - "existing" = this entry URL was seen in a previous refresh
                #     of THIS tracked source (DB-level dedup within the source).
                #   - ConflictDetector checks the VAULT: same video_id in a
                #     report, same content_hash in SourceArchive, Deep Notes
                #     already present — these are file-level checks against
                #     the knowledge base, not against the tracked source.
                #   - "existing" entries show no import action in the entries
                #     list, so the user won't see contradictory recommendations.
                #   - If the user manually re-imports via /sources/import,
                #     ConflictDetector provides the correct vault-level guidance.
                db_entry = session.query(TSE).filter_by(id=entry_id).first()
                if db_entry and db_entry.status == "new":
                    update_tracked_source_entry_status(session, entry_id, "existing")
                continue

            # New entry: build ImportPreview
            new_count += 1
            try:
                preview = build_import_preview(entry.url, vault_path)
                preview_ids.append(preview.preview_id)
                preview_store[preview.preview_id] = preview

                # P3-A: Dual-write to persistent ingest_jobs
                try:
                    from signalvault.sources.ingest_jobs import IngestJobManager
                    IngestJobManager.create_job(
                        source_type="tracked_entry",
                        source_url=entry.url,
                        source_hash=getattr(preview, "content_hash", "") or "",
                        source_name=getattr(preview, "title", "") or entry.title or entry.url,
                        preview_id=preview.preview_id,
                        preview_data=json.dumps(
                            preview,
                            default=lambda o: o.__dict__,
                            ensure_ascii=False,
                        ),
                        tracked_source_id=tracked_source_id,
                        tracked_entry_id=entry_id,
                    )
                except Exception:
                    pass  # Non-critical — memory store is primary for now

                # Minimal quality → treat as failed (nothing useful to import)
                if preview.parse_quality == "minimal":
                    failed_count += 1
                    new_count -= 1
                    update_tracked_source_entry_status(
                        session,
                        entry_id,
                        "failed",
                        error_message=(
                            preview.warning_messages[0][:500]
                            if preview.warning_messages
                            else "页面解析质量极低，无法提取有效内容"
                        ),
                    )
                    continue

                update_tracked_source_entry_status(
                    session,
                    entry_id,
                    "preview_ready",
                    preview_id=preview.preview_id,
                    detected_youtube_video_id=preview.detected_youtube_video_id,
                    content_hash=preview.content_hash or None,
                )
            except Exception as e:
                failed_count += 1
                logger.warning(
                    "Preview generation failed for entry %s: %s", entry.url, e,
                )
                update_tracked_source_entry_status(
                    session,
                    entry_id,
                    "failed",
                    error_message=str(e)[:500],
                )

        # Step 3: Update tracked source stats
        total_discovered = new_count + existing_count + failed_count
        imported_count = session.query(func.count(TSE.id)).filter_by(
            tracked_source_id=tracked_source_id, status="imported",
        ).scalar() or 0

        ts_obj = session.query(TrackedSource).filter_by(id=tracked_source_id).first()
        if ts_obj:
            ts_obj.entries_discovered_count = total_discovered
            ts_obj.entries_imported_count = imported_count
            ts_obj.last_checked_at = datetime.now()
            ts_obj.last_success_at = datetime.now()
            ts_obj.status = "active" if failed_count == 0 else "degraded"
            ts_obj.last_error = ""

        session.commit()
    finally:
        session.close()

    return {
        "success": True,
        "message": (
            f"发现 {new_count} 条新内容，{existing_count} 条已发现"
            + (f"，{failed_count} 条失败" if failed_count > 0 else "")
        ),
        "total_on_page": len(entries),
        "new_entries": new_count,
        "existing_entries": existing_count,
        "failed_entries": failed_count,
        "preview_ids": preview_ids,
    }


def import_tracked_source_entries(
    tracked_source_id: int,
    entry_ids: list[int],
    action,
    vault_path: Path,
    preview_store: dict,
) -> dict:
    """Batch import selected tracked source entries.

    1. For each entry: pop preview from preview_store
    2. execute_import_action(preview, action, vault_path)
    3. Update entry status to 'imported' or 'failed'

    Returns:
        {success, total, imported, failed, results: list[dict]}
    """
    from sqlalchemy import func

    from signalvault.db.models import TrackedSource
    from signalvault.db.models import TrackedSourceEntry as TSE
    from signalvault.db.repository import (
        get_tracked_source_entry,
        update_tracked_source_entry_status,
    )
    from signalvault.db.session import get_session, init_db
    from signalvault.sources.import_preview import execute_import_action

    init_db()
    session = get_session()

    imported = 0
    failed = 0
    results: list[dict] = []

    try:
        for entry_id in entry_ids:
            entry = get_tracked_source_entry(session, entry_id)
            if not entry:
                results.append({
                    "entry_id": entry_id, "success": False,
                    "message": "条目不存在",
                })
                failed += 1
                continue

            preview_id = entry.get("preview_id", "")
            preview = preview_store.pop(preview_id, None)

            if preview is None:
                results.append({
                    "entry_id": entry_id,
                    "title": entry.get("title", ""),
                    "success": False,
                    "message": "预览已过期，请重新刷新",
                })
                update_tracked_source_entry_status(
                    session, entry_id, "failed",
                    error_message="预览已过期",
                )
                failed += 1
                continue

            try:
                result = execute_import_action(preview, action, vault_path)
                if result.get("success"):
                    update_tracked_source_entry_status(session, entry_id, "imported")
                    imported += 1
                    # P3-A: Dual-confirm in ingest_jobs
                    try:
                        from signalvault.sources.ingest_jobs import (
                            IngestJobManager,
                        )
                        IngestJobManager.confirm_job(
                            preview_id, action=action.value if hasattr(action, 'value') else str(action),
                            action_label=str(action),
                            result_path=result.get("path", ""),
                            result_message=result.get("message", ""),
                        )
                    except Exception:
                        pass
                    results.append({
                        "entry_id": entry_id,
                        "title": entry.get("title", ""),
                        "success": True,
                        "message": result.get("message", ""),
                    })
                else:
                    update_tracked_source_entry_status(
                        session, entry_id, "failed",
                        error_message=result.get("message", "导入失败"),
                    )
                    failed += 1
                    results.append({
                        "entry_id": entry_id,
                        "title": entry.get("title", ""),
                        "success": False,
                        "message": result.get("message", "导入失败"),
                    })
            except Exception as e:
                update_tracked_source_entry_status(
                    session, entry_id, "failed",
                    error_message=str(e)[:500],
                )
                failed += 1
                results.append({
                    "entry_id": entry_id,
                    "title": entry.get("title", ""),
                    "success": False,
                    "message": str(e)[:200],
                })

        # Update import count on tracked source
        imported_count = session.query(func.count(TSE.id)).filter_by(
            tracked_source_id=tracked_source_id, status="imported",
        ).scalar() or 0
        ts_obj = session.query(TrackedSource).filter_by(id=tracked_source_id).first()
        if ts_obj:
            ts_obj.entries_imported_count = imported_count

        session.commit()
    finally:
        session.close()

    return {
        "success": True,
        "total": len(entry_ids),
        "imported": imported,
        "failed": failed,
        "results": results,
    }
