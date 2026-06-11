"""YouTube URL 解析：从各种 URL 格式中提取 video_id。"""

import re
from urllib.parse import parse_qs, urlparse


def extract_video_id(url: str) -> str:
    """从 YouTube URL 中提取 video_id。

    支持：
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/shorts/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
    - https://m.youtube.com/watch?v=VIDEO_ID
    """
    parsed = urlparse(url)

    # youtu.be 短链接
    if parsed.hostname and parsed.hostname in ("youtu.be", "www.youtu.be"):
        path = parsed.path.lstrip("/")
        if path and re.match(r"^[\w-]{11}$", path):
            return path
        raise ValueError(f"无法从 youtu.be URL 提取 video_id: {url}")

    # youtube.com 常规域名
    if parsed.hostname and "youtube.com" in parsed.hostname:
        # /watch?v= 格式
        if parsed.path.startswith("/watch"):
            qs = parse_qs(parsed.query)
            vid = qs.get("v", [None])[0]
            if vid and re.match(r"^[\w-]{11}$", vid):
                return vid
            raise ValueError(f"无法从 watch URL 提取 video_id: {url}")

        # /shorts/ 和 /embed/ 格式
        for prefix in ("/shorts/", "/embed/"):
            if parsed.path.startswith(prefix):
                vid = parsed.path[len(prefix):]
                if vid and re.match(r"^[\w-]{11}$", vid):
                    return vid
                raise ValueError(f"无法从 {prefix} URL 提取 video_id: {url}")

    raise ValueError(f"不是有效的 YouTube URL: {url}")


def is_youtube_url(url: str) -> bool:
    """判断是否为 YouTube URL。"""
    try:
        parsed = urlparse(url)
        if parsed.hostname and parsed.hostname in ("youtu.be", "www.youtu.be"):
            return True
        if parsed.hostname and "youtube.com" in parsed.hostname:
            return True
    except Exception:
        pass
    return False


def extract_channel_id(url: str) -> str:
    """从 YouTube 频道 URL 中提取频道 ID 或 handle。

    支持：
    - https://www.youtube.com/@ChannelHandle
    - https://www.youtube.com/channel/UC...
    - https://www.youtube.com/c/ChannelName

    Returns:
        频道 ID（如果是 @handle 格式，去除 @ 前缀；如果是 /channel/UC...，返回 UC ID）
    """
    parsed = urlparse(url)
    if not parsed.hostname or "youtube.com" not in parsed.hostname:
        raise ValueError(f"不是有效的 YouTube 频道 URL: {url}")

    path = parsed.path.rstrip("/")

    # /@Handle format
    if path.startswith("/@"):
        channel_id = path[2:]  # remove /@
        return channel_id

    # /channel/UC... format
    if "/channel/" in path:
        idx = path.index("/channel/")
        channel_id = path[idx + 9:]  # after /channel/
        if "/" in channel_id:
            channel_id = channel_id.split("/")[0]
        return channel_id

    # /c/Name format (legacy)
    if "/c/" in path:
        idx = path.index("/c/")
        channel_id = path[idx + 3:]
        if "/" in channel_id:
            channel_id = channel_id.split("/")[0]
        return channel_id

    raise ValueError(f"无法从 URL 提取频道 ID: {url}")
