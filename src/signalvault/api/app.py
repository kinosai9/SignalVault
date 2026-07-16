"""FastAPI app factory."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

API_PREFIX = "/api"


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from signalvault.db.session import init_db
        init_db()
        yield

    app = FastAPI(
        title="SignalVault 多源投资研究助手 API",
        description="SignalVault 的只读研究数据 API。用于访问报告、观点、实体、来源和统一搜索结果。",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        lifespan=lifespan,
    )

    # JSON API routes
    from signalvault.api.routes.health import router as health_router
    from signalvault.api.routes.reports import router as reports_router
    from signalvault.api.routes.search import router as search_router

    app.include_router(health_router, prefix=API_PREFIX)
    app.include_router(reports_router, prefix=API_PREFIX)
    app.include_router(search_router, prefix=API_PREFIX)

    # P1-C: HTML page routes
    from signalvault.web.routes import router as web_router

    app.include_router(web_router)

    # C1-C: Settings & integration JSON API routes
    from signalvault.web.routes_settings import router as settings_router

    app.include_router(settings_router)

    # Static files
    static_dir = Path(__file__).parent.parent / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app
