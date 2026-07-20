"""GET /api/health"""

from fastapi import APIRouter

from signalvault import __version__
from signalvault.api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> dict:
    return {
        "status": "ok",
        "app": "signalvault",
        "version": __version__,
        "database": "ok",
    }
