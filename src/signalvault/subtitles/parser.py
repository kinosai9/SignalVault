"""字幕解析器：支持 SRT、VTT 和 TXT 格式，输出 SubtitleSegment 列表。"""

import re
from pathlib import Path

from signalvault.analysis.models import SubtitleSegment


def detect_format(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".srt":
        return "srt"
    if ext == ".vtt":
        return "vtt"
    if ext == ".txt":
        return "txt"
    raise ValueError(f"不支持的字幕格式: {ext}，仅支持 .srt / .vtt / .txt")


def parse_subtitle(path: Path) -> list[SubtitleSegment]:
    fmt = detect_format(path)
    text = path.read_text(encoding="utf-8")
    if fmt == "srt":
        return _parse_srt(text)
    if fmt == "vtt":
        return _parse_vtt(text)
    return _parse_txt(text)


_SRT_TIMESTAMP = re.compile(
    r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})"
)

_VTT_TIMESTAMP = re.compile(
    r"((?:\d{1,2}:)?\d{2}:\d{2}\.\d{3})\s*-->\s*((?:\d{1,2}:)?\d{2}:\d{2}\.\d{3})"
)

# WebVTT 内联标签（<b>, <i>, <u>, <c>, <v>, <lang>, <ruby>, <rt> 等）
_VTT_TAGS = re.compile(r"<[^>]+>")


def _parse_srt(text: str) -> list[SubtitleSegment]:
    blocks = re.split(r"\n\s*\n", text.strip())
    segments = []
    idx = 0
    for block in blocks:
        lines = block.strip().split("\n")
        ts_match = _SRT_TIMESTAMP.search(lines[1] if len(lines) > 1 else "")
        if not ts_match:
            continue
        start = ts_match.group(1).replace(",", ".")
        end = ts_match.group(2).replace(",", ".")
        content_lines = lines[2:] if len(lines) > 2 else []
        content = " ".join(content_lines).strip()
        if not content:
            continue
        idx += 1
        segments.append(
            SubtitleSegment(
                segment_id=f"seg_{idx:03d}",
                start_time=start,
                end_time=end,
                text=content,
            )
        )
    return segments


def _parse_vtt(text: str) -> list[SubtitleSegment]:
    """WebVTT 格式解析。

    处理要点：
    - 跳过 WEBVTT 头和 NOTE/STYLE/REGION 块
    - 时间戳用 . 分隔毫秒（与 SRT 的 , 不同）
    - 去除内联 HTML 标签（<b>, <i>, <v Speaker> 等）
    - 时间戳行可能带 cue settings（position, align 等），忽略
    """
    text = text.strip()
    if not text.upper().startswith("WEBVTT"):
        raise ValueError("不是合法的 WebVTT 文件：缺少 WEBVTT 头")

    # 去掉 WEBVTT 头行（可能附带说明文字）
    header_end = text.index("\n") if "\n" in text else len(text)
    body = text[header_end:].strip()

    blocks = re.split(r"\n\s*\n", body)
    segments = []
    idx = 0

    for block in blocks:
        lines = block.strip().split("\n")
        if not lines:
            continue

        # 跳过 NOTE / STYLE / REGION 块
        first_line = lines[0].strip()
        if first_line.startswith(("NOTE", "STYLE", "REGION")):
            continue

        # 找时间戳行：可能是第一行（无 cue id）或第二行（有 cue id）
        ts_match = None
        ts_line_idx = -1
        for i, line in enumerate(lines[:2]):
            ts_match = _VTT_TIMESTAMP.search(line)
            if ts_match:
                ts_line_idx = i
                break

        if not ts_match or ts_line_idx < 0:
            continue

        start_raw = ts_match.group(1)
        end_raw = ts_match.group(2)
        # 统一为 HH:MM:SS.mmm 格式
        start = _normalize_vtt_time(start_raw)
        end = _normalize_vtt_time(end_raw)

        content_lines = lines[ts_line_idx + 1:]
        # 去除内联标签
        content = " ".join(
            _VTT_TAGS.sub("", line).strip() for line in content_lines
        ).strip()
        if not content:
            continue

        idx += 1
        segments.append(
            SubtitleSegment(
                segment_id=f"seg_{idx:03d}",
                start_time=start,
                end_time=end,
                text=content,
            )
        )

    return segments


def _normalize_vtt_time(raw: str) -> str:
    """将 VTT 时间戳统一为 HH:MM:SS.mmm 格式。

    VTT 允许省略小时位（MM:SS.mmm），这里补齐为 HH:MM:SS.mmm。
    """
    parts = raw.split(":")
    if len(parts) == 2:
        # MM:SS.mmm → 00:MM:SS.mmm
        return f"00:{parts[0]}:{parts[1]}"
    return raw


def _parse_txt(text: str) -> list[SubtitleSegment]:
    """TXT 格式无时间戳，每行一段，时间戳留空。"""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    segments = []
    for i, line in enumerate(lines, 1):
        segments.append(
            SubtitleSegment(
                segment_id=f"seg_{i:03d}",
                start_time="",
                end_time="",
                text=line,
            )
        )
    return segments
