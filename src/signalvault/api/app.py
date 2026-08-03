"""FastAPI app factory."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

API_PREFIX = "/api"


def _start_scheduler() -> None:
    """Start the desktop scheduler if automation is enabled."""
    import logging
    _log = logging.getLogger(__name__)
    try:
        from signalvault.settings.service import get_config_service
        svc = get_config_service()
        enabled = svc.get_bool("automation.enabled")
        if enabled is False:
            _log.info("Automation disabled in config, scheduler not started")
            return

        from signalvault.services.desktop_scheduler import get_desktop_scheduler
        scheduler = get_desktop_scheduler()
        scheduler.register_default_tasks()
        scheduler.start()
        _log.info("DesktopScheduler started with default tasks")
    except Exception:
        _log.exception("Failed to start DesktopScheduler")


def _stop_scheduler() -> None:
    """Stop the desktop scheduler gracefully."""
    import logging
    _log = logging.getLogger(__name__)
    try:
        from signalvault.services.desktop_scheduler import get_desktop_scheduler
        scheduler = get_desktop_scheduler()
        scheduler.stop()
        _log.info("DesktopScheduler stopped")
    except Exception:
        _log.exception("Failed to stop DesktopScheduler")


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from signalvault.db.session import init_db
        init_db()

        # M4-C: start desktop scheduler for background automation
        _start_scheduler()

        yield

        # M4-C: stop desktop scheduler before background threads
        _stop_scheduler()

        # M2: graceful shutdown of background threads
        from signalvault.services.job_service import shutdown_background_jobs
        shutdown_background_jobs(timeout=5.0)

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
