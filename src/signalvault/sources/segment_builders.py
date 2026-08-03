"""M3-C-2b: Universal Intake — Segment Builders.

Orchestrator 的 Parser 阶段。把非字幕来源（纯文本 / 网页 / 文件）转成
list[SubtitleSegment]，使其能接入 _run_pipeline —— 与 YouTube / PDF 共用同一条
分析流水线。

设计原则（约束 3）：
- SubtitleSegment 保持作为 pipeline 契约（核心 4 字段不变；metadata 为可选扩展）
- 追溯信息（page / file / url / source）通过 segment.metadata 携带
- 转换模式仿 pdf_analysis._pages_to_segments（已验证的非字幕 → Segment 路径）
"""

from __future__ import annotations

import re

from signalvault.analysis.models import SubtitleSegment

# 段落分隔：空行分隔的段落块
_PARA_SPLIT_RE = re.compile(r"\n\s*\n")


def text_to_segments(
    text: str,
    source_id: str = "text",
    *,
    source_url: str = "",
    source_file: str = "",
) -> list[SubtitleSegment]:
    """纯文本 → SubtitleSegment 列表（按段落切分）。

    每个非空段落成为一个 segment。segment_id 形如 "{source_id}_block_{N}"。
    非时间轴来源的 start_time/end_time 留空（pipeline 不依赖）。
    追溯信息（url/file）写入每个 segment.metadata。
    """
    if not text or not text.strip():
        return []

    metadata: dict[str, str] = {"source": source_id}
    if source_url:
        metadata["url"] = source_url
    if source_file:
        metadata["file"] = source_file

    paragraphs = [p.strip() for p in _PARA_SPLIT_RE.split(text) if p.strip()]
    # 无段落分隔（单段多行）时按行切，避免整篇挤成一个 segment
    if len(paragraphs) <= 1 and "\n" in text:
        paragraphs = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not paragraphs:
        return []

    return [
        SubtitleSegment(
            segment_id=f"{source_id}_block_{idx}",
            start_time="",
            end_time="",
            text=para,
            metadata=metadata,
        )
        for idx, para in enumerate(paragraphs)
    ]


def web_page_to_segments(
    paragraphs: list[str],
    source_id: str = "web",
    *,
    source_url: str = "",
    title: str = "",
) -> list[SubtitleSegment]:
    """网页解析结果（段落列表）→ SubtitleSegment 列表。

    接收已提取的段落（来自 GenericWebPageAdapter 等），每段一个 segment。
    接收 paragraphs 而非 adapter 对象，避免耦合具体 adapter 类型。
    """
    metadata: dict[str, str] = {"source": source_id}
    if source_url:
        metadata["url"] = source_url
    if title:
        metadata["title"] = title

    segments: list[SubtitleSegment] = []
    for idx, para in enumerate(paragraphs):
        text = para.strip()
        if not text:
            continue
        segments.append(SubtitleSegment(
            segment_id=f"{source_id}_block_{idx}",
            start_time="",
            end_time="",
            text=text,
            metadata=metadata,
        ))
    return segments


def file_to_segments(
    text: str,
    filename: str,
    *,
    source_id: str = "file",
) -> list[SubtitleSegment]:
    """文件文本 → SubtitleSegment 列表（text_to_segments 的文件语义封装）。"""
    return text_to_segments(text, source_id=source_id, source_file=filename)
