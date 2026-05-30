"""Claim / Signal review workflow: list, show, update-status.

Deterministic. No LLM calls. Safe write-only updates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

VALID_CLAIM_STATUSES = {"active", "verified", "challenged", "outdated", "archived"}
VALID_SIGNAL_STATUSES = {"open", "watching", "resolved", "invalidated", "archived"}
VALID_QUALITY = {"high", "medium", "low"}
VALID_REVIEW_PRIORITY = {"high", "normal", "low"}
VALID_GRANULARITY = {"atomic", "broad", "duplicate", "unclear"}
VALID_SIGNAL_TYPES = {
    "competition", "technology_bottleneck", "regulation", "adoption",
    "business_model", "pricing", "infrastructure", "market_structure",
    "financial_metric", "unknown",
}


@dataclass
class ClaimInfo:
    """Lightweight claim card info for listing."""
    card_id: str
    status: str
    statement: str
    source_reports: list[str] = field(default_factory=list)
    updated_at: str = ""
    quality: str = "medium"
    review_priority: str = "normal"
    granularity: str = "atomic"


@dataclass
class SignalInfo:
    """Lightweight signal card info for listing."""
    card_id: str
    status: str
    statement: str
    source_reports: list[str] = field(default_factory=list)
    updated_at: str = ""
    quality: str = "medium"
    review_priority: str = "normal"
    signal_type: str = "unknown"


def _parse_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter into a flat dict."""
    if not content.startswith("---"):
        return {}
    end_idx = content.find("---", 3)
    if end_idx == -1:
        return {}
    fm_text = content[3:end_idx].strip()
    result = {}
    current_key = None
    list_values = []
    for line in fm_text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith('- "') and current_key:
            list_values.append(stripped[3:].rstrip('"').strip())
            continue
        elif stripped.startswith("- ") and current_key:
            list_values.append(stripped[2:].strip().strip('"'))
            continue
        elif stripped == "[]" and current_key:
            list_values = []
            continue
        if current_key and list_values is not None:
            result[current_key] = list_values
            list_values = []
            current_key = None
        if ":" in stripped and not stripped.startswith("-"):
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val:
                result[key] = val
                current_key = None
                list_values = []
            else:
                current_key = key
                list_values = []
    if current_key and list_values is not None:
        result[current_key] = list_values
    return result


def _update_frontmatter_field(content: str, field: str, new_value: str) -> str:
    """Update a single field in YAML frontmatter."""
    lines = content.split("\n")
    result = []
    in_fm = False
    fm_closed = False
    updated = False
    for line in lines:
        stripped = line.strip()
        if stripped == "---" and not fm_closed:
            if not in_fm:
                in_fm = True
                result.append(line)
                continue
            else:
                fm_closed = True
                result.append(line)
                continue
        if in_fm and not fm_closed and not updated:
            if line.startswith(f"{field}:"):
                result.append(f'{field}: {new_value}')
                updated = True
                continue
        result.append(line)
    return "\n".join(result)


def list_claims(
    vault_path: Path,
    status: str | None = None,
    limit: int | None = None,
) -> list[ClaimInfo]:
    """List claim cards from 06_Claims/.

    Args:
        vault_path: Path to vault root
        status: Filter by status (active/verified/challenged/outdated/archived)
        limit: Max number to return

    Returns:
        List of ClaimInfo objects
    """
    claims_dir = vault_path / "06_Claims"
    if not claims_dir.exists():
        return []

    results = []
    for card_path in sorted(claims_dir.glob("*.md")):
        content = card_path.read_text(encoding="utf-8")
        fm = _parse_frontmatter(content)
        card_status = fm.get("status", "active")

        if status and card_status != status:
            continue

        results.append(ClaimInfo(
            card_id=card_path.stem,
            status=card_status,
            statement=fm.get("claim", card_path.stem)[:80],
            source_reports=fm.get("source_reports", []) if isinstance(fm.get("source_reports"), list) else [],
            updated_at=fm.get("updated_at", ""),
            quality=fm.get("quality", "medium"),
            review_priority=fm.get("review_priority", "normal"),
            granularity=fm.get("granularity", "atomic"),
        ))

        if limit and len(results) >= limit:
            break

    return results


def list_signals(
    vault_path: Path,
    status: str | None = None,
    limit: int | None = None,
) -> list[SignalInfo]:
    """List signal cards from 07_Signals/.

    Args:
        vault_path: Path to vault root
        status: Filter by status (open/watching/resolved/invalidated/archived)
        limit: Max number to return

    Returns:
        List of SignalInfo objects
    """
    signals_dir = vault_path / "07_Signals"
    if not signals_dir.exists():
        return []

    results = []
    for card_path in sorted(signals_dir.glob("*.md")):
        content = card_path.read_text(encoding="utf-8")
        fm = _parse_frontmatter(content)
        card_status = fm.get("status", "open")

        if status and card_status != status:
            continue

        results.append(SignalInfo(
            card_id=card_path.stem,
            status=card_status,
            statement=fm.get("signal", card_path.stem)[:80],
            source_reports=fm.get("source_reports", []) if isinstance(fm.get("source_reports"), list) else [],
            updated_at=fm.get("updated_at", ""),
            quality=fm.get("quality", "medium"),
            review_priority=fm.get("review_priority", "normal"),
            signal_type=fm.get("signal_type", "unknown"),
        ))

        if limit and len(results) >= limit:
            break

    return results


def get_claim(vault_path: Path, claim_id: str) -> str | None:
    """Get full content of a claim card."""
    card_path = vault_path / "06_Claims" / f"{claim_id}.md"
    if not card_path.exists():
        return None
    return card_path.read_text(encoding="utf-8")


def get_signal(vault_path: Path, signal_id: str) -> str | None:
    """Get full content of a signal card."""
    card_path = vault_path / "07_Signals" / f"{signal_id}.md"
    if not card_path.exists():
        return None
    return card_path.read_text(encoding="utf-8")


def update_claim_status(
    vault_path: Path,
    claim_id: str,
    new_status: str,
    note: str = "",
) -> bool:
    """Update a claim card's status and append review history.

    Args:
        vault_path: Path to vault root
        claim_id: Card filename stem
        new_status: New status (active/verified/challenged/outdated/archived)
        note: Optional review note

    Returns:
        True if successful, False if error
    """
    card_path = vault_path / "06_Claims" / f"{claim_id}.md"
    if not card_path.exists():
        logger.warning("Claim card not found: %s", claim_id)
        return False

    if new_status not in VALID_CLAIM_STATUSES:
        logger.warning("Invalid claim status: %s", new_status)
        return False

    content = card_path.read_text(encoding="utf-8")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # Update frontmatter status + updated_at
    updated = _update_frontmatter_field(content, "status", new_status)
    updated = _update_frontmatter_field(updated, "updated_at", f'"{now_iso}"')

    # Append review history
    history_entry = f"\n- {now} — status: {new_status}"
    if note:
        history_entry += f" — {note}"

    if "## Review History" in updated:
        # Append after the section header
        idx = updated.find("## Review History")
        next_section = updated.find("\n## ", idx + 5)
        if next_section > 0:
            updated = updated[:next_section] + history_entry + "\n" + updated[next_section:]
        else:
            updated = updated.rstrip() + history_entry + "\n"
    else:
        # Add Review History section before the end
        updated = updated.rstrip() + f"\n\n## Review History{history_entry}\n"

    card_path.write_text(updated, encoding="utf-8")
    logger.info("Claim '%s' status updated to %s", claim_id, new_status)

    # Update index
    _rebuild_claim_index(vault_path)
    # Write log
    _write_claim_review_log(vault_path, claim_id, new_status, note)

    return True


def update_signal_status(
    vault_path: Path,
    signal_id: str,
    new_status: str,
    note: str = "",
) -> bool:
    """Update a signal card's status and append to Updates section.

    Args:
        vault_path: Path to vault root
        signal_id: Card filename stem
        new_status: New status (open/watching/resolved/invalidated/archived)
        note: Optional review note

    Returns:
        True if successful, False if error
    """
    card_path = vault_path / "07_Signals" / f"{signal_id}.md"
    if not card_path.exists():
        logger.warning("Signal card not found: %s", signal_id)
        return False

    if new_status not in VALID_SIGNAL_STATUSES:
        logger.warning("Invalid signal status: %s", new_status)
        return False

    content = card_path.read_text(encoding="utf-8")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # Update frontmatter
    updated = _update_frontmatter_field(content, "status", new_status)
    updated = _update_frontmatter_field(updated, "updated_at", f'"{now_iso}"')

    # Append to Updates section
    update_entry = f"\n- {now} — status: {new_status}"
    if note:
        update_entry += f" — {note}"

    if "## Updates" in updated:
        idx = updated.find("## Updates")
        next_section = updated.find("\n## ", idx + 5)
        if next_section > 0:
            updated = updated[:next_section] + update_entry + "\n" + updated[next_section:]
        else:
            updated = updated.rstrip() + update_entry + "\n"
    else:
        updated = updated.rstrip() + f"\n\n## Updates{update_entry}\n"

    card_path.write_text(updated, encoding="utf-8")
    logger.info("Signal '%s' status updated to %s", signal_id, new_status)

    # Update index
    _rebuild_signal_index(vault_path)
    # Write log
    _write_signal_review_log(vault_path, signal_id, new_status, note)

    return True


def _rebuild_claim_index(vault_path: Path) -> None:
    """Rebuild Claim Index with status statistics."""
    claims = list_claims(vault_path)
    if not claims:
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Count by status
    status_counts: dict[str, int] = {}
    for c in claims:
        status_counts[c.status] = status_counts.get(c.status, 0) + 1

    lines = ["# Claim Index\n", f"\nGenerated: {now}\n"]
    lines.append("\n## Summary\n")
    lines.append("\n| Status | Count |")
    lines.append("\n|---|---:|")
    for s in ["active", "verified", "challenged", "outdated", "archived"]:
        count = status_counts.get(s, 0)
        if count:
            lines.append(f"\n| {s} | {count} |")
    lines.append(f"\n\n**Total**: {len(claims)}\n")

    lines.append("\n## Claims\n")
    for c in claims:
        sr = c.source_reports[0] if c.source_reports else "-"
        lines.append(f"\n- [{c.status}] [[../06_Claims/{c.card_id}|{c.statement[:60]}]] — {sr}")

    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    (system_dir / "Claim Index.md").write_text("".join(lines), encoding="utf-8")


def _rebuild_signal_index(vault_path: Path) -> None:
    """Rebuild Signal Index with status statistics."""
    signals = list_signals(vault_path)
    if not signals:
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_counts: dict[str, int] = {}
    for s in signals:
        status_counts[s.status] = status_counts.get(s.status, 0) + 1

    lines = ["# Signal Index\n", f"\nGenerated: {now}\n"]
    lines.append("\n## Summary\n")
    lines.append("\n| Status | Count |")
    lines.append("\n|---|---:|")
    for s in ["open", "watching", "resolved", "invalidated", "archived"]:
        count = status_counts.get(s, 0)
        if count:
            lines.append(f"\n| {s} | {count} |")
    lines.append(f"\n\n**Total**: {len(signals)}\n")

    lines.append("\n## Signals\n")
    for s in signals:
        sr = s.source_reports[0] if s.source_reports else "-"
        lines.append(f"\n- [{s.status}] [[../07_Signals/{s.card_id}|{s.statement[:60]}]] — {sr}")

    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    (system_dir / "Signal Index.md").write_text("".join(lines), encoding="utf-8")


def _write_claim_review_log(vault_path: Path, claim_id: str, status: str, note: str) -> None:
    """Append to Claim_Review_Log.md."""
    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    log_path = system_dir / "Claim_Review_Log.md"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    entry = f"## {now}\n\n- **Claim**: [[../06_Claims/{claim_id}]]\n- **Status**: {status}\n"
    if note:
        entry += f"- **Note**: {note}\n"
    entry += "\n"

    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        header = "# Claim Review Log"
        if header in existing:
            existing = existing.replace(header + "\n\n", header + "\n\n" + entry)
            log_path.write_text(existing, encoding="utf-8")
        else:
            log_path.write_text(header + "\n\n" + entry + existing)
    else:
        log_path.write_text("# Claim Review Log\n\n" + entry)


def _write_signal_review_log(vault_path: Path, signal_id: str, status: str, note: str) -> None:
    """Append to Signal_Review_Log.md."""
    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    log_path = system_dir / "Signal_Review_Log.md"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    entry = f"## {now}\n\n- **Signal**: [[../07_Signals/{signal_id}]]\n- **Status**: {status}\n"
    if note:
        entry += f"- **Note**: {note}\n"
    entry += "\n"

    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        header = "# Signal Review Log"
        if header in existing:
            existing = existing.replace(header + "\n\n", header + "\n\n" + entry)
            log_path.write_text(existing, encoding="utf-8")
        else:
            log_path.write_text(header + "\n\n" + entry + existing)
    else:
        log_path.write_text("# Signal Review Log\n\n" + entry)


# ---------------------------------------------------------------------------
# P2-F.2: Metadata, find-similar, backlog
# ---------------------------------------------------------------------------


def update_claim_meta(
    vault_path: Path,
    claim_id: str,
    quality: str | None = None,
    review_priority: str | None = None,
    granularity: str | None = None,
) -> bool:
    """Update claim metadata fields (quality, review_priority, granularity).

    Returns True if successful.
    """
    card_path = vault_path / "06_Claims" / f"{claim_id}.md"
    if not card_path.exists():
        return False
    if quality and quality not in VALID_QUALITY:
        return False
    if review_priority and review_priority not in VALID_REVIEW_PRIORITY:
        return False
    if granularity and granularity not in VALID_GRANULARITY:
        return False

    content = card_path.read_text(encoding="utf-8")
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    updated = _update_frontmatter_field(content, "updated_at", f'"{now_iso}"')
    if quality:
        updated = _ensure_frontmatter_field(updated, "quality", quality)
    if review_priority:
        updated = _ensure_frontmatter_field(updated, "review_priority", review_priority)
    if granularity:
        updated = _ensure_frontmatter_field(updated, "granularity", granularity)

    card_path.write_text(updated, encoding="utf-8")
    _rebuild_claim_index(vault_path)
    _write_claim_review_log(vault_path, claim_id, "meta_updated",
                            f"quality={quality}, priority={review_priority}, granularity={granularity}")
    return True


def update_signal_meta(
    vault_path: Path,
    signal_id: str,
    quality: str | None = None,
    review_priority: str | None = None,
    signal_type: str | None = None,
) -> bool:
    """Update signal metadata fields.

    Returns True if successful.
    """
    card_path = vault_path / "07_Signals" / f"{signal_id}.md"
    if not card_path.exists():
        return False
    if quality and quality not in VALID_QUALITY:
        return False
    if review_priority and review_priority not in VALID_REVIEW_PRIORITY:
        return False
    if signal_type and signal_type not in VALID_SIGNAL_TYPES:
        return False

    content = card_path.read_text(encoding="utf-8")
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    updated = _update_frontmatter_field(content, "updated_at", f'"{now_iso}"')
    if quality:
        updated = _ensure_frontmatter_field(updated, "quality", quality)
    if review_priority:
        updated = _ensure_frontmatter_field(updated, "review_priority", review_priority)
    if signal_type:
        updated = _ensure_frontmatter_field(updated, "signal_type", signal_type)

    card_path.write_text(updated, encoding="utf-8")
    _rebuild_signal_index(vault_path)
    _write_signal_review_log(vault_path, signal_id, "meta_updated",
                             f"quality={quality}, priority={review_priority}, signal_type={signal_type}")
    return True


def _ensure_frontmatter_field(content: str, field: str, value: str) -> str:
    """Add or update a field in frontmatter. If field doesn't exist, insert before closing ---."""
    # If field already exists, update it
    if f"\n{field}:" in content or content.startswith(f"{field}:"):
        return _update_frontmatter_field(content, field, value)
    # Insert before closing ---
    closing = content.find("---", 3)
    if closing > 0:
        return content[:closing] + f'{field}: {value}\n' + content[closing:]
    return content


def _tokenize(text: str) -> set[str]:
    """Split text into word tokens for similarity comparison."""
    import re
    tokens = re.findall(r'[a-zA-Z0-9一-鿿]{2,}', text.lower())
    return set(tokens)


@dataclass
class SimilarPair:
    """Pair of similar items."""
    item_a: str
    item_b: str
    similarity_reason: str
    suggested_action: str  # manual_review / possible_duplicate / keep_separate
    item_type: str = "claim"


def find_similar_claims(vault_path: Path) -> list[SimilarPair]:
    """Find potentially similar claim pairs based on token overlap."""
    claims = list_claims(vault_path)
    if len(claims) < 2:
        return []

    pairs = []
    for i in range(len(claims)):
        tokens_a = _tokenize(claims[i].statement)
        for j in range(i + 1, len(claims)):
            tokens_b = _tokenize(claims[j].statement)
            if not tokens_a or not tokens_b:
                continue
            overlap = tokens_a & tokens_b
            union = tokens_a | tokens_b
            ratio = len(overlap) / len(union) if union else 0
            if ratio > 0.4:
                action = "possible_duplicate" if ratio > 0.7 else "manual_review"
                pairs.append(SimilarPair(
                    item_a=claims[i].card_id[:50],
                    item_b=claims[j].card_id[:50],
                    similarity_reason=f"token_overlap={ratio:.0%}",
                    suggested_action=action,
                    item_type="claim",
                ))
    return sorted(pairs, key=lambda p: -1 if p.suggested_action == "possible_duplicate" else 0)


def find_similar_signals(vault_path: Path) -> list[SimilarPair]:
    """Find potentially similar signal pairs."""
    signals = list_signals(vault_path)
    if len(signals) < 2:
        return []

    pairs = []
    for i in range(len(signals)):
        tokens_a = _tokenize(signals[i].statement)
        for j in range(i + 1, len(signals)):
            tokens_b = _tokenize(signals[j].statement)
            if not tokens_a or not tokens_b:
                continue
            overlap = tokens_a & tokens_b
            union = tokens_a | tokens_b
            ratio = len(overlap) / len(union) if union else 0
            if ratio > 0.4:
                action = "possible_duplicate" if ratio > 0.7 else "manual_review"
                pairs.append(SimilarPair(
                    item_a=signals[i].card_id[:50],
                    item_b=signals[j].card_id[:50],
                    similarity_reason=f"token_overlap={ratio:.0%}",
                    suggested_action=action,
                    item_type="signal",
                ))
    return sorted(pairs, key=lambda p: -1 if p.suggested_action == "possible_duplicate" else 0)


def generate_claim_backlog(vault_path: Path) -> None:
    """Generate Claim Review Backlog sorted by priority."""
    claims = list_claims(vault_path)
    if not claims:
        return

    # Sort: review_priority high first, then status=active, then quality=high
    def sort_key(c):
        prio = {"high": 0, "normal": 1, "low": 2}
        status_order = {"active": 0, "verified": 1, "challenged": 2, "outdated": 3, "archived": 4}
        return (prio.get(getattr(c, "review_priority", "normal"), 1),
                status_order.get(c.status, 2),
                0 if getattr(c, "quality", "medium") == "high" else 1)

    sorted_claims = sorted(claims, key=sort_key)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = ["# Claim Review Backlog\n", f"\nGenerated: {now}\n"]
    lines.append(f"\nTotal: {len(sorted_claims)}\n\n")
    for c in sorted_claims:
        fm = _parse_frontmatter((vault_path / "06_Claims" / f"{c.card_id}.md").read_text(encoding="utf-8"))
        quality = fm.get("quality", "medium")
        priority = fm.get("review_priority", "normal")
        granularity = fm.get("granularity", "atomic")
        lines.append(
            f"- [{c.status}] [{quality}|{priority}|{granularity}] "
            f"[[../06_Claims/{c.card_id}|{c.statement[:60]}]]\n"
        )

    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    (system_dir / "Claim Review Backlog.md").write_text("".join(lines), encoding="utf-8")


def generate_signal_backlog(vault_path: Path) -> None:
    """Generate Signal Review Backlog sorted by priority."""
    signals = list_signals(vault_path)
    if not signals:
        return

    def sort_key(s):
        prio = {"high": 0, "normal": 1, "low": 2}
        status_order = {"open": 0, "watching": 1, "resolved": 2, "invalidated": 3, "archived": 4}
        return (prio.get(getattr(s, "review_priority", "normal"), 1),
                status_order.get(s.status, 2),
                0 if getattr(s, "quality", "medium") == "high" else 1)

    sorted_signals = sorted(signals, key=sort_key)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = ["# Signal Review Backlog\n", f"\nGenerated: {now}\n"]
    lines.append(f"\nTotal: {len(sorted_signals)}\n\n")
    for s in sorted_signals:
        fm = _parse_frontmatter((vault_path / "07_Signals" / f"{s.card_id}.md").read_text(encoding="utf-8"))
        quality = fm.get("quality", "medium")
        priority = fm.get("review_priority", "normal")
        stype = fm.get("signal_type", "unknown")
        lines.append(
            f"- [{s.status}] [{quality}|{priority}|{stype}] "
            f"[[../07_Signals/{s.card_id}|{s.statement[:60]}]]\n"
        )

    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    (system_dir / "Signal Review Backlog.md").write_text("".join(lines), encoding="utf-8")


def _update_claim_index_with_meta(vault_path: Path) -> None:
    """Rebuild index with quality/priority/granularity columns."""
    claims = list_claims(vault_path)
    if not claims:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_counts: dict[str, int] = {}
    for c in claims:
        status_counts[c.status] = status_counts.get(c.status, 0) + 1

    lines = ["# Claim Index\n", f"\nGenerated: {now}\n"]
    lines.append("\n## Summary\n\n| Status | Count |\n|---|---:|\n")
    for s in ["active", "verified", "challenged", "outdated", "archived"]:
        if status_counts.get(s):
            lines.append(f"| {s} | {status_counts[s]} |\n")
    lines.append(f"\n**Total**: {len(claims)}\n\n")

    lines.append("## Claims\n")
    for c in claims:
        fm = _parse_frontmatter((vault_path / "06_Claims" / f"{c.card_id}.md").read_text(encoding="utf-8"))
        q = fm.get("quality", "medium")
        p = fm.get("review_priority", "normal")
        g = fm.get("granularity", "atomic")
        sr = c.source_reports[0] if c.source_reports else "-"
        lines.append(f"\n- [{c.status}] `{q}|{p}|{g}` [[../06_Claims/{c.card_id}|{c.statement[:60]}]] — {sr}")

    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    (system_dir / "Claim Index.md").write_text("".join(lines), encoding="utf-8")


def _update_signal_index_with_meta(vault_path: Path) -> None:
    """Rebuild index with quality/priority/signal_type columns."""
    signals = list_signals(vault_path)
    if not signals:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_counts: dict[str, int] = {}
    for s in signals:
        status_counts[s.status] = status_counts.get(s.status, 0) + 1

    lines = ["# Signal Index\n", f"\nGenerated: {now}\n"]
    lines.append("\n## Summary\n\n| Status | Count |\n|---|---:|\n")
    for s in ["open", "watching", "resolved", "invalidated", "archived"]:
        if status_counts.get(s):
            lines.append(f"| {s} | {status_counts[s]} |\n")
    lines.append(f"\n**Total**: {len(signals)}\n\n")

    lines.append("## Signals\n")
    for s in signals:
        fm = _parse_frontmatter((vault_path / "07_Signals" / f"{s.card_id}.md").read_text(encoding="utf-8"))
        q = fm.get("quality", "medium")
        p = fm.get("review_priority", "normal")
        st = fm.get("signal_type", "unknown")
        sr = s.source_reports[0] if s.source_reports else "-"
        lines.append(f"\n- [{s.status}] `{q}|{p}|{st}` [[../07_Signals/{s.card_id}|{s.statement[:60]}]] — {sr}")

    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    (system_dir / "Signal Index.md").write_text("".join(lines), encoding="utf-8")


# Replace old index rebuild functions with meta-aware versions
_rebuild_claim_index = _update_claim_index_with_meta
_rebuild_signal_index = _update_signal_index_with_meta


# ---------------------------------------------------------------------------
# P2-F.3: Signal Tracking Schema & Manual Update Workflow
# ---------------------------------------------------------------------------

VALID_TRACKING_STATUSES = {"not_started", "active", "paused", "resolved", "invalidated", "archived"}
VALID_TRACKING_METHODS = {
    "manual", "news", "earnings", "product_release", "metric",
    "expert_commentary", "youtube", "rss", "unknown",
}


def update_signal_tracking(
    vault_path: Path,
    signal_id: str,
    tracking_status: str | None = None,
    tracking_method: str | None = None,
    tracking_query: str | None = None,
    resolution_criteria: str | None = None,
    invalidation_criteria: str | None = None,
) -> bool:
    """Update signal tracking metadata.

    Returns True if successful.
    """
    card_path = vault_path / "07_Signals" / f"{signal_id}.md"
    if not card_path.exists():
        return False
    if tracking_status and tracking_status not in VALID_TRACKING_STATUSES:
        return False
    if tracking_method and tracking_method not in VALID_TRACKING_METHODS:
        return False

    content = card_path.read_text(encoding="utf-8")
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    updated = _update_frontmatter_field(content, "updated_at", f'"{now_iso}"')

    if tracking_status:
        updated = _ensure_frontmatter_field(updated, "tracking_status", tracking_status)
        if tracking_status == "active" and "last_checked_at:" not in updated:
            updated = _ensure_frontmatter_field(updated, "last_checked_at", f'"{now_iso}"')
    if tracking_method:
        updated = _ensure_frontmatter_field(updated, "tracking_method", tracking_method)
    if tracking_query:
        updated = _ensure_frontmatter_field(updated, "tracking_query", f'"{tracking_query}"')
    if resolution_criteria:
        updated = _ensure_frontmatter_field(updated, "resolution_criteria", f'"{resolution_criteria}"')
    if invalidation_criteria:
        updated = _ensure_frontmatter_field(updated, "invalidation_criteria", f'"{invalidation_criteria}"')

    card_path.write_text(updated, encoding="utf-8")
    _rebuild_signal_index(vault_path)
    _write_signal_tracking_log(vault_path, signal_id, "tracking_updated",
                               f"status={tracking_status}, method={tracking_method}")
    return True


def add_signal_update(
    vault_path: Path,
    signal_id: str,
    note: str,
    source: str = "",
    evidence_url: str = "",
    new_status: str | None = None,
    checked_at: str | None = None,
) -> bool:
    """Add a manual update note to a signal card.

    Appends to ## Updates section, updates frontmatter timestamps.
    """
    card_path = vault_path / "07_Signals" / f"{signal_id}.md"
    if not card_path.exists():
        return False

    content = card_path.read_text(encoding="utf-8")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    check_iso = checked_at or now_iso

    # Update frontmatter: last_checked_at, updated_at, optionally status
    updated = _update_frontmatter_field(content, "updated_at", f'"{now_iso}"')
    updated = _ensure_frontmatter_field(updated, "last_checked_at", f'"{check_iso}"')
    if new_status:
        updated = _update_frontmatter_field(updated, "status", new_status)

    # Append to Updates section
    entry = f"\n- {now}"
    if source:
        entry += f"\n  - Source: {source}"
    if evidence_url:
        entry += f"\n  - Evidence URL: {evidence_url}"
    if new_status:
        entry += f"\n  - Status: {new_status}"
    entry += f"\n  - {note}"

    if "## Updates" in updated:
        idx = updated.find("## Updates")
        next_section = updated.find("\n## ", idx + 5)
        if next_section > 0:
            updated = updated[:next_section] + entry + "\n" + updated[next_section:]
        else:
            updated = updated.rstrip() + entry + "\n"
    else:
        updated = updated.rstrip() + f"\n\n## Updates{entry}\n"

    card_path.write_text(updated, encoding="utf-8")
    _rebuild_signal_index(vault_path)
    _write_signal_tracking_log(vault_path, signal_id, "manual_update",
                               f"{note[:80]}, status={new_status}")
    return True


def generate_signal_tracking_backlog(vault_path: Path) -> None:
    """Generate Signal Tracking Backlog sorted by tracking priority."""
    signals = list_signals(vault_path)
    if not signals:
        return

    def sort_key(s):
        fm = _parse_frontmatter((vault_path / "07_Signals" / f"{s.card_id}.md").read_text(encoding="utf-8"))
        tracking_status = fm.get("tracking_status", "not_started")
        tstatus_order = {"active": 0, "not_started": 1, "paused": 2, "resolved": 3, "invalidated": 4, "archived": 5}
        prio = {"high": 0, "normal": 1, "low": 2}
        return (tstatus_order.get(tracking_status, 2),
                prio.get(s.review_priority, 1),
                0 if s.quality == "high" else 1)

    sorted_signals = sorted(signals, key=sort_key)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = ["# Signal Tracking Backlog\n", f"\nGenerated: {now}\n"]
    lines.append(f"\nTotal: {len(sorted_signals)}\n\n")
    for s in sorted_signals:
        fm = _parse_frontmatter((vault_path / "07_Signals" / f"{s.card_id}.md").read_text(encoding="utf-8"))
        tstatus = fm.get("tracking_status", "not_started")
        tmethod = fm.get("tracking_method", "manual")
        tquery = fm.get("tracking_query", "")[:40]
        next_check = fm.get("next_check_at", "")[:10]
        lines.append(
            f"- [{tstatus}] `{tmethod}` {tquery} | next={next_check} "
            f"[[../07_Signals/{s.card_id}|{s.statement[:50]}]]\n"
        )

    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    (system_dir / "Signal Tracking Backlog.md").write_text("".join(lines), encoding="utf-8")


def _update_signal_index_with_tracking(vault_path: Path) -> None:
    """Rebuild Signal Index with tracking fields."""
    signals = list_signals(vault_path)
    if not signals:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_counts: dict[str, int] = {}
    for s in signals:
        status_counts[s.status] = status_counts.get(s.status, 0) + 1

    lines = ["# Signal Index\n", f"\nGenerated: {now}\n"]
    lines.append("\n## Summary\n\n| Status | Count |\n|---|---:|\n")
    for st in ["open", "watching", "resolved", "invalidated", "archived"]:
        if status_counts.get(st):
            lines.append(f"| {st} | {status_counts[st]} |\n")
    lines.append(f"\n**Total**: {len(signals)}\n\n")

    lines.append("## Signals\n")
    for s in signals:
        fm = _parse_frontmatter((vault_path / "07_Signals" / f"{s.card_id}.md").read_text(encoding="utf-8"))
        tstatus = fm.get("tracking_status", "not_started")
        tmethod = fm.get("tracking_method", "manual")
        last_check = fm.get("last_checked_at", "")[:10]
        next_check = fm.get("next_check_at", "")[:10]
        sr = s.source_reports[0] if s.source_reports else "-"
        lines.append(
            f"- [{s.status}] `{tstatus}|{tmethod}|last={last_check}|next={next_check}` "
            f"[[../07_Signals/{s.card_id}|{s.statement[:50]}]] — {sr}\n"
        )

    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    (system_dir / "Signal Index.md").write_text("".join(lines), encoding="utf-8")


# Replace signal index rebuild with tracking-aware version
_rebuild_signal_index = _update_signal_index_with_tracking


def _write_signal_tracking_log(vault_path: Path, signal_id: str, action: str, detail: str) -> None:
    """Append to Signal_Tracking_Log.md."""
    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    log_path = system_dir / "Signal_Tracking_Log.md"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    entry = f"## {now}\n\n- **Signal**: [[../07_Signals/{signal_id}]]\n- **Action**: {action}\n- **Detail**: {detail}\n\n"

    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        header = "# Signal Tracking Log"
        if header in existing:
            existing = existing.replace(header + "\n\n", header + "\n\n" + entry)
            log_path.write_text(existing, encoding="utf-8")
        else:
            log_path.write_text(header + "\n\n" + entry + existing)
    else:
        log_path.write_text("# Signal Tracking Log\n\n" + entry)
