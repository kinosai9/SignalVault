"""P2-N.4.4: Actionability gate — determines what the user should do
with each claim/signal, and whether it should appear in Today recommendations.

Shared by Dashboard 今日建议, Home, Review Queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from signalvault.workspace.canonicalize import DuplicateGroup
    from signalvault.workspace.scanner import (
        ClaimInfo,
        SignalInfo,
        WorkspaceSnapshot,
    )

# ── Actionability result ────────────────────────────────────────────

@dataclass
class Actionability:
    """Whether and how a claim/signal should be actionable by the user."""
    is_actionable: bool = False
    primary_action: str = ""      # "accept" / "follow" / "review" / ""
    secondary_action: str = ""    # "ignore" / "archive" / ""
    status_label: str = ""        # "需确认" / "已在跟踪" / "已采纳" / "重复" / ""
    reason: str = ""              # why this actionability was assigned
    item_type: str = ""           # "claim" / "signal"
    icon: str = ""                # "🔴" / "🟠" / "✅" / "🔔" / ""


# ── Accessors ────────────────────────────────────────────────────────

CLAIM_CLOSED_STATUSES = frozenset({"verified", "archived", "outdated"})
SIGNAL_CLOSED_STATUSES = frozenset({"resolved", "invalidated", "archived"})
SIGNAL_FOLLOWED_STATUSES = frozenset({"watching"})
TRACKING_ACTIVE_STATUSES = frozenset({"active", "tracking"})


def is_signal_fragment(signal: "SignalInfo") -> bool:
    """Detect Target-only or otherwise invalid signal fragments.

    Matches patterns like:
      - "Target: Anthropic"
      - "Target: OpenAI API"
      - "Target: OpenAI Codex"
      - "Target: OpenAI GPT-5"
      - "Target: Enterprise AI Budget Trends"

    Rules: starts with 'Target:' prefix, or text is too short
    (< 20 chars) with no observable event/change indicator.
    """
    text = (getattr(signal, 'signal', '') or '').strip()
    if not text:
        return True

    # Strip markdown bold
    import re
    clean = re.sub(r'\*\*(.+?)\*\*', r'\1', text).strip()

    # Target: prefix with no real observation
    if clean.lower().startswith('target:'):
        return True

    # Too short to be meaningful (< 20 chars AND no verb/indicator)
    if len(clean) < 20:
        has_verb = any(w in clean.lower() for w in
                       ('增长', '下降', '变化', '发布', '推出', '超过',
                        '突破', '增长', '减少', '达到', '增长', '进入',
                        'grow', 'drop', 'change', 'launch', 'release',
                        'increase', 'decrease', 'reach', 'expand',
                        'announce', 'report', '数据', '收入', '估值'))
        if not has_verb:
            return True

    return False


def is_claim_fragment(claim: "ClaimInfo") -> bool:
    """Detect invalid claim fragments (Target: prefix or extremely short)."""
    text = (getattr(claim, 'claim', '') or '').strip()
    if not text:
        return True
    import re
    clean = re.sub(r'\*\*(.+?)\*\*', r'\1', text).strip()
    if clean.lower().startswith('target:'):
        return True
    # Only flag extremely short text (< 10 chars)
    return len(clean) < 10


def get_claim_actionability(
    claim: "ClaimInfo",
    is_canonical: bool = True,
    duplicate_group: "DuplicateGroup | None" = None,
) -> Actionability:
    """Determine actionability for a claim.

    P2-N.4.4.1: Fragment gating, status gating, then priority gating.
    high priority alone does NOT imply needs_review — must combine
    with canonical status and actionable status.
    """
    status = getattr(claim, 'status', '') or ''
    priority = getattr(claim, 'review_priority', '') or ''

    # Fragment → never actionable
    if is_claim_fragment(claim):
        return Actionability(
            is_actionable=False,
            status_label="无效片段",
            reason="该判断内容不完整，无法审阅",
            item_type="claim",
            icon="",
            primary_action="",
        )

    # Duplicate → not actionable
    if not is_canonical:
        return Actionability(
            is_actionable=False,
            status_label="重复",
            reason="该判断与另一条相同，已合并展示",
            item_type="claim",
            icon="",
        )

    # Already accepted/closed
    if status in CLAIM_CLOSED_STATUSES:
        label = "已采纳" if status == "verified" else "已关闭"
        return Actionability(
            is_actionable=False,
            status_label=label,
            reason=f"状态已为 {status}",
            item_type="claim",
            icon="✅",
        )

    # Actionable: high/critical priority + active/challenged
    if priority in ('critical', 'high') and status in ('active', 'challenged'):
        return Actionability(
            is_actionable=True,
            primary_action="accept",
            secondary_action="ignore",
            status_label="需确认",
            reason="高优先级核心观点，建议确认或归档",
            item_type="claim",
            icon="🟠" if priority == 'high' else "🔴",
        )

    # Normal/low priority → not surfaced in Today
    return Actionability(
        is_actionable=False,
        status_label="常规",
        reason="优先级较低，系统已归档",
        item_type="claim",
        icon="",
    )


def get_signal_actionability(
    signal: "SignalInfo",
    is_canonical: bool = True,
    duplicate_group: "DuplicateGroup | None" = None,
) -> Actionability:
    """Determine actionability for a signal.

    P2-N.4.4.1: Fragment gating first, then status, then priority.
    Target: XXX fragments are never actionable.
    """
    status = getattr(signal, 'status', '') or ''
    tracking_status = getattr(signal, 'tracking_status', '') or ''
    priority = getattr(signal, 'review_priority', '') or ''

    # Fragment → never actionable
    if is_signal_fragment(signal):
        return Actionability(
            is_actionable=False,
            status_label="无效片段",
            reason="Target-only 或内容不完整的信号",
            item_type="signal",
            icon="",
            primary_action="",
        )

    # Duplicate → not actionable
    if not is_canonical:
        return Actionability(
            is_actionable=False,
            status_label="重复",
            reason="该信号与另一条相同，已合并展示",
            item_type="signal",
            icon="",
        )

    # Closed
    if status in SIGNAL_CLOSED_STATUSES:
        return Actionability(
            is_actionable=False,
            status_label="已关闭",
            reason=f"状态已为 {status}",
            item_type="signal",
            icon="✅",
        )

    # Already followed
    if status in SIGNAL_FOLLOWED_STATUSES or tracking_status in TRACKING_ACTIVE_STATUSES:
        return Actionability(
            is_actionable=False,
            status_label="已在跟踪",
            reason="该信号已标记为持续观察",
            item_type="signal",
            icon="🔔",
        )

    # Actionable: high/critical + open
    if priority in ('critical', 'high') and status == 'open':
        return Actionability(
            is_actionable=True,
            primary_action="follow",
            secondary_action="ignore",
            status_label="需确认",
            reason="高优先级信号，建议关注或忽略",
            item_type="signal",
            icon="🟠" if priority == 'high' else "🔴",
        )

    # Normal/low → not surfaced
    return Actionability(
        is_actionable=False,
        status_label="常规",
        reason="优先级较低，系统已归档",
        item_type="signal",
        icon="",
    )


# ── Actionable recommendations builder ──────────────────────────────

def build_actionable_recommendations(
    snapshot: "WorkspaceSnapshot",
    watchlist_config=None,
    limit: int = 3,
) -> list[dict]:
    """Build actionable recommendations for Dashboard 今日建议.

    Replaces the old _build_recommendations() in routes.py.
    Uses canonicalization + actionability to avoid showing:
      - duplicates
      - already-handled items
      - non-actionable statuses
    """
    from signalvault.workspace.canonicalize import (
        group_duplicate_claims,
        group_duplicate_signals,
    )
    from signalvault.workspace.review_priority import (
        PRIORITY_CRITICAL,
        PRIORITY_HIGH,
    )

    items: list[dict] = []

    # Canonicalize
    claim_groups = group_duplicate_claims(snapshot.claims)
    signal_groups = group_duplicate_signals(snapshot.signals)

    # Collect actionable signals (open only, high/critical priority, canonical)
    actionable_signals = []
    for sg in signal_groups:
        a = get_signal_actionability(sg.canonical, is_canonical=True)
        if a.is_actionable:
            actionable_signals.append((sg.canonical, a))

    # Collect actionable claims (active/challenged, high/critical priority, canonical)
    actionable_claims = []
    for cg in claim_groups:
        a = get_claim_actionability(cg.canonical, is_canonical=True)
        if a.is_actionable:
            actionable_claims.append((cg.canonical, a))

    # Priority 1: pending patches (keep as-is from old logic)
    if getattr(snapshot, 'llm_patches', None):
        pending = [p for p in snapshot.llm_patches if p.status == "pending_review"]
        if pending:
            p = sorted(pending, key=lambda x: x.generated_at or "", reverse=True)[0]
            items.append({
                "icon": "📋",
                "primary_action": "view_patch",
                "secondary_action": "",
                "is_actionable": True,
                "status_label": "AI 建议",
                "reason": f"AI 整理了「{p.target}」的最新内容",
                "patch_id": p.patch_id,
                "target": p.target,
                "text": f"AI 整理了「{p.target}」的最新内容，建议确认后采纳",
                "post_url": "",
            })

    # Priority 2: first actionable signal
    for sig, a in actionable_signals:
        if len(items) >= limit:
            break
        sig_text = getattr(sig, 'signal', '') or ''
        from signalvault.utils.display import clean_display_text
        items.append({
            "icon": a.icon,
            "primary_action": a.primary_action,
            "secondary_action": a.secondary_action,
            "is_actionable": a.is_actionable,
            "status_label": a.status_label,
            "reason": a.reason,
            "card_id": sig.card_id,
            "text": clean_display_text(sig_text, 100),
            "post_url": f"/signals/{sig.card_id}/status",
        })

    # Priority 3: first actionable claim
    for cl, a in actionable_claims:
        if len(items) >= limit:
            break
        claim_text = getattr(cl, 'claim', '') or ''
        from signalvault.utils.display import clean_display_text
        items.append({
            "icon": a.icon,
            "primary_action": a.primary_action,
            "secondary_action": a.secondary_action,
            "is_actionable": a.is_actionable,
            "status_label": a.status_label,
            "reason": a.reason,
            "card_id": cl.card_id,
            "text": clean_display_text(claim_text, 120),
            "post_url": f"/claims/{cl.card_id}/status",
        })

    # Fallback: recent report
    if len(items) < 2 and snapshot.reports:
        recent = snapshot.recent_reports(3)
        if recent:
            r = recent[0]
            items.append({
                "icon": "📄",
                "primary_action": "view_report",
                "secondary_action": "",
                "is_actionable": True,
                "status_label": "",
                "reason": f"最新分析内容，{r.analyzed_at[:10] if r.analyzed_at else '?'}",
                "text": f"阅读最新报告：{(r.channel or '?').split(' ')[0]} — {(r.title or r.filename)[:50]}",
                "post_url": "",
            })

    return items[:limit]
