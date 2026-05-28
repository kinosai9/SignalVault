"""GET /api/health"""

from fastapi import APIRouter

from podcast_research.api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> dict:
    return {"status": "ok", "app": "podcast_research", "database": "ok"}
