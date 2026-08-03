"""M4-B.3: Graph Sync Service — incremental knowledge graph synchronization.

Triggers on report generation: syncs entities, views, signals, evidence, and
claims into the knowledge graph incrementally, without requiring a full rebuild.

Edge classification:
  Deterministic (confidence 1.0): mentioned_in, derived_from, contains, tracks, cites
  Inferred (confidence < 1.0):   supports, contradicts (from Claim relationships)

Design principles:
- Reuses existing knowledge_graph node/edge builders for consistency
- Incremental: syncs only one report at a time
- Idempotent: re-syncing the same report is safe (upsert semantics)
- Graph-first: Graph is the core value, not an afterthought
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from signalvault.db.knowledge_graph import (
    _node_exists,
    _upsert_edge,
    _upsert_node,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Incremental sync — single report
# ═══════════════════════════════════════════════════════════════════════════════


def sync_report_to_graph(report_id: int, session: Session | None = None) -> dict:
    """Incrementally sync a single report to the knowledge graph.

    Creates/updates:
      - Report node
      - Entity nodes (from views) + mentioned_in edges
      - View nodes + derived_from edges
      - Signal nodes + derived_from + tracks edges
      - Evidence nodes + cites edges
      - Claim nodes + claim edges (supports/contradicts — inferred)

    All operations use upsert semantics — safe to call multiple times.

    Args:
        report_id: The report ID to sync.
        session: DB session (creates its own if None).

    Returns:
        Stats dict with node/edge counts.
    """
    if session is None:
        from signalvault.db.session import get_session
        session = get_session()
        _owns = True
    else:
        _owns = False

    stats = {
        "nodes_created": 0,
        "nodes_updated": 0,
        "edges_created": 0,
        "deterministic_edges": 0,
        "inferred_edges": 0,
        "claims_synced": 0,
    }

    try:
        # 1. Report node
        _sync_report_node(session, report_id, stats)

        # 2. View nodes + entity nodes + edges (deterministic)
        _sync_views(session, report_id, stats)

        # 3. Signal nodes + edges (deterministic)
        _sync_signals(session, report_id, stats)

        # 4. Evidence nodes + cites edges (deterministic)
        _sync_evidence(session, report_id, stats)

        # 5. Claim nodes + inferred edges
        _sync_claims(session, report_id, stats)

        # 6. Source document links
        _sync_source_document_links(session, report_id, stats)

        session.commit()

        logger.info(
            "Graph sync for report %d: %d nodes, %d edges (%d deterministic, %d inferred)",
            report_id,
            stats["nodes_created"],
            stats["edges_created"],
            stats["deterministic_edges"],
            stats["inferred_edges"],
        )

    except Exception:
        session.rollback()
        logger.exception("Graph sync failed for report %d", report_id)
        raise
    finally:
        if _owns:
            session.close()

    return stats


# ── Stage builders ───────────────────────────────────────────────────────────


def _sync_report_node(session: Session, report_id: int, stats: dict) -> None:
    """Create/update the report node."""
    from signalvault.db.models import Episode, Report

    report = session.query(Report).filter_by(id=report_id).first()
    if not report:
        return

    episode = session.query(Episode).filter_by(id=report.episode_id).first()

    key = f"report:{report_id}"
    source_type = "youtube"
    if episode:
        if episode.source == "pdf_upload":
            source_type = "pdf_upload"
        elif episode.source == "zsxq_topic":
            source_type = "zsxq_topic"

    existing = _node_exists(session, key)
    _upsert_node(
        session, key, "report",
        label=(episode.title if episode else f"Report #{report_id}"),
        source_ref=key,
        metadata={
            "report_id": report_id,
            "source_type": source_type,
            "video_id": episode.video_id if episode else "",
            "title": episode.title if episode else "",
        },
    )
    if not existing:
        stats["nodes_created"] += 1


def _sync_views(session: Session, report_id: int, stats: dict) -> None:
    """Sync investment views and their entity nodes + edges."""
    from signalvault.db.models import InvestmentViewRecord

    views = (
        session.query(InvestmentViewRecord)
        .filter_by(report_id=report_id)
        .all()
    )

    for view in views:
        # View node
        view_key = f"investment_view:{view.id}"
        if not _node_exists(session, view_key):
            _upsert_node(
                session, view_key, "investment_view",
                label=view.target_name or f"View #{view.id}",
                source_ref=view_key,
                metadata={
                    "view_id": view.id, "report_id": view.report_id,
                    "target_name": view.target_name,
                    "view_direction": view.view_direction,
                    "evidence_page": view.evidence_page,
                    "timestamp_start": view.timestamp_start,
                },
            )
            stats["nodes_created"] += 1

        # Entity node (from target_name)
        ent_name = (view.normalized_target_name or view.target_name).lower().strip()
        if ent_name:
            ent_key = f"entity:{ent_name}"
            ent_type = view.target_type or "company"
            if ent_type not in ("company", "topic", "person", "technology"):
                ent_type = "company"
            if ent_type == "technology":
                ent_type = "topic"

            if not _node_exists(session, ent_key):
                _upsert_node(
                    session, ent_key, ent_type,
                    label=view.target_name,
                    source_ref=f"entity:from_view:{view.id}",
                    metadata={"entity_name": view.target_name, "entity_type": ent_type},
                )
                stats["nodes_created"] += 1

            # mentioned_in edge: entity → report
            edge_key = f"mentioned_in:{ent_key}>report:{report_id}"
            if not _edge_exists(session, edge_key):
                _upsert_edge(
                    session, edge_key, ent_key, f"report:{report_id}",
                    "mentioned_in", weight=1.0, report_id=report_id,
                )
                stats["edges_created"] += 1
                stats["deterministic_edges"] += 1

        # derived_from edge: view → report
        edge_key = f"derived_from:{view_key}>report:{report_id}"
        if not _edge_exists(session, edge_key):
            _upsert_edge(
                session, edge_key, view_key, f"report:{report_id}",
                "derived_from", weight=1.0,
                evidence_ref=f"view:{view.id}",
                report_id=report_id,
                page_number=view.evidence_page,
                timestamp=view.timestamp_start,
            )
            stats["edges_created"] += 1
            stats["deterministic_edges"] += 1


def _sync_signals(session: Session, report_id: int, stats: dict) -> None:
    """Sync tracking signals and their edges."""
    from signalvault.db.models import TrackingSignalRecord

    signals = (
        session.query(TrackingSignalRecord)
        .filter_by(report_id=report_id)
        .all()
    )

    for sig in signals:
        # Signal node
        sig_key = f"tracking_signal:{sig.id}"
        if not _node_exists(session, sig_key):
            _upsert_node(
                session, sig_key, "tracking_signal",
                label=sig.target_name or f"Signal #{sig.id}",
                source_ref=sig_key,
                metadata={
                    "signal_id": sig.id, "report_id": sig.report_id,
                    "target_name": sig.target_name, "status": sig.status,
                },
            )
            stats["nodes_created"] += 1

        # derived_from edge: signal → report
        edge_key = f"derived_from:{sig_key}>report:{report_id}"
        if not _edge_exists(session, edge_key):
            _upsert_edge(
                session, edge_key, sig_key, f"report:{report_id}",
                "derived_from", weight=1.0,
                evidence_ref=f"signal:{sig.id}",
                report_id=report_id,
                timestamp=sig.timestamp,
            )
            stats["edges_created"] += 1
            stats["deterministic_edges"] += 1

        # tracks edge: signal → entity
        ent_name = sig.target_name.lower().strip()
        if ent_name:
            ent_key = f"entity:{ent_name}"
            if _node_exists(session, ent_key):
                edge_key = f"tracks:{sig_key}>{ent_key}"
                if not _edge_exists(session, edge_key):
                    _upsert_edge(
                        session, edge_key, sig_key, ent_key,
                        "tracks", weight=1.0,
                        evidence_ref=f"signal:{sig.id}",
                        report_id=report_id,
                    )
                    stats["edges_created"] += 1
                    stats["deterministic_edges"] += 1


def _sync_evidence(session: Session, report_id: int, stats: dict) -> None:
    """Sync evidence nodes and cites edges."""
    from signalvault.db.models import InvestmentViewRecord

    views = (
        session.query(InvestmentViewRecord)
        .filter_by(report_id=report_id)
        .filter(
            InvestmentViewRecord.source_quote.is_not(None),
            InvestmentViewRecord.source_quote != "",
        )
        .all()
    )

    for view in views:
        if view.evidence_page:
            ev_key = f"evidence:report:{report_id}:page:{view.evidence_page}"
            edge_type = "cites_page"
        elif view.timestamp_start:
            ev_key = f"evidence:report:{report_id}:ts:{view.timestamp_start}"
            edge_type = "cites_timestamp"
        else:
            ev_key = f"evidence:view:{view.id}"
            edge_type = "cites_page"

        # Evidence node
        if not _node_exists(session, ev_key):
            _upsert_node(
                session, ev_key, "evidence",
                label=(view.source_quote or "")[:200],
                source_ref=f"view:{view.id}",
                metadata={
                    "view_id": view.id, "report_id": report_id,
                    "page_number": view.evidence_page,
                    "timestamp": view.timestamp_start,
                    "source_quote": (view.source_quote or "")[:200],
                },
            )
            stats["nodes_created"] += 1

        # cites edge: evidence → report
        edge_key = f"{edge_type}:{ev_key}>report:{report_id}"
        if not _edge_exists(session, edge_key):
            _upsert_edge(
                session, edge_key, ev_key, f"report:{report_id}",
                edge_type, weight=1.0,
                evidence_ref=f"view:{view.id}",
                report_id=report_id,
                page_number=view.evidence_page,
                timestamp=view.timestamp_start,
            )
            stats["edges_created"] += 1
            stats["deterministic_edges"] += 1


def _sync_claims(session: Session, report_id: int, stats: dict) -> None:
    """Sync claim nodes and their inferred edges (supports / contradicts).

    Claims are first-class graph nodes. This stage:
      1. Creates claim nodes from the claims table
      2. Builds inferred edges between claims (supports/contradicts)
    """
    from signalvault.db.models import Claim

    claims = session.query(Claim).filter_by(source_report_id=report_id).all()

    for claim in claims:
        # Claim node
        claim_key = f"claim:{claim.id}"
        if not _node_exists(session, claim_key):
            _upsert_node(
                session, claim_key, "claim",
                label=claim.claim_text[:200],
                source_ref=f"claim:{claim.id}",
                metadata={
                    "claim_id": claim.id,
                    "claim_type": claim.claim_type,
                    "confidence": claim.confidence,
                    "source_report_id": claim.source_report_id,
                    "source_view_id": claim.source_view_id,
                },
            )
            stats["nodes_created"] += 1

        # derived_from edge: claim → report
        edge_key = f"derived_from:{claim_key}>report:{report_id}"
        if not _edge_exists(session, edge_key):
            _upsert_edge(
                session, edge_key, claim_key, f"report:{report_id}",
                "derived_from", weight=claim.confidence,
                evidence_ref=f"claim:{claim.id}",
                report_id=report_id,
            )
            stats["edges_created"] += 1
            stats["deterministic_edges"] += 1

        # Inferred: find similar claims and create supports/contradicts edges
        _build_claim_inferred_edges(session, claim, stats)

    stats["claims_synced"] = len(claims)


def _build_claim_inferred_edges(
    session: Session,
    claim,
    stats: dict,
) -> None:
    """Build inferred edges (supports/contradicts) for a claim.

    Strategy: keyword-based heuristic matching.
      - Same target entity + same direction → supports
      - Same target entity + opposite direction → contradicts

    This is a lightweight heuristic; future M4-E can use embedding similarity.
    """
    from signalvault.db.models import Claim

    claim_key = f"claim:{claim.id}"

    # Find other claims mentioning the same entities
    # Extract simple entity names from claim text (capitalized words)
    import re
    entities = set(re.findall(r'[一-鿿]{2,8}|[A-Z][a-z]{2,}', claim.claim_text))

    if not entities:
        return

    # Find other claims with overlapping entities
    other_claims = (
        session.query(Claim)
        .filter(
            Claim.id != claim.id,
            Claim.source_report_id != claim.source_report_id,
        )
        .all()
    )

    for other in other_claims:
        other_entities = set(re.findall(
            r'[一-鿿]{2,8}|[A-Z][a-z]{2,}', other.claim_text
        ))
        overlap = entities & other_entities

        if not overlap:
            continue

        other_key = f"claim:{other.id}"

        # Determine relationship type
        if claim.claim_type == "prediction" and other.claim_type == "prediction":
            # Simple heuristic: if both predict same direction → supports
            # If opposite → contradicts
            bullish_words = {"看多", "bullish", "利好", "增长", "上涨", "增持", "买入"}
            bearish_words = {"看空", "bearish", "利空", "下跌", "下降", "减持", "卖出"}

            claim_is_bullish = any(w in claim.claim_text for w in bullish_words)
            claim_is_bearish = any(w in claim.claim_text for w in bearish_words)
            other_is_bullish = any(w in other.claim_text for w in bullish_words)
            other_is_bearish = any(w in other.claim_text for w in bearish_words)

            if claim_is_bullish and other_is_bearish or claim_is_bearish and other_is_bullish:
                edge_type = "contradicts"
                confidence = 0.6
            elif (claim_is_bullish and other_is_bullish) or (claim_is_bearish and other_is_bearish):
                edge_type = "supports"
                confidence = 0.7
            else:
                continue
        else:
            # Non-prediction claims: if same entities → related
            edge_type = "related_to"
            confidence = 0.5

        edge_key = f"{edge_type}:{claim_key}>{other_key}"
        if not _edge_exists(session, edge_key):
            _upsert_edge(
                session, edge_key, claim_key, other_key,
                edge_type, weight=confidence,
                evidence_ref=f"claim:{claim.id}",
                report_id=claim.source_report_id,
                metadata={
                    "is_deterministic": False,
                    "confidence": confidence,
                    "inference_method": "keyword_heuristic",
                    "shared_entities": list(overlap),
                },
            )
            stats["edges_created"] += 1
            stats["inferred_edges"] += 1


def _sync_source_document_links(
    session: Session, report_id: int, stats: dict
) -> None:
    """Link report to its SourceDocument in the graph."""
    from signalvault.db.models import Episode, Report, SourceDocument

    report = session.query(Report).filter_by(id=report_id).first()
    if not report:
        return

    episode = session.query(Episode).filter_by(id=report.episode_id).first()
    if not episode:
        return

    # Try to find the SourceDocument for this episode
    source_doc = None
    if episode.video_id:
        # YouTube transcript
        source_doc = (
            session.query(SourceDocument)
            .filter(SourceDocument.source_url.contains(episode.video_id))
            .first()
        )
    elif episode.source_url:
        source_doc = (
            session.query(SourceDocument)
            .filter_by(source_url=episode.source_url)
            .first()
        )

    if source_doc:
        # source_of edge: SourceDocument → report
        src_key = f"source_document:{source_doc.source_doc_id}"
        if _node_exists(session, src_key):
            edge_key = f"source_of:{source_doc.source_doc_id}>report:{report_id}"
            if not _edge_exists(session, edge_key):
                _upsert_edge(
                    session, edge_key, src_key, f"report:{report_id}",
                    "source_of", weight=1.0, report_id=report_id,
                    source_type=source_doc.source_type,
                    source_path=source_doc.source_path,
                )
                stats["edges_created"] += 1
                stats["deterministic_edges"] += 1


# ── Helpers ──────────────────────────────────────────────────────────────────


def _edge_exists(session: Session, edge_key: str) -> bool:
    """Check if a knowledge edge already exists."""
    from signalvault.db.models import KnowledgeEdge
    return session.query(KnowledgeEdge).filter_by(edge_key=edge_key).first() is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Batch sync — all reports
# ═══════════════════════════════════════════════════════════════════════════════


def sync_all_reports(session: Session | None = None) -> dict:
    """Incrementally sync all existing reports to the knowledge graph.

    Unlike rebuild_knowledge_graph(), this is incremental: it only adds
    nodes/edges that don't already exist. Safe to run periodically.

    Returns aggregate stats.
    """
    if session is None:
        from signalvault.db.session import get_session
        session = get_session()
        _owns = True
    else:
        _owns = False

    from signalvault.db.models import Report

    reports = session.query(Report).all()
    aggregate = {
        "reports_processed": 0,
        "nodes_created": 0,
        "edges_created": 0,
        "deterministic_edges": 0,
        "inferred_edges": 0,
        "claims_synced": 0,
        "errors": [],
    }

    for report in reports:
        try:
            stats = sync_report_to_graph(report.id, session=session)
            aggregate["reports_processed"] += 1
            aggregate["nodes_created"] += stats["nodes_created"]
            aggregate["edges_created"] += stats["edges_created"]
            aggregate["deterministic_edges"] += stats["deterministic_edges"]
            aggregate["inferred_edges"] += stats["inferred_edges"]
            aggregate["claims_synced"] += stats["claims_synced"]
        except Exception as e:
            aggregate["errors"].append({
                "report_id": report.id,
                "error": str(e),
            })

    if _owns:
        session.close()

    logger.info(
        "Batch graph sync: %d reports, %d nodes, %d edges",
        aggregate["reports_processed"],
        aggregate["nodes_created"],
        aggregate["edges_created"],
    )
    return aggregate


# ── Convenience function ─────────────────────────────────────────────────────

def sync_report(report_id: int) -> dict:
    """Sync a single report to the knowledge graph.

    Shortcut for sync_report_to_graph() with automatic session management.
    """
    return sync_report_to_graph(report_id)
