"""Curation status: add/update curation_status field on Topic, Company, Claim, Signal cards.

Deterministic rules. No LLM. No external APIs. Read-only unless dry_run=False.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from signalvault.claim_signal.review import (
    _ensure_frontmatter_field,
    _parse_frontmatter,
)
from signalvault.utils.file_io import read_text_safe

logger = logging.getLogger(__name__)

CURATION_STATUSES = {"raw", "indexed", "reviewed", "enhanced", "archived"}


def refresh_curation_status(
    vault_path: Path,
    *,
    dry_run: bool = True,
) -> dict:
    """Add/update curation_status on all topic, company, claim, and signal cards.

    Args:
        vault_path: Path to Obsidian vault root.
        dry_run: If True, scan and report but don't write.

    Returns:
        dict with 'results' list and 'stats' summary.
    """
    results: list[dict] = []
    stats = {
        "topics_scanned": 0,
        "topics_updated": 0,
        "companies_scanned": 0,
        "companies_updated": 0,
        "claims_scanned": 0,
        "claims_updated": 0,
        "signals_scanned": 0,
        "signals_updated": 0,
    }

    # Process topics
    topics_dir = vault_path / "02_Topics"
    if topics_dir.exists():
        for p in sorted(topics_dir.glob("*.md")):
            try:
                content = read_text_safe(p)
            except Exception:
                logger.warning(f"Cannot read topic: {p}")
                continue
            stats["topics_scanned"] += 1
            new_status = _determine_topic_curation(content)
            result = _apply_curation(p, content, new_status, dry_run)
            results.append(result)
            if result.get("updated"):
                stats["topics_updated"] += 1

    # Process companies
    companies_dir = vault_path / "03_Companies"
    if companies_dir.exists():
        for p in sorted(companies_dir.glob("*.md")):
            try:
                content = read_text_safe(p)
            except Exception:
                logger.warning(f"Cannot read company: {p}")
                continue
            stats["companies_scanned"] += 1
            new_status = _determine_company_curation(content)
            result = _apply_curation(p, content, new_status, dry_run)
            results.append(result)
            if result.get("updated"):
                stats["companies_updated"] += 1

    # Process claims
    claims_dir = vault_path / "06_Claims"
    if claims_dir.exists():
        for p in sorted(claims_dir.glob("*.md")):
            try:
                content = read_text_safe(p)
            except Exception:
                logger.warning(f"Cannot read claim: {p}")
                continue
            stats["claims_scanned"] += 1
            fm = _parse_frontmatter(content)
            new_status = _determine_claim_curation(fm)
            result = _apply_curation(p, content, new_status, dry_run)
            results.append(result)
            if result.get("updated"):
                stats["claims_updated"] += 1

    # Process signals
    signals_dir = vault_path / "07_Signals"
    if signals_dir.exists():
        for p in sorted(signals_dir.glob("*.md")):
            try:
                content = read_text_safe(p)
            except Exception:
                logger.warning(f"Cannot read signal: {p}")
                continue
            stats["signals_scanned"] += 1
            fm = _parse_frontmatter(content)
            new_status = _determine_signal_curation(fm)
            result = _apply_curation(p, content, new_status, dry_run)
            results.append(result)
            if result.get("updated"):
                stats["signals_updated"] += 1

    return {"results": results, "stats": stats}


# ── Curation determination ────────────────────────────────────────


def _determine_topic_curation(content: str) -> str:
    """Determine curation_status for a topic card.

    P2-N.4.3: Now delegates to system_curation module for richer rules.
    Falls back to simple rules if snapshot not available.
    """
    has_llm_wiki = "<!-- LLM-WIKI:BEGIN" in content
    fm = _parse_frontmatter(content)
    source_reports = fm.get("source_reports", [])
    if not isinstance(source_reports, list):
        source_reports = []

    # P2-N.4.3: LLM-WIKI enhanced overrides everything
    if has_llm_wiki:
        return "enhanced"

    # P2-N.4.3: Check user_curation first — user override wins
    user_curation = fm.get("curation_status", "")
    if user_curation and user_curation not in ("raw", "unknown", ""):
        return user_curation

    # Fall back to simple rules (detailed system_curation computed at scan time)
    if len(source_reports) > 0:
        return "indexed"
    return "raw"


def _determine_company_curation(content: str) -> str:
    """Determine curation_status for a company card.

    P2-N.4.3: Now delegates to system_curation module for richer rules.
    Falls back to simple rules if snapshot not available.
    """
    has_llm_wiki = "<!-- LLM-WIKI:BEGIN" in content
    fm = _parse_frontmatter(content)
    source_reports = fm.get("source_reports", [])
    if not isinstance(source_reports, list):
        source_reports = []

    # P2-N.4.3: LLM-WIKI enhanced overrides everything
    if has_llm_wiki:
        return "enhanced"

    # P2-N.4.3: Check user_curation first — user override wins
    user_curation = fm.get("curation_status", "")
    if user_curation and user_curation not in ("raw", "unknown", ""):
        return user_curation

    # Fall back to simple rules (detailed system_curation computed at scan time)
    if len(source_reports) > 0:
        return "indexed"
    return "raw"


def _determine_claim_curation(fm: dict) -> str:
    """Determine curation_status for a claim card based on frontmatter."""
    status = fm.get("status", "")

    if status == "archived":
        return "archived"
    elif status == "verified":
        return "reviewed"
    else:
        return "indexed"


def _determine_signal_curation(fm: dict) -> str:
    """Determine curation_status for a signal card based on frontmatter."""
    status = fm.get("status", "")

    if status == "archived":
        return "archived"
    elif status in ("watching", "resolved", "invalidated"):
        return "reviewed"
    else:
        return "indexed"


# ── Apply ─────────────────────────────────────────────────────────


def _apply_curation(
    card_path: Path,
    content: str,
    new_status: str,
    dry_run: bool,
) -> dict:
    """Apply curation_status to a card, returning result dict."""
    fm = _parse_frontmatter(content)
    current_status = fm.get("curation_status", "")

    result = {
        "card_id": card_path.stem,
        "current_curation": current_status,
        "new_curation": new_status,
        "updated": False,
    }

    if current_status == new_status:
        return result

    result["updated"] = True
    if not dry_run:
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        updated = _ensure_frontmatter_field(content, "curation_status", new_status)
        updated = _ensure_frontmatter_field(updated, "updated_at", f'"{now_iso}"')
        card_path.write_text(updated, encoding="utf-8")

    return result
