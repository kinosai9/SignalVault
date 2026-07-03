import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from podcast_research.analysis.models import (
    Entity,
    ExtractionResult,
    InvestmentView,
    TrackingSignal,
)
from podcast_research.db.models import (
    EntityRecord,
    Episode,
    InvestmentViewRecord,
    Report,
    TrackingSignalRecord,
)
from podcast_research.utils.file_io import read_text_safe


def save_episode(
    session: Session,
    title: str,
    subtitle_path: str,
    subtitle_format: str,
    subtitle_hash: str,
    source: str = "local",
    source_url: str = "",
    video_id: str = "",
    language: str = "",
) -> int:
    ep = Episode(
        source=source,
        title=title,
        subtitle_path=subtitle_path,
        subtitle_format=subtitle_format,
        subtitle_hash=subtitle_hash,
        source_url=source_url,
        video_id=video_id,
        language=language,
    )
    session.add(ep)
    session.flush()
    return ep.id


def save_report(
    session: Session,
    episode_id: int,
    extraction: ExtractionResult,
    report_markdown: str,
    llm_provider: str = "mock",
    llm_model: str = "mock-v1",
    analysis_depth: str = "standard",
) -> int:
    rep = Report(
        episode_id=episode_id,
        focus_areas=json.dumps(extraction.focus_areas, ensure_ascii=False),
        analysis_depth=analysis_depth,
        llm_provider=llm_provider,
        llm_model=llm_model,
        extraction_json=json.dumps(extraction.model_dump(), ensure_ascii=False),
        report_markdown=report_markdown,
    )
    session.add(rep)
    session.flush()
    return rep.id


def save_investment_views(session: Session, report_id: int, views: list[InvestmentView]) -> None:
    # P2-N.1: Dedup by (target_name, view_direction) within same report
    seen: set[tuple[str, str]] = set()
    deduped: list[InvestmentView] = []
    for v in views:
        key = (v.target_name.strip().lower(), v.view_direction)
        if key not in seen:
            seen.add(key)
            deduped.append(v)
    for v in deduped:
        rec = InvestmentViewRecord(
            report_id=report_id,
            target_name=v.target_name,
            target_type=v.target_type,
            ticker=v.ticker,
            market=v.market,
            view_direction=v.view_direction,
            confidence=v.confidence,
            time_horizon=v.time_horizon,
            logic_chain=v.logic_chain,
            evidence_type=v.evidence.evidence_type,
            evidence_detail=v.evidence.evidence_detail,
            evidence_strength=v.evidence.evidence_strength,
            missing_info=v.evidence.missing_info,
            risk_warning=v.risk_warning,
            speaker_label=v.speaker_label,
            speaker_role=v.speaker_role,
            speaker_confidence=v.speaker_confidence,
            source_quote=v.source_quote,
            timestamp_start=v.timestamp_start,
            timestamp_end=v.timestamp_end,
            ai_value_chain_layer=v.ai_value_chain_layer,
            technology_driver=v.technology_driver,
            business_impact=v.business_impact,
            investment_relevance=v.investment_relevance,
            topic_tags=json.dumps(v.topic_tags, ensure_ascii=False),
            quote_support_strength=v.quote_support_strength,
            evidence_page=v.evidence.page_number,  # P4-B: PDF page number
        )
        session.add(rec)


def save_tracking_signals(session: Session, report_id: int, signals: list[TrackingSignal]) -> None:
    for s in signals:
        rec = TrackingSignalRecord(
            report_id=report_id,
            target_name=s.target_name,
            signal=s.signal,
            trigger_condition=s.trigger_condition,
            expected_date=s.expected_date,
            source_quote=s.source_quote,
            timestamp=s.timestamp,
        )
        session.add(rec)


def save_entities(session: Session, entities: list[Entity]) -> None:
    for e in entities:
        rec = EntityRecord(
            name=e.name,
            normalized_name=e.normalized_name or e.name,
            entity_type=e.entity_type,
            aliases=json.dumps(e.aliases, ensure_ascii=False) if e.aliases else "",
        )
        session.add(rec)


# ---------------------------------------------------------------------------
# 查询方法（P1-A）
# ---------------------------------------------------------------------------


def _infer_source_type(episode: Episode) -> str:
    """从 Episode 字段推断数据来源类型。"""
    if episode.video_id:
        return "youtube"
    if episode.source_url and ("youtube.com" in episode.source_url or "youtu.be" in episode.source_url):
        return "youtube"
    if episode.source == "pdf_upload":
        return "pdf_upload"
    if episode.source == "zsxq_topic":
        return "zsxq_topic"
    return "local"


def _parse_focus_areas(raw: str) -> list[str]:
    """安全解析 focus_areas JSON 字符串。"""
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def find_report_by_video_id(session: Session, video_id: str) -> dict | None:
    """Find the most recent report for a given YouTube video_id.

    Returns the latest report dict (id, created_at, episode_id) or None.
    Used to prevent duplicate analysis of the same video.
    """
    if not video_id:
        return None
    row = (
        session.query(Report, Episode)
        .join(Episode, Report.episode_id == Episode.id)
        .filter(Episode.video_id == video_id)
        .order_by(Report.analysis_timestamp.desc())
        .first()
    )
    if not row:
        return None
    report, episode = row
    return {
        "id": report.id,
        "episode_id": report.episode_id,
        "video_id": episode.video_id,
        "created_at": report.analysis_timestamp,
        "title": episode.title,
    }


def _count_views(session: Session, report_id: int) -> int:
    return session.query(func.count(InvestmentViewRecord.id)).filter_by(report_id=report_id).scalar() or 0


def _count_entities_in_extraction(extraction_json: str) -> int:
    """从 extraction_json 中统计实体数。"""
    try:
        data = json.loads(extraction_json)
        return len(data.get("mentioned_entities", []))
    except (json.JSONDecodeError, TypeError):
        return 0


def list_reports(
    session: Session,
    limit: int = 20,
    source_type: str | None = None,
) -> list[dict]:
    """列出报告摘要，按创建时间倒序。"""
    rows = (
        session.query(Report, Episode)
        .join(Episode, Report.episode_id == Episode.id)
        .order_by(Report.analysis_timestamp.desc())
        .limit(limit)
        .all()
    )
    results = []
    for report, episode in rows:
        st = _infer_source_type(episode)
        if source_type and st != source_type:
            continue
        title = episode.video_id or episode.title
        results.append({
            "id": report.id,
            "episode_title": title,
            "title": episode.title,
            "source_type": st,
            "video_id": episode.video_id,
            "source_url": episode.source_url,
            "language": episode.language,
            "created_at": report.analysis_timestamp,
            "focus_areas": _parse_focus_areas(report.focus_areas),
            "analysis_depth": report.analysis_depth,
            "view_count": _count_views(session, report.id),
            "entity_count": _count_entities_in_extraction(report.extraction_json),
        })
    return results


def get_report(session: Session, report_id: int) -> dict | None:
    """获取单个报告基本信息。"""
    row = (
        session.query(Report, Episode)
        .join(Episode, Report.episode_id == Episode.id)
        .filter(Report.id == report_id)
        .first()
    )
    if not row:
        return None
    report, episode = row
    return {
        "id": report.id,
        "episode_title": episode.video_id or episode.title,
        "source_type": _infer_source_type(episode),
        "source_url": episode.source_url,
        "video_id": episode.video_id,
        "language": episode.language,
        "focus_areas": _parse_focus_areas(report.focus_areas),
        "analysis_depth": report.analysis_depth,
        "llm_provider": report.llm_provider,
        "llm_model": report.llm_model,
        "created_at": report.analysis_timestamp,
        "view_count": _count_views(session, report.id),
        "entity_count": _count_entities_in_extraction(report.extraction_json),
        "report_markdown": report.report_markdown,
    }


def get_report_detail(session: Session, report_id: int) -> dict | None:
    """获取报告完整详情：报告 + Episode + 观点 + 信号。"""
    row = (
        session.query(Report, Episode)
        .join(Episode, Report.episode_id == Episode.id)
        .filter(Report.id == report_id)
        .first()
    )
    if not row:
        return None
    report, episode = row

    views = session.query(InvestmentViewRecord).filter_by(report_id=report_id).all()
    signals = session.query(TrackingSignalRecord).filter_by(report_id=report_id).all()

    return {
        "id": report.id,
        "episode_title": episode.video_id or episode.title,
        "source_type": _infer_source_type(episode),
        "source_url": episode.source_url,
        "video_id": episode.video_id,
        "language": episode.language,
        "focus_areas": _parse_focus_areas(report.focus_areas),
        "analysis_depth": report.analysis_depth,
        "llm_provider": report.llm_provider,
        "llm_model": report.llm_model,
        "created_at": report.analysis_timestamp,
        "extraction_json": report.extraction_json or "",
        "report_markdown": report.report_markdown or "",
        "views": [
            {
                "target_name": v.target_name,
                "normalized_target_name": v.normalized_target_name,
                "target_type": v.target_type,
                "view_direction": v.view_direction,
                "logic_chain": v.logic_chain,
                "source_quote": v.source_quote,
                "timestamp_start": v.timestamp_start,
                "risk_warning": v.risk_warning,
                "evidence_strength": v.evidence_strength,
                "evidence_type": v.evidence_type,
                "evidence_detail": v.evidence_detail,
                "confidence": v.confidence,
                "speaker_label": v.speaker_label,
                "time_horizon": v.time_horizon,
                "ai_value_chain_layer": v.ai_value_chain_layer,
                "business_impact": v.business_impact,
                "investment_relevance": v.investment_relevance,
                "quote_support_strength": v.quote_support_strength,
                "evidence_page": v.evidence_page,
            }
            for v in views
        ],
        "signals": [
            {
                "target_name": s.target_name,
                "signal": s.signal,
                "trigger_condition": s.trigger_condition,
                "source_quote": s.source_quote or "",
                "timestamp": s.timestamp or "",
            }
            for s in signals
        ],
    }


def search_reports(
    session: Session,
    keyword: str,
    limit: int = 20,
) -> list[dict]:
    """全文搜索报告。优先 FTS5，不可用时 fallback 到 LIKE。"""
    from podcast_research.db.fts import search_fts

    fts_results = search_fts(session, keyword, limit=limit)
    if fts_results is not None:
        # 用 Report 数据补充 created_at
        report_ids = [r["report_id"] for r in fts_results]
        reports_map = {
            r.id: r for r in session.query(Report).filter(Report.id.in_(report_ids)).all()
        }
        for item in fts_results:
            rep = reports_map.get(item["report_id"])
            item["created_at"] = rep.analysis_timestamp if rep else None
        return fts_results

    return _search_reports_like(session, keyword, limit=limit)


def _search_reports_like(
    session: Session,
    keyword: str,
    limit: int = 20,
) -> list[dict]:
    """LIKE 搜索报告（FTS5 不可用时的 fallback）。"""
    pattern = f"%{keyword}%"
    results: list[dict] = []
    seen_ids: set[int] = set()

    # 1. 搜索 report_markdown
    md_rows = (
        session.query(Report, Episode)
        .join(Episode, Report.episode_id == Episode.id)
        .filter(Report.report_markdown.like(pattern))
        .order_by(Report.analysis_timestamp.desc())
        .limit(limit)
        .all()
    )
    for report, episode in md_rows:
        if report.id in seen_ids:
            continue
        seen_ids.add(report.id)
        excerpt = _extract_excerpt(report.report_markdown, keyword)
        results.append({
            "report_id": report.id,
            "match_type": "like-fallback",
            "match_excerpt": excerpt,
            "source_type": _infer_source_type(episode),
            "created_at": report.analysis_timestamp,
        })

    # 2. 搜索 investment_views.target_name
    view_rows = (
        session.query(InvestmentViewRecord, Report, Episode)
        .join(Report, InvestmentViewRecord.report_id == Report.id)
        .join(Episode, Report.episode_id == Episode.id)
        .filter(InvestmentViewRecord.target_name.like(pattern))
        .order_by(Report.analysis_timestamp.desc())
        .limit(limit)
        .all()
    )
    for view, report, episode in view_rows:
        if report.id in seen_ids:
            continue
        seen_ids.add(report.id)
        results.append({
            "report_id": report.id,
            "match_type": "like-fallback",
            "match_excerpt": f"{view.target_name} ({view.view_direction})",
            "source_type": _infer_source_type(episode),
            "created_at": report.analysis_timestamp,
        })

    # 3. 搜索 investment_views.logic_chain
    lc_rows = (
        session.query(InvestmentViewRecord, Report, Episode)
        .join(Report, InvestmentViewRecord.report_id == Report.id)
        .join(Episode, Report.episode_id == Episode.id)
        .filter(InvestmentViewRecord.logic_chain.like(pattern))
        .order_by(Report.analysis_timestamp.desc())
        .limit(limit)
        .all()
    )
    for view, report, episode in lc_rows:
        if report.id in seen_ids:
            continue
        seen_ids.add(report.id)
        results.append({
            "report_id": report.id,
            "match_type": "like-fallback",
            "match_excerpt": view.logic_chain[:80],
            "source_type": _infer_source_type(episode),
            "created_at": report.analysis_timestamp,
        })

    return results[:limit]


def _extract_excerpt(text: str, keyword: str, context: int = 40) -> str:
    """从文本中提取关键词前后的上下文片段，清理 markdown 格式。"""
    if not text:
        return ""
    # 先清理 markdown 格式和 BMP 外字符，避免终端编码问题
    import re
    clean = re.sub(r"[|\-*#_`]{1,}", " ", text)  # 去除 markdown 格式符号
    clean = "".join(c for c in clean if ord(c) <= 0xFFFF)  # 去除 emoji 等 BMP 外字符
    clean = re.sub(r"\s+", " ", clean).strip()

    idx = clean.lower().find(keyword.lower())
    if idx < 0:
        return clean[:80]
    start = max(0, idx - context)
    end = min(len(clean), idx + len(keyword) + context)
    excerpt = clean[start:end].strip()
    if start > 0:
        excerpt = "..." + excerpt
    if end < len(clean):
        excerpt = excerpt + "..."
    return excerpt


def list_targets(session: Session, limit: int = 100) -> list[dict]:
    """汇总投资标的：出现次数、最近出现时间、最近观点方向。"""
    rows = (
        session.query(
            InvestmentViewRecord.target_name,
            func.count(InvestmentViewRecord.id).label("cnt"),
            func.max(InvestmentViewRecord.created_at).label("last_seen"),
        )
        .group_by(InvestmentViewRecord.target_name)
        .order_by(func.count(InvestmentViewRecord.id).desc())
        .limit(limit)
        .all()
    )
    results = []
    for target_name, cnt, last_seen in rows:
        last_view = (
            session.query(InvestmentViewRecord)
            .filter_by(target_name=target_name)
            .order_by(InvestmentViewRecord.created_at.desc())
            .first()
        )
        results.append({
            "target_name": target_name,
            "count": cnt,
            "last_seen": last_seen,
            "last_direction": last_view.view_direction if last_view else "",
        })
    return results


def list_entities(
    session: Session,
    entity_type: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """列出实体，可按类型过滤。"""
    from podcast_research.db.models import EntityRecord

    query = session.query(EntityRecord)
    if entity_type:
        query = query.filter_by(entity_type=entity_type)
    rows = query.order_by(EntityRecord.id.desc()).limit(limit).all()
    results = []
    for e in rows:
        aliases_raw = e.aliases or ""
        try:
            aliases = json.loads(aliases_raw) if aliases_raw else []
        except (json.JSONDecodeError, TypeError):
            aliases = []
        results.append({
            "name": e.name,
            "normalized_name": e.normalized_name or e.name,
            "entity_type": e.entity_type,
            "aliases": aliases,
        })
    return results


def list_sources(session: Session) -> list[dict]:
    """统计各来源报告数量和最近报告时间。"""
    rows = (
        session.query(Report, Episode)
        .join(Episode, Report.episode_id == Episode.id)
        .order_by(Report.analysis_timestamp.desc())
        .all()
    )
    source_map: dict[str, dict] = {}
    for report, episode in rows:
        st = _infer_source_type(episode)
        if st not in source_map:
            source_map[st] = {"source_type": st, "count": 0, "last_report_at": report.analysis_timestamp}
        source_map[st]["count"] += 1
    return list(source_map.values())


# ═════════════════════════════════════════════════════════════════════════════
# P2-M.1: Channel & ChannelVideo CRUD
# ═════════════════════════════════════════════════════════════════════════════

from podcast_research.db.models import (
    Channel,
    ChannelVideo,
    TrackedSource,
    TrackedSourceEntry,
)


def upsert_channel(
    session: Session,
    youtube_channel_id: str,
    name: str = "",
    url: str = "",
    tags: str = "[]",
    priority: str = "watch",
    default_focus: str = "",
    default_depth: str = "standard",
) -> int:
    """Insert or update a channel by youtube_channel_id. Returns channel id."""
    ch = session.query(Channel).filter_by(youtube_channel_id=youtube_channel_id).first()
    if ch:
        ch.name = name or ch.name
        ch.url = url or ch.url
        if tags and tags != "[]":
            ch.tags = tags
        if priority:
            ch.priority = priority
        if default_focus:
            ch.default_focus = default_focus
        if default_depth:
            ch.default_depth = default_depth
        ch.is_active = True
        session.flush()
        return ch.id
    else:
        ch = Channel(
            youtube_channel_id=youtube_channel_id,
            name=name,
            url=url,
            tags=tags,
            priority=priority,
            default_focus=default_focus,
            default_depth=default_depth,
            is_active=True,
        )
        session.add(ch)
        session.flush()
        return ch.id


def list_channels(session: Session, active_only: bool = False) -> list[dict]:
    """List all channels, optionally only active ones."""
    q = session.query(Channel).order_by(Channel.added_at.desc())
    if active_only:
        q = q.filter_by(is_active=True)
    results = []
    for ch in q.all():
        # Count videos per status
        video_counts = {}
        for row in session.query(
            ChannelVideo.status, func.count(ChannelVideo.id)
        ).filter_by(channel_id=ch.id).group_by(ChannelVideo.status).all():
            video_counts[row[0]] = row[1]
        results.append({
            "id": ch.id,
            "youtube_channel_id": ch.youtube_channel_id,
            "name": ch.name,
            "url": ch.url,
            "tags": ch.tags,
            "priority": ch.priority,
            "default_focus": ch.default_focus,
            "default_depth": ch.default_depth,
            "is_active": ch.is_active,
            "added_at": ch.added_at,
            "last_refreshed_at": ch.last_refreshed_at,
            "video_counts": video_counts,
            "total_videos": sum(video_counts.values()),
        })
    return results


def get_channel(session: Session, channel_id: int) -> dict | None:
    """Get a single channel by id."""
    ch = session.query(Channel).filter_by(id=channel_id).first()
    if not ch:
        return None
    return {
        "id": ch.id,
        "youtube_channel_id": ch.youtube_channel_id,
        "name": ch.name,
        "url": ch.url,
        "tags": ch.tags,
        "priority": ch.priority,
        "default_focus": ch.default_focus,
        "default_depth": ch.default_depth,
        "is_active": ch.is_active,
        "last_refreshed_at": ch.last_refreshed_at,
    }


def update_channel(
    session: Session,
    channel_id: int,
    name: str | None = None,
    priority: str | None = None,
    default_focus: str | None = None,
    default_depth: str | None = None,
) -> bool:
    """Update editable fields of a channel. Returns True if updated."""
    ch = session.query(Channel).filter_by(id=channel_id).first()
    if not ch:
        return False
    if name is not None:
        ch.name = name
    if priority is not None:
        ch.priority = priority
    if default_focus is not None:
        ch.default_focus = default_focus
    if default_depth is not None:
        ch.default_depth = default_depth
    session.flush()
    return True


def delete_channel(session: Session, channel_id: int) -> bool:
    """Soft-delete a channel by setting is_active=False. Returns True if deleted."""
    ch = session.query(Channel).filter_by(id=channel_id).first()
    if not ch:
        return False
    ch.is_active = False
    session.flush()
    return True


def upsert_channel_video(
    session: Session,
    channel_id: int,
    video_id: str,
    title: str = "",
    url: str = "",
    published_at: str = "",
    duration_seconds: int = 0,
) -> bool:
    """Insert or update a channel_video row. Returns True if new, False if upserted."""
    cv = session.query(ChannelVideo).filter_by(
        channel_id=channel_id, video_id=video_id
    ).first()
    if cv:
        cv.title = title or cv.title
        cv.url = url or cv.url
        cv.published_at = published_at or cv.published_at
        if duration_seconds:
            cv.duration_seconds = duration_seconds
        cv.last_checked_at = datetime.now()
        session.flush()
        return False  # upserted
    else:
        cv = ChannelVideo(
            channel_id=channel_id,
            video_id=video_id,
            title=title,
            url=url,
            published_at=published_at,
            duration_seconds=duration_seconds,
            status="new",
            last_checked_at=datetime.now(),
        )
        session.add(cv)
        session.flush()
        return True  # new


def list_channel_videos(
    session: Session,
    channel_id: int,
    status_filter: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """List videos for a channel, optionally filtered by status."""
    q = session.query(ChannelVideo).filter_by(channel_id=channel_id)
    if status_filter:
        q = q.filter_by(status=status_filter)
    q = q.order_by(ChannelVideo.published_at.desc())
    if limit:
        q = q.limit(limit)
    return [
        {
            "id": cv.id,
            "channel_id": cv.channel_id,
            "video_id": cv.video_id,
            "title": cv.title,
            "url": cv.url,
            "published_at": cv.published_at,
            "duration_seconds": cv.duration_seconds,
            "status": cv.status,
            "report_id": cv.report_id,
            "failure_reason": cv.failure_reason,
            "active_job_id": cv.active_job_id,
            "last_job_id": cv.last_job_id,
            "last_checked_at": cv.last_checked_at,
        }
        for cv in q.all()
    ]


def update_channel_video_status(
    session: Session,
    channel_video_id: int,
    status: str,
    report_id: int | None = None,
    failure_reason: str = "",
    active_job_id: str | None = None,
) -> None:
    """Update status and optionally report_id/active_job_id for a channel_video."""
    cv = session.query(ChannelVideo).filter_by(id=channel_video_id).first()
    if cv:
        cv.status = status
        cv.last_checked_at = datetime.now()
        if report_id is not None:
            cv.report_id = report_id
        if failure_reason:
            cv.failure_reason = failure_reason
        # P2-M.2: active_job_id — None means "clear", empty string means "don't change"
        if active_job_id is not None:
            cv.active_job_id = active_job_id if active_job_id else None
        session.flush()


def get_channel_video_by_video_id(session: Session, video_id: str) -> dict | None:
    """Get a channel_video row by video_id."""
    cv = session.query(ChannelVideo).filter_by(video_id=video_id).first()
    if not cv:
        return None
    return {
        "id": cv.id,
        "channel_id": cv.channel_id,
        "video_id": cv.video_id,
        "title": cv.title,
        "url": cv.url,
        "status": cv.status,
        "report_id": cv.report_id,
        "failure_reason": cv.failure_reason,
        "active_job_id": cv.active_job_id,
        "last_job_id": cv.last_job_id,
    }


def refresh_channel_timestamp(session: Session, channel_id: int) -> None:
    """Update last_refreshed_at for a channel."""
    ch = session.query(Channel).filter_by(id=channel_id).first()
    if ch:
        ch.last_refreshed_at = datetime.now()
        session.flush()


# ═════════════════════════════════════════════════════════════════════════════
# P2-M.1: Video import status detection
# ═════════════════════════════════════════════════════════════════════════════


def get_report_by_video_id(session: Session, video_id: str) -> dict | None:
    """Get a report dict by video_id via Report JOIN Episode."""
    ep = session.query(Episode).filter_by(video_id=video_id).first()
    if not ep:
        return None
    report = session.query(Report).filter_by(episode_id=ep.id).order_by(
        Report.analysis_timestamp.desc()
    ).first()
    if not report:
        return None
    return {
        "id": report.id,
        "episode_id": ep.id,
        "video_id": ep.video_id,
        "source_url": ep.source_url,
        "title": ep.title,
        "report_markdown": report.report_markdown,
        "analysis_timestamp": report.analysis_timestamp,
    }

def detect_video_import_status(
    session: Session,
    video_id: str,
    vault_path: str | None = None,
) -> str:
    """Detect the import status of a video across DB + Obsidian Vault.

    Checks:
        1. channel_videos table → returns stored status if present
        2. episodes.video_id → "analyzed"
        3. Obsidian 01_Reports/ frontmatter.video_id → "synced"
        4. Default → "new"

    Returns one of: "new", "processing", "analyzed", "synced", "skipped", "failed"
    """
    # 1. Check channel_videos for stored status
    cv = session.query(ChannelVideo).filter_by(video_id=video_id).first()
    if cv:
        if cv.status == "new" and cv.report_id is None:
            # Check if it's actually been analyzed since added to channel_videos
            ep = session.query(Episode).filter_by(video_id=video_id).first()
            if ep:
                report = session.query(Report).filter_by(episode_id=ep.id).first()
                if report:
                    return "analyzed"
        return cv.status if cv.status != "new" else "new"

    # 2. Check episodes table
    ep = session.query(Episode).filter_by(video_id=video_id).first()
    if ep:
        report = session.query(Report).filter_by(episode_id=ep.id).first()
        if report:
            # Check if synced to vault
            if vault_path:
                reports_dir = Path(vault_path) / "01_Reports"
                if reports_dir.exists():
                    for rf in reports_dir.glob("*.md"):
                        try:
                            content = read_text_safe(rf)
                            if f"video_id: {video_id}" in content:
                                return "synced"
                        except Exception:
                            pass
            return "analyzed"

    # 3. Check Obsidian vault (even if DB was cleared)
    if vault_path:
        reports_dir = Path(vault_path) / "01_Reports"
        if reports_dir.exists():
            for rf in reports_dir.glob("*.md"):
                try:
                    content = read_text_safe(rf)
                    if f"video_id: {video_id}" in content:
                        return "synced"
                except Exception:
                    pass

    return "new"


# ── P2-S.3.2: TrackedSource & TrackedSourceEntry CRUD ────────────────────


def create_tracked_source(
    session: Session,
    name: str,
    provider: str,
    homepage_url: str,
    adapter_name: str,
    source_kind: str = "external_html",
    default_import_policy: str = "",
    discovery_strategy: str = "",
    identity_strategy: str = "",
    change_detection_strategy: str = "",
    profile_confidence: float | None = None,
    profile_warnings: str = "",
) -> int:
    """Create a new TrackedSource. Returns its id."""
    ts = TrackedSource(
        name=name,
        provider=provider,
        source_kind=source_kind,
        homepage_url=homepage_url,
        adapter_name=adapter_name,
        default_import_policy=default_import_policy,
        discovery_strategy=discovery_strategy,
        identity_strategy=identity_strategy,
        change_detection_strategy=change_detection_strategy,
        profile_confidence=profile_confidence,
        profiled_at=datetime.now() if profile_confidence is not None else None,
        profile_warnings=profile_warnings,
    )
    session.add(ts)
    session.flush()
    return ts.id


def list_tracked_sources(session: Session, enabled_only: bool = False) -> list[dict]:
    """List all tracked sources with per-status entry counts."""
    q = session.query(TrackedSource).order_by(TrackedSource.created_at.desc())
    if enabled_only:
        q = q.filter_by(enabled=True)
    results = []
    for ts in q.all():
        entry_counts = {}
        for row in session.query(
            TrackedSourceEntry.status, func.count(TrackedSourceEntry.id)
        ).filter_by(tracked_source_id=ts.id).group_by(TrackedSourceEntry.status).all():
            entry_counts[row[0]] = row[1]
        results.append({
            "id": ts.id,
            "name": ts.name,
            "provider": ts.provider,
            "source_kind": ts.source_kind,
            "homepage_url": ts.homepage_url,
            "adapter_name": ts.adapter_name,
            "enabled": ts.enabled,
            "status": ts.status,
            "default_import_policy": ts.default_import_policy,
            "discovery_strategy": ts.discovery_strategy,
            "identity_strategy": ts.identity_strategy,
            "change_detection_strategy": ts.change_detection_strategy,
            "profile_confidence": ts.profile_confidence,
            "profiled_at": ts.profiled_at,
            "profile_warnings": ts.profile_warnings,
            "last_checked_at": ts.last_checked_at,
            "last_success_at": ts.last_success_at,
            "last_error": ts.last_error,
            "entries_discovered_count": ts.entries_discovered_count,
            "entries_imported_count": ts.entries_imported_count,
            "created_at": ts.created_at,
            "entry_counts": entry_counts,
        })
    return results


def get_tracked_source(session: Session, ts_id: int) -> dict | None:
    """Get a single tracked source by id."""
    ts = session.query(TrackedSource).filter_by(id=ts_id).first()
    if not ts:
        return None
    return {
        "id": ts.id,
        "name": ts.name,
        "provider": ts.provider,
        "source_kind": ts.source_kind,
        "homepage_url": ts.homepage_url,
        "adapter_name": ts.adapter_name,
        "enabled": ts.enabled,
        "status": ts.status,
        "default_import_policy": ts.default_import_policy,
        "discovery_strategy": ts.discovery_strategy,
        "identity_strategy": ts.identity_strategy,
        "change_detection_strategy": ts.change_detection_strategy,
        "profile_confidence": ts.profile_confidence,
        "profiled_at": ts.profiled_at,
        "profile_warnings": ts.profile_warnings,
        "last_checked_at": ts.last_checked_at,
        "last_success_at": ts.last_success_at,
        "last_error": ts.last_error,
        "entries_discovered_count": ts.entries_discovered_count,
        "entries_imported_count": ts.entries_imported_count,
        "created_at": ts.created_at,
    }


def update_tracked_source_status(
    session: Session,
    ts_id: int,
    status: str,
    last_error: str = "",
) -> bool:
    """Update the status of a tracked source. Returns True if found."""
    ts = session.query(TrackedSource).filter_by(id=ts_id).first()
    if not ts:
        return False
    ts.status = status
    ts.last_checked_at = datetime.now()
    if status == "active":
        ts.last_success_at = datetime.now()
        ts.last_error = ""
    elif last_error:
        ts.last_error = last_error
    session.flush()
    return True


def delete_tracked_source(session: Session, ts_id: int) -> bool:
    """Delete a tracked source and all its entries. Returns True if found."""
    ts = session.query(TrackedSource).filter_by(id=ts_id).first()
    if not ts:
        return False
    session.query(TrackedSourceEntry).filter_by(tracked_source_id=ts_id).delete()
    session.delete(ts)
    session.flush()
    return True


# ── TrackedSourceEntry CRUD ──────────────────────────────────────────────


def upsert_tracked_source_entry(
    session: Session,
    tracked_source_id: int,
    url: str,
    title: str = "",
    slug: str = "",
    published_at: str = "",
) -> tuple[int, bool]:
    """Insert or update a tracked source entry by URL. Returns (entry_id, is_new)."""
    entry = session.query(TrackedSourceEntry).filter_by(
        tracked_source_id=tracked_source_id, url=url,
    ).first()
    if entry:
        entry.title = title or entry.title
        entry.slug = slug or entry.slug
        entry.published_at = published_at or entry.published_at
        entry.last_seen_at = datetime.now()
        session.flush()
        return entry.id, False
    else:
        entry = TrackedSourceEntry(
            tracked_source_id=tracked_source_id,
            url=url,
            title=title,
            slug=slug,
            published_at=published_at,
            status="new",
            last_seen_at=datetime.now(),
        )
        session.add(entry)
        session.flush()
        return entry.id, True


def list_tracked_source_entries(
    session: Session,
    tracked_source_id: int,
    status_filter: str | None = None,
) -> list[dict]:
    """List entries for a tracked source, optionally filtered by status."""
    q = session.query(TrackedSourceEntry).filter_by(
        tracked_source_id=tracked_source_id,
    )
    if status_filter:
        q = q.filter_by(status=status_filter)
    q = q.order_by(TrackedSourceEntry.published_at.desc())
    return [
        {
            "id": e.id,
            "tracked_source_id": e.tracked_source_id,
            "title": e.title,
            "url": e.url,
            "slug": e.slug,
            "published_at": e.published_at,
            "detected_youtube_video_id": e.detected_youtube_video_id,
            "content_hash": e.content_hash,
            "status": e.status,
            "preview_id": e.preview_id,
            "last_seen_at": e.last_seen_at,
            "error_message": e.error_message,
        }
        for e in q.all()
    ]


def get_tracked_source_entry(session: Session, entry_id: int) -> dict | None:
    """Get a single entry by id."""
    e = session.query(TrackedSourceEntry).filter_by(id=entry_id).first()
    if not e:
        return None
    return {
        "id": e.id,
        "tracked_source_id": e.tracked_source_id,
        "title": e.title,
        "url": e.url,
        "slug": e.slug,
        "published_at": e.published_at,
        "detected_youtube_video_id": e.detected_youtube_video_id,
        "content_hash": e.content_hash,
        "status": e.status,
        "preview_id": e.preview_id,
        "last_seen_at": e.last_seen_at,
        "error_message": e.error_message,
    }


def update_tracked_source_entry_status(
    session: Session,
    entry_id: int,
    status: str,
    preview_id: str | None = None,
    detected_youtube_video_id: str = "",
    content_hash: str | None = None,
    error_message: str = "",
) -> None:
    """Update status and optional metadata for a tracked source entry."""
    e = session.query(TrackedSourceEntry).filter_by(id=entry_id).first()
    if not e:
        return
    e.status = status
    if preview_id is not None:
        e.preview_id = preview_id if preview_id else None
    if detected_youtube_video_id:
        e.detected_youtube_video_id = detected_youtube_video_id
    if content_hash is not None:
        e.content_hash = content_hash
    if error_message:
        e.error_message = error_message
    session.flush()
