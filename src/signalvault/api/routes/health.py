"""GET /api/health"""

from fastapi import APIRouter

from signalvault.api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> dict:
    return {"status": "ok", "app": "signalvault", "database": "ok"}
