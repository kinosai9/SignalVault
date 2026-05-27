"""YouTube URL 解析工具测试。"""

from podcast_research.utils.youtube import extract_video_id, is_youtube_url


class TestExtractVideoId:
    def test_watch_url(self) -> None:
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_watch_url_with_params(self) -> None:
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42") == "dQw4w9WgXcQ"

    def test_short_url(self) -> None:
        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_shorts_url(self) -> None:
        assert extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self) -> None:
        assert extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_mobile_url(self) -> None:
        assert extract_video_id("https://m.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_invalid_url_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="不是有效的 YouTube URL"):
            extract_video_id("https://example.com/video")

    def test_invalid_watch_url_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="无法从 watch URL"):
            extract_video_id("https://www.youtube.com/watch?v=")

    def test_invalid_short_url_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="无法从 youtu.be URL"):
            extract_video_id("https://youtu.be/")


class TestIsYoutubeUrl:
    def test_watch(self) -> None:
        assert is_youtube_url("https://www.youtube.com/watch?v=abc") is True

    def test_short(self) -> None:
        assert is_youtube_url("https://youtu.be/abc") is True

    def test_non_youtube(self) -> None:
        assert is_youtube_url("https://example.com") is False