"""字幕清洗器测试。"""

from signalvault.analysis.models import SubtitleSegment
from signalvault.subtitles.cleaner import clean_segments


def _make_segment(idx: int, text: str, start: str = "00:00:00", end: str = "00:00:05") -> SubtitleSegment:
    return SubtitleSegment(segment_id=f"seg_{idx:03d}", start_time=start, end_time=end, text=text)


def test_remove_empty() -> None:
    segments = [_make_segment(1, ""), _make_segment(2, "有内容")]
    result = clean_segments(segments, merge_short=False, remove_ads=False)
    assert len(result) == 1
    assert result[0].text == "有内容"


def test_deduplicate() -> None:
    segments = [_make_segment(1, "重复"), _make_segment(2, "重复"), _make_segment(3, "不同")]
    result = clean_segments(segments, merge_short=False, remove_ads=False)
    assert len(result) == 2


def test_mark_ads() -> None:
    segments = [_make_segment(1, "这是赞助内容"), _make_segment(2, "正常内容")]
    result = clean_segments(segments, merge_short=False, remove_ads=True)
    assert "[广告]" in result[0].text
    assert "[广告]" not in result[1].text


def test_merge_short() -> None:
    segments = [_make_segment(i, f"段{i}") for i in range(1, 5)]
    result = clean_segments(segments, merge_short=True, remove_ads=False)
    assert len(result) < len(segments)


def test_full_clean_pipeline() -> None:
    raw = [
        _make_segment(1, ""),
        _make_segment(2, "赞助播报"),
        _make_segment(3, "观点1"),
        _make_segment(4, "观点2"),
    ]
    result = clean_segments(raw, merge_short=True, remove_ads=True)
    assert any("[广告]" in s.text for s in result)
    assert all(s.text.strip() for s in result)
