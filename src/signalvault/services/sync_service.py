"""P2-K.2: Knowledge Sync Service — sync a report to Obsidian Vault and refresh briefs.

Orchestrates: export report → sync channel cards → generate topic/company cards →
backfill relations → refresh curation → polish metadata → refresh workspace →
generate research brief + watchlist brief.

No LLM, no external APIs, no subprocess CLI. All operations reuse existing Python functions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# User-visible stage labels
SYNC_STAGES: dict[str, str] = {
    "queued": "已收到同步请求",
    "exporting_report": "正在导出报告到知识库",
    "updating_cards": "正在更新主题和公司卡片",
    "generating_claims_signals": "正在生成观点和信号",
    "updating_relations": "正在建立知识关联",
    "refreshing_brief": "正在刷新研究摘要",
    "refreshing_watchlist": "正在刷新我的关注",
    "success": "知识库已更新",
    "failed": "同步失败",
}


@dataclass
class SyncResult:
    """Result of a single-report knowledge sync operation."""

    report_id: int
    exported_reports: int = 0
    cards_updated: int = 0
    relations_updated: int = 0
    brief_updated: bool = False
    watchlist_updated: bool = False
    error: str = ""


def sync_report_to_knowledge_base(
    report_id: int,
    vault_path: Path | None = None,
    progress_callback: Callable[[str, str], None] | None = None,
) -> SyncResult:
    """Sync a single report to the Obsidian knowledge base.

    Steps:
        1. Export report markdown to 01_Reports/
        2. Sync channel cards in 05_Channels/
        3. Generate topic/company cards in 02_Topics/ and 03_Companies/
        4. Backfill relations on claim/signal cards
        5. Refresh curation status on all cards
        6. Polish report metadata (title, published_at from DB)
        7. Refresh workspace (Home.md, Knowledge Map, Review Queue)
        8. Mark brief/watchlist as refreshed (these are generated on-demand)

    Args:
        report_id: The report ID in SQLite.
        vault_path: Path to Obsidian vault. If None, reads OBSIDIAN_VAULT_PATH env var.
        progress_callback: Optional (stage, message) callback for progress updates.

    Returns:
        SyncResult with counts and status.

    Raises:
        Does not raise — errors are captured in SyncResult.error.
    """
    from signalvault.config_store import get_user_vault_path

    if vault_path is None:
        vault_path_str = get_user_vault_path()
        if not vault_path_str:
            result = SyncResult(report_id=report_id)
            result.error = "知识库路径尚未配置，请通过 /setup/obsidian 初始化。"
            return result
        vault_path = Path(vault_path_str)

    if not vault_path.exists():
        result = SyncResult(report_id=report_id)
        result.error = f"知识库路径不存在: {vault_path}"
        return result

    result = SyncResult(report_id=report_id)

    def _progress(stage: str):
        msg = SYNC_STAGES.get(stage, stage)
        logger.info(f"Sync report_id={report_id} stage={stage}: {msg}")
        if progress_callback:
            progress_callback(stage, msg)

    try:
        # Step 1: Export report to vault
        _progress("exporting_report")
        from signalvault.exporters.obsidian import export_to_vault

        export_result = export_to_vault(
            vault_path=vault_path,
            source_type="youtube",
            report_id=report_id,
            overwrite=False,
            dry_run=False,
        )
        result.exported_reports = export_result.get("created", 0)

        # Step 2: Sync channel cards
        _progress("updating_cards")
        from signalvault.exporters.obsidian import sync_channel_cards

        channel_result = sync_channel_cards(
            vault_path=vault_path,
            dry_run=False,
        )
        result.cards_updated += channel_result.get("created", 0) + channel_result.get("updated", 0)

        # Step 2b: Generate topic/company cards
        from signalvault.exporters.obsidian import generate_cards

        card_result = generate_cards(
            vault_path=vault_path,
            dry_run=False,
        )
        result.cards_updated += (
            card_result.get("topics_created", 0)
            + card_result.get("topics_updated", 0)
            + card_result.get("companies_created", 0)
            + card_result.get("companies_updated", 0)
        )

        # Step 2c: Generate claims/signals from reports (P2-L.2: fix company relation count)
        _progress("generating_claims_signals")
        from signalvault.claim_signal.generator import (
            generate_all as generate_claims_signals,
        )

        cs_result = generate_claims_signals(
            vault_path=vault_path,
            dry_run=False,
            source="reports",
            limit=50,
            overwrite=False,
        )
        result.cards_updated += (
            cs_result.claims_created
            + cs_result.signals_created
            + cs_result.claims_overwritten
            + cs_result.signals_overwritten
        )

        # Step 3: Backfill relations + refresh curation + polish metadata
        _progress("updating_relations")
        from signalvault.workspace import (
            backfill_relations,
            polish_report_metadata,
            refresh_curation_status,
        )

        rel_result = backfill_relations(vault_path, dry_run=False, apply=True)
        result.relations_updated = (
            rel_result.get("stats", {}).get("topics_added", 0)
            + rel_result.get("stats", {}).get("companies_added", 0)
        )

        refresh_curation_status(vault_path, dry_run=False)
        polish_report_metadata(vault_path, dry_run=False, apply=True)

        # Step 4: Refresh workspace (Home.md, Knowledge Map, Review Queue)
        from signalvault.workspace import refresh_workspace

        refresh_workspace(vault_path, dry_run=False)

        # Step 5: Briefs are generated on-demand when users visit /briefs/latest
        # and /watchlist. We just mark them as refreshed.
        _progress("refreshing_brief")
        result.brief_updated = True

        _progress("refreshing_watchlist")
        result.watchlist_updated = True

        _progress("success")
        return result

    except Exception as e:
        logger.exception(f"Sync failed for report_id={report_id}: {e}")
        result.error = f"同步失败: {e}"
        return result
