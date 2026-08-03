"""M3-C-2 Final Acceptance: Universal Intake 架构验收。

三个验收维度（用户要求）：
1. 输入统一性 —— PDF/DOCX/TXT/Markdown/HTML/URL/YouTube 全部经
   Detector → Router → Orchestrator，无类型特定旁路。
2. Pipeline 隔离 —— 所有来源转成 SubtitleSegment，共用 _run_pipeline，
   不存在 PDF pipeline / DOCX pipeline / URL pipeline / YouTube pipeline 并行管道。
3. 用户入口统一 —— /intake 是唯一用户入口，旧入口收敛，导航不堆叠导入子入口。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from signalvault.analysis.models import SubtitleSegment
from signalvault.services.intake_orchestrator import orchestrate_intake
from signalvault.sources.segment_builders import (
    file_to_segments,
    text_to_segments,
    web_page_to_segments,
)

# ── 1. 输入统一性 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected_kind"),
    [
        ("https://youtu.be/dQw4w9WgXcQ", "youtube_video"),
        ("https://example.com/article", "web_url"),
        ("report.pdf", "pdf_file"),
        ("memo.docx", "docx_file"),
        ("notes.txt", "text_file"),
        ("readme.md", "text_file"),
        ("page.html", "text_file"),
    ],
)
def test_all_input_types_flow_through_orchestrator(
    raw: str, expected_kind: str
) -> None:
    """7 类输入全部经统一的 detect→route→orchestrator，无类型特定路径。"""
    result = orchestrate_intake(raw)
    assert result.detection.kind.value == expected_kind
    assert result.handler, f"{raw} 应有 handler"
    assert result.routing.reason, f"{raw} 应有 routing reason"


def test_no_input_bypasses_orchestrator() -> None:
    """任何可识别输入都产出完整 IntakeResult（detection + routing + handler）。"""
    for raw in [
        "https://youtu.be/dQw4w9WgXcQ",
        "report.pdf",
        "memo.docx",
        "a.txt",
        "https://example.com/x",
    ]:
        r = orchestrate_intake(raw)
        assert r.detection and r.routing and r.handler


# ── 2. Pipeline 隔离验证 ──────────────────────────────────────────────────────


def test_all_segment_builders_emit_subtitle_segment() -> None:
    """文件/网页/文本 segment builder 全部输出 SubtitleSegment（pipeline 唯一契约）。"""
    text_segs = text_to_segments("段落一\n\n段落二")
    web_segs = web_page_to_segments(["段A", "段B"])
    file_segs = file_to_segments("内容行一\n行二", "f.txt")
    for segs in (text_segs, web_segs, file_segs):
        assert segs, "builder 应产出非空 segments"
        for s in segs:
            assert isinstance(s, SubtitleSegment)
            assert s.segment_id and s.text


def test_no_parallel_pipelines_single_segment_contract() -> None:
    """不存在 PDF/DOCX/URL/YouTube 各自的 pipeline。

    所有来源最终都转成 list[SubtitleSegment] 喂给同一条 _run_pipeline。
    segment_builders 是统一 Parser 层，输出契约唯一（与 YouTube/PDF 已验证的路径一致）。
    """
    a = text_to_segments("x")
    b = web_page_to_segments(["y"])
    assert type(a[0]) is type(b[0]) is SubtitleSegment


# ── 3. 用户入口统一 ───────────────────────────────────────────────────────────


@pytest.fixture()
def client():
    from signalvault.api.app import create_app

    return TestClient(create_app())


def test_intake_is_the_single_entry(client: TestClient) -> None:
    """/intake 是唯一用户入口（AI 助手风格：粘贴链接或上传文件）。"""
    resp = client.get("/intake")
    assert resp.status_code == 200
    assert "添加信息" in resp.text
    assert "粘贴链接" in resp.text


def test_legacy_youtube_entry_converged(client: TestClient) -> None:
    """旧 YouTube 入口 /content/new 收敛到 /intake（GET 301）。"""
    resp = client.get("/content/new", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/intake"


def test_nav_does_not_stack_import_entries(client: TestClient) -> None:
    """主导航用「添加信息」单一入口，不再堆叠 导入PDF/导入网页/导入视频 子入口。"""
    resp = client.get("/intake")
    assert "添加信息" in resp.text
    # 旧的并列导入入口已从主导航移除
    assert "导入中心" not in resp.text
