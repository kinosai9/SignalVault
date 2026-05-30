"""P1-E: yt-dlp 频道视频列表 Adapter。

使用 yt-dlp --flat-playlist 获取频道最近视频元数据，不下载视频/音频。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


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
        """获取频道最近视频列表。"""
        import json

        import yt_dlp

        opts: dict = {
            "quiet": True,
            "extract_flat": True,
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
            items.append(ChannelVideoItem(
                video_id=vid,
                title=entry.get("title", ""),
                url=f"https://www.youtube.com/watch?v={vid}",
                published_at=entry.get("upload_date", "") or "",
                duration_seconds=int(dur),
                channel_name=channel_name,
            ))

        logger.info("Fetched %d videos from channel %s", len(items), channel_url)
        return items
