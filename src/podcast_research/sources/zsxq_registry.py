"""P6-A1: ZSXQ Group Registry — local read-only source registry.

Manages zsxq_groups as a JSON file on disk (minimal intrusion, no DB migration).
Supports manual refresh, access_status tracking, and historical data preservation.
"""

from __future__ import annotations

import json as _json
import logging
from datetime import datetime

from podcast_research.config import DATA_DIR
from podcast_research.sources.zsxq_models import ZsxqGroup

logger = logging.getLogger(__name__)

REGISTRY_FILE = DATA_DIR / "zsxq_groups.json"


# ── Registry CRUD ───────────────────────────────────────────────────────────


def _load_registry() -> list[dict]:
    """Load group registry from disk. Returns empty list if file missing."""
    if not REGISTRY_FILE.exists():
        return []
    try:
        data = _json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (_json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load ZSXQ group registry: %s", e)
        return []


def _save_registry(groups: list[dict]) -> None:
    """Save group registry to disk atomically."""
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY_FILE.with_suffix(".json.tmp")
    tmp.write_text(_json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(REGISTRY_FILE)


def list_registry() -> list[ZsxqGroup]:
    """List all groups in the local registry."""
    groups = _load_registry()
    return [_dict_to_group(g) for g in groups]


def get_group(group_id: str) -> ZsxqGroup | None:
    """Get a single group by ID."""
    for g in _load_registry():
        if g.get("group_id") == group_id:
            return _dict_to_group(g)
    return None


def refresh_registry(cli_groups: list[dict]) -> dict:
    """Refresh the local registry from zsxq-cli group list output.

    Args:
        cli_groups: List of dicts from zsxq-cli output.
            Each dict: {"group_id": str, "name": str, "topic_count": int}

    Returns:
        {"added": N, "reactivated": N, "deactivated": N, "unchanged": N}
    """
    now = datetime.now().isoformat()
    local = _load_registry()
    local_by_id = {g["group_id"]: g for g in local}
    cli_ids = {g["group_id"] for g in cli_groups}

    added = 0
    reactivated = 0
    deactivated = 0
    unchanged = 0

    # Process CLI groups
    for cg in cli_groups:
        gid = cg.get("group_id", "")
        if not gid:
            continue
        if gid in local_by_id:
            existing = local_by_id[gid]
            if existing.get("access_status") == "inaccessible":
                existing["access_status"] = "active"
                existing["last_refreshed_at"] = now
                existing["topic_count"] = cg.get("topic_count", existing.get("topic_count", 0))
                existing["group_name"] = cg.get("name", existing.get("group_name", ""))
                reactivated += 1
            else:
                existing["last_refreshed_at"] = now
                existing["topic_count"] = cg.get("topic_count", existing.get("topic_count", 0))
                existing["group_name"] = cg.get("name", existing.get("group_name", ""))
                unchanged += 1
        else:
            local.append({
                "group_id": gid,
                "group_name": cg.get("name", ""),
                "access_status": "active",
                "topic_count": cg.get("topic_count", 0),
                "last_refreshed_at": now,
                "first_seen_at": now,
                "notes": "",
            })
            added += 1

    # Mark local groups not in CLI output as inaccessible
    for g in local:
        if g["group_id"] not in cli_ids and g.get("access_status") == "active":
            g["access_status"] = "inaccessible"
            g["last_refreshed_at"] = now
            deactivated += 1

    _save_registry(local)
    logger.info("ZSXQ registry refreshed: +%d ↻%d −%d =%d", added, reactivated, deactivated, unchanged)
    return {"added": added, "reactivated": reactivated,
            "deactivated": deactivated, "unchanged": unchanged}


# ── Helpers ─────────────────────────────────────────────────────────────────


def _dict_to_group(d: dict) -> ZsxqGroup:
    return ZsxqGroup(
        group_id=d.get("group_id", ""),
        group_name=d.get("group_name", ""),
        access_status=d.get("access_status", "active"),
        topic_count=d.get("topic_count", 0),
        last_refreshed_at=d.get("last_refreshed_at", ""),
        first_seen_at=d.get("first_seen_at", ""),
        notes=d.get("notes", ""),
    )
