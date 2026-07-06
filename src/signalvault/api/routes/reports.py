"""GET /api/reports/*, /api/entities, /api/targets, /api/sources"""

from fastapi import APIRouter, HTTPException, Query

from signalvault.api.schemas import (
    EntityItem,
    ReportDetailResponse,
    ReportItem,
    ReportListResponse,
    SourceItem,
    TargetItem,
)
from signalvault.db.repository import (
    get_report_detail,
    list_entities,
    list_reports,
    list_sources,
    list_targets,
)
from signalvault.db.session import get_session, init_db

router = APIRouter(tags=["reports"])


def _get_session():
    init_db()
    return get_session()


@router.get("/reports", response_model=ReportListResponse)
def api_list_reports(
    limit: int = Query(20, ge=1, le=100),
    source: str | None = Query(None, alias="source"),
) -> dict:
    session = _get_session()
    try:
        rows = list_reports(session, limit=limit, source_type=source)
    finally:
        session.close()

    items = [
        ReportItem(
            id=r["id"],
            created_at=r["created_at"],
            source_type=r["source_type"],
            title=r["title"],
            video_id=r["video_id"],
            source_url=r["source_url"],
            focus_areas=r["focus_areas"],
            analysis_depth=r["analysis_depth"],
            view_count=r["view_count"],
            entity_count=r["entity_count"],
        )
        for r in rows
    ]
    return {"items": items, "count": len(items)}


@router.get("/reports/{report_id}", response_model=ReportDetailResponse)
def api_get_report(report_id: int) -> dict:
    session = _get_session()
    try:
        detail = get_report_detail(session, report_id)
    finally:
        session.close()

    if not detail:
        raise HTTPException(status_code=404, detail=f"报告 ID={report_id} 不存在")

    return detail


@router.get("/reports/{report_id}/views")
def api_get_report_views(report_id: int) -> dict:
    session = _get_session()
    try:
        detail = get_report_detail(session, report_id)
    finally:
        session.close()

    if not detail:
        raise HTTPException(status_code=404, detail=f"报告 ID={report_id} 不存在")

    return {"report_id": report_id, "views": detail["views"], "count": len(detail["views"])}


@router.get("/reports/{report_id}/signals")
def api_get_report_signals(report_id: int) -> dict:
    session = _get_session()
    try:
        detail = get_report_detail(session, report_id)
    finally:
        session.close()

    if not detail:
        raise HTTPException(status_code=404, detail=f"报告 ID={report_id} 不存在")

    return {"report_id": report_id, "signals": detail["signals"], "count": len(detail["signals"])}


@router.get("/entities")
def api_list_entities(
    type: str | None = Query(None, alias="type"),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    session = _get_session()
    try:
        rows = list_entities(session, entity_type=type, limit=limit)
    finally:
        session.close()

    items = [EntityItem(**r) for r in rows]
    return {"items": items, "count": len(items)}


@router.get("/targets")
def api_list_targets(
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    session = _get_session()
    try:
        rows = list_targets(session, limit=limit)
    finally:
        session.close()

    items = [TargetItem(**r) for r in rows]
    return {"items": items, "count": len(items)}


@router.get("/sources")
def api_list_sources() -> dict:
    session = _get_session()
    try:
        rows = list_sources(session)
    finally:
        session.close()

    items = [SourceItem(**r) for r in rows]
    return {"items": items, "count": len(items)}
