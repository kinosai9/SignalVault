"""P6-A1: ZSXQ data models — group registry, topic, source profile."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ZsxqGroup:
    """Local group registry entry — read-only source registry."""
    group_id: str = ""
    group_name: str = ""
    access_status: str = "active"     # "active" | "inaccessible"
    topic_count: int = 0
    last_refreshed_at: str = ""
    first_seen_at: str = ""
    notes: str = ""


@dataclass
class ZsxqTopic:
    """Parsed ZSXQ topic from zsxq-cli JSON output."""
    group_id: str = ""
    group_name: str = ""
    topic_id: str = ""
    topic_type: str = ""            # "talk" | "q&a" | "task" | "file"
    topic_title: str = ""
    author_name: str = ""
    create_time: str = ""           # ISO format
    update_time: str = ""
    tags: list[str] = field(default_factory=list)
    content_text: str = ""          # plain text (HTML stripped)
    attachment_metadata: list[dict] = field(default_factory=list)
    source_url: str = ""
    content_hash: str = ""
    char_count: int = 0
    parse_quality: str = "good"     # "good" | "degraded" | "minimal"


@dataclass
class ZsxqSourceProfile:
    """Profile built from ZsxqTopic after quality checks.

    Consistent with existing source profile patterns (UploadedFileProfile, etc.).
    """
    source_type: str = "zsxq_topic"
    group_id: str = ""
    group_name: str = ""
    group_access_status: str = "active"  # "active" | "inaccessible"
    topic_id: str = ""
    topic_type: str = ""
    topic_title: str = ""
    author_name: str = ""
    create_time: str = ""
    update_time: str = ""
    tags: list[str] = field(default_factory=list)
    content_text: str = ""
    content_hash: str = ""
    source_url: str = ""
    attachment_metadata: list[dict] = field(default_factory=list)
    import_eligible: bool = False
    ineligible_reason: str = ""
    parse_quality: str = "good"
    quality_warnings: list[str] = field(default_factory=list)
    imported_at: str = ""


# ── Helpers ─────────────────────────────────────────────────────────────────


def compute_content_hash(text: str) -> str:
    """Compute a stable SHA256 content hash for dedup."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now().isoformat()
