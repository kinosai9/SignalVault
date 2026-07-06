"""P1-E: yt-dlp 频道视频列表 Adapter。

使用 yt-dlp --flat-playlist 获取频道最近视频元数据，不下载视频/音频。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _format_upload_date(raw: str) -> str:
    """Convert yt-dlp YYYYMMDD upload_date to human-readable YYYY-MM-DD."""
    if not raw:
        return ""
    raw = raw.strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw  # already formatted or unknown format


@dataclass
class ChannelVideoItem:
    """频道视频元数据。"""
    video_id: str = ""
    title: str = ""
    url: str = ""
    published_at: str = ""
    duration_seconds: int = 0
    channel_name: str = ""


class ChannelVideoAdapter:
    """使用 yt-dlp 获取 YouTube 频道视频列表。"""

    def fetch_channel_videos(
        self,
        channel_url: str,
        limit: int = 20,
    ) -> list[ChannelVideoItem]:
        """获取频道最近视频列表。

        不使用 --flat-playlist（该模式不返回 upload_date/timestamp），
        直接做完整 playlist 提取以获取发布日期。
        """

        import yt_dlp

        opts: dict = {
            "quiet": True,
            "extract_flat": False,
            "playlistend": limit,
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"{channel_url.rstrip('/')}/videos", download=False)
        except Exception as e:
            logger.error("yt-dlp failed for %s: %s", channel_url, e)
            raise RuntimeError(f"获取频道视频列表失败: {e}") from e

        channel_name = info.get("channel", "") or info.get("uploader", "") or ""
        entries = info.get("entries", [])

        items = []
        for entry in entries:
            vid = entry.get("id", "")
            if not vid:
                continue
            # 过滤频道 playlist 项（非视频）
            if vid.startswith("UC") and len(vid) == 24:
                continue
            dur = entry.get("duration", 0) or 0
            # 非 flat 模式下 upload_date 可用（YYYYMMDD 格式）
            raw_date = entry.get("upload_date", "") or ""
            formatted_date = _format_upload_date(raw_date)
            items.append(ChannelVideoItem(
                video_id=vid,
                title=entry.get("title", ""),
                url=f"https://www.youtube.com/watch?v={vid}",
                published_at=formatted_date,
                duration_seconds=int(dur),
                channel_name=channel_name,
            ))

        logger.info("Fetched %d videos from channel %s", len(items), channel_url)
        return items
