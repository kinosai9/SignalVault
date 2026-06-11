"""字幕解析器测试。"""

from pathlib import Path

import pytest

from podcast_research.analysis.models import SubtitleSegment
from podcast_research.subtitles.parser import (
    _normalize_vtt_time,
    _parse_vtt,
    detect_format,
    parse_subtitle,
)

SAMPLE_SRT = Path(__file__).resolve().parent.parent / "data" / "subtitles" / "sample.srt"
SAMPLE_VTT = Path(__file__).resolve().parent.parent / "data" / "subtitles" / "sample.vtt"


# --- format detection ---

def test_detect_format_srt() -> None:
    assert detect_format(Path("test.srt")) == "srt"


def test_detect_format_vtt() -> None:
    assert detect_format(Path("test.vtt")) == "vtt"


def test_detect_format_txt() -> None:
    assert detect_format(Path("test.txt")) == "txt"


def test_detect_format_unsupported() -> None:
    with pytest.raises(ValueError, match="不支持"):
        detect_format(Path("test.ass"))


# --- SRT parsing ---

def test_parse_srt_file() -> None:
    segments = parse_subtitle(SAMPLE_SRT)
    assert len(segments) > 0
    assert all(isinstance(s, SubtitleSegment) for s in segments)
    first = segments[0]
    assert first.segment_id.startswith("seg_")
    assert first.start_time.startswith("00:")
    assert first.text.strip() != ""


def test_parse_srt_timestamps() -> None:
    segments = parse_subtitle(SAMPLE_SRT)
    for s in segments:
        assert "." in s.start_time or ":" in s.start_time


# --- TXT parsing ---

def test_parse_txt() -> None:
    from podcast_research.subtitles.parser import _parse_txt
    segments = _parse_txt("第一行\n第二行\n第三行")
    assert len(segments) == 3
    assert segments[0].text == "第一行"
    assert segments[0].start_time == ""


# --- VTT parsing ---

def test_parse_vtt_file() -> None:
    """sample.vtt 能正确解析出 15 段字幕。"""
    segments = parse_subtitle(SAMPLE_VTT)
    assert len(segments) == 15
    assert all(isinstance(s, SubtitleSegment) for s in segments)


def test_parse_vtt_first_segment() -> None:
    segments = parse_subtitle(SAMPLE_VTT)
    first = segments[0]
    assert first.segment_id == "seg_001"
    assert first.start_time == "00:00:01.000"
    assert first.end_time == "00:00:05.000"
    assert "投资播客" in first.text


def test_parse_vtt_strips_html_tags() -> None:
    """<b> 和 <v Speaker> 等内联标签应被去除。"""
    segments = parse_subtitle(SAMPLE_VTT)
    # seg_002 原文有 <b>新能源板块</b>
    assert "<b>" not in segments[1].text
    assert "新能源板块" in segments[1].text
    # seg_003 原文有 <v SpeakerA>...</v>
    assert "<v" not in segments[2].text
    assert "储能赛道" in segments[2].text


def test_parse_vtt_skips_note_blocks() -> None:
    """NOTE 注释块不应出现在解析结果中。"""
    segments = parse_subtitle(SAMPLE_VTT)
    all_text = " ".join(s.text for s in segments)
    assert "注释" not in all_text


def test_parse_vtt_timestamp_format() -> None:
    """所有时间戳应为 HH:MM:SS.mmm 格式。"""
    segments = parse_subtitle(SAMPLE_VTT)
    for s in segments:
        assert "." in s.start_time
        parts = s.start_time.split(":")
        assert len(parts) == 3


def test_parse_vtt_segment_ids_sequential() -> None:
    segments = parse_subtitle(SAMPLE_VTT)
    for i, s in enumerate(segments, 1):
        assert s.segment_id == f"seg_{i:03d}"


def test_parse_vtt_missing_header() -> None:
    """缺少 WEBVTT 头应抛 ValueError。"""
    with pytest.raises(ValueError, match="WEBVTT"):
        _parse_vtt("00:00:01.000 --> 00:00:05.000\nhello")


def test_parse_vtt_with_style_block() -> None:
    """STYLE 块应被跳过。"""
    vtt = "WEBVTT\n\nSTYLE\n::cue { color: white }\n\n00:00:01.000 --> 00:00:05.000\nhello"
    segments = _parse_vtt(vtt)
    assert len(segments) == 1
    assert segments[0].text == "hello"


def test_parse_vtt_no_cue_id() -> None:
    """无 cue identifier 的时间戳块应正确解析。"""
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:05.000\nno cue id here"
    segments = _parse_vtt(vtt)
    assert len(segments) == 1
    assert segments[0].text == "no cue id here"


def test_parse_vtt_short_timestamp() -> None:
    """MM:SS.mmm 短格式应补齐为 00:MM:SS.mmm。"""
    vtt = "WEBVTT\n\n01:23.456 --> 01:25.000\nshort time"
    segments = _parse_vtt(vtt)
    assert len(segments) == 1
    assert segments[0].start_time == "00:01:23.456"


def test_normalize_vtt_time_full() -> None:
    assert _normalize_vtt_time("01:02:03.456") == "01:02:03.456"


def test_normalize_vtt_time_short() -> None:
    assert _normalize_vtt_time("02:03.456") == "00:02:03.456"


def test_parse_vtt_with_cue_settings() -> None:
    """时间戳行附带 cue settings 时应正确解析。"""
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:05.000 position:10% align:start\nwith settings"
    segments = _parse_vtt(vtt)
    assert len(segments) == 1
    assert segments[0].text == "with settings"


def test_parse_vtt_multiline_text() -> None:
    """多行文本应合并为单段。"""
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:05.000\n第一行\n第二行"
    segments = _parse_vtt(vtt)
    assert len(segments) == 1
    assert "第一行" in segments[0].text
    assert "第二行" in segments[0].text
