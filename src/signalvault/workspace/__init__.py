"""P2-H.2: Obsidian Workspace Dashboard & Knowledge Workspace Hardening.

Generates Home.md, Knowledge Map, and Review Queue for Obsidian vault navigation.
Also provides relation backfill and curation status refresh.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from signalvault.workspace.backfill import backfill_relations
from signalvault.workspace.curation import refresh_curation_status
from signalvault.workspace.generators import (
    BLOCK_HOME,
    BLOCK_KNOWLEDGE_MAP,
    BLOCK_REVIEW_QUEUE,
    generate_home_dashboard,
    generate_knowledge_map,
    generate_review_queue,
)
from signalvault.workspace.longtail import cleanup_long_tail_topics
from signalvault.workspace.managed_block import (
    _has_managed_block,
    _remove_managed_block,
    _upsert_managed_block,
)
from signalvault.workspace.metadata import polish_report_metadata
from signalvault.workspace.research_brief import ResearchBrief, generate_brief
from signalvault.workspace.scanner import (
    ChannelInfo,
    ClaimInfo,
    CompanyInfo,
    LWPatchInfo,
    ReportInfo,
    SignalInfo,
    TopicInfo,
    VaultScanner,
    WorkspaceSnapshot,
)

logger = logging.getLogger(__name__)

__all__ = [
    "refresh_workspace",
    "backfill_relations",
    "refresh_curation_status",
    "polish_report_metadata",
    "cleanup_long_tail_topics",
    "VaultScanner",
    "WorkspaceSnapshot",
    "BLOCK_HOME",
    "BLOCK_KNOWLEDGE_MAP",
    "BLOCK_REVIEW_QUEUE",
]


def refresh_workspace(
    vault_path: Path,
    *,
    dry_run: bool = False,
    home_only: bool = False,
    knowledge_map_only: bool = False,
    review_queue_only: bool = False,
) -> dict:
    """Scan vault and regenerate Home.md, Knowledge Map, and Review Queue.

    P2-N.4.3: Now computes system_curation for topics/companies and review_priority
    for claims/signals. Passes research brief and watchlist to Home for richer display.

    Args:
        vault_path: Path to Obsidian vault root.
        dry_run: If True, scan and generate content but don't write files.
        home_only: Only refresh Home.md.
        knowledge_map_only: Only refresh Knowledge Map.
        review_queue_only: Only refresh Review Queue.

    Returns:
        dict with 'home', 'knowledge_map', 'review_queue' content strings,
        'stats' dict with counts, and 'files_written' list.
    """
    # Determine which files to refresh
    refresh_all = not (home_only or knowledge_map_only or review_queue_only)
    do_home = refresh_all or home_only
    do_km = refresh_all or knowledge_map_only
    do_rq = refresh_all or review_queue_only

    # Scan
    scanner = VaultScanner(vault_path)
    snapshot = scanner.scan()

    # P2-N.4.3: Compute system_curation for topics and companies
    try:
        from signalvault.workspace.system_curation import (
            compute_company_system_curation,
            compute_topic_system_curation,
        )
        from signalvault.workspace.watchlist import load_watchlist
        wl_config = load_watchlist(vault_path)
        wl_companies = set(wl_config.companies)
        wl_topics = set(wl_config.topics)
    except Exception:
        wl_config = None
        wl_companies = set()
        wl_topics = set()

    for t in snapshot.topics:
        t.system_curation = compute_topic_system_curation(t, snapshot, wl_topics)
    for c in snapshot.companies:
        c.system_curation = compute_company_system_curation(c, snapshot, wl_companies)

    # P2-N.4.3: Compute review_priority for claims and signals
    try:
        from signalvault.workspace.review_priority import (
            compute_claim_review_priority,
            compute_signal_review_priority,
        )
        for cl in snapshot.claims:
            cl.review_priority = compute_claim_review_priority(
                cl, snapshot, wl_companies, wl_topics,
            )
        for s in snapshot.signals:
            s.review_priority = compute_signal_review_priority(
                s, snapshot, wl_companies, wl_topics,
            )
    except Exception:
        pass

    # P2-N.4.3: Generate research brief and watchlist items for Home enrichment
    research_brief = None
    watchlist_items = None
    if do_home:
        try:
            from signalvault.workspace.research_brief import generate_brief
            research_brief = generate_brief(snapshot)
        except Exception:
            pass
        try:
            from signalvault.workspace.watchlist import generate_watchlist_brief
            if wl_config and (wl_config.companies or wl_config.topics):
                watchlist_items = generate_watchlist_brief(snapshot, vault_path)
        except Exception:
            pass

    result = {
        "home": "",
        "knowledge_map": "",
        "review_queue": "",
        "stats": {
            "reports": len(snapshot.reports),
            "topics": len(snapshot.topics),
            "core_topics": len(snapshot.core_topics()),
            "companies": len(snapshot.companies),
            "core_companies": len(snapshot.core_companies()),
            "claims": len(snapshot.claims),
            "active_claims": len(snapshot.active_claims()),
            "signals": len(snapshot.signals),
            "open_signals": len(snapshot.open_signals()),
            "watching_signals": len(snapshot.watching_signals()),
            "patches": len(snapshot.llm_patches),
            "pending_patches": len(snapshot.pending_patches()),
            "channels": len(snapshot.channels),
            "curation": snapshot.curation_summary(),
        },
        "files_written": [],
    }

    # Generate content
    if do_home:
        result["home"] = generate_home_dashboard(
            snapshot,
            research_brief=research_brief,
            watchlist_items=watchlist_items,
            watchlist_config=wl_config,
        )
    if do_km:
        result["knowledge_map"] = generate_knowledge_map(snapshot)
    if do_rq:
        result["review_queue"] = generate_review_queue(
            snapshot,
            watchlist_config=wl_config,
        )

    # Write files (unless dry-run)
    if not dry_run:
        system_dir = vault_path / "99_System"
        system_dir.mkdir(parents=True, exist_ok=True)

        if do_home:
            home_path = vault_path / "Home.md"
            _upsert_managed_block(home_path, BLOCK_HOME, result["home"])
            result["files_written"].append(str(home_path))

        if do_km:
            km_path = system_dir / "Knowledge Map.md"
            _upsert_managed_block(km_path, BLOCK_KNOWLEDGE_MAP, result["knowledge_map"])
            result["files_written"].append(str(km_path))

        if do_rq:
            rq_path = system_dir / "Review Queue.md"
            _upsert_managed_block(rq_path, BLOCK_REVIEW_QUEUE, result["review_queue"])
            result["files_written"].append(str(rq_path))

    return result
