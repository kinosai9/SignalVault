"""P2-H.2: Obsidian Workspace Dashboard & Knowledge Workspace Hardening.

Generates Home.md, Knowledge Map, and Review Queue for Obsidian vault navigation.
Also provides relation backfill and curation status refresh.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from podcast_research.workspace.backfill import backfill_relations
from podcast_research.workspace.curation import refresh_curation_status
from podcast_research.workspace.generators import (
    BLOCK_HOME,
    BLOCK_KNOWLEDGE_MAP,
    BLOCK_REVIEW_QUEUE,
    generate_home_dashboard,
    generate_knowledge_map,
    generate_review_queue,
)
from podcast_research.workspace.longtail import cleanup_long_tail_topics
from podcast_research.workspace.managed_block import (
    _has_managed_block,
    _remove_managed_block,
    _upsert_managed_block,
)
from podcast_research.workspace.metadata import polish_report_metadata
from podcast_research.workspace.research_brief import ResearchBrief, generate_brief
from podcast_research.workspace.scanner import (
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
        result["home"] = generate_home_dashboard(snapshot)
    if do_km:
        result["knowledge_map"] = generate_knowledge_map(snapshot)
    if do_rq:
        result["review_queue"] = generate_review_queue(snapshot)

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
