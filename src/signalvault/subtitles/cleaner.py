"""字幕清洗器：去空行、合并短段、去重、标记疑似广告。"""

from signalvault.analysis.models import SubtitleSegment

_AD_KEYWORDS = ["赞助", "广告", "推广", "赞助商", "特别鸣谢", "brand", "sponsor"]
_MERGE_THRESHOLD_SEC = 5.0
_MERGE_THRESHOLD_LINES = 6


def clean_segments(
    segments: list[SubtitleSegment],
    merge_short: bool = True,
    remove_ads: bool = True,
) -> list[SubtitleSegment]:
    result = _remove_empty(segments)
    result = _deduplicate(result)
    if remove_ads:
        result = _mark_ads(result)
    if merge_short:
        result = _merge_short(result)
    return result


def _remove_empty(segments: list[SubtitleSegment]) -> list[SubtitleSegment]:
    return [s for s in segments if s.text.strip()]


def _deduplicate(segments: list[SubtitleSegment]) -> list[SubtitleSegment]:
    seen: set[str] = set()
    result = []
    for s in segments:
        key = s.text.strip()
        if key not in seen:
            seen.add(key)
            result.append(s)
    return result


def _mark_ads(segments: list[SubtitleSegment]) -> list[SubtitleSegment]:
    ad_set: set[str] = set()
    for kw in _AD_KEYWORDS:
        for s in segments:
            if kw in s.text.lower():
                ad_set.add(s.segment_id)
    return [
        SubtitleSegment(
            segment_id=s.segment_id,
            start_time=s.start_time,
            end_time=s.end_time,
            text=s.text + " [广告]" if s.segment_id in ad_set else s.text,
        )
        for s in segments
    ]


def _merge_short(segments: list[SubtitleSegment]) -> list[SubtitleSegment]:
    if not segments:
        return segments

    merged = []
    buffer: list[SubtitleSegment] = []

    for s in segments:
        # 只合并长度 < 20 字符的短段
        if len(s.text.strip()) < 20 and len(buffer) < 4:
            buffer.append(s)
        else:
            if buffer:
                merged.append(_join_buffer(buffer))
                buffer = []
            merged.append(s)

    if buffer:
        merged.append(_join_buffer(buffer))
    return merged


def _join_buffer(buffer: list[SubtitleSegment]) -> SubtitleSegment:
    start = buffer[0].start_time
    end = buffer[-1].end_time
    text = " ".join(s.text for s in buffer)
    return SubtitleSegment(
        segment_id=buffer[0].segment_id,
        start_time=start,
        end_time=end,
        text=text,
    )
