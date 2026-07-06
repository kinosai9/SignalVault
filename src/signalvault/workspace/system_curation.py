"""P2-N.4.3: System auto-curation for Topic and Company cards.

Deterministic rules based on report/claim/signal counts and watchlist status.
No LLM, no external APIs. Pure computation from WorkspaceSnapshot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from signalvault.workspace.scanner import (
        CompanyInfo,
        TopicInfo,
        WorkspaceSnapshot,
    )

# ── Topic system curation tiers ──

TOPIC_CURATION_RAW = "raw"
TOPIC_CURATION_EMERGING = "emerging"
TOPIC_CURATION_TRACKING = "tracking"
TOPIC_CURATION_ESTABLISHED = "established"
TOPIC_CURATION_IGNORED = "ignored"

# ── Company system curation tiers ──

COMPANY_CURATION_MENTIONED = "mentioned"
COMPANY_CURATION_COVERED = "covered"
COMPANY_CURATION_TRACKING = "tracking"
COMPANY_CURATION_WATCHLIST = "watchlist"
COMPANY_CURATION_HIGH_ATTENTION = "high_attention"
COMPANY_CURATION_IGNORED = "ignored"


def compute_topic_system_curation(
    topic_info: "TopicInfo",
    snapshot: "WorkspaceSnapshot",
    watchlist_topics: set[str] | None = None,
) -> str:
    """Compute system_curation for a topic card.

    Rules (first match wins):
        ignored:  name matches generic blacklist or topic_quality == "noisy"
        raw:      reports <= 1 AND claims <= 1 AND signals == 0
        emerging: reports >= 2 OR claims >= 3
        tracking: signals >= 1 OR watchlist_match == true
        established: reports >= 5 AND claims >= 5 AND cross_report_support >= 2
    """
    if watchlist_topics is None:
        watchlist_topics = set()

    reports_n = len(topic_info.source_reports)
    claims_n = snapshot.claims_count_for(topic_info.name)
    signals_n = snapshot.signals_count_for(topic_info.name)

    # Cross-report support: claims tied to this topic that have >= 2 source reports
    cross_report_support = sum(
        1 for c in snapshot.claims
        if topic_info.name in c.related_topics and len(c.source_reports) >= 2
    )

    # ── ignored check ──
    if topic_info.topic_quality == "noisy":
        return TOPIC_CURATION_IGNORED

    # ── established check ──
    if reports_n >= 5 and claims_n >= 5 and cross_report_support >= 2:
        return TOPIC_CURATION_ESTABLISHED

    # ── tracking check ──
    if signals_n >= 1 or topic_info.name in watchlist_topics:
        return TOPIC_CURATION_TRACKING

    # ── emerging check ──
    if reports_n >= 2 or claims_n >= 3:
        return TOPIC_CURATION_EMERGING

    # ── raw ──
    return TOPIC_CURATION_RAW


def compute_company_system_curation(
    company_info: "CompanyInfo",
    snapshot: "WorkspaceSnapshot",
    watchlist_companies: set[str] | None = None,
) -> str:
    """Compute system_curation for a company card.

    Rules (first match wins):
        ignored:       non-company entity type OR _NOT_A_COMPANY match
        high_attention: watchlist AND claims/signals growing
        watchlist:      in user Watchlist
        tracking:       signals >= 1
        covered:        reports >= 3 OR claims >= 2
        mentioned:      reports >= 1
    """
    if watchlist_companies is None:
        watchlist_companies = set()

    reports_n = len(company_info.source_reports)
    claims_n = snapshot.claims_count_for(company_info.name)
    signals_n = snapshot.signals_count_for(company_info.name)

    # Check entity_type from frontmatter (if available)
    entity_type = getattr(company_info, "entity_type", "") or ""

    # ── ignored check: non-company entities ──
    _NON_COMPANY_TYPES = {
        "product", "model", "person", "topic", "macro",
        "technology", "concept", "product_or_model",
    }
    if entity_type.lower() in _NON_COMPANY_TYPES:
        return COMPANY_CURATION_IGNORED

    # ── watchlist/high_attention check ──
    in_watchlist = company_info.name in watchlist_companies
    if in_watchlist:
        # Check if activity is growing (claims + signals > threshold)
        if claims_n >= 2 or signals_n >= 1:
            return COMPANY_CURATION_HIGH_ATTENTION
        return COMPANY_CURATION_WATCHLIST

    # ── tracking check ──
    if signals_n >= 1:
        return COMPANY_CURATION_TRACKING

    # ── covered check ──
    if reports_n >= 3 or claims_n >= 2:
        return COMPANY_CURATION_COVERED

    # ── mentioned check ──
    if reports_n >= 1:
        return COMPANY_CURATION_MENTIONED

    # ── fallback: raw/unknown → use mentioned if any data at all ──
    return COMPANY_CURATION_MENTIONED


# ── Display helpers ──

CURATION_LABELS: dict[str, str] = {
    # Topic
    TOPIC_CURATION_RAW: "待积累",
    TOPIC_CURATION_EMERGING: "新兴",
    TOPIC_CURATION_TRACKING: "跟踪中",
    TOPIC_CURATION_ESTABLISHED: "已确立",
    TOPIC_CURATION_IGNORED: "已忽略",
    # Company
    COMPANY_CURATION_MENTIONED: "提及",
    COMPANY_CURATION_COVERED: "覆盖中",
    COMPANY_CURATION_TRACKING: "跟踪中",
    COMPANY_CURATION_WATCHLIST: "关注中",
    COMPANY_CURATION_HIGH_ATTENTION: "重点关注",
    COMPANY_CURATION_IGNORED: "已忽略",
}


def curation_label(curation: str) -> str:
    """Human-readable label for a curation status."""
    return CURATION_LABELS.get(curation, curation or "未知")
