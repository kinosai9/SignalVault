"""FastAPI app factory."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

API_PREFIX = "/api"


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from podcast_research.db.session import init_db
        init_db()
        yield

    app = FastAPI(
        title="投资音视频研究助手 API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # JSON API routes
    from podcast_research.api.routes.health import router as health_router
    from podcast_research.api.routes.reports import router as reports_router
    from podcast_research.api.routes.search import router as search_router

    app.include_router(health_router, prefix=API_PREFIX)
    app.include_router(reports_router, prefix=API_PREFIX)
    app.include_router(search_router, prefix=API_PREFIX)

    # P1-C: HTML page routes
    from podcast_research.web.routes import router as web_router

    app.include_router(web_router)

    # Static files
    static_dir = Path(__file__).parent.parent / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app
