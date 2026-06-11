"""P1-F: 频道与视频 Repository（tags / priority / seed / filtering）。"""

import json

from sqlalchemy import func
from sqlalchemy.orm import Session

from podcast_research.db.models import Channel, ChannelVideo

# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------

def add_channel(
    session: Session,
    youtube_channel_id: str,
    url: str,
    name: str = "",
    tags: list[str] | None = None,
    priority: str = "secondary",
    default_focus: str = "",
    default_limit: int = 10,
    default_max_analyze: int = 3,
    notes: str = "",
) -> int:
    """添加关注的频道（如已存在则更新字段并返回已有 ID）。"""
    existing = session.query(Channel).filter_by(youtube_channel_id=youtube_channel_id).first()
    if existing:
        if name:
            existing.name = name
        if url:
            existing.url = url
        if tags is not None:
            existing.tags = json.dumps(tags, ensure_ascii=False)
        if priority:
            existing.priority = priority
        if default_focus:
            existing.default_focus = default_focus
        if default_limit != 10:
            existing.default_limit = default_limit
        if default_max_analyze != 3:
            existing.default_max_analyze = default_max_analyze
        if notes:
            existing.notes = notes
        session.flush()
        return existing.id

    ch = Channel(
        youtube_channel_id=youtube_channel_id,
        name=name or youtube_channel_id,
        url=url,
        tags=json.dumps(tags or [], ensure_ascii=False),
        priority=priority,
        default_focus=default_focus,
        default_limit=default_limit,
        default_max_analyze=default_max_analyze,
        notes=notes,
    )
    session.add(ch)
    session.flush()
    return ch.id


def update_channel_tags(
    session: Session,
    channel_id: int,
    add: list[str] | None = None,
    remove: list[str] | None = None,
    set_tags: list[str] | None = None,
) -> bool:
    """更新频道标签。支持 add / remove / set 三种操作，set 优先级最高。"""
    ch = session.query(Channel).filter_by(id=channel_id).first()
    if not ch:
        return False

    if set_tags is not None:
        ch.tags = json.dumps(set_tags, ensure_ascii=False)
    else:
        current = _parse_tags(ch.tags)
        if remove:
            remove_set = {t.strip() for t in remove}
            current = [t for t in current if t not in remove_set]
        if add:
            add_set = {t.strip() for t in add}
            for t in add_set:
                if t not in current:
                    current.append(t)
        ch.tags = json.dumps(current, ensure_ascii=False)
    session.flush()
    return True


def _parse_tags(raw: str) -> list[str]:
    """安全解析 tags JSON 字符串。"""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def list_channels(
    session: Session,
    tag: str | None = None,
    priority: str | None = None,
) -> list[dict]:
    """列出关注的频道，支持 tag / priority 过滤。"""
    rows = session.query(Channel).order_by(Channel.added_at.desc()).all()
    results = []
    for ch in rows:
        tags_list = _parse_tags(ch.tags)
        # tag 过滤
        if tag and tag not in tags_list:
            continue
        # priority 过滤
        if priority and ch.priority != priority:
            continue

        video_count = session.query(func.count(ChannelVideo.id)).filter_by(channel_id=ch.id).scalar() or 0
        new_count = session.query(func.count(ChannelVideo.id)).filter_by(channel_id=ch.id, status="new").scalar() or 0
        results.append({
            "id": ch.id,
            "youtube_channel_id": ch.youtube_channel_id,
            "name": ch.name,
            "url": ch.url,
            "tags": tags_list,
            "priority": ch.priority,
            "default_focus": ch.default_focus,
            "default_limit": ch.default_limit,
            "default_max_analyze": ch.default_max_analyze,
            "notes": ch.notes,
            "added_at": ch.added_at,
            "last_refreshed_at": ch.last_refreshed_at,
            "video_count": video_count,
            "new_video_count": new_count,
        })
    return results


def get_channel(session: Session, channel_id: int) -> dict | None:
    """获取单个频道信息（含新增字段）。"""
    ch = session.query(Channel).filter_by(id=channel_id).first()
    if not ch:
        return None
    video_count = session.query(func.count(ChannelVideo.id)).filter_by(channel_id=ch.id).scalar() or 0
    return {
        "id": ch.id,
        "youtube_channel_id": ch.youtube_channel_id,
        "name": ch.name,
        "url": ch.url,
        "tags": _parse_tags(ch.tags),
        "priority": ch.priority,
        "default_focus": ch.default_focus,
        "default_limit": ch.default_limit,
        "default_max_analyze": ch.default_max_analyze,
        "notes": ch.notes,
        "added_at": ch.added_at,
        "last_refreshed_at": ch.last_refreshed_at,
        "video_count": video_count,
    }


def get_channel_defaults(session: Session, channel_id: int) -> dict | None:
    """获取频道默认配置（focus / limit / max_analyze / priority）。"""
    ch = session.query(Channel).filter_by(id=channel_id).first()
    if not ch:
        return None
    return {
        "default_focus": ch.default_focus,
        "default_limit": ch.default_limit,
        "default_max_analyze": ch.default_max_analyze,
        "priority": ch.priority,
    }


# ---------------------------------------------------------------------------
# Default Channel Pack
# ---------------------------------------------------------------------------

DEFAULT_TECH_AI_CHANNELS = [
    {
        "youtube_channel_id": "@allin",
        "url": "https://www.youtube.com/@allin",
        "name": "All-In Podcast",
        "tags": ["tech", "ai", "vc", "macro", "markets", "podcast"],
        "priority": "core",
        "default_focus": "AI投资, 科技股, 宏观政策, 风险资产, 创业投资",
        "default_limit": 10,
        "default_max_analyze": 3,
        "notes": "硅谷顶级投资人圆桌，每周更新，覆盖科技/AI/宏观/加密",
    },
    {
        "youtube_channel_id": "@BG2Pod",
        "url": "https://www.youtube.com/@BG2Pod",
        "name": "BG2Pod",
        "tags": ["tech", "ai", "investing", "markets", "venture", "podcast"],
        "priority": "core",
        "default_focus": "AI投资, 科技股, 估值, VC市场, 资本开支",
        "default_limit": 10,
        "default_max_analyze": 3,
        "notes": "Bill Gurley & Brad Gerstner，深度科技投资分析",
    },
    {
        "youtube_channel_id": "@LatentSpacePod",
        "url": "https://www.youtube.com/@LatentSpacePod",
        "name": "Latent Space",
        "tags": ["ai", "ai-engineering", "models", "agents", "infra", "developer-tools"],
        "priority": "core",
        "default_focus": "AI工程, AI基础设施, Agent, 模型工具链, 开发者生态",
        "default_limit": 10,
        "default_max_analyze": 3,
        "notes": "swyx & Alessio，AI 工程与开发者工具深度访谈",
    },
    {
        "youtube_channel_id": "@AcquiredFM",
        "url": "https://www.youtube.com/@AcquiredFM",
        "name": "Acquired",
        "tags": ["business", "tech", "strategy", "company", "moat", "deep-dive"],
        "priority": "core",
        "default_focus": "科技公司, 商业模式, 护城河, 长期竞争力, 资本市场",
        "default_limit": 5,
        "default_max_analyze": 1,
        "notes": "Ben Gilbert & David Rosenthal，科技公司深度剖析，单集超长（2-4h），精选分析",
    },
]


def seed_default_channels(
    session: Session,
    channel_pack: str = "tech_ai",
) -> dict:
    """播种默认 Tech/AI 频道包。幂等+自愈：按 youtube_channel_id 去重，
    已存在但配置为空/默认值的自动补齐，已有自定义配置的 skip。"""
    if channel_pack != "tech_ai":
        return {"added": 0, "updated": 0, "skipped": 0, "errors": [f"Unknown channel pack: {channel_pack}"]}

    added = 0
    updated = 0
    skipped = 0
    errors = []

    for cfg in DEFAULT_TECH_AI_CHANNELS:
        try:
            existing = (
                session.query(Channel)
                .filter_by(youtube_channel_id=cfg["youtube_channel_id"])
                .first()
            )
            if existing:
                # 自愈：空 tags 或默认 priority 的频道补齐配置
                existing_tags = _parse_tags(existing.tags)
                needs_update = (
                    not existing_tags
                    or existing.priority == "secondary"
                )
                if needs_update:
                    if not existing_tags:
                        existing.tags = json.dumps(cfg["tags"], ensure_ascii=False)
                    if existing.priority == "secondary":
                        existing.priority = cfg["priority"]
                    if not existing.default_focus:
                        existing.default_focus = cfg["default_focus"]
                    if existing.default_limit == 10:
                        existing.default_limit = cfg["default_limit"]
                    if existing.default_max_analyze == 3:
                        existing.default_max_analyze = cfg["default_max_analyze"]
                    if not existing.notes:
                        existing.notes = cfg["notes"]
                    updated += 1
                else:
                    skipped += 1
                continue

            ch = Channel(
                youtube_channel_id=cfg["youtube_channel_id"],
                name=cfg["name"],
                url=cfg["url"],
                tags=json.dumps(cfg["tags"], ensure_ascii=False),
                priority=cfg["priority"],
                default_focus=cfg["default_focus"],
                default_limit=cfg["default_limit"],
                default_max_analyze=cfg["default_max_analyze"],
                notes=cfg["notes"],
            )
            session.add(ch)
            added += 1
        except Exception as e:
            errors.append(f"{cfg['youtube_channel_id']}: {e}")

    session.flush()
    return {"added": added, "updated": updated, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# Channel Videos
# ---------------------------------------------------------------------------

def upsert_videos(
    session: Session,
    channel_id: int,
    videos: list[dict],
) -> int:
    """插入新视频（按 video_id 去重），返回新增数量。"""
    added = 0
    for v in videos:
        existing = (
            session.query(ChannelVideo)
            .filter_by(channel_id=channel_id, video_id=v["video_id"])
            .first()
        )
        if existing:
            continue
        cv = ChannelVideo(
            channel_id=channel_id,
            video_id=v["video_id"],
            title=v.get("title", ""),
            url=v.get("url", ""),
            published_at=v.get("published_at", ""),
            duration_seconds=v.get("duration_seconds", 0),
            status="new",
        )
        session.add(cv)
        added += 1
    session.flush()
    return added


def list_channel_videos(
    session: Session,
    channel_id: int,
    limit: int = 50,
    status: str | None = None,
) -> list[dict]:
    """列出频道下的视频。"""
    q = session.query(ChannelVideo).filter_by(channel_id=channel_id)
    if status:
        q = q.filter_by(status=status)
    q = q.order_by(ChannelVideo.published_at.desc(), ChannelVideo.added_at.desc()).limit(limit)
    rows = q.all()

    results = []
    for cv in rows:
        results.append({
            "id": cv.id,
            "channel_id": cv.channel_id,
            "video_id": cv.video_id,
            "title": cv.title,
            "url": cv.url,
            "published_at": cv.published_at,
            "duration_seconds": cv.duration_seconds,
            "status": cv.status,
            "report_id": cv.report_id,
            "added_at": cv.added_at,
        })
    return results


def mark_video_status(
    session: Session,
    video_id: str,
    status: str,
    report_id: int | None = None,
) -> bool:
    """更新视频状态（analyzed / skipped）。返回是否找到并更新。"""
    cv = session.query(ChannelVideo).filter_by(video_id=video_id).first()
    if not cv:
        return False
    cv.status = status
    if report_id is not None:
        cv.report_id = report_id
    session.flush()
    return True


def get_channel_video_by_video_id(session: Session, video_id: str) -> dict | None:
    """按 video_id 联表查询 channel + channel_video 完整元数据。

    返回 None 表示该 video_id 未在 channel_videos 表中注册。
    用于 channels analyze-video 时传递频道元数据到 pipeline。
    """
    row = (
        session.query(ChannelVideo, Channel)
        .join(Channel, ChannelVideo.channel_id == Channel.id)
        .filter(ChannelVideo.video_id == video_id)
        .first()
    )
    if not row:
        return None
    cv, ch = row
    return {
        "channel_name": ch.name,
        "channel_url": ch.url,
        "channel_tags": _parse_tags(ch.tags),
        "channel_priority": ch.priority,
        "channel_default_focus": ch.default_focus,
        "video_title": cv.title,
        "video_id": cv.video_id,
        "video_url": cv.url or f"https://www.youtube.com/watch?v={cv.video_id}",
        "published_at": cv.published_at,
        "duration_seconds": cv.duration_seconds,
        "status": cv.status,
        "report_id": cv.report_id,
        "channel_id": ch.id,
    }


def get_video(session: Session, video_id: str) -> dict | None:
    """按 video_id 查找视频记录。"""
    cv = session.query(ChannelVideo).filter_by(video_id=video_id).first()
    if not cv:
        return None
    return {
        "id": cv.id,
        "channel_id": cv.channel_id,
        "video_id": cv.video_id,
        "title": cv.title,
        "url": cv.url,
        "published_at": cv.published_at,
        "duration_seconds": cv.duration_seconds,
        "status": cv.status,
        "report_id": cv.report_id,
    }
