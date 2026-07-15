"""P5-A: Unified search engine — FTS5 + LIKE fallback + metadata filters.

Searches across reports, investment_views, tracking_signals, and entities
with a single query, returning normalized UnifiedSearchResult objects.

Graceful fallback: if FTS5 is unavailable, falls back to multi-table LIKE.
Metadata filters (source_type, entity_type, view_direction, etc.) are
applied on top of the text search layer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import or_
from sqlalchemy.orm import Session

from signalvault.db.models import (
    EntityRecord,
    InvestmentViewRecord,
    Report,
    TrackingSignalRecord,
)

logger = logging.getLogger(__name__)

# ── Unified Search Result ───────────────────────────────────────────────────


@dataclass
class UnifiedSearchResult:
    """Normalized search result across all content types."""
    result_type: str = ""        # "report" | "investment_view" | "tracking_signal" | "entity"
    title: str = ""
    snippet: str = ""
    relevance_score: float = 0.0
    matched_fields: list[str] = field(default_factory=list)

    # Source traceability
    report_id: int | None = None
    source_type: str = ""        # "youtube" | "pdf_upload" | "local"
    source_path: str = ""        # video_url or pdf source_path
    source_title: str = ""       # episode title or pdf file_name
    video_url: str = ""
    channel_name: str = ""

    # Evidence positioning
    timestamp: str = ""          # "00:12:30" or "p.12"
    page_number: int | None = None
    source_quote: str = ""

    # Entity context
    entity_name: str = ""
    entity_type: str = ""        # "company" | "topic" | "technology" | "person" | "stock"

    # View/Signal context
    view_direction: str = ""     # "bullish" | "bearish" | "neutral"
    signal_status: str = ""      # "open" | "triggered" | "resolved"

    # Source Provenance (SourceDocument / SourceSegment)
    source_doc_id: str = ""
    segment_id: str = ""
    segment_type: str = ""       # "timestamp" | "paragraph" | "page" | "topic_body" | "comment"
    heading_path: str = ""

    # Extra metadata
    metadata: dict = field(default_factory=dict)

    # Internal: raw DB id for dedup
    _dedup_key: str = field(default="", repr=False)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _clean_snippet(text: str, keyword: str, max_len: int = 200) -> str:
    """Extract a keyword-relevant snippet, truncated and cleaned."""
    if not text:
        return ""
    # Strip markdown formatting
    import re
    clean = re.sub(r"[|\-*#_`]{1,}", " ", text)
    clean = re.sub(r"\s+", " ", clean).strip()

    kw_lower = keyword.lower()
    idx = clean.lower().find(kw_lower)
    if idx < 0:
        return clean[:max_len]

    start = max(0, idx - 60)
    end = min(len(clean), idx + len(keyword) + 60)
    snippet = clean[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(clean):
        snippet = snippet + "..."
    return snippet[:max_len]


def _score_from_matches(matched_fields: list[str], keyword: str) -> float:
    """Compute a lightweight relevance score from matched fields."""
    score = 0.0
    kw_lower = keyword.lower()
    for fname in matched_fields:
        fname_lower = fname.lower()
        if "target_name" in fname_lower or "entity" in fname_lower:
            if kw_lower in fname_lower:
                score += 0.3  # Exact entity match is high-value
        elif "source_quote" in fname_lower:
            score += 0.25
        elif "logic_chain" in fname_lower:
            score += 0.2
        elif "report_markdown" in fname_lower or "title" in fname_lower:
            score += 0.15
        else:
            score += 0.1
    return min(score, 1.0)


# ── LIKE Fallback Search ────────────────────────────────────────────────────


def _unified_search_like(
    session: Session,
    keyword: str,
    result_types: list[str] | None = None,
    source_type: str = "all",
    entity_type: str | None = None,
    view_direction: str = "all",
    signal_status: str = "all",
    limit: int = 20,
) -> list[UnifiedSearchResult]:
    """Multi-table LIKE search — fallback when FTS5 is unavailable."""

    from signalvault.db.models import Episode

    pattern = f"%{keyword}%"
    results: list[UnifiedSearchResult] = []
    seen: set[str] = set()
    types = set(result_types) if result_types else {"report", "investment_view", "tracking_signal", "entity"}

    kw_lower = keyword.lower()

    # 1. Reports
    if "report" in types and source_type != "pdf_upload":
        rows = (
            session.query(Report, Episode)
            .join(Episode, Report.episode_id == Episode.id)
            .filter(
                or_(
                    Report.report_markdown.like(pattern),
                    Report.executive_summary.like(pattern),
                )
            )
            .order_by(Report.analysis_timestamp.desc())
            .limit(limit * 2)
            .all()
        )
        for report, episode in rows:
            key = f"report:{report.id}"
            if key in seen:
                continue
            seen.add(key)
            st = _infer_source_type(episode)
            if source_type != "all" and st != source_type:
                continue
            snippet = _clean_snippet(report.report_markdown or "", keyword)
            matched = ["report_markdown"] if kw_lower in (report.report_markdown or "").lower() else ["executive_summary"]
            results.append(UnifiedSearchResult(
                result_type="report",
                title=episode.title or episode.video_id or f"Report #{report.id}",
                snippet=snippet,
                relevance_score=_score_from_matches(matched, keyword),
                matched_fields=matched,
                report_id=report.id,
                source_type=st,
                source_path=episode.source_url or "",
                source_title=episode.title or "",
                video_url=episode.source_url if st == "youtube" else "",
                channel_name="",
                _dedup_key=key,
            ))

    # 2. Investment Views
    if "investment_view" in types:
        rows = (
            session.query(InvestmentViewRecord, Report, Episode)
            .join(Report, InvestmentViewRecord.report_id == Report.id)
            .join(Episode, Report.episode_id == Episode.id)
            .filter(
                or_(
                    InvestmentViewRecord.target_name.like(pattern),
                    InvestmentViewRecord.logic_chain.like(pattern),
                    InvestmentViewRecord.source_quote.like(pattern),
                    InvestmentViewRecord.evidence_detail.like(pattern),
                )
            )
            .order_by(InvestmentViewRecord.created_at.desc())
            .limit(limit * 2)
            .all()
        )
        for view, report, episode in rows:
            key = f"view:{view.id}"
            if key in seen:
                continue
            seen.add(key)
            st = _infer_source_type(episode)
            if source_type != "all" and st != source_type:
                continue
            if entity_type and view.target_type != entity_type:
                continue
            if view_direction != "all" and view.view_direction != view_direction:
                continue
            matched = []
            texts = {
                "target_name": view.target_name,
                "logic_chain": view.logic_chain,
                "source_quote": view.source_quote,
                "evidence_detail": view.evidence_detail,
            }
            for field_name, text in texts.items():
                if text and kw_lower in text.lower():
                    matched.append(field_name)
            snippet_text = view.logic_chain or view.source_quote or ""
            snippet = _clean_snippet(snippet_text, keyword)
            results.append(UnifiedSearchResult(
                result_type="investment_view",
                title=view.target_name or "Investment View",
                snippet=snippet,
                relevance_score=_score_from_matches(matched, keyword),
                matched_fields=matched,
                report_id=report.id,
                source_type=st,
                source_path=episode.source_url or "",
                source_title=episode.title or "",
                video_url=episode.source_url if st == "youtube" else "",
                timestamp=view.timestamp_start or "",
                page_number=view.evidence_page,
                source_quote=(view.source_quote or "")[:200],
                entity_name=view.target_name or "",
                entity_type=view.target_type or "",
                view_direction=view.view_direction or "",
                _dedup_key=key,
            ))

    # 3. Tracking Signals
    if "tracking_signal" in types:
        rows = (
            session.query(TrackingSignalRecord, Report, Episode)
            .join(Report, TrackingSignalRecord.report_id == Report.id)
            .join(Episode, Report.episode_id == Episode.id)
            .filter(
                or_(
                    TrackingSignalRecord.target_name.like(pattern),
                    TrackingSignalRecord.signal.like(pattern),
                    TrackingSignalRecord.trigger_condition.like(pattern),
                    TrackingSignalRecord.source_quote.like(pattern),
                )
            )
            .order_by(TrackingSignalRecord.created_at.desc())
            .limit(limit * 2)
            .all()
        )
        for signal, report, episode in rows:
            key = f"signal:{signal.id}"
            if key in seen:
                continue
            seen.add(key)
            st = _infer_source_type(episode)
            if source_type != "all" and st != source_type:
                continue
            if signal_status != "all" and signal.status != signal_status:
                continue
            matched = []
            texts = {
                "target_name": signal.target_name,
                "signal": signal.signal,
                "trigger_condition": signal.trigger_condition,
                "source_quote": signal.source_quote,
            }
            for field_name, text in texts.items():
                if text and kw_lower in text.lower():
                    matched.append(field_name)
            snippet = _clean_snippet(signal.signal or signal.trigger_condition or "", keyword)
            results.append(UnifiedSearchResult(
                result_type="tracking_signal",
                title=signal.target_name or "Signal",
                snippet=snippet,
                relevance_score=_score_from_matches(matched, keyword),
                matched_fields=matched,
                report_id=report.id,
                source_type=st,
                source_path=episode.source_url or "",
                source_title=episode.title or "",
                video_url=episode.source_url if st == "youtube" else "",
                timestamp=signal.timestamp or "",
                source_quote=(signal.source_quote or "")[:200],
                entity_name=signal.target_name or "",
                signal_status=signal.status or "",
                _dedup_key=key,
            ))

    # 4. Entities
    if "entity" in types:
        rows = (
            session.query(EntityRecord)
            .filter(
                or_(
                    EntityRecord.name.like(pattern),
                    EntityRecord.normalized_name.like(pattern),
                    EntityRecord.aliases.like(pattern),
                )
            )
            .order_by(EntityRecord.id.desc())
            .limit(limit * 2)
            .all()
        )
        for entity in rows:
            key = f"entity:{entity.id}"
            if key in seen:
                continue
            seen.add(key)
            if entity_type and entity.entity_type != entity_type:
                continue
            snippet = entity.name
            aliases = _parse_aliases(entity.aliases)
            if aliases:
                snippet += f" (aka {', '.join(aliases[:3])})"
            results.append(UnifiedSearchResult(
                result_type="entity",
                title=entity.name or entity.normalized_name or "",
                snippet=snippet,
                relevance_score=0.6 if kw_lower == (entity.name or "").lower() else 0.4,
                matched_fields=["name"],
                entity_name=entity.name or "",
                entity_type=entity.entity_type or "",
                _dedup_key=key,
            ))

    # 5. Source Documents (by title/url)
    if "source_document" in types:
        from signalvault.db.models import SourceDocument as SD
        rows = (
            session.query(SD)
            .filter(
                or_(
                    SD.title.like(pattern),
                    SD.source_url.like(pattern),
                    SD.canonical_url.like(pattern),
                )
            )
            .order_by(SD.created_at.desc())
            .limit(limit * 2)
            .all()
        )
        for doc in rows:
            key = f"source_document:{doc.source_doc_id}"
            if key in seen:
                continue
            seen.add(key)
            snippet = _clean_snippet(doc.title or doc.source_url or "", keyword)
            results.append(UnifiedSearchResult(
                result_type="source_document",
                title=doc.title or doc.source_url or "",
                snippet=snippet,
                relevance_score=0.3,
                matched_fields=["title"],
                source_type=doc.source_type,
                source_path=doc.source_path or "",
                source_title=doc.title,
                source_doc_id=doc.source_doc_id,
                metadata={
                    "source_doc_id": doc.source_doc_id,
                    "canonical_url": doc.canonical_url,
                    "status": doc.status,
                    "language": doc.language,
                },
                _dedup_key=key,
            ))

    # 6. Source Segments (by text content)
    if "source_segment" in types:
        from signalvault.db.models import SourceDocument as SD
        from signalvault.db.models import SourceSegment as SS
        rows = (
            session.query(SS, SD)
            .join(SD, SS.source_doc_id == SD.source_doc_id)
            .filter(
                or_(
                    SS.text_original.like(pattern),
                    SS.text_normalized.like(pattern),
                    SS.text_translated.like(pattern),
                )
            )
            .order_by(SS.sequence_index)
            .limit(limit * 2)
            .all()
        )
        for seg, doc in rows:
            key = f"source_segment:{seg.id}"
            if key in seen:
                continue
            seen.add(key)
            text = seg.text_original or seg.text_normalized or ""
            snippet = _clean_snippet(text, keyword)
            results.append(UnifiedSearchResult(
                result_type="source_segment",
                title=doc.title or f"Segment #{seg.sequence_index}",
                snippet=snippet,
                relevance_score=0.25,
                matched_fields=["text"],
                source_type=doc.source_type,
                source_path=doc.source_path or "",
                source_doc_id=seg.source_doc_id,
                segment_id=seg.segment_id,
                segment_type=seg.segment_type,
                timestamp=seg.start_time,
                page_number=seg.page_number,
                heading_path=seg.heading_path or "",
                source_quote=text[:200],
                metadata={
                    "paragraph_index": seg.paragraph_index,
                    "translation_status": seg.translation_status,
                },
                _dedup_key=key,
            ))

    # Sort by relevance_score descending
    results.sort(key=lambda r: r.relevance_score, reverse=True)
    return results[:limit]


def _infer_source_type(episode) -> str:
    if episode is None:
        return "local"
    if episode.video_id:
        return "youtube"
    if episode.source_url and ("youtube.com" in episode.source_url or "youtu.be" in episode.source_url):
        return "youtube"
    # Check if this is a PDF source
    if episode.source == "pdf_upload":
        return "pdf_upload"
    # P6-A2: ZSXQ topic source
    if episode.source == "zsxq_topic":
        return "zsxq_topic"
    return "local"


def _parse_aliases(raw: str) -> list[str]:
    import json as _json
    if not raw:
        return []
    try:
        return _json.loads(raw)
    except (_json.JSONDecodeError, TypeError):
        return []


# ── FTS5 Search ─────────────────────────────────────────────────────────────


def _unified_search_fts(
    session: Session,
    keyword: str,
    result_types: list[str] | None = None,
    source_type: str = "all",
    entity_type: str | None = None,
    view_direction: str = "all",
    signal_status: str = "all",
    limit: int = 20,
) -> list[UnifiedSearchResult] | None:
    """FTS5-based unified search. Returns None if FTS is unavailable."""
    from signalvault.db.fts import search_fts

    types = set(result_types) if result_types else {"report", "investment_view", "tracking_signal", "entity"}
    if "report" not in types:
        # FTS currently only indexes reports — fall through to LIKE for other types
        return None

    fts_results = search_fts(session, keyword, limit=limit * 2)
    if fts_results is None:
        return None

    from signalvault.db.models import Episode

    results: list[UnifiedSearchResult] = []
    report_ids = [r["report_id"] for r in fts_results]
    reports_map = {r.id: r for r in session.query(Report).filter(Report.id.in_(report_ids)).all()}
    episodes_map = {}
    for rep in reports_map.values():
        ep = session.query(Episode).filter_by(id=rep.episode_id).first()
        if ep:
            episodes_map[rep.id] = ep

    for fts_item in fts_results:
        rid = fts_item["report_id"]
        rep = reports_map.get(rid)
        ep = episodes_map.get(rid)
        if not rep:
            continue
        st = _infer_source_type(ep)
        if source_type != "all" and st != source_type:
            continue

        key = f"report:{rid}"
        snippet = fts_item.get("match_excerpt", "")[:200]
        results.append(UnifiedSearchResult(
            result_type="report",
            title=ep.title or ep.video_id or f"Report #{rid}" if ep else f"Report #{rid}",
            snippet=snippet,
            relevance_score=min(1.0, 1.0 / (1 + (fts_item.get("score", 1) or 1) * 0.1)),
            matched_fields=["report_markdown"],
            report_id=rid,
            source_type=st,
            source_path=ep.source_url if ep else "",
            source_title=ep.title if ep else "",
            video_url=ep.source_url if ep and st == "youtube" else "",
            _dedup_key=key,
        ))

    # If only reports requested, return FTS results
    if types == {"report"}:
        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:limit]

    # For mixed types, supplement with LIKE search for non-report types
    non_report_types = types - {"report"}
    like_results = _unified_search_like(
        session, keyword,
        result_types=list(non_report_types),
        source_type=source_type,
        entity_type=entity_type,
        view_direction=view_direction,
        signal_status=signal_status,
        limit=limit,
    )
    results.extend(like_results)
    results.sort(key=lambda r: r.relevance_score, reverse=True)
    return results[:limit]


# ── Public API ──────────────────────────────────────────────────────────────


def unified_search(
    session: Session,
    keyword: str,
    result_types: list[str] | None = None,
    source_type: str = "all",
    entity_type: str | None = None,
    view_direction: str = "all",
    signal_status: str = "all",
    limit: int = 20,
) -> list[UnifiedSearchResult]:
    """Unified search across reports, views, signals, and entities.

    Tries FTS5 first; falls back to multi-table LIKE if FTS5 is unavailable.
    Metadata filters are applied on top of text search results.

    Args:
        session: SQLAlchemy session.
        keyword: Search query.
        result_types: List of types to include. Default: all four.
        source_type: "youtube" | "pdf_upload" | "local" | "all".
        entity_type: Entity type filter.
        view_direction: "bullish" | "bearish" | "neutral" | "all".
        signal_status: "open" | "triggered" | "resolved" | "all".
        limit: Max results (default 20, max 100).

    Returns:
        List of UnifiedSearchResult, sorted by relevance_score descending.
    """
    limit = min(max(1, limit), 100)  # clamp to 1–100

    if not keyword or not keyword.strip():
        return []

    keyword = keyword.strip()

    # Try FTS5 first
    fts_results = _unified_search_fts(
        session, keyword,
        result_types=result_types,
        source_type=source_type,
        entity_type=entity_type,
        view_direction=view_direction,
        signal_status=signal_status,
        limit=limit,
    )
    if fts_results is not None:
        return fts_results

    # Fallback to LIKE
    logger.info("FTS5 unavailable, using LIKE fallback for unified search")
    return _unified_search_like(
        session, keyword,
        result_types=result_types,
        source_type=source_type,
        entity_type=entity_type,
        view_direction=view_direction,
        signal_status=signal_status,
        limit=limit,
    )


# ── JSON Serialization ──────────────────────────────────────────────────────


def serialize_unified_result(r: UnifiedSearchResult) -> dict:
    """Serialize a UnifiedSearchResult to a JSON-safe dict."""
    return {
        "result_type": r.result_type,
        "title": r.title,
        "snippet": r.snippet,
        "relevance_score": round(r.relevance_score, 3),
        "matched_fields": r.matched_fields,
        "report_id": r.report_id,
        "source_type": r.source_type,
        "source_path": r.source_path,
        "source_title": r.source_title,
        "video_url": r.video_url,
        "channel_name": r.channel_name,
        "timestamp": r.timestamp,
        "page_number": r.page_number,
        "source_quote": r.source_quote,
        "entity_name": r.entity_name,
        "entity_type": r.entity_type,
        "view_direction": r.view_direction,
        "signal_status": r.signal_status,
        "source_doc_id": r.source_doc_id,
        "segment_id": r.segment_id,
        "segment_type": r.segment_type,
        "heading_path": r.heading_path,
        "metadata": r.metadata,
    }
