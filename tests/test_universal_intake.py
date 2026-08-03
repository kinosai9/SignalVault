"""M3-C-2b: Universal Intake — Detector / Router / Segment Builders 测试。

测试重点（约束 4）：
- detector 输入覆盖（七类输入 + 边界）
- router 成本边界（allow_auto_analyze 红线 + 动作组合）
- segment builder 统一输出（SubtitleSegment + metadata）
"""

from __future__ import annotations

from signalvault.analysis.models import SubtitleSegment
from signalvault.sources.detector import DetectedKind, detect_kind
from signalvault.sources.models import ActionEnum, ConflictInfo
from signalvault.sources.router import route_action
from signalvault.sources.segment_builders import (
    file_to_segments,
    text_to_segments,
    web_page_to_segments,
)

# ── Detector 输入覆盖 ─────────────────────────────────────────────────────────


class TestDetector:
    def test_youtube_video_url(self) -> None:
        r = detect_kind("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert r.kind == DetectedKind.youtube_video
        assert r.confidence == 1.0
        assert r.metadata["video_id"] == "dQw4w9WgXcQ"

    def test_youtu_be_short_link(self) -> None:
        r = detect_kind("https://youtu.be/dQw4w9WgXcQ")
        assert r.kind == DetectedKind.youtube_video
        assert r.metadata["video_id"] == "dQw4w9WgXcQ"

    def test_youtube_channel_url(self) -> None:
        r = detect_kind("https://www.youtube.com/@somechannel")
        assert r.kind == DetectedKind.youtube_channel
        assert "channel_handle" in r.metadata

    def test_generic_web_url(self) -> None:
        r = detect_kind("https://example.com/article/123")
        assert r.kind == DetectedKind.web_url
        assert r.metadata["domain"] == "example.com"

    def test_html_url_is_web_url_not_text_file(self) -> None:
        """URL 优先于扩展名：.html 网页是 web_url，不是 text_file。"""
        r = detect_kind("https://example.com/page.html")
        assert r.kind == DetectedKind.web_url

    def test_pdf_file(self) -> None:
        r = detect_kind("report.pdf")
        assert r.kind == DetectedKind.pdf_file
        assert r.metadata["extension"] == ".pdf"

    def test_docx_file(self) -> None:
        r = detect_kind("memo.docx")
        assert r.kind == DetectedKind.docx_file

    def test_text_files(self) -> None:
        for name, ext in [("a.txt", ".txt"), ("b.md", ".md"), ("c.html", ".html"), ("d.htm", ".htm")]:
            r = detect_kind(name)
            assert r.kind == DetectedKind.text_file, f"{name} should be text_file"
            assert r.metadata["extension"] == ext

    def test_local_path_with_extension(self) -> None:
        r = detect_kind("/home/user/docs/report.pdf")
        assert r.kind == DetectedKind.pdf_file

    def test_unknown_empty(self) -> None:
        assert detect_kind("").kind == DetectedKind.unknown
        assert detect_kind("   ").kind == DetectedKind.unknown

    def test_unknown_garbage(self) -> None:
        r = detect_kind("just some text without structure")
        assert r.kind == DetectedKind.unknown

    def test_unsupported_extension(self) -> None:
        r = detect_kind("archive.zip")
        assert r.kind == DetectedKind.unknown

    def test_source_value_preserved(self) -> None:
        r = detect_kind("https://example.com/x")
        assert r.source_value == "https://example.com/x"


# ── Router 成本边界 ───────────────────────────────────────────────────────────


class TestRouterCostBoundary:
    def _yt(self):
        return detect_kind("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_no_auto_analyze_by_default(self) -> None:
        """成本红线：默认 allow_auto_analyze=False → should_analyze 永远 False。"""
        d = route_action(self._yt(), parse_quality="good")
        assert d.should_analyze is False

    def test_auto_analyze_requires_explicit_opt_in(self) -> None:
        """显式开启 + good + 无冲突 → should_analyze=True。"""
        d = route_action(self._yt(), parse_quality="good", allow_auto_analyze=True)
        assert d.should_analyze is True

    def test_auto_analyze_blocked_by_minimal_quality(self) -> None:
        d = route_action(self._yt(), parse_quality="minimal", allow_auto_analyze=True)
        assert d.should_analyze is False
        assert d.ignore is True

    def test_auto_analyze_blocked_by_degraded_quality(self) -> None:
        d = route_action(self._yt(), parse_quality="degraded", allow_auto_analyze=True)
        assert d.should_analyze is False

    def test_auto_analyze_blocked_by_conflict(self) -> None:
        blocker = ConflictInfo(conflict_type="same_content_hash", severity="blocker")
        d = route_action(self._yt(), conflicts=[blocker], allow_auto_analyze=True)
        assert d.should_analyze is False

    def test_analyze_path_available_even_when_auto_off(self) -> None:
        """analyze 路径可用性独立于 should_analyze：用户始终可手动选分析。"""
        d = route_action(self._yt(), parse_quality="good", allow_auto_analyze=False)
        assert d.analyze is True  # 路径可用
        assert d.should_analyze is False  # 但系统不建议自动
        assert ActionEnum.analyze in d.available_actions


class TestRouterComposition:
    """约束 2：archive + analyze 可组合，互不锁定。"""

    def test_youtube_both_archive_and_analyze(self) -> None:
        r = detect_kind("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        d = route_action(r, parse_quality="good")
        assert d.archive is True
        assert d.analyze is True  # 组合：既可归档也可分析

    def test_web_url_archive_only(self) -> None:
        r = detect_kind("https://example.com/article")
        d = route_action(r, parse_quality="good")
        assert d.archive is True
        assert d.analyze is False  # web_url 不在 _ANALYZABLE_KINDS

    def test_requires_confirmation_when_auto_off(self) -> None:
        r = detect_kind("https://example.com/article")
        d = route_action(r, parse_quality="good", allow_auto_analyze=False)
        assert d.requires_confirmation is True

    def test_no_confirmation_when_auto_and_clean(self) -> None:
        """自动模式 + 无冲突 + good → 可免确认（自动归档）。"""
        r = detect_kind("https://example.com/article")
        d = route_action(r, parse_quality="good", allow_auto_analyze=True)
        assert d.requires_confirmation is False

    def test_blocker_forces_confirmation_and_review(self) -> None:
        r = detect_kind("report.pdf")
        blocker = ConflictInfo(conflict_type="same_content_hash", severity="blocker")
        d = route_action(r, conflicts=[blocker], allow_auto_analyze=True)
        assert d.requires_confirmation is True
        assert d.review is True

    def test_reason_is_populated(self) -> None:
        r = detect_kind("report.pdf")
        d = route_action(r, parse_quality="good")
        assert d.reason  # 非空

    def test_unknown_kind_ignored(self) -> None:
        r = detect_kind("garbage")
        d = route_action(r)
        assert d.ignore is True
        assert d.archive is False
        assert d.analyze is False


class TestRouterAutoMode:
    """M3-C-3c: auto_mode 成本分级（off / high_value / all）。"""

    def test_high_value_only_analyzes_high_value_kinds(self) -> None:
        yt = detect_kind("https://youtu.be/dQw4w9WgXcQ")
        assert (
            route_action(yt, parse_quality="good", auto_mode="high_value").should_analyze
            is True
        )
        docx = detect_kind("memo.docx")
        assert (
            route_action(docx, parse_quality="good", auto_mode="high_value").should_analyze
            is False
        )

    def test_all_analyzes_every_analyzable_kind(self) -> None:
        docx = detect_kind("memo.docx")
        assert (
            route_action(docx, parse_quality="good", auto_mode="all").should_analyze is True
        )

    def test_off_never_auto_analyzes(self) -> None:
        yt = detect_kind("https://youtu.be/dQw4w9WgXcQ")
        assert (
            route_action(yt, parse_quality="good", auto_mode="off").should_analyze is False
        )

    def test_high_value_blocked_by_minimal_quality(self) -> None:
        yt = detect_kind("https://youtu.be/dQw4w9WgXcQ")
        assert (
            route_action(yt, parse_quality="minimal", auto_mode="high_value").should_analyze
            is False
        )


# ── Segment Builder 统一输出 ──────────────────────────────────────────────────


class TestSegmentBuilders:
    def test_text_to_segments_splits_paragraphs(self) -> None:
        text = "第一段内容。\n\n第二段内容。\n\n第三段内容。"
        segs = text_to_segments(text, source_id="doc")
        assert len(segs) == 3
        assert all(isinstance(s, SubtitleSegment) for s in segs)
        assert segs[0].text == "第一段内容。"
        assert segs[0].segment_id == "doc_block_0"

    def test_text_to_segments_line_fallback(self) -> None:
        """无段落分隔（单段多行）时按行切分。"""
        segs = text_to_segments("行一\n行二\n行三", source_id="t")
        assert len(segs) == 3

    def test_text_to_segments_metadata_url_and_file(self) -> None:
        segs = text_to_segments(
            "内容", source_id="x", source_url="https://a.com", source_file="a.txt"
        )
        assert segs[0].metadata["url"] == "https://a.com"
        assert segs[0].metadata["file"] == "a.txt"
        assert segs[0].metadata["source"] == "x"

    def test_text_to_segments_empty(self) -> None:
        assert text_to_segments("") == []
        assert text_to_segments("   ") == []

    def test_web_page_to_segments(self) -> None:
        segs = web_page_to_segments(["段A", "段B"], source_url="https://x.com", title="标题")
        assert len(segs) == 2
        assert segs[0].metadata["url"] == "https://x.com"
        assert segs[0].metadata["title"] == "标题"

    def test_web_page_to_segments_skips_empty(self) -> None:
        segs = web_page_to_segments(["段A", "", "  ", "段B"])
        assert len(segs) == 2

    def test_file_to_segments_carries_filename(self) -> None:
        segs = file_to_segments("段落一", "report.txt")
        assert segs[0].metadata["file"] == "report.txt"
        assert segs[0].metadata["source"] == "file"

    def test_segments_compatible_with_pipeline_contract(self) -> None:
        """输出是合法 SubtitleSegment（pipeline 契约），核心字段齐全。"""
        segs = text_to_segments("测试内容", source_id="c")
        for s in segs:
            assert s.segment_id
            assert isinstance(s.text, str)
            assert hasattr(s, "start_time")
            assert hasattr(s, "end_time")
            assert isinstance(s.metadata, dict)

    def test_subtitle_segment_metadata_default_empty(self) -> None:
        """向后兼容：不传 metadata 的 SubtitleSegment 仍有空 dict。"""
        s = SubtitleSegment(segment_id="x", start_time="", end_time="", text="t")
        assert s.metadata == {}
