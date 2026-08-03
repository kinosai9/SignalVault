"""M3-C-2c: Intake Orchestrator 测试。

验证 detect → route → handler 映射的编排逻辑。
"""

from __future__ import annotations

from signalvault.services.intake_orchestrator import (
    IntakeHandler,
    handler_label,
    orchestrate_intake,
)
from signalvault.sources.detector import DetectedKind


def test_youtube_routes_to_analyze() -> None:
    r = orchestrate_intake("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert r.handler == IntakeHandler.YOUTUBE_ANALYZE
    assert r.target_route == "/content/new"
    assert r.detection.kind == DetectedKind.youtube_video


def test_url_routes_to_import() -> None:
    r = orchestrate_intake("https://example.com/article")
    assert r.handler == IntakeHandler.URL_IMPORT
    assert r.target_route == "/sources/import"


def test_pdf_routes_to_file() -> None:
    r = orchestrate_intake("report.pdf")
    assert r.handler == IntakeHandler.FILE_IMPORT
    assert r.target_route == "/sources/files/import"


def test_docx_routes_to_file() -> None:
    r = orchestrate_intake("memo.docx")
    assert r.handler == IntakeHandler.FILE_IMPORT


def test_text_routes_to_file() -> None:
    r = orchestrate_intake("notes.md")
    assert r.handler == IntakeHandler.FILE_IMPORT


def test_unknown_ignored() -> None:
    r = orchestrate_intake("garbage input")
    assert r.handler == IntakeHandler.IGNORE
    assert r.routing.ignore is True


def test_routing_auto_analyze_passed_through() -> None:
    """成本红线通过 orchestrator 传递：开启时 should_analyze=True。"""
    r = orchestrate_intake(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ", allow_auto_analyze=True
    )
    assert r.routing.should_analyze is True


def test_routing_auto_analyze_off_by_default() -> None:
    """默认不开启 → should_analyze=False（绝不默认自动花真钱）。"""
    r = orchestrate_intake("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert r.routing.should_analyze is False


def test_handler_label() -> None:
    assert handler_label(IntakeHandler.YOUTUBE_ANALYZE) == "YouTube 视频分析"
    assert handler_label(IntakeHandler.URL_IMPORT) == "网页导入"
    assert handler_label(IntakeHandler.IGNORE) == "无法识别"


def test_detection_and_routing_both_populated() -> None:
    """orchestrator 同时产出 detection 与 routing，供入口层展示。"""
    r = orchestrate_intake("https://example.com/x")
    assert r.detection.kind == DetectedKind.web_url
    assert r.routing.archive is True  # web_url 可归档
    assert r.routing.reason  # 有判定理由
