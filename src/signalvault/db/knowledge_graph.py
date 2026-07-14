"""P5-B: Lightweight knowledge graph — SQLite-based node/edge store.

Provides rebuild, entity neighborhood, evidence trail, edge listing,
and JSON export. No external graph DB dependencies.
"""

from __future__ import annotations

import json as _json
import logging
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from signalvault.db.models import (
    Channel,
    EntityRecord,
    Episode,
    InvestmentViewRecord,
    KnowledgeEdge,
    KnowledgeNode,
    Report,
    TrackingSignalRecord,
)

logger = logging.getLogger(__name__)

# ── Node/Edge type constants ────────────────────────────────────────────────

NODE_TYPES = frozenset({
    "report", "source", "company", "topic", "person",
    "investment_view", "tracking_signal", "evidence",
})

EDGE_TYPES = frozenset({
    "mentioned_in", "derived_from", "supports", "related_to",
    "tracks", "cites_page", "cites_timestamp",
})


# ═════════════════════════════════════════════════════════════════════════════
# Rebuild
# ═════════════════════════════════════════════════════════════════════════════


def rebuild_knowledge_graph(session: Session) -> dict:
    """Full rebuild of the knowledge graph from existing DB tables.

    Idempotent: clears existing nodes/edges, then rebuilds from scratch.
    Uses node_key/edge_key dedup to prevent duplicates on re-run.

    Returns:
        {"nodes": count, "edges": count, "node_types": {...}, "edge_types": {...}}
    """
    # Clear
    session.query(KnowledgeEdge).delete()
    session.query(KnowledgeNode).delete()
    session.flush()

    # Build nodes
    _build_report_nodes(session)
    _build_source_nodes(session)
    _build_entity_nodes(session)
    _build_view_nodes(session)
    _build_signal_nodes(session)
    _build_evidence_nodes(session)
    _build_source_document_nodes(session)
    _build_source_segment_nodes(session)

    # Build edges
    _build_mentioned_in_edges(session)
    _build_derived_from_edges(session)
    _build_tracks_edges(session)
    _build_cites_edges(session)
    _build_contains_edges(session)

    session.commit()

    node_count = session.query(func.count(KnowledgeNode.id)).scalar() or 0
    edge_count = session.query(func.count(KnowledgeEdge.id)).scalar() or 0

    node_type_counts = dict(session.query(
        KnowledgeNode.node_type, func.count(KnowledgeNode.id),
    ).group_by(KnowledgeNode.node_type).all())

    edge_type_counts = dict(session.query(
        KnowledgeEdge.edge_type, func.count(KnowledgeEdge.id),
    ).group_by(KnowledgeEdge.edge_type).all())

    logger.info("Graph rebuilt: %d nodes, %d edges", node_count, edge_count)
    return {
        "nodes": node_count,
        "edges": edge_count,
        "node_types": node_type_counts,
        "edge_types": edge_type_counts,
    }


# ── Node builders ───────────────────────────────────────────────────────────


def _upsert_node(session: Session, node_key: str, node_type: str,
                 label: str = "", source_ref: str = "", metadata: dict | None = None):
    """Insert or skip a node by node_key."""
    existing = session.query(KnowledgeNode).filter_by(node_key=node_key).first()
    if existing:
        return existing
    node = KnowledgeNode(
        node_key=node_key,
        node_type=node_type,
        label=label[:500],
        normalized_label=label.lower().strip()[:500],
        source_ref=source_ref[:200],
        metadata_json=_json.dumps(metadata or {}, ensure_ascii=False),
    )
    session.add(node)
    session.flush()
    return node


def _build_report_nodes(session: Session) -> int:
    count = 0
    for report, episode in (
        session.query(Report, Episode)
        .join(Episode, Report.episode_id == Episode.id).all()
    ):
        key = f"report:{report.id}"
        st = "youtube" if episode.video_id else ("pdf_upload" if episode.source == "pdf_upload" else "local")
        _upsert_node(session, key, "report",
                     label=episode.title or f"Report #{report.id}",
                     source_ref=key,
                     metadata={"report_id": report.id, "source_type": st,
                               "video_id": episode.video_id, "title": episode.title})
        count += 1
    return count


def _build_source_nodes(session: Session) -> int:
    count = 0
    seen: set[str] = set()
    # YouTube channels
    for ch in session.query(Channel).filter(Channel.is_active).all():
        key = f"source:channel:{ch.youtube_channel_id}"
        if key in seen:
            continue
        seen.add(key)
        _upsert_node(session, key, "source",
                     label=ch.name or ch.youtube_channel_id,
                     source_ref=f"channel:{ch.id}",
                     metadata={"channel_id": ch.id, "url": ch.url, "source_type": "youtube"})
        count += 1
    # PDF sources (from episodes with source=pdf_upload)
    for ep in session.query(Episode).filter(Episode.source == "pdf_upload").all():
        key = f"source:pdf:{ep.source_url or ep.id}"
        if key in seen:
            continue
        seen.add(key)
        _upsert_node(session, key, "source",
                     label=ep.title or ep.source_url or f"PDF #{ep.id}",
                     source_ref=f"episode:{ep.id}",
                     metadata={"episode_id": ep.id, "source_type": "pdf_upload",
                               "source_url": ep.source_url})
        count += 1
    # P6-A2: ZSXQ topic sources (from episodes with source=zsxq_topic)
    for ep in session.query(Episode).filter(Episode.source == "zsxq_topic").all():
        key = f"source:zsxq:{ep.source_url or ep.id}"
        if key in seen:
            continue
        seen.add(key)
        _upsert_node(session, key, "source",
                     label=ep.title or ep.source_url or f"ZSXQ #{ep.id}",
                     source_ref=f"episode:{ep.id}",
                     metadata={"episode_id": ep.id, "source_type": "zsxq_topic",
                               "source_url": ep.source_url})
        count += 1
    return count


def _build_entity_nodes(session: Session) -> int:
    count = 0
    for ent in session.query(EntityRecord).all():
        etype = ent.entity_type or "company"
        if etype not in ("company", "topic", "person", "technology", "stock"):
            etype = "company"
        if etype == "technology":
            etype = "topic"  # normalize
        if etype == "stock":
            etype = "company"
        key = f"entity:{ent.normalized_name.lower()}" if ent.normalized_name else f"entity:{ent.name.lower()}"
        _upsert_node(session, key, etype,
                     label=ent.name,
                     source_ref=f"entity:{ent.id}",
                     metadata={"entity_id": ent.id, "name": ent.name,
                               "normalized_name": ent.normalized_name, "entity_type": ent.entity_type})
        count += 1
    return count


def _build_view_nodes(session: Session) -> int:
    count = 0
    for v in session.query(InvestmentViewRecord).all():
        key = f"investment_view:{v.id}"
        _upsert_node(session, key, "investment_view",
                     label=v.target_name or f"View #{v.id}",
                     source_ref=key,
                     metadata={"view_id": v.id, "report_id": v.report_id,
                               "target_name": v.target_name,
                               "view_direction": v.view_direction,
                               "evidence_page": v.evidence_page,
                               "timestamp_start": v.timestamp_start})
        count += 1
    return count


def _build_signal_nodes(session: Session) -> int:
    count = 0
    for s in session.query(TrackingSignalRecord).all():
        key = f"tracking_signal:{s.id}"
        _upsert_node(session, key, "tracking_signal",
                     label=s.target_name or f"Signal #{s.id}",
                     source_ref=key,
                     metadata={"signal_id": s.id, "report_id": s.report_id,
                               "target_name": s.target_name, "status": s.status})
        count += 1
    return count


def _build_evidence_nodes(session: Session) -> int:
    count = 0
    for v in session.query(InvestmentViewRecord).filter(
        (InvestmentViewRecord.source_quote.is_not(None)) & (InvestmentViewRecord.source_quote != "")
    ).all():
        if v.evidence_page:
            key = f"evidence:report:{v.report_id}:page:{v.evidence_page}"
        elif v.timestamp_start:
            key = f"evidence:report:{v.report_id}:ts:{v.timestamp_start}"
        else:
            key = f"evidence:view:{v.id}"
        _upsert_node(session, key, "evidence",
                     label=(v.source_quote or "")[:200],
                     source_ref=f"view:{v.id}",
                     metadata={"view_id": v.id, "report_id": v.report_id,
                               "page_number": v.evidence_page,
                               "timestamp": v.timestamp_start,
                               "source_quote": (v.source_quote or "")[:200]})
        count += 1
    return count


# ── Edge builders ───────────────────────────────────────────────────────────


def _upsert_edge(session: Session, edge_key: str, source_key: str, target_key: str,
                 edge_type: str, weight: float = 1.0, evidence_ref: str = "",
                 report_id: int | None = None, source_type: str = "",
                 source_path: str = "", page_number: int | None = None,
                 timestamp: str = "", metadata: dict | None = None):
    existing = session.query(KnowledgeEdge).filter_by(edge_key=edge_key).first()
    if existing:
        return existing
    edge = KnowledgeEdge(
        edge_key=edge_key,
        source_node_key=source_key,
        target_node_key=target_key,
        edge_type=edge_type,
        weight=weight,
        evidence_ref=evidence_ref[:200],
        report_id=report_id,
        source_type=source_type[:20],
        source_path=source_path[:500],
        page_number=page_number,
        timestamp=timestamp[:20],
        metadata_json=_json.dumps(metadata or {}, ensure_ascii=False),
    )
    session.add(edge)
    session.flush()
    return edge


# ── Source Provenance node/edge builders ──────────────────────────────────


def _build_source_document_nodes(session: Session) -> int:
    from signalvault.db.models import SourceDocument as SD
    count = 0
    for doc in session.query(SD).all():
        key = f"source_document:{doc.source_doc_id}"
        _upsert_node(session, key, "source_document",
                     label=doc.title or doc.source_url or doc.source_doc_id,
                     source_ref=key,
                     metadata={
                         "source_doc_id": doc.source_doc_id,
                         "source_type": doc.source_type,
                         "status": doc.status,
                     })
        count += 1
    return count


def _build_source_segment_nodes(session: Session) -> int:
    from signalvault.db.models import SourceSegment as SS, SourceDocument as SD
    count = 0
    for seg, doc in (
        session.query(SS, SD)
        .join(SD, SS.source_doc_id == SD.source_doc_id).all()
    ):
        key = f"source_segment:{seg.source_doc_id}:{seg.sequence_index}"
        label = (doc.title or "Segment") + (f" [{seg.start_time}]" if seg.start_time else "")
        _upsert_node(session, key, "source_segment",
                     label=label[:500], source_ref=key,
                     metadata={
                         "source_doc_id": seg.source_doc_id,
                         "segment_type": seg.segment_type,
                         "page_number": seg.page_number,
                         "start_time": seg.start_time,
                     })
        count += 1
    return count


def _build_contains_edges(session: Session) -> int:
    from signalvault.db.models import SourceSegment as SS
    count = 0
    for seg in session.query(SS).all():
        src_key = f"source_document:{seg.source_doc_id}"
        tgt_key = f"source_segment:{seg.source_doc_id}:{seg.sequence_index}"
        if not _node_exists(session, src_key) or not _node_exists(session, tgt_key):
            continue
        edge_key = f"contains:{seg.source_doc_id}>{seg.sequence_index}"
        _upsert_edge(session, edge_key, src_key, tgt_key, "contains",
                     weight=0.5, source_type=seg.segment_type,
                     page_number=seg.page_number, timestamp=seg.start_time or "")
        count += 1
    return count


def _build_mentioned_in_edges(session: Session) -> int:
    count = 0
    # Entity → Report (via investment_views)
    for v in session.query(InvestmentViewRecord).all():
        ent_name = (v.normalized_target_name or v.target_name).lower().strip()
        if not ent_name:
            continue
        source_key = f"entity:{ent_name}"
        target_key = f"report:{v.report_id}"
        if not _node_exists(session, source_key) or not _node_exists(session, target_key):
            continue
        edge_key = f"mentioned_in:{source_key}>{target_key}"
        _upsert_edge(session, edge_key, source_key, target_key, "mentioned_in",
                     weight=1.0, report_id=v.report_id)
        count += 1
    return count


def _build_derived_from_edges(session: Session) -> int:
    count = 0
    # View → Report
    for v in session.query(InvestmentViewRecord).all():
        source_key = f"investment_view:{v.id}"
        target_key = f"report:{v.report_id}"
        if not _node_exists(session, target_key):
            continue
        edge_key = f"derived_from:{source_key}>{target_key}"
        _upsert_edge(session, edge_key, source_key, target_key, "derived_from",
                     weight=1.0, evidence_ref=f"view:{v.id}",
                     report_id=v.report_id,
                     page_number=v.evidence_page, timestamp=v.timestamp_start)
        count += 1
    # Signal → Report
    for s in session.query(TrackingSignalRecord).all():
        source_key = f"tracking_signal:{s.id}"
        target_key = f"report:{s.report_id}"
        if not _node_exists(session, target_key):
            continue
        edge_key = f"derived_from:{source_key}>{target_key}"
        _upsert_edge(session, edge_key, source_key, target_key, "derived_from",
                     weight=1.0, evidence_ref=f"signal:{s.id}",
                     report_id=s.report_id, timestamp=s.timestamp)
        count += 1
    return count


def _build_tracks_edges(session: Session) -> int:
    count = 0
    for s in session.query(TrackingSignalRecord).all():
        ent_name = s.target_name.lower().strip()
        if not ent_name:
            continue
        source_key = f"tracking_signal:{s.id}"
        target_key = f"entity:{ent_name}"
        if not _node_exists(session, target_key):
            continue
        edge_key = f"tracks:{source_key}>{target_key}"
        _upsert_edge(session, edge_key, source_key, target_key, "tracks",
                     weight=1.0, evidence_ref=f"signal:{s.id}",
                     report_id=s.report_id)
        count += 1
    return count


def _build_cites_edges(session: Session) -> int:
    count = 0
    for v in session.query(InvestmentViewRecord).filter(
        InvestmentViewRecord.source_quote.is_not(None),
        InvestmentViewRecord.source_quote != "",
    ).all():
        # Evidence → Report with page/timestamp info
        if v.evidence_page:
            ev_key = f"evidence:report:{v.report_id}:page:{v.evidence_page}"
            edge_type = "cites_page"
        elif v.timestamp_start:
            ev_key = f"evidence:report:{v.report_id}:ts:{v.timestamp_start}"
            edge_type = "cites_timestamp"
        else:
            ev_key = f"evidence:view:{v.id}"
            edge_type = "cites_page"  # fallback
        target_key = f"report:{v.report_id}"
        if not _node_exists(session, ev_key) or not _node_exists(session, target_key):
            continue
        edge_key = f"{edge_type}:{ev_key}>{target_key}"
        _upsert_edge(session, edge_key, ev_key, target_key, edge_type,
                     weight=1.0, evidence_ref=f"view:{v.id}",
                     report_id=v.report_id,
                     page_number=v.evidence_page, timestamp=v.timestamp_start)
        count += 1
    return count


def _node_exists(session: Session, node_key: str) -> bool:
    return session.query(KnowledgeNode).filter_by(node_key=node_key).first() is not None


# ═════════════════════════════════════════════════════════════════════════════
# Query API
# ═════════════════════════════════════════════════════════════════════════════


def get_entity_neighborhood(
    session: Session,
    entity_name: str,
    entity_type: str | None = None,
    depth: int = 1,
    limit: int = 50,
) -> dict:
    """Query the subgraph around an entity by name.

    Args:
        entity_name: Entity name (case-insensitive partial match on label).
        entity_type: Optional filter on node_type.
        depth: Neighborhood depth (1 = direct neighbors only).
        limit: Max neighbors to return.

    Returns:
        {"center": node_dict, "neighbors": [...], "edges": [...], "summary": {...}}
    """
    normalized = entity_name.lower().strip()
    query = session.query(KnowledgeNode).filter(
        KnowledgeNode.normalized_label.like(f"%{normalized}%"),
    )
    if entity_type:
        query = query.filter_by(node_type=entity_type)
    center = query.first()

    if not center:
        return {"center": None, "neighbors": [], "edges": [], "summary": {"total": 0}}

    # Find all edges connected to center
    edges = session.query(KnowledgeEdge).filter(
        (KnowledgeEdge.source_node_key == center.node_key)
        | (KnowledgeEdge.target_node_key == center.node_key),
    ).limit(limit).all()

    # Collect neighbor node keys
    neighbor_keys: set[str] = set()
    for e in edges:
        if e.source_node_key != center.node_key:
            neighbor_keys.add(e.source_node_key)
        if e.target_node_key != center.node_key:
            neighbor_keys.add(e.target_node_key)

    neighbors = session.query(KnowledgeNode).filter(
        KnowledgeNode.node_key.in_(neighbor_keys),
    ).limit(limit).all()

    return {
        "center": _node_to_dict(center),
        "neighbors": [_node_to_dict(n) for n in neighbors],
        "edges": [_edge_to_dict(e) for e in edges],
        "summary": {
            "total_connections": len(edges),
            "neighbor_count": len(neighbors),
            "depth": depth,
        },
    }


def get_evidence_trail(
    session: Session,
    view_id: int | None = None,
    signal_id: int | None = None,
) -> dict:
    """Trace the evidence chain for a view or signal.

    Returns the view/signal → evidence nodes → report → source chain.
    """
    if view_id:
        target_key = f"investment_view:{view_id}"
        target_type = "investment_view"
    elif signal_id:
        target_key = f"tracking_signal:{signal_id}"
        target_type = "tracking_signal"
    else:
        return {"target": None, "evidence": [], "report": None, "source": None}

    target_node = session.query(KnowledgeNode).filter_by(node_key=target_key).first()
    if not target_node:
        # Build node on the fly from DB
        target_node = _build_target_node_on_demand(session, target_type, view_id or signal_id)
    if not target_node:
        return {"target": None, "evidence": [], "report": None, "source": None}

    # Find evidence citations from views
    if view_id:
        view = session.query(InvestmentViewRecord).filter_by(id=view_id).first()
        evidence_items = []
        if view:
            evidence_items.append({
                "type": "citation",
                "page_number": view.evidence_page,
                "timestamp": view.timestamp_start,
                "source_quote": (view.source_quote or "")[:300],
                "source_type": "",
                "source_path": "",
            })

        # Find derived_from edges to reports
        report_edges = session.query(KnowledgeEdge).filter(
            KnowledgeEdge.source_node_key == target_key,
            KnowledgeEdge.edge_type == "derived_from",
        ).all()
        report_node = None
        source_node = None
        if report_edges:
            report_key = report_edges[0].target_node_key
            report_node = _node_to_dict(
                session.query(KnowledgeNode).filter_by(node_key=report_key).first()
            ) if session.query(KnowledgeNode).filter_by(node_key=report_key).first() else None

        return {
            "target": _node_to_dict(target_node),
            "evidence": evidence_items,
            "report": report_node,
            "source": source_node,
        }

    if signal_id:
        signal = session.query(TrackingSignalRecord).filter_by(id=signal_id).first()
        return {
            "target": _node_to_dict(target_node),
            "evidence": [{
                "type": "signal_tracking",
                "source_quote": (signal.source_quote or "")[:300] if signal else "",
                "timestamp": signal.timestamp if signal else "",
            }] if signal else [],
            "report": None,
            "source": None,
        }

    return {"target": _node_to_dict(target_node), "evidence": [], "report": None, "source": None}


def _build_target_node_on_demand(session, node_type, obj_id):
    """Build a node dict from DB when the graph node doesn't exist yet."""
    if node_type == "investment_view":
        v = session.query(InvestmentViewRecord).filter_by(id=obj_id).first()
        if v:
            return type('Node', (), {
                'node_key': f"investment_view:{v.id}",
                'node_type': 'investment_view',
                'label': v.target_name or '',
                'normalized_label': (v.target_name or '').lower(),
                'source_ref': f"view:{v.id}",
                'metadata_json': _json.dumps({"view_id": v.id, "report_id": v.report_id,
                    "target_name": v.target_name, "view_direction": v.view_direction}),
            })()
    elif node_type == "tracking_signal":
        s = session.query(TrackingSignalRecord).filter_by(id=obj_id).first()
        if s:
            return type('Node', (), {
                'node_key': f"tracking_signal:{s.id}",
                'node_type': 'tracking_signal',
                'label': s.target_name or '',
                'normalized_label': (s.target_name or '').lower(),
                'source_ref': f"signal:{s.id}",
                'metadata_json': _json.dumps({"signal_id": s.id, "report_id": s.report_id,
                    "target_name": s.target_name, "status": s.status}),
            })()
    return None


def list_graph_edges(
    session: Session,
    edge_type: str | None = None,
    entity_name: str | None = None,
    limit: int = 30,
) -> list[dict]:
    """List graph edges, optionally filtered by type or entity name."""
    q = session.query(KnowledgeEdge)
    if edge_type:
        q = q.filter_by(edge_type=edge_type)
    if entity_name:
        normalized = entity_name.lower().strip()
        # Find entity node keys
        entity_nodes = session.query(KnowledgeNode).filter(
            KnowledgeNode.normalized_label.like(f"%{normalized}%"),
        ).all()
        if entity_nodes:
            keys = [n.node_key for n in entity_nodes]
            q = q.filter(
                KnowledgeEdge.source_node_key.in_(keys)
                | KnowledgeEdge.target_node_key.in_(keys),
            )
        else:
            return []
    edges = q.order_by(KnowledgeEdge.id.desc()).limit(limit).all()
    return [_edge_to_dict(e) for e in edges]


def export_graph_json(session: Session) -> str:
    """Export the full graph as a JSON string."""
    nodes = [_node_to_dict(n) for n in session.query(KnowledgeNode).all()]
    edges = [_edge_to_dict(e) for e in session.query(KnowledgeEdge).all()]
    result = {
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "node_count": len(nodes),
            "edge_count": len(edges),
        },
    }
    return _json.dumps(result, ensure_ascii=False, indent=2)


# ── Serialization helpers ───────────────────────────────────────────────────


def _node_to_dict(node) -> dict:
    if node is None:
        return {}
    try:
        meta = _json.loads(node.metadata_json)
    except (_json.JSONDecodeError, TypeError):
        meta = {}
    return {
        "id": node.id,
        "node_key": node.node_key,
        "node_type": node.node_type,
        "label": node.label,
        "normalized_label": node.normalized_label,
        "source_ref": node.source_ref,
        "metadata": meta,
        "created_at": node.created_at.isoformat() if node.created_at else None,
        "updated_at": node.updated_at.isoformat() if node.updated_at else None,
    }


def _edge_to_dict(edge) -> dict:
    if edge is None:
        return {}
    try:
        meta = _json.loads(edge.metadata_json)
    except (_json.JSONDecodeError, TypeError):
        meta = {}
    return {
        "id": edge.id,
        "edge_key": edge.edge_key,
        "source_node_key": edge.source_node_key,
        "target_node_key": edge.target_node_key,
        "edge_type": edge.edge_type,
        "weight": edge.weight,
        "evidence_ref": edge.evidence_ref,
        "report_id": edge.report_id,
        "source_type": edge.source_type,
        "source_path": edge.source_path,
        "page_number": edge.page_number,
        "timestamp": edge.timestamp,
        "metadata": meta,
        "created_at": edge.created_at.isoformat() if edge.created_at else None,
    }
