"""YouTubeTranscriptAdapter mock 测试：不调用真实 YouTube API。"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from podcast_research.adapters.base import TranscriptResult
from podcast_research.adapters.youtube_transcript import YouTubeTranscriptAdapter

# 模拟 youtube-transcript-api 返回的 transcript 数据
MOCK_TRANSCRIPT_DATA = [
    {"text": "大家好，今天我们来聊聊AI投资", "start": 0.0, "duration": 3.5},
    {"text": "NVIDIA的GPU在AI训练中非常重要", "start": 3.5, "duration": 4.0},
    {"text": "我认为AI算力需求会持续增长", "start": 7.5, "duration": 3.0},
]


def _make_mock_transcript_fetch() -> MagicMock:
    """创建模拟的 transcript fetch 对象。"""
    mock_transcript = MagicMock()
    mock_transcript.language_code = "zh-Hans"
    mock_transcript.is_generated = False
    mock_transcript.fetch.return_value = MOCK_TRANSCRIPT_DATA
    mock_transcript.find_transcript = MagicMock(return_value=mock_transcript)
    return mock_transcript


def _make_mock_transcript_list(mock_transcript: MagicMock) -> MagicMock:
    """创建模拟的 transcript_list 对象。"""
    mock_list = MagicMock()
    mock_list.find_transcript.return_value = mock_transcript
    # 使 transcript_list 可迭代
    mock_list.__iter__ = MagicMock(return_value=iter([mock_transcript]))
    return mock_list


class TestYouTubeTranscriptAdapterFetch:
    """测试 fetch 方法，mock youtube-transcript-api。"""

    @patch("podcast_research.adapters.youtube_transcript.YouTubeTranscriptApi")
    def test_fetch_with_url(self, mock_api_class: MagicMock) -> None:
        mock_transcript = _make_mock_transcript_fetch()
        mock_list = _make_mock_transcript_list(mock_transcript)
        mock_api_instance = mock_api_class.return_value
        mock_api_instance.list.return_value = mock_list

        adapter = YouTubeTranscriptAdapter()
        result = adapter.fetch(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        assert result.source_type == "youtube"
        assert result.video_id == "dQw4w9WgXcQ"
        assert result.language == "zh-Hans"
        assert len(result.segments) == 3
        assert result.segments[0].text == "大家好，今天我们来聊聊AI投资"
        assert result.segments[0].start_time.startswith("00:00:00")
        assert result.metadata["is_generated"] is False

    @patch("podcast_research.adapters.youtube_transcript.YouTubeTranscriptApi")
    def test_fetch_with_video_id(self, mock_api_class: MagicMock) -> None:
        mock_transcript = _make_mock_transcript_fetch()
        mock_list = _make_mock_transcript_list(mock_transcript)
        mock_api_instance = mock_api_class.return_value
        mock_api_instance.list.return_value = mock_list

        adapter = YouTubeTranscriptAdapter()
        result = adapter.fetch(video_id="dQw4w9WgXcQ")

        assert result.video_id == "dQw4w9WgXcQ"
        assert result.source_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_fetch_no_input_raises(self) -> None:
        adapter = YouTubeTranscriptAdapter()
        with pytest.raises(ValueError, match="必须提供"):
            adapter.fetch()

    @patch("podcast_research.adapters.youtube_transcript.YouTubeTranscriptApi")
    def test_fetch_transcripts_disabled(self, mock_api_class: MagicMock) -> None:
        from youtube_transcript_api import TranscriptsDisabled
        mock_api_instance = mock_api_class.return_value
        mock_api_instance.list.side_effect = TranscriptsDisabled("vid123")

        adapter = YouTubeTranscriptAdapter()
        with pytest.raises(ValueError, match="字幕功能被禁用"):
            adapter.fetch(video_id="vid123")

    @patch("podcast_research.adapters.youtube_transcript.YouTubeTranscriptApi")
    def test_fetch_no_transcript_found(self, mock_api_class: MagicMock) -> None:
        from youtube_transcript_api import NoTranscriptFound
        mock_list = MagicMock()
        mock_list.find_transcript.side_effect = NoTranscriptFound("vid123", ["zh-Hans"], MagicMock())
        mock_list.__iter__ = MagicMock(return_value=iter([]))
        mock_api_instance = mock_api_class.return_value
        mock_api_instance.list.return_value = mock_list

        adapter = YouTubeTranscriptAdapter()
        with pytest.raises(ValueError, match="没有可用字幕"):
            adapter.fetch(video_id="vid123")

    @patch("podcast_research.adapters.youtube_transcript.YouTubeTranscriptApi")
    def test_fetch_language_fallback(self, mock_api_class: MagicMock) -> None:
        """测试语言 fallback：zh-Hans 不存在时 fallback 到 en。"""
        from youtube_transcript_api import NoTranscriptFound

        mock_transcript_en = MagicMock()
        mock_transcript_en.language_code = "en"
        mock_transcript_en.is_generated = True
        mock_transcript_en.fetch.return_value = MOCK_TRANSCRIPT_DATA

        mock_list = MagicMock()
        # zh-Hans 和 zh 都找不到
        mock_list.find_transcript.side_effect = [
            NoTranscriptFound("vid123", ["zh-Hans"], MagicMock()),
            NoTranscriptFound("vid123", ["zh"], MagicMock()),
            mock_transcript_en,  # en 找到了
        ]
        mock_api_instance = mock_api_class.return_value
        mock_api_instance.list.return_value = mock_list

        adapter = YouTubeTranscriptAdapter()
        result = adapter.fetch(video_id="vid123")

        assert result.language == "en"
        assert result.metadata["is_generated"] is True


class TestYouTubeTranscriptAdapterConvert:
    """测试 segments 转换逻辑。"""

    def test_convert_segments(self) -> None:
        adapter = YouTubeTranscriptAdapter()
        segments = adapter._convert_segments(MOCK_TRANSCRIPT_DATA, "vid123")
        assert len(segments) == 3
        assert segments[0].segment_id == "yt_001"
        assert segments[0].text == "大家好，今天我们来聊聊AI投资"

    def test_convert_skips_empty_text(self) -> None:
        data = [{"text": "", "start": 0, "duration": 1}] + MOCK_TRANSCRIPT_DATA
        adapter = YouTubeTranscriptAdapter()
        segments = adapter._convert_segments(data, "vid123")
        assert len(segments) == 3  # 空文本被跳过


class TestYouTubeTranscriptAdapterCache:
    """测试缓存读写。"""

    def test_cache_save_and_load(self, tmp_path: Path) -> None:
        adapter = YouTubeTranscriptAdapter(cache_dir=tmp_path)

        # 手动构造一个结果来保存
        from podcast_research.analysis.models import SubtitleSegment
        result = TranscriptResult(
            source_type="youtube",
            source_url="https://www.youtube.com/watch?v=vid123",
            video_id="vid123",
            language="zh-Hans",
            segments=[
                SubtitleSegment(segment_id="yt_001", start_time="00:00:00.000", end_time="00:00:03.500", text="测试文本"),
            ],
            metadata={"is_generated": False},
        )
        adapter._save_cache("vid123", result)

        loaded = adapter._load_cache("vid123")
        assert loaded is not None
        assert loaded.video_id == "vid123"
        assert len(loaded.segments) == 1
        assert loaded.segments[0].text == "测试文本"

    @patch("podcast_research.adapters.youtube_transcript.YouTubeTranscriptApi")
    def test_fetch_uses_cache(self, mock_api_class: MagicMock, tmp_path: Path) -> None:
        """第二次 fetch 应使用缓存，不调用 API。"""
        from podcast_research.analysis.models import SubtitleSegment

        # 先保存缓存
        adapter = YouTubeTranscriptAdapter(cache_dir=tmp_path)
        cached_result = TranscriptResult(
            source_type="youtube",
            source_url="https://www.youtube.com/watch?v=vid123",
            video_id="vid123",
            language="zh-Hans",
            segments=[
                SubtitleSegment(segment_id="yt_001", start_time="00:00:00.000", end_time="00:00:03.500", text="缓存文本"),
            ],
            metadata={},
        )
        adapter._save_cache("vid123", cached_result)

        # fetch 应返回缓存，不调用 API
        result = adapter.fetch(video_id="vid123")
        assert result.segments[0].text == "缓存文本"
        mock_api_class.list.assert_not_called()

    @patch("podcast_research.adapters.youtube_transcript.YouTubeTranscriptApi")
    def test_fetch_refresh_bypasses_cache(self, mock_api_class: MagicMock, tmp_path: Path) -> None:
        """refresh=True 应忽略缓存并调用 API。"""
        from podcast_research.analysis.models import SubtitleSegment

        adapter = YouTubeTranscriptAdapter(cache_dir=tmp_path)
        cached_result = TranscriptResult(
            source_type="youtube",
            source_url="https://www.youtube.com/watch?v=vid123",
            video_id="vid123",
            language="zh-Hans",
            segments=[
                SubtitleSegment(segment_id="yt_001", start_time="00:00:00.000", end_time="00:00:03.500", text="缓存文本"),
            ],
            metadata={},
        )
        adapter._save_cache("vid123", cached_result)

        # 设置 mock API
        mock_transcript = _make_mock_transcript_fetch()
        mock_list = _make_mock_transcript_list(mock_transcript)
        mock_api_instance = mock_api_class.return_value
        mock_api_instance.list.return_value = mock_list

        result = adapter.fetch(video_id="vid123", refresh=True)
        assert len(result.segments) == 3
        mock_api_instance.list.assert_called_once_with("vid123")


class TestFormatTime:
    """测试时间格式化。"""

    def test_zero(self) -> None:
        from podcast_research.adapters.youtube_transcript import _format_time
        assert _format_time(0) == "00:00:00.000"

    def test_with_seconds(self) -> None:
        from podcast_research.adapters.youtube_transcript import _format_time
        assert _format_time(3.5) == "00:00:03.500"

    def test_with_minutes(self) -> None:
        from podcast_research.adapters.youtube_transcript import _format_time
        assert _format_time(125.123) == "00:02:05.123"

    def test_with_hours(self) -> None:
        from podcast_research.adapters.youtube_transcript import _format_time
        assert _format_time(3661.5) == "01:01:01.500"


class TestTranscriptResultMetadata:
    """测试 TranscriptResult P0-B 元数据字段。"""

    def test_has_is_generated_field(self) -> None:
        result = TranscriptResult(
            source_type="youtube",
            is_generated=True,
        )
        assert result.is_generated is True

    def test_has_channel_name_field(self) -> None:
        result = TranscriptResult(
            source_type="youtube",
            channel_name="Test Channel",
        )
        assert result.channel_name == "Test Channel"

    def test_has_fetched_at_field(self) -> None:
        result = TranscriptResult(
            source_type="youtube",
            fetched_at="2026-05-27T10:00:00",
        )
        assert result.fetched_at == "2026-05-27T10:00:00"

    def test_transcript_segment_count(self) -> None:
        from podcast_research.analysis.models import SubtitleSegment
        result = TranscriptResult(
            source_type="youtube",
            segments=[
                SubtitleSegment(segment_id="1", start_time="0", end_time="1", text="a"),
                SubtitleSegment(segment_id="2", start_time="1", end_time="2", text="b"),
            ],
        )
        assert result.transcript_segment_count == 2

    def test_transcript_segment_count_empty(self) -> None:
        result = TranscriptResult(source_type="youtube")
        assert result.transcript_segment_count == 0

    def test_default_values(self) -> None:
        result = TranscriptResult(source_type="youtube")
        assert result.channel_name == ""
        assert result.is_generated is False
        assert result.fetched_at == ""

    @patch("podcast_research.adapters.youtube_transcript.YouTubeTranscriptApi")
    def test_fetch_populates_metadata(self, mock_api_class: MagicMock) -> None:
        """fetch 应填充 is_generated / fetched_at / channel_name。"""
        mock_transcript = _make_mock_transcript_fetch()
        mock_list = _make_mock_transcript_list(mock_transcript)
        mock_api_instance = mock_api_class.return_value
        mock_api_instance.list.return_value = mock_list

        adapter = YouTubeTranscriptAdapter()
        result = adapter.fetch(video_id="dQw4w9WgXcQ")

        assert result.is_generated is False
        assert result.fetched_at != ""
        assert isinstance(result.channel_name, str)
        assert result.transcript_segment_count == 3

    def test_cache_roundtrip_with_new_fields(self, tmp_path: Path) -> None:
        """缓存读写应保留新元数据字段。"""
        from podcast_research.analysis.models import SubtitleSegment
        adapter = YouTubeTranscriptAdapter(cache_dir=tmp_path)
        result = TranscriptResult(
            source_type="youtube",
            source_url="https://www.youtube.com/watch?v=vid123",
            video_id="vid123",
            language="en",
            channel_name="Test Channel",
            is_generated=True,
            fetched_at="2026-05-27T10:00:00",
            segments=[
                SubtitleSegment(segment_id="yt_001", start_time="00:00:00.000", end_time="00:00:03.500", text="test"),
            ],
            metadata={"is_generated": True, "fetched_at": "2026-05-27T10:00:00"},
        )
        adapter._save_cache("vid123", result)
        loaded = adapter._load_cache("vid123")

        assert loaded is not None
        assert loaded.channel_name == "Test Channel"
        assert loaded.is_generated is True
        assert loaded.fetched_at == "2026-05-27T10:00:00"
