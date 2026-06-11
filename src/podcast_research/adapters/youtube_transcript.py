"""YouTubeTranscriptAdapter：通过 youtube-transcript-api 获取字幕。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)

from podcast_research.adapters.base import TranscriptAdapter, TranscriptResult
from podcast_research.analysis.models import SubtitleSegment
from podcast_research.utils.youtube import extract_video_id

logger = logging.getLogger(__name__)

_LANG_PRIORITY = ["zh-Hans", "zh", "zh-Hant", "en", "zh-CN"]


class YouTubeTranscriptAdapter(TranscriptAdapter):
    """从 YouTube 视频获取字幕并转换为 SubtitleSegment 列表。

    不下载视频/音频，只获取字幕文本。
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._cache_dir = cache_dir
        self._api = YouTubeTranscriptApi()

    def fetch(
        self,
        url: str | None = None,
        video_id: str | None = None,
        languages: list[str] | None = None,
        refresh: bool = False,
    ) -> TranscriptResult:
        """获取 YouTube 视频字幕。

        Args:
            url: YouTube 视频 URL。
            video_id: YouTube 视频 ID（与 url 二选一）。
            languages: 语言优先级列表，默认 zh-Hans > zh > en。
            refresh: 是否强制重新获取（忽略缓存）。

        Returns:
            TranscriptResult 包含 SubtitleSegment 列表。
        """
        if url:
            vid = extract_video_id(url)
        elif video_id:
            vid = video_id
        else:
            raise ValueError("必须提供 url 或 video_id")

        lang_list = languages or _LANG_PRIORITY

        # 缓存检查
        if not refresh and self._cache_dir:
            cached = self._load_cache(vid)
            if cached:
                logger.info("使用缓存 transcript: %s", vid)
                return cached

        # 获取 transcript
        try:
            transcript_list = self._api.list(vid)
            # 找到可用的 transcript
            transcript = None
            for lang in lang_list:
                try:
                    transcript = transcript_list.find_transcript([lang])
                    break
                except NoTranscriptFound:
                    continue

            if transcript is None:
                # fallback: 尝试任何可用语言
                available = transcript_list  # type: ignore[assignment]
                for t in available:
                    transcript = t
                    break

            if transcript is None:
                raise ValueError(f"该视频没有可用字幕: {vid}")

            fetched = transcript.fetch()
            lang_code = transcript.language_code
            is_generated = transcript.is_generated

        except TranscriptsDisabled:
            raise ValueError("该视频没有可用字幕（字幕功能被禁用）")
        except NoTranscriptFound as e:
            raise ValueError(f"该视频没有可用字幕: {e}")

        # 转换为 SubtitleSegment
        segments = self._convert_segments(fetched, vid)
        fetched_at = datetime.now().isoformat()

        result = TranscriptResult(
            source_type="youtube",
            source_url=url or f"https://www.youtube.com/watch?v={vid}",
            video_id=vid,
            language=lang_code,
            channel_name="",  # youtube-transcript-api 不提供频道名
            is_generated=is_generated,
            fetched_at=fetched_at,
            segments=segments,
            metadata={
                "is_generated": is_generated,
                "fetched_at": fetched_at,
            },
        )

        # 写缓存
        if self._cache_dir:
            self._save_cache(vid, result)

        return result

    def _convert_segments(
        self,
        fetched,
        video_id: str,
    ) -> list[SubtitleSegment]:
        """将 youtube-transcript-api 返回的数据转换为 SubtitleSegment。

        新版 API fetch() 返回 FetchedTranscript（含 .snippets 列表），
        每个 snippet 为 FetchedTranscriptSnippet（有 .text/.start/.duration）。
        测试 mock 中 fetch() 返回 list[dict]，此处兼容两种格式。
        """
        if hasattr(fetched, 'snippets'):
            items = fetched.snippets
        else:
            items = fetched

        segments = []
        for i, item in enumerate(items, 1):
            if isinstance(item, dict):
                start = item.get("start", 0)
                duration = item.get("duration", 0)
                text = item.get("text", "").strip()
            else:
                start = getattr(item, "start", 0)
                duration = getattr(item, "duration", 0)
                text = getattr(item, "text", "").strip()
            if not text:
                continue
            end = start + duration
            segments.append(
                SubtitleSegment(
                    segment_id=f"yt_{i:03d}",
                    start_time=_format_time(start),
                    end_time=_format_time(end),
                    text=text,
                )
            )
        return segments

    def _cache_path(self, video_id: str) -> Path:
        if not self._cache_dir:
            raise ValueError("缓存目录未设置")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        return self._cache_dir / f"{video_id}.json"

    def _load_cache(self, video_id: str) -> TranscriptResult | None:
        path = self._cache_path(video_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            segments = [
                SubtitleSegment(**s) for s in data.get("segments", [])
            ]
            return TranscriptResult(
                source_type=data.get("source_type", "youtube"),
                source_url=data.get("source_url", ""),
                video_id=data.get("video_id", video_id),
                language=data.get("language", ""),
                title=data.get("title", ""),
                channel_name=data.get("channel_name", ""),
                is_generated=data.get("is_generated", False),
                fetched_at=data.get("fetched_at", ""),
                segments=segments,
                metadata=data.get("metadata", {}),
            )
        except Exception:
            logger.warning("缓存读取失败: %s", path)
            return None

    def _save_cache(self, video_id: str, result: TranscriptResult) -> None:
        path = self._cache_path(video_id)
        data = {
            "source_type": result.source_type,
            "source_url": result.source_url,
            "video_id": result.video_id,
            "language": result.language,
            "title": result.title,
            "channel_name": result.channel_name,
            "is_generated": result.is_generated,
            "fetched_at": result.fetched_at,
            "segments": [s.model_dump() for s in result.segments],
            "metadata": result.metadata,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _format_time(seconds: float) -> str:
    """将秒数格式化为 HH:MM:SS.mmm 时间戳字符串。"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
