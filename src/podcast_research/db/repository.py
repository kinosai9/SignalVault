import json
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from podcast_research.analysis.models import ExtractionResult, InvestmentView, TrackingSignal, Entity
from podcast_research.db.models import (
    Episode,
    Report,
    InvestmentViewRecord,
    TrackingSignalRecord,
    EntityRecord,
)


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
    for v in views:
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
    return "local"


def _parse_focus_areas(raw: str) -> list[str]:
    """安全解析 focus_areas JSON 字符串。"""
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


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
        "report_markdown": report.report_markdown,
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