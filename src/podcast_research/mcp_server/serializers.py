"""JSON-safe serialization helpers for MCP tool responses.

All functions accept ORM objects or dicts and return JSON-serializable
dicts with datetime → ISO string conversion and sensible defaults.
"""

from __future__ import annotations

from datetime import datetime


def _iso(dt: datetime | None) -> str | None:
    """Convert datetime to ISO string, or None."""
    if dt is None:
        return None
    return dt.isoformat()


def serialize_report_summary(r: dict) -> dict:
    """Serialize a report summary dict (from list_reports / search_reports)."""
    return {
        "id": r.get("id") or r.get("report_id"),
        "title": r.get("episode_title") or r.get("title") or "",
        "source_type": r.get("source_type", ""),
        "video_id": r.get("video_id", ""),
        "source_url": r.get("source_url", ""),
        "channel": r.get("channel", ""),
        "language": r.get("language", ""),
        "focus_areas": r.get("focus_areas", []) or [],
        "analysis_depth": r.get("analysis_depth", ""),
        "view_count": r.get("view_count", 0),
        "entity_count": r.get("entity_count", 0),
        "created_at": _iso(r.get("created_at")),
        "match_excerpt": r.get("match_excerpt", ""),
        "match_type": r.get("match_type", ""),
    }


def serialize_report_detail(d: dict) -> dict:
    """Serialize a full report detail dict (from get_report_detail)."""
    return {
        "id": d.get("id"),
        "title": d.get("episode_title") or "",
        "source_type": d.get("source_type", ""),
        "source_url": d.get("source_url", ""),
        "video_id": d.get("video_id", ""),
        "language": d.get("language", ""),
        "focus_areas": d.get("focus_areas", []) or [],
        "analysis_depth": d.get("analysis_depth", ""),
        "llm_provider": d.get("llm_provider", ""),
        "llm_model": d.get("llm_model", ""),
        "created_at": _iso(d.get("created_at")),
        "report_markdown": d.get("report_markdown", ""),
        "source_file": d.get("source_file", ""),          # P4-B: PDF source file
        "source_hash": d.get("source_hash", ""),           # P4-B: PDF content hash
        "page_count": d.get("page_count"),                 # P4-B: PDF page count
        "views": [serialize_investment_view(v) for v in (d.get("views") or [])],
        "signals": [serialize_tracking_signal(s) for s in (d.get("signals") or [])],
    }


def serialize_investment_view(v: dict) -> dict:
    """Serialize an investment view dict."""
    return {
        "target_name": v.get("target_name", ""),
        "normalized_target_name": v.get("normalized_target_name", ""),
        "target_type": v.get("target_type", ""),
        "view_direction": v.get("view_direction", ""),
        "confidence": v.get("confidence", ""),
        "time_horizon": v.get("time_horizon", ""),
        "logic_chain": v.get("logic_chain", ""),
        "evidence_type": v.get("evidence_type", ""),
        "evidence_detail": v.get("evidence_detail", ""),
        "evidence_strength": v.get("evidence_strength", ""),
        "risk_warning": v.get("risk_warning", ""),
        "source_quote": v.get("source_quote", ""),
        "timestamp_start": v.get("timestamp_start", ""),
        "timestamp_end": v.get("timestamp_end", ""),
        "speaker_label": v.get("speaker_label", ""),
        "ai_value_chain_layer": v.get("ai_value_chain_layer", ""),
        "business_impact": v.get("business_impact", ""),
        "investment_relevance": v.get("investment_relevance", ""),
        "evidence_page": v.get("evidence_page"),  # P4-B: PDF page number
    }


def serialize_tracking_signal(s: dict) -> dict:
    """Serialize a tracking signal dict."""
    return {
        "target_name": s.get("target_name", ""),
        "signal": s.get("signal", ""),
        "trigger_condition": s.get("trigger_condition", ""),
        "expected_date": s.get("expected_date", ""),
        "status": s.get("status", ""),
        "source_quote": s.get("source_quote", ""),
        "timestamp": s.get("timestamp", ""),
    }


def serialize_channel(ch: dict) -> dict:
    """Serialize a channel dict."""
    return {
        "id": ch.get("id"),
        "name": ch.get("name", ""),
        "url": ch.get("url", ""),
        "youtube_channel_id": ch.get("youtube_channel_id", ""),
        "tags": ch.get("tags", ""),
        "priority": ch.get("priority", ""),
        "default_focus": ch.get("default_focus", ""),
        "default_depth": ch.get("default_depth", ""),
        "is_active": ch.get("is_active", True),
        "added_at": _iso(ch.get("added_at")),
        "last_refreshed_at": _iso(ch.get("last_refreshed_at")),
        "video_counts": ch.get("video_counts", {}),
        "total_videos": ch.get("total_videos", 0),
    }


def serialize_entity(e: dict) -> dict:
    """Serialize an entity dict."""
    return {
        "name": e.get("name", ""),
        "normalized_name": e.get("normalized_name", ""),
        "entity_type": e.get("entity_type", ""),
        "aliases": e.get("aliases", []) or [],
    }


def serialize_review_item(item: dict) -> dict:
    """Serialize a review item dict."""
    return {
        "id": item.get("id"),
        "item_type": item.get("item_type", ""),
        "severity": item.get("severity", ""),
        "status": item.get("status", ""),
        "title": item.get("title", ""),
        "description": item.get("description", ""),
        "source_ref": item.get("source_ref", ""),
        "source_path": item.get("source_path", ""),
        "suggested_action_json": item.get("suggested_action_json", ""),
        "resolution_note": item.get("resolution_note", ""),
        "created_at": item.get("created_at", ""),
        "resolved_at": item.get("resolved_at", ""),
    }
