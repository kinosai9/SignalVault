"""P2-N.4.4.2: Unified canonical views — single source of truth for all surfaces.

Every consumer (Home, Review Queue, Dashboard, Watchlist, Research Brief)
consumes the same CanonicalClaimView / CanonicalSignalView / ReviewItemView,
eliminating local dedup fragmentation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from signalvault.workspace.actionability import Actionability
    from signalvault.workspace.canonicalize import DuplicateGroup
    from signalvault.workspace.scanner import (
        ClaimInfo,
        SignalInfo,
        WorkspaceSnapshot,
    )
    from signalvault.workspace.watchlist import WatchlistConfig


# ── Canonical view dataclasses ──────────────────────────────────────

@dataclass
class CanonicalClaimView:
    """Unified view of a canonical claim for any consumer surface."""
    canonical_id: str                      # card_id of canonical claim
    display_text: str                      # normalized, clean text for display
    fingerprint: str                       # stable fingerprint
    source_item: "ClaimInfo"              # the canonical ClaimInfo
    duplicates: list["ClaimInfo"] = field(default_factory=list)
    duplicate_count: int = 0
    source_reports: list[str] = field(default_factory=list)
    related_topics: list[str] = field(default_factory=list)
    related_companies: list[str] = field(default_factory=list)
    status: str = ""
    review_priority: str = ""
    actionability: "Actionability | None" = None

    @property
    def is_actionable(self) -> bool:
        return self.actionability is not None and self.actionability.is_actionable

    @property
    def primary_action(self) -> str:
        return self.actionability.primary_action if self.actionability else ""

    @property
    def status_label(self) -> str:
        return self.actionability.status_label if self.actionability else ""


@dataclass
class CanonicalSignalView:
    """Unified view of a canonical signal for any consumer surface."""
    canonical_id: str
    display_text: str
    fingerprint: str
    source_item: "SignalInfo"
    duplicates: list["SignalInfo"] = field(default_factory=list)
    duplicate_count: int = 0
    source_reports: list[str] = field(default_factory=list)
    related_topics: list[str] = field(default_factory=list)
    related_companies: list[str] = field(default_factory=list)
    status: str = ""
    tracking_status: str = ""
    review_priority: str = ""
    actionability: "Actionability | None" = None

    @property
    def is_actionable(self) -> bool:
        return self.actionability is not None and self.actionability.is_actionable

    @property
    def primary_action(self) -> str:
        return self.actionability.primary_action if self.actionability else ""

    @property
    def status_label(self) -> str:
        return self.actionability.status_label if self.actionability else ""


@dataclass
class ReviewItemView:
    """A single review item ready for display in Review Queue / Home."""
    item_type: str          # "claim" / "signal"
    canonical_id: str
    display_text: str
    status: str
    status_label: str
    is_actionable: bool
    primary_action: str
    icon: str
    card_type: str          # "06_Claims" / "07_Signals"
    card_id: str


@dataclass
class EvidenceView:
    """Evidence items for a single watchlist item, deduped across sections."""
    direct_claims: list[str] = field(default_factory=list)
    direct_signals: list[str] = field(default_factory=list)
    indirect_items: list[str] = field(default_factory=list)
    reinforced: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    # Counts (non-deduped, for stats)
    direct_count: int = 0
    indirect_count: int = 0
    reinforced_count: int = 0
    observation_count: int = 0


# ── Builders ────────────────────────────────────────────────────────

def build_canonical_claim_views(snapshot: "WorkspaceSnapshot") -> list[CanonicalClaimView]:
    """Build canonical claim views from snapshot.

    Groups all claims by fingerprint, selects canonical per group,
    computes actionability for each canonical.
    """
    from signalvault.workspace.actionability import get_claim_actionability
    from signalvault.workspace.canonicalize import (
        claim_fingerprint,
        group_duplicate_claims,
        normalize_claim_text,
    )

    groups = group_duplicate_claims(snapshot.claims)
    views: list[CanonicalClaimView] = []

    for g in groups:
        c = g.canonical
        claim_text = getattr(c, 'claim', '') or ''
        fp = claim_fingerprint(claim_text)
        display = normalize_claim_text(claim_text)[:120]

        actionability = get_claim_actionability(c, is_canonical=True)

        views.append(CanonicalClaimView(
            canonical_id=c.card_id,
            display_text=display,
            fingerprint=fp,
            source_item=c,
            duplicates=g.duplicates,
            duplicate_count=len(g.duplicates),
            source_reports=getattr(c, 'source_reports', []) or [],
            related_topics=getattr(c, 'related_topics', []) or [],
            related_companies=getattr(c, 'related_companies', []) or [],
            status=getattr(c, 'status', '') or '',
            review_priority=getattr(c, 'review_priority', '') or '',
            actionability=actionability,
        ))

    return views


def build_canonical_signal_views(snapshot: "WorkspaceSnapshot") -> list[CanonicalSignalView]:
    """Build canonical signal views from snapshot."""
    from signalvault.workspace.actionability import get_signal_actionability
    from signalvault.workspace.canonicalize import (
        group_duplicate_signals,
        normalize_signal_text,
        signal_fingerprint,
    )

    groups = group_duplicate_signals(snapshot.signals)
    views: list[CanonicalSignalView] = []

    for g in groups:
        s = g.canonical
        sig_text = getattr(s, 'signal', '') or ''
        fp = signal_fingerprint(sig_text)
        display = normalize_signal_text(sig_text)[:120]

        actionability = get_signal_actionability(s, is_canonical=True)

        views.append(CanonicalSignalView(
            canonical_id=s.card_id,
            display_text=display,
            fingerprint=fp,
            source_item=s,
            duplicates=g.duplicates,
            duplicate_count=len(g.duplicates),
            source_reports=getattr(s, 'source_reports', []) or [],
            related_topics=getattr(s, 'related_topics', []) or [],
            related_companies=getattr(s, 'related_companies', []) or [],
            status=getattr(s, 'status', '') or '',
            tracking_status=getattr(s, 'tracking_status', '') or '',
            review_priority=getattr(s, 'review_priority', '') or '',
            actionability=actionability,
        ))

    return views


def build_review_item_views(
    snapshot: "WorkspaceSnapshot",
    watchlist_config: "WatchlistConfig | None" = None,
) -> list[ReviewItemView]:
    """Build actionable review items for Home / Review Queue.

    Uses canonical views + actionability gate. Returns only items that
    need user attention (is_actionable + primary_action).
    """
    from signalvault.workspace.review_priority import (
        PRIORITY_CRITICAL,
        PRIORITY_HIGH,
    )

    claim_views = build_canonical_claim_views(snapshot)
    signal_views = build_canonical_signal_views(snapshot)

    items: list[ReviewItemView] = []

    for cv in claim_views:
        if not cv.is_actionable or not cv.primary_action:
            continue
        if cv.review_priority not in (PRIORITY_CRITICAL, PRIORITY_HIGH):
            continue
        items.append(ReviewItemView(
            item_type="claim",
            canonical_id=cv.canonical_id,
            display_text=cv.display_text[:60],
            status=cv.status,
            status_label=cv.status_label,
            is_actionable=True,
            primary_action=cv.primary_action,
            icon="🔴" if cv.review_priority == PRIORITY_CRITICAL else "🟠",
            card_type="06_Claims",
            card_id=cv.canonical_id,
        ))

    for sv in signal_views:
        if not sv.is_actionable or not sv.primary_action:
            continue
        if sv.review_priority not in (PRIORITY_CRITICAL, PRIORITY_HIGH):
            continue
        items.append(ReviewItemView(
            item_type="signal",
            canonical_id=sv.canonical_id,
            display_text=sv.display_text[:60],
            status=sv.status,
            status_label=sv.status_label,
            is_actionable=True,
            primary_action=sv.primary_action,
            icon="🔴" if sv.review_priority == PRIORITY_CRITICAL else "🟠",
            card_type="07_Signals",
            card_id=sv.canonical_id,
        ))

    # Sort: claims first, then signals, critical before high
    items.sort(key=lambda x: (
        0 if x.item_type == "claim" else 1,
        0 if "critical" in (x.status_label or "") else 1,
        x.canonical_id,
    ))
    return items


def build_watchlist_evidence(
    snapshot: "WorkspaceSnapshot",
    watchlist_item_name: str,
    item_type: str,
    claim_views: list | None = None,
    signal_views: list | None = None,
) -> EvidenceView:
    """Build deduped evidence for a single watchlist item.

    All sections (direct, indirect, reinforced, observations) share
    one canonical fingerprint set — same claim/signal never appears twice.
    Direct claims/signals take priority over indirect/reinforced.
    Target-only fragments and already_followed signals are excluded.

    claim_views / signal_views: Pre-computed from build_canonical_claim_views()
        and build_canonical_signal_views(). Pass from the caller to avoid
        recomputing per watchlist item (0.4s each × N items).
    """
    from signalvault.workspace.actionability import (
        is_claim_fragment,
        is_signal_fragment,
    )
    from signalvault.workspace.canonicalize import (
        normalize_claim_text,
        normalize_signal_text,
    )

    if claim_views is None:
        claim_views = build_canonical_claim_views(snapshot)
    if signal_views is None:
        signal_views = build_canonical_signal_views(snapshot)

    ev = EvidenceView()

    # ── Pass 1: Direct claims (canonical, clean, deduped) ──
    direct_claim_fps: set[str] = set()
    direct_claim_texts: list[str] = []
    direct_claim_count = 0

    for cv in claim_views:
        if item_type == "company":
            if watchlist_item_name not in cv.related_companies:
                continue
        else:
            if watchlist_item_name not in cv.related_topics:
                continue
        direct_claim_count += 1 + cv.duplicate_count
        if cv.fingerprint not in direct_claim_fps:
            direct_claim_fps.add(cv.fingerprint)
            direct_claim_texts.append(cv.display_text[:80])

    ev.direct_claims = direct_claim_texts[:3]
    all_seen_fps: set[str] = set(direct_claim_fps)  # Master dedup set

    # ── Pass 2: Direct signals (canonical, not fragment, not followed) ──
    direct_signal_texts: list[str] = []
    direct_signal_count = 0

    for sv in signal_views:
        if item_type == "company":
            if watchlist_item_name not in sv.related_companies:
                continue
        else:
            if watchlist_item_name not in sv.related_topics:
                continue
        direct_signal_count += 1 + sv.duplicate_count
        # Skip fragments and already-followed
        if sv.status_label in ("无效片段", "已在跟踪", "已关闭", "重复"):
            continue
        if sv.fingerprint not in all_seen_fps:
            all_seen_fps.add(sv.fingerprint)
            direct_signal_texts.append(sv.display_text[:80])

    ev.direct_signals = direct_signal_texts[:3]
    ev.direct_count = direct_claim_count + direct_signal_count

    # ── Pass 3: Indirect (contextual, skip if already seen) ──
    indirect_texts: list[str] = []
    if item_type == "company":
        for t in snapshot.topics:
            if t.name == watchlist_item_name:
                continue
            for cv in claim_views:
                if (watchlist_item_name in cv.related_companies
                        and t.name in cv.related_topics):
                    text = f"与升温主题「{t.name}」关联: {cv.display_text[:60]}"
                    fp = cv.fingerprint
                    if fp not in all_seen_fps:
                        all_seen_fps.add(fp)
                        indirect_texts.append(text)
    elif item_type == "topic":
        for co in snapshot.companies:
            if co.name == watchlist_item_name:
                continue
            for cv in claim_views:
                if (watchlist_item_name in cv.related_topics
                        and co.name in cv.related_companies):
                    text = f"与活跃公司「{co.name}」关联: {cv.display_text[:60]}"
                    fp = cv.fingerprint
                    if fp not in all_seen_fps:
                        all_seen_fps.add(fp)
                        indirect_texts.append(text)

    ev.indirect_items = sorted(set(indirect_texts))[:3]
    ev.indirect_count = len(indirect_texts)

    # ── Pass 4: Reinforced (claims with >=2 reports, skip if seen) ──
    reinforced_texts: list[str] = []
    reinforced_count = 0
    for cv in claim_views:
        if item_type == "company":
            if watchlist_item_name not in cv.related_companies:
                continue
        else:
            if watchlist_item_name not in cv.related_topics:
                continue
        if len(cv.source_reports) >= 2:
            reinforced_count += 1 + cv.duplicate_count
            if cv.fingerprint not in all_seen_fps:
                all_seen_fps.add(cv.fingerprint)
                reinforced_texts.append(cv.display_text[:80])

    ev.reinforced = reinforced_texts[:3]
    ev.reinforced_count = reinforced_count

    # ── Pass 5: Observations (signals to watch, skip fragments/followed/seen) ──
    obs_texts: list[str] = []
    obs_count = 0
    for sv in signal_views:
        if item_type == "company":
            if watchlist_item_name not in sv.related_companies:
                continue
        else:
            if watchlist_item_name not in sv.related_topics:
                continue
        # Only open signals that need watching
        if sv.status not in ("open", "watching"):
            continue
        obs_count += 1 + sv.duplicate_count
        if sv.status_label in ("无效片段", "重复"):
            continue
        if sv.fingerprint not in all_seen_fps:
            all_seen_fps.add(sv.fingerprint)
            if sv.status == "watching":
                obs_texts.append(f"[已在跟踪] {sv.display_text[:80]}")
            else:
                obs_texts.append(sv.display_text[:80])

    ev.observations = obs_texts[:5]
    ev.observation_count = obs_count

    return ev


# ── Duplicate visibility audit ──────────────────────────────────────

def audit_duplicate_visibility(snapshot: "WorkspaceSnapshot") -> dict:
    """Audit duplicate visibility across all surfaces.

    Returns dict with counts of duplicate groups visible in each surface.
    Target: all *_duplicate counts should be 0.
    """
    from signalvault.workspace.actionability import (
        is_claim_fragment,
        is_signal_fragment,
    )
    from signalvault.workspace.canonicalize import (
        group_duplicate_claims,
        group_duplicate_signals,
    )

    claim_groups = group_duplicate_claims(snapshot.claims)
    signal_groups = group_duplicate_signals(snapshot.signals)

    duplicate_claim_groups = [g for g in claim_groups if g.group_size > 1]
    duplicate_signal_groups = [g for g in signal_groups if g.group_size > 1]

    # Total duplicates (including canonical)
    total_duplicate_claims = sum(g.group_size - 1 for g in duplicate_claim_groups)
    total_duplicate_signals = sum(g.group_size - 1 for g in duplicate_signal_groups)

    # Fragment signals
    fragment_signals = sum(
        1 for s in snapshot.signals if is_signal_fragment(s))
    fragment_claims = sum(
        1 for c in snapshot.claims if is_claim_fragment(c))

    # Already followed that might be actionable
    from signalvault.workspace.actionability import (
        get_claim_actionability,
        get_signal_actionability,
    )
    followed_but_high = sum(
        1 for s in snapshot.signals
        if getattr(s, 'review_priority', '') in ('critical', 'high')
        and get_signal_actionability(s).status_label == "已在跟踪")

    accepted_but_high = sum(
        1 for c in snapshot.claims
        if getattr(c, 'review_priority', '') in ('critical', 'high')
        and get_claim_actionability(c).status_label in ("已采纳", "已关闭"))

    return {
        "duplicate_claim_groups_total": len(duplicate_claim_groups),
        "duplicate_signal_groups_total": len(duplicate_signal_groups),
        "duplicate_claims_hidden": total_duplicate_claims,
        "duplicate_signals_hidden": total_duplicate_signals,
        "fragment_signals_count": fragment_signals,
        "fragment_claims_count": fragment_claims,
        "followed_but_high_priority": followed_but_high,
        "accepted_but_high_priority": accepted_but_high,
    }
