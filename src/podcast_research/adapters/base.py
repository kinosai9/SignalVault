"""数据源 Adapter 基类。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from podcast_research.analysis.models import SubtitleSegment


@dataclass
class TranscriptResult:
    """统一 transcript 获取结果。"""
    source_type: str
    source_url: str = ""
    video_id: str = ""
    language: str = ""
    title: str = ""
    channel_name: str = ""
    is_generated: bool = False
    fetched_at: str = ""
    segments: list[SubtitleSegment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def transcript_segment_count(self) -> int:
        return len(self.segments)


class TranscriptAdapter:
    """数据源 Adapter 基类：获取字幕并转换为 SubtitleSegment。"""

    def fetch(self, **kwargs: Any) -> TranscriptResult:
        raise NotImplementedError