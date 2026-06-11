"""GET /api/search"""

from fastapi import APIRouter, Query

from podcast_research.api.schemas import SearchResponse
from podcast_research.db.repository import search_reports
from podcast_research.db.session import get_session, init_db

router = APIRouter(tags=["search"])


def _get_session():
    init_db()
    return get_session()


@router.get("/search", response_model=SearchResponse)
def api_search(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    session = _get_session()
    try:
        results = search_reports(session, q, limit=limit)
    finally:
        session.close()

    return {"keyword": q, "results": results, "count": len(results)}
