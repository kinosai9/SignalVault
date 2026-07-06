"""P2-N.4.3: Review priority computation for claims and signals.

Deterministic rules based on watchlist relevance, confidence, evidence,
cross-report support, and risk factors. No LLM, no external APIs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from signalvault.workspace.scanner import (
        ClaimInfo,
        SignalInfo,
        WorkspaceSnapshot,
    )

# ── Priority tiers ──

PRIORITY_CRITICAL = "critical"
PRIORITY_HIGH = "high"
PRIORITY_NORMAL = "normal"
PRIORITY_LOW = "low"
PRIORITY_AUTO_ACCEPTED = "auto_accepted"

# ── Needs user attention: critical + high ──
NEEDS_REVIEW_PRIORITIES = {PRIORITY_CRITICAL, PRIORITY_HIGH}


def compute_claim_review_priority(
    claim_info: "ClaimInfo",
    snapshot: "WorkspaceSnapshot",
    watchlist_companies: set[str] | None = None,
    watchlist_topics: set[str] | None = None,
) -> str:
    """Compute review_priority for a claim.

    Rules (first match wins):
        auto_accepted: high confidence + evidence exists + non-duplicate
                       + has company/topic association + non-controversial
        critical:      watchlist match + challenged status
                      OR watchlist match + low confidence
        high:          watchlist match
                      OR challenged status
                      OR (multi-report support + low confidence)
        low:           single mention + low relevance + no watchlist
        normal:        everything else
    """
    if watchlist_companies is None:
        watchlist_companies = set()
    if watchlist_topics is None:
        watchlist_topics = set()

    # Determine if claim relates to watchlist
    has_watchlist_company = bool(
        watchlist_companies & set(claim_info.related_companies)
    )
    has_watchlist_topic = bool(
        watchlist_topics & set(claim_info.related_topics)
    )
    is_watchlist_related = has_watchlist_company or has_watchlist_topic

    # Report count
    report_count = len(claim_info.source_reports)

    # Read existing quality/review_priority from frontmatter
    quality = getattr(claim_info, "quality", "") or ""
    granularity = getattr(claim_info, "granularity", "") or ""

    # ── auto_accepted: high confidence, evidence, non-controversial ──
    if (
        quality == "high"
        and report_count >= 1
        and granularity != "duplicate"
        and claim_info.status != "challenged"
    ):
        return PRIORITY_AUTO_ACCEPTED

    # ── critical ──
    if is_watchlist_related and claim_info.status == "challenged":
        return PRIORITY_CRITICAL
    if is_watchlist_related and quality == "low":
        return PRIORITY_CRITICAL

    # ── high ──
    if is_watchlist_related:
        return PRIORITY_HIGH
    if claim_info.status == "challenged":
        return PRIORITY_HIGH
    if report_count >= 2 and quality == "low":
        return PRIORITY_HIGH

    # ── low ──
    if report_count <= 1 and not is_watchlist_related and quality != "high":
        return PRIORITY_LOW
    if granularity == "duplicate":
        return PRIORITY_LOW

    # ── normal ──
    return PRIORITY_NORMAL


def compute_signal_review_priority(
    signal_info: "SignalInfo",
    snapshot: "WorkspaceSnapshot",
    watchlist_companies: set[str] | None = None,
    watchlist_topics: set[str] | None = None,
) -> str:
    """Compute review_priority for a signal.

    Rules (first match wins):
        auto_accepted: resolved/invalidated status
                       OR (high confidence + non-risk)
        critical:      watchlist match + (watching or major risk signal)
        high:          watchlist match
                      OR watching status
                      OR risk signal type
        low:           single mention + no watchlist + generic signal
        normal:        everything else
    """
    if watchlist_companies is None:
        watchlist_companies = set()
    if watchlist_topics is None:
        watchlist_topics = set()

    # Determine if signal relates to watchlist
    has_watchlist_company = bool(
        watchlist_companies & set(signal_info.related_companies)
    )
    has_watchlist_topic = bool(
        watchlist_topics & set(signal_info.related_topics)
    )
    is_watchlist_related = has_watchlist_company or has_watchlist_topic

    # Report count
    report_count = len(signal_info.source_reports)

    # Read existing fields
    quality = getattr(signal_info, "quality", "") or ""
    signal_type = getattr(signal_info, "signal_type", "") or ""

    # Risk signal types (these matter more)
    RISK_TYPES = {
        "regulation", "technology_bottleneck", "competition",
        "market_structure", "infrastructure",
    }

    # ── auto_accepted ──
    if signal_info.status in ("resolved", "invalidated"):
        return PRIORITY_AUTO_ACCEPTED
    if quality == "high" and signal_type not in RISK_TYPES:
        return PRIORITY_AUTO_ACCEPTED

    # ── critical ──
    if is_watchlist_related and signal_info.status == "watching":
        return PRIORITY_CRITICAL
    if is_watchlist_related and signal_type in RISK_TYPES:
        return PRIORITY_CRITICAL

    # ── high ──
    if is_watchlist_related:
        return PRIORITY_HIGH
    if signal_info.status == "watching":
        return PRIORITY_HIGH
    if signal_type in RISK_TYPES:
        return PRIORITY_HIGH

    # ── low ──
    if report_count <= 1 and not is_watchlist_related:
        return PRIORITY_LOW
    if signal_type == "unknown" and not is_watchlist_related:
        return PRIORITY_LOW

    # ── normal ──
    return PRIORITY_NORMAL


def compute_all_claim_priorities(
    snapshot: "WorkspaceSnapshot",
    watchlist_companies: set[str],
    watchlist_topics: set[str],
) -> dict[str, str]:
    """Compute review_priority for all claims in snapshot.

    Returns dict mapping card_id -> priority.
    """
    priorities: dict[str, str] = {}
    for claim in snapshot.claims:
        priorities[claim.card_id] = compute_claim_review_priority(
            claim, snapshot, watchlist_companies, watchlist_topics,
        )
    return priorities


def compute_all_signal_priorities(
    snapshot: "WorkspaceSnapshot",
    watchlist_companies: set[str],
    watchlist_topics: set[str],
) -> dict[str, str]:
    """Compute review_priority for all signals in snapshot.

    Returns dict mapping card_id -> priority.
    """
    priorities: dict[str, str] = {}
    for signal in snapshot.signals:
        priorities[signal.card_id] = compute_signal_review_priority(
            signal, snapshot, watchlist_companies, watchlist_topics,
        )
    return priorities


def claims_needing_review(
    snapshot: "WorkspaceSnapshot",
    watchlist_companies: set[str] | None = None,
    watchlist_topics: set[str] | None = None,
) -> list["ClaimInfo"]:
    """Return claims that need user review (critical + high priority)."""
    if watchlist_companies is None:
        watchlist_companies = set()
    if watchlist_topics is None:
        watchlist_topics = set()

    result = []
    for claim in snapshot.claims:
        priority = compute_claim_review_priority(
            claim, snapshot, watchlist_companies, watchlist_topics,
        )
        if priority in NEEDS_REVIEW_PRIORITIES:
            result.append(claim)
    return result


def signals_needing_review(
    snapshot: "WorkspaceSnapshot",
    watchlist_companies: set[str] | None = None,
    watchlist_topics: set[str] | None = None,
) -> list["SignalInfo"]:
    """Return signals that need user review (critical + high priority)."""
    if watchlist_companies is None:
        watchlist_companies = set()
    if watchlist_topics is None:
        watchlist_topics = set()

    result = []
    for signal in snapshot.signals:
        priority = compute_signal_review_priority(
            signal, snapshot, watchlist_companies, watchlist_topics,
        )
        if priority in NEEDS_REVIEW_PRIORITIES:
            result.append(signal)
    return result


# ── Display helpers ──

PRIORITY_LABELS: dict[str, str] = {
    PRIORITY_CRITICAL: "紧急",
    PRIORITY_HIGH: "需确认",
    PRIORITY_NORMAL: "常规",
    PRIORITY_LOW: "低优先",
    PRIORITY_AUTO_ACCEPTED: "已自动整理",
}


def priority_label(priority: str) -> str:
    """Human-readable label for a review priority."""
    return PRIORITY_LABELS.get(priority, priority or "常规")
