"""Markdown 报告生成测试。"""

from podcast_research.analysis.models import ExtractionResult
from podcast_research.llm.mock_provider import MockLLMProvider

# 用包含投资关键词的测试文本模拟真实字幕
MOCK_SEGMENTS = (
    "[00:00:01.000-00:00:10.000] 嘉宾A：我认为宁德时代在储能赛道是看多的方向。\n"
    "[00:00:11.000-00:00:20.000] 不过海外政策风险也需要警惕。\n"
    "[00:00:21.000-00:00:30.000] 港股红利估值偏低，适合防御配置。\n"
    "[00:00:31.000-00:00:40.000] 嘉宾B：我不同意，港股红利的吸引力已经减弱。\n"
)
MOCK_TEXT = (
    "嘉宾A：我认为宁德时代在储能赛道是看多的方向。"
    "不过海外政策风险也需要警惕。"
    "港股红利估值偏低，适合防御配置。"
    "嘉宾B：我不同意，港股红利的吸引力已经减弱。"
)


def test_mock_provider_extract_facts() -> None:
    provider = MockLLMProvider()
    result = provider.extract_facts(MOCK_TEXT, MOCK_SEGMENTS)
    assert isinstance(result, ExtractionResult)
    assert len(result.investment_views) > 0
    assert len(result.mentioned_entities) > 0
    # 验证观点来源于实际输入内容
    for v in result.investment_views:
        assert v.target_name in MOCK_TEXT


def test_mock_provider_empty_input() -> None:
    provider = MockLLMProvider()
    result = provider.extract_facts("普通文字没有投资内容", "[]")
    assert isinstance(result, ExtractionResult)
    # 无投资关键词时应产出 0 条观点
    assert len(result.investment_views) == 0


def test_mock_provider_render_report() -> None:
    provider = MockLLMProvider()
    extraction = provider.extract_facts(MOCK_TEXT, MOCK_SEGMENTS)
    report = provider.render_report(extraction)
    assert "免责声明" in report
    assert "核心观点矩阵" in report
    assert "风险提示" in report
    assert "待验证信号" in report


def test_report_includes_view_matrix() -> None:
    provider = MockLLMProvider()
    extraction = provider.extract_facts(MOCK_TEXT, MOCK_SEGMENTS)
    report = provider.render_report(extraction)
    for v in extraction.investment_views:
        assert v.target_name in report
        assert (v.view_direction_label or v.view_direction) in report


def test_report_shows_youtube_source_info() -> None:
    """报告应展示 YouTube 数据来源信息（P2-A2.1: 字段化展示）。"""
    provider = MockLLMProvider()
    extraction = ExtractionResult(
        source_info={
            "source_type": "youtube",
            "source_url": "https://www.youtube.com/watch?v=test123",
            "video_id": "test123",
            "language": "zh-Hans",
            "is_generated": False,
            "transcript_segment_count": 100,
            "channel_name": "",
            "title": "",
            "fetched_at": "2026-05-27T10:00:00",
        },
    )
    report = provider.render_report(extraction)
    assert "数据来源" in report
    assert "视频 ID" in report
    assert "test123" in report
    assert "zh-Hans" in report
    assert "100" in report
    assert "视频链接" in report


def test_report_shows_local_source_info() -> None:
    """报告应展示本地字幕文件来源信息。"""
    provider = MockLLMProvider()
    extraction = ExtractionResult(
        source_info={
            "source_type": "local",
            "source_path": "data/subtitles/sample.srt",
        },
    )
    report = provider.render_report(extraction)
    assert "数据来源" in report
    assert "本地字幕文件" in report
    assert "sample.srt" in report


def test_report_no_source_info_still_renders() -> None:
    """没有 source_info 时报告仍正常渲染。"""
    provider = MockLLMProvider()
    extraction = ExtractionResult()
    report = provider.render_report(extraction)
    assert "免责声明" in report
    assert "执行摘要" in report


def test_mock_english_zero_views_valid_report() -> None:
    """英文字幕在 mock provider 下 0 观点仍生成合法报告。"""
    provider = MockLLMProvider()
    english_text = "The Federal Reserve raised interest rates by 25 basis points today."
    english_segments = "[00:00:01.000-00:00:10.000] The Federal Reserve raised interest rates by 25 basis points today."
    extraction = provider.extract_facts(english_text, english_segments)
    extraction.source_info = {
        "source_type": "youtube",
        "video_id": "test_en",
        "language": "en",
        "transcript_segment_count": 1,
    }
    # 英文内容 mock 下应为 0 观点
    assert len(extraction.investment_views) == 0
    # 但仍能生成合法报告
    report = provider.render_report(extraction)
    assert "免责声明" in report
    assert "执行摘要" in report
    assert "0" in report  # 0 条观点
    assert "数据来源" in report
    assert "视频 ID" in report
