"""P1-C: HTML 页面路由 — GET / /reports /reports/{id} /search"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader

from podcast_research.db.repository import (
    get_report_detail,
    list_reports,
    search_reports,
)
from podcast_research.db.session import get_session, init_db

router = APIRouter(tags=["web"])

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=True,
    cache_size=0,
)


def _render(name: str, context: dict, status_code: int = 200) -> HTMLResponse:
    template = _env.get_template(name)
    return HTMLResponse(template.render(context), status_code=status_code)


def _get_session():
    init_db()
    return get_session()


@router.get("/")
def page_index():
    return RedirectResponse(url="/reports", status_code=302)


@router.get("/reports")
def page_reports(
    request: Request,
    limit: int = 50,
    source: str | None = None,
):
    session = _get_session()
    try:
        reports = list_reports(session, limit=limit, source_type=source)
    finally:
        session.close()
    return _render(
        "reports_list.html",
        {"request": request, "reports": reports},
    )


@router.get("/reports/{report_id}")
def page_report_detail(request: Request, report_id: int):
    session = _get_session()
    try:
        report = get_report_detail(session, report_id)
    finally:
        session.close()

    if not report:
        return _render(
            "error.html",
            {"request": request, "status_code": 404, "detail": f"报告 ID={report_id} 不存在"},
            status_code=404,
        )

    return _render(
        "report_detail.html",
        {"request": request, "report": report},
    )


@router.get("/search")
def page_search(request: Request, q: str = ""):
    if not q.strip():
        return _render(
            "search.html",
            {"request": request, "q": "", "results": [], "count": 0},
        )

    session = _get_session()
    try:
        results = search_reports(session, q.strip(), limit=20)
    finally:
        session.close()

    return _render(
        "search.html",
        {
            "request": request,
            "q": q.strip(),
            "results": results,
            "count": len(results),
        },
    )
