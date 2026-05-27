import json
from datetime import datetime

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