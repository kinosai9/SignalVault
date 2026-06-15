"""Dashboard generators: Home.md, Knowledge Map, Review Queue.

Pure string builders. Take a WorkspaceSnapshot, return markdown content.
No file I/O, no LLM calls, no external APIs.
"""

from __future__ import annotations

from podcast_research.utils.display import clean_display_text
from podcast_research.workspace.scanner import WorkspaceSnapshot

# Managed block names
BLOCK_HOME = "home-dashboard"
BLOCK_KNOWLEDGE_MAP = "knowledge-map"
BLOCK_REVIEW_QUEUE = "review-queue"

# Review Queue Top-N limits
MAX_CLAIMS_IN_REVIEW_QUEUE = 10
MAX_SIGNALS_IN_REVIEW_QUEUE = 10
MAX_NEEDS_REVIEW_ITEMS = 6   # P2-N.4.3.2: show at most 6, not 10


def generate_home_dashboard(
    snapshot: WorkspaceSnapshot,
    research_brief=None,       # P2-N.4.3: optional ResearchBrief for summary section
    watchlist_items=None,      # P2-N.4.3: optional WatchlistItemBrief list
    watchlist_config=None,     # P2-N.4.3: optional WatchlistConfig for priority calc
) -> str:
    """Build Home.md managed block content.

    P2-N.4.3: Restructured from "object index" to "research workbench".
    Shows priority review items, system auto-curation, and research insights.
    """
    from podcast_research.workspace.review_priority import (
        PRIORITY_AUTO_ACCEPTED,
        PRIORITY_CRITICAL,
        PRIORITY_HIGH,
        PRIORITY_LOW,
        claims_needing_review,
        compute_claim_review_priority,
        compute_signal_review_priority,
        signals_needing_review,
    )
    from podcast_research.workspace.system_curation import curation_label

    lines: list[str] = []

    # Resolve watchlist sets for priority computation
    wl_companies: set[str] = set()
    wl_topics: set[str] = set()
    if watchlist_config is not None:
        wl_companies = set(watchlist_config.companies) if hasattr(watchlist_config, 'companies') else set()
        wl_topics = set(watchlist_config.topics) if hasattr(watchlist_config, 'topics') else set()

    # ── 1. Quick Navigation (user-facing only) ──
    lines.extend([
        "## 快速入口",
        "",
        "- [[99_System/Knowledge Map|知识地图]] | [[99_System/Review Queue|审阅队列]]",
        "- [[99_System/Watchlist Brief|关注简报]] | [[99_System/Research Brief|研究简报]]",
        "",
    ])

    # ── 2. 本批研究摘要 ──
    if research_brief and getattr(research_brief, 'summary', None):
        lines.extend([
            "## 研究摘要",
            "",
        ])
        for bullet in research_brief.summary[:3]:
            lines.append(f"- {bullet}")
        lines.extend([
            "",
            f"*基于 {research_brief.total_reports} 份报告，{research_brief.total_claims} 条判断，{research_brief.total_signals} 个观察点*",
            "",
        ])

    # ── 3. 我的关注变化 ──
    if watchlist_items:
        direct_items = [wi for wi in watchlist_items if getattr(wi, 'status', '') == 'direct']
        indirect_items = [wi for wi in watchlist_items if getattr(wi, 'status', '') == 'indirect']
        if direct_items or indirect_items:
            lines.extend(["## 我的关注变化", ""])
            # P2-N.4.3.2: Group by company / direction
            companies_direct = [wi for wi in direct_items if getattr(wi, 'item_type', '') == 'company']
            topics_direct = [wi for wi in direct_items if getattr(wi, 'item_type', '') == 'topic']
            themes = [wi for wi in direct_items if getattr(wi, 'item_type', '') == 'theme']
            if companies_direct or topics_direct:
                if companies_direct:
                    lines.append("**关注公司**")
                    for wi in companies_direct[:5]:
                        lines.append(f"- 🟢 **{wi.name}**: {getattr(wi, 'summary', '')}")
                if topics_direct:
                    lines.append("**关注方向**")
                    for wi in topics_direct[:5]:
                        lines.append(f"- 🟢 **{wi.name}**: {getattr(wi, 'summary', '')}")
                if themes:
                    for wi in themes[:3]:
                        lines.append(f"- 🟢 **{wi.name}**: {getattr(wi, 'summary', '')}")
            for wi in indirect_items[:3]:
                lines.append(f"- 🟡 **{wi.name}**: {getattr(wi, 'summary', '')}")
            lines.append("")

    # ── 4. 需要你确认 ──
    # P2-N.4.4.2: Single canonical entry point for all surfaces
    from podcast_research.workspace.canonical_view import build_review_item_views

    review_items = build_review_item_views(snapshot, watchlist_config)
    total_needs_review = len(review_items)

    # Count priorities for summary
    auto_accepted_claims = sum(
        1 for c in snapshot.claims
        if compute_claim_review_priority(c, snapshot, wl_companies, wl_topics) == PRIORITY_AUTO_ACCEPTED
    )
    auto_accepted_signals = sum(
        1 for s in snapshot.signals
        if compute_signal_review_priority(s, snapshot, wl_companies, wl_topics) == PRIORITY_AUTO_ACCEPTED
    )
    low_priority_claims = sum(
        1 for c in snapshot.claims
        if compute_claim_review_priority(c, snapshot, wl_companies, wl_topics) == PRIORITY_LOW
    )
    low_priority_signals = sum(
        1 for s in snapshot.signals
        if compute_signal_review_priority(s, snapshot, wl_companies, wl_topics) == PRIORITY_LOW
    )
    tracking_signal_count = len(snapshot.tracking_signals())

    lines.extend([
        "## 需要你确认",
        "",
    ])
    if review_items:
        display_items = review_items[:MAX_NEEDS_REVIEW_ITEMS]
        lines.append(f"本轮共有 {total_needs_review} 条需审阅，以下是最重要的 {len(display_items)} 条：")
        lines.append("")
        for rv in display_items:
            lines.append(
                f"- {rv.icon} [[{rv.card_type}/{rv.card_id}|{rv.display_text}]] "
                f"`{rv.status_label}`"
            )
        lines.append("")
        lines.append("[[99_System/Review Queue|查看全部审阅队列 →]]")
    else:
        lines.append("*没有需要你确认的项目。*")
    lines.append("")

    # Summary of system actions
    auto_total = auto_accepted_claims + auto_accepted_signals
    low_total = low_priority_claims + low_priority_signals
    if auto_total > 0 or low_total > 0 or tracking_signal_count > 0:
        parts = []
        if auto_total > 0:
            parts.append(f"系统已自动整理 {auto_total} 条")
        if tracking_signal_count > 0:
            parts.append(f"正在跟踪 {tracking_signal_count} 条")
        if low_total > 0:
            parts.append(f"低优先级归档 {low_total} 条")
        lines.append(f"*{'，'.join(parts)}*")
        lines.append("")

    # ── 5. 正在跟踪的信号 ──
    tracking = snapshot.tracking_signals()
    if tracking:
        lines.extend([
            "## 正在跟踪的信号",
            "",
        ])
        for s in tracking[:5]:
            lines.append(f"- [[07_Signals/{s.card_id}|{clean_display_text(s.signal, 60)}...]] `tracking: {s.tracking_status}`")
        lines.append("")

    # ── 6. 核心主题 ──
    core = sorted(snapshot.core_topics(), key=lambda t: t.name)
    lines.extend([
        "## 核心主题",
        "",
        "| Topic | Reports | Claims | Signals | Curation | Card |",
        "|-------|---------|--------|---------|----------|------|",
    ])
    if core:
        for t in core:
            reports_n = len(t.source_reports)
            claims_n = snapshot.claims_count_for(t.name)
            signals_n = snapshot.signals_count_for(t.name)
            # P2-N.4.3: Show system_curation with label; user_curation takes priority
            sys_cur = t.system_curation or ""
            user_cur = t.curation_status or ""
            if user_cur and user_cur not in ("raw", "unknown", "indexed", ""):
                display_cur = user_cur
            elif sys_cur:
                display_cur = curation_label(sys_cur)
            else:
                display_cur = "—"
            lines.append(
                f"| {t.name} | {reports_n} | {claims_n} | {signals_n} | "
                f"`{display_cur}` | [[02_Topics/{t.name}|→]] |"
            )
    else:
        lines.append("| *No core topics yet* ||||||")
    lines.append("")

    # ── 7. 核心公司 ──
    core_companies = sorted(snapshot.core_companies(), key=lambda c: c.name)
    lines.extend([
        "## 核心公司",
        "",
        "| Company | Reports | Claims | Signals | Curation | Card |",
        "|---------|---------|--------|---------|----------|------|",
    ])
    if core_companies:
        for c in core_companies:
            reports_n = len(c.source_reports)
            claims_n = snapshot.claims_count_for(c.name)
            signals_n = snapshot.signals_count_for(c.name)
            # P2-N.4.3: Show system_curation with label
            sys_cur = c.system_curation or ""
            user_cur = c.curation_status or ""
            if user_cur and user_cur not in ("raw", "unknown", "indexed", ""):
                display_cur = user_cur
            elif sys_cur:
                display_cur = curation_label(sys_cur)
            else:
                display_cur = "—"
            lines.append(
                f"| {c.name} | {reports_n} | {claims_n} | {signals_n} | "
                f"`{display_cur}` | [[03_Companies/{c.name}|→]] |"
            )
    else:
        lines.append("| *No core companies yet* ||||||")
    lines.append("")

    # ── 8. 最近报告 ──
    recent = snapshot.recent_reports(10)
    lines.extend([
        "## 最近报告",
        "",
        "| Date | Channel | Report |",
        "|------|---------|--------|",
    ])
    if recent:
        for r in recent:
            date = r.analyzed_at[:10] if r.analyzed_at else "?"
            ch = (r.channel or "?").split(" ")[0]  # P2-N.4.3.2: first word of channel
            raw_title = r.title or r.filename
            # P2-N.4.3.2: clean title, max 60 chars, no escaping in alias
            alias = clean_display_text(raw_title, 60)
            lines.append(f"| {date} | {ch} | [[01_Reports/{r.filename}|{alias}]] |")
    else:
        lines.append("| *No reports yet* |||")
    lines.append("")

    # ── 9. 系统健康 ──
    lines.extend([
        "## 系统健康",
        "",
        f"- **总报告**: {len(snapshot.reports)} | **主题**: {len(snapshot.topics)} (core: {len(core)}) | **公司**: {len(snapshot.core_companies())}",
        f"- **判断**: {len(snapshot.claims)} | **信号**: {len(snapshot.signals)} | **频道**: {len(snapshot.channels)}",
    ])
    if snapshot.llm_patches:
        pending_n = len(snapshot.pending_patches())
        if pending_n > 0:
            lines.append(f"- **待处理补丁**: {pending_n}")
    lines.append("")

    # ── 10. 系统索引 (collapsed, developer tools) ──
    lines.extend([
        "## 系统索引",
        "",
        "- [[99_System/Claim Index|Claim Index]] | [[99_System/Signal Index|Signal Index]]",
        "- [[99_System/Topic Taxonomy|Topic Taxonomy]] | [[99_System/Report Index|Report Index]]",
        "- [[99_System/Company Index|Company Index]] | [[99_System/Topic Index|Topic Index]]",
        "- [[99_System/Claim Review Backlog|Claim Review Backlog]] | [[99_System/Signal Review Backlog|Signal Review Backlog]]",
        "",
    ])

    # ── 最近更新 ──
    log_entries = snapshot.recent_log_entries(10)
    lines.append("## 最近更新")
    lines.append("")
    if log_entries:
        for entry in log_entries:
            lines.append(f"- {entry}")
    else:
        lines.append("*No recent log entries.*")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def generate_knowledge_map(snapshot: WorkspaceSnapshot) -> str:
    """Build 99_System/Knowledge Map.md managed block content."""
    lines: list[str] = []

    # ── Core Topics ──
    from podcast_research.workspace.system_curation import curation_label
    core = sorted(snapshot.core_topics(), key=lambda t: t.name)
    lines.extend([
        "## Core Topics",
        "",
    ])
    if core:
        for t in core:
            sys_cur = t.system_curation or ""
            user_cur = t.curation_status or ""
            if user_cur and user_cur not in ("raw", "unknown", "indexed", ""):
                cs = user_cur
            elif sys_cur:
                cs = curation_label(sys_cur)
            else:
                cs = "—"
            lines.append(
                f"- [[02_Topics/{t.name}|{t.name}]] "
                f"({len(t.source_reports)} reports, "
                f"{snapshot.claims_count_for(t.name)} claims, "
                f"{snapshot.signals_count_for(t.name)} signals) "
                f"`{cs}`"
            )
    else:
        lines.append("*No core topics.*")
    lines.append("")

    long_tail = snapshot.long_tail_topics()
    no_status = snapshot.topics_without_status()
    other_count = len(long_tail) + len(no_status)
    if other_count > 0:
        # Quality breakdown
        all_other = long_tail + no_status
        useful = sum(1 for t in all_other if t.topic_quality == "useful")
        noisy = sum(1 for t in all_other if t.topic_quality == "noisy")
        alias_merged = sum(1 for t in all_other if t.topic_quality == "alias")
        mr = sum(1 for t in all_other if t.topic_quality == "manual_review")
        long_tail_n = len([t for t in all_other if t.topic_quality in ("long_tail", "")])

        parts = [f"{other_count} other topics"]
        if useful:
            parts.append(f"{useful} useful")
        if noisy:
            parts.append(f"{noisy} noisy")
        if alias_merged:
            parts.append(f"{alias_merged} alias")
        if long_tail_n:
            parts.append(f"{long_tail_n} long-tail")
        if mr:
            parts.append(f"{mr} manual_review")
        lines.append(
            f"*{', '.join(parts)} — "
            f"see [[99_System/Topic Index|Topic Index]]*"
        )
    lines.append("")

    # ── Core Companies ──
    core_companies = sorted(snapshot.core_companies(), key=lambda c: c.name)
    lines.extend([
        "## Core Companies",
        "",
    ])
    if core_companies:
        for c in core_companies:
            sys_cur = c.system_curation or ""
            user_cur = c.curation_status or ""
            if user_cur and user_cur not in ("raw", "unknown", "indexed", ""):
                cs = user_cur
            elif sys_cur:
                cs = curation_label(sys_cur)
            else:
                cs = "—"
            lines.append(
                f"- [[03_Companies/{c.name}|{c.name}]] "
                f"({len(c.source_reports)} reports, "
                f"{snapshot.claims_count_for(c.name)} claims) "
                f"`{cs}`"
            )
    else:
        lines.append("*No core companies.*")
    lines.append("")

    # ── Active Claims ──
    active = snapshot.active_claims()
    lines.extend([
        "## Active Claims",
        "",
    ])
    if active:
        for c in sorted(active, key=lambda x: x.status):
            lines.append(f"- [[06_Claims/{c.card_id}|{clean_display_text(c.claim, 60)}...]] `{c.status}`")
    else:
        lines.append("*No active claims.*")
    lines.append("")

    # ── Watching Signals ──
    watching = snapshot.watching_signals()
    lines.extend([
        "## Watching Signals",
        "",
    ])
    if watching:
        for s in sorted(watching, key=lambda x: x.status):
            lines.append(f"- [[07_Signals/{s.card_id}|{clean_display_text(s.signal, 60)}...]] `{s.status}`")
    else:
        lines.append("*No watching signals.*")
    lines.append("")

    # ── Recent Reports ──
    recent = snapshot.recent_reports(10)
    lines.extend([
        "## Recent Reports",
        "",
    ])
    if recent:
        for r in recent:
            lines.append(f"- [[01_Reports/{r.filename}|{r.filename}]] ({r.channel})")
    else:
        lines.append("*No reports.*")
    lines.append("")

    # ── Source Channels ──
    lines.extend([
        "## Source Channels",
        "",
    ])
    if snapshot.channels:
        for ch in sorted(snapshot.channels, key=lambda x: x.name):
            lines.append(f"- [[05_Channels/{ch.name}|{ch.name}]] ({ch.priority or 'unset'})")
    else:
        lines.append("*No channels.*")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def generate_review_queue(
    snapshot: WorkspaceSnapshot,
    watchlist_config=None,     # P2-N.4.3: optional WatchlistConfig for priority calc
) -> str:
    """Build 99_System/Review Queue.md managed block content.

    P2-N.4.3: Shows only high-priority items needing user attention.
    Auto-accepted and low-priority items are summarized, not listed.
    """
    from podcast_research.workspace.review_priority import (
        PRIORITY_AUTO_ACCEPTED,
        PRIORITY_CRITICAL,
        PRIORITY_HIGH,
        PRIORITY_LOW,
        claims_needing_review,
        compute_claim_review_priority,
        compute_signal_review_priority,
        signals_needing_review,
    )

    # Resolve watchlist
    wl_companies: set[str] = set()
    wl_topics: set[str] = set()
    if watchlist_config is not None:
        wl_companies = set(watchlist_config.companies) if hasattr(watchlist_config, 'companies') else set()
        wl_topics = set(watchlist_config.topics) if hasattr(watchlist_config, 'topics') else set()

    lines: list[str] = []

    # ── Pending LLM Patches ──
    pending = sorted(
        snapshot.pending_patches(),
        key=lambda p: p.generated_at, reverse=True,
    )
    lines.extend([
        "## Pending LLM Patches",
        "",
    ])
    if pending:
        lines.append("| Patch | Target | Type | Generated |")
        lines.append("|-------|--------|------|-----------|")
        for p in pending:
            gen_date = p.generated_at[:10] if p.generated_at else "?"
            lines.append(
                f"| [[00_Inbox/LLM_Patches/{p.patch_id}|→]] "
                f"| {p.target} | {p.target_type} | {gen_date} |"
            )
    else:
        lines.append("*No pending patches.*")
    lines.append("")

    # ── P2-N.4.4.2: 需要你确认 (canonical/actionability-first) ──
    from podcast_research.workspace.canonical_view import build_review_item_views

    review_items = build_review_item_views(snapshot, watchlist_config)
    total_needs = len(review_items)

    lines.extend([
        "## 需要你确认",
        "",
    ])
    if total_needs > 0:
        lines.append("| 类型 | 内容 | 状态 |")
        lines.append("|------|------|------|")
        claim_shown = 0
        signal_shown = 0
        for rv in review_items:
            if rv.item_type == "claim" and claim_shown >= MAX_CLAIMS_IN_REVIEW_QUEUE:
                continue
            if rv.item_type == "signal" and signal_shown >= MAX_SIGNALS_IN_REVIEW_QUEUE:
                continue
            label = "Claim" if rv.item_type == "claim" else "Signal"
            card_path = f"{rv.card_type}/{rv.card_id}"
            lines.append(
                f"| {rv.icon} {label} | [[{card_path}|{rv.display_text}...]] "
                f"| `{rv.status_label}` |"
            )
            if rv.item_type == "claim":
                claim_shown += 1
            else:
                signal_shown += 1
        remaining = (total_needs - claim_shown - signal_shown)
        if remaining > 0:
            lines.append(f"| … | *{remaining} more items* ||")
    else:
        lines.append("*没有需要你确认的项目。*")
    lines.append("")

    # ── P2-N.4.3: 系统自动整理摘要 ──
    auto_claims = sum(
        1 for c in snapshot.claims
        if compute_claim_review_priority(c, snapshot, wl_companies, wl_topics) == PRIORITY_AUTO_ACCEPTED
    )
    auto_signals = sum(
        1 for s in snapshot.signals
        if compute_signal_review_priority(s, snapshot, wl_companies, wl_topics) == PRIORITY_AUTO_ACCEPTED
    )
    low_claims = sum(
        1 for c in snapshot.claims
        if compute_claim_review_priority(c, snapshot, wl_companies, wl_topics) == PRIORITY_LOW
    )
    low_signals = sum(
        1 for s in snapshot.signals
        if compute_signal_review_priority(s, snapshot, wl_companies, wl_topics) == PRIORITY_LOW
    )
    tracking_count = len(snapshot.tracking_signals())

    summary_parts = []
    if auto_claims + auto_signals > 0:
        summary_parts.append(f"系统已自动整理 {auto_claims + auto_signals} 条（{auto_claims} 判断 + {auto_signals} 信号）")
    if tracking_count > 0:
        summary_parts.append(f"正在跟踪 {tracking_count} 个信号")
    if low_claims + low_signals > 0:
        summary_parts.append(f"低优先级归档 {low_claims + low_signals} 条")
    if summary_parts:
        lines.extend([
            "## 系统自动整理",
            "",
        ])
        for part in summary_parts:
            lines.append(f"- {part}")
        lines.append("")

    # ── Tracking Items ──
    tracking = snapshot.tracking_signals()
    lines.extend([
        "## 正在跟踪",
        "",
    ])
    if tracking:
        for s in tracking:
            lines.append(
                f"- [[07_Signals/{s.card_id}|{clean_display_text(s.signal, 60)}...]] "
                f"`tracking: {s.tracking_status}`"
            )
    else:
        lines.append("*No active tracking items.*")
    lines.append("")

    # ── Recently Added Reports ──
    recent = snapshot.recent_reports(10)
    lines.extend([
        "## Recently Added Reports",
        "",
    ])
    if recent:
        for r in recent:
            lines.append(f"- [[01_Reports/{r.filename}|{r.filename}]] ({r.channel})")
    else:
        lines.append("*No reports.*")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ── Priority-based sorting helpers ────────────────────────────────

def _sort_claims_by_priority(claims):
    """Sort claims by review_priority (critical > high > normal > low), then challenged, then card_id."""
    PRIORITY_ORDER = {"critical": 0, "high": 1, "normal": 2, "low": 3, "auto_accepted": 4}
    def _key(c):
        rp = getattr(c, "review_priority", "") or ""
        rp_weight = PRIORITY_ORDER.get(rp, 2)
        st_weight = 0 if c.status == "challenged" else 1
        return (rp_weight, st_weight, c.card_id)
    return sorted(claims, key=_key)


def _sort_signals_by_priority(signals):
    """Sort signals by review_priority (critical > high > normal > low), tracking=active, watching first."""
    PRIORITY_ORDER = {"critical": 0, "high": 1, "normal": 2, "low": 3, "auto_accepted": 4}
    def _key(s):
        rp = getattr(s, "review_priority", "") or ""
        rp_weight = PRIORITY_ORDER.get(rp, 2)
        ts_weight = 0 if getattr(s, "tracking_status", "") == "active" else 1
        st_weight = 0 if s.status == "watching" else 1
        return (rp_weight, ts_weight, st_weight, s.card_id)
    return sorted(signals, key=_key)


# ── P2-N.4.3.2: Dedup helper ──────────────────────────────────────

def _strip_for_dedup(text: str) -> str:
    """Strip markdown formatting and trailing tags for comparison purposes."""
    import re
    # Strip bold/italic
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(?!\*)([^*\n]+?)\*(?!\*)', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Strip all hashtag tokens (including CJK and partial tags at end)
    text = re.sub(r'#[\w一-鿿-]*', '', text)
    # Strip trailing backtick fragments
    text = re.sub(r'`[^`]*$', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _token_overlap(text1: str, text2: str) -> float:
    """Compute Jaccard-like token overlap ratio between two texts."""
    t1 = _strip_for_dedup(text1)
    t2 = _strip_for_dedup(text2)
    tokens1 = set(t1.lower().split())
    tokens2 = set(t2.lower().split())
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    return len(intersection) / len(union)


def _prefix_overlap(text1: str, text2: str) -> bool:
    """Check if two texts share a long common prefix (likely duplicate cards)."""
    t1 = _strip_for_dedup(text1)
    t2 = _strip_for_dedup(text2)
    min_len = min(len(t1), len(t2))
    if min_len < 60:
        return False
    prefix_len = min(60, min_len)
    return t1[:prefix_len] == t2[:prefix_len]


def _dedup_needs_review_items(items: list) -> list:
    """Dedup claims/signals by token overlap (>40%) or common prefix (>60 chars).

    P2-N.4.3.2: Strips markdown before comparing to catch duplicate cards
    that differ only in formatting (e.g., one has **bold** and another doesn't).
    """
    from podcast_research.workspace.scanner import ClaimInfo
    result = []
    for item in items:
        item_text = getattr(item, 'claim', '') or getattr(item, 'signal', '') or ''
        is_dup = False
        for existing in result:
            existing_text = getattr(existing, 'claim', '') or getattr(existing, 'signal', '') or ''
            if _prefix_overlap(item_text, existing_text):
                is_dup = True
                break
            if _token_overlap(item_text, existing_text) > 0.30:
                is_dup = True
                break
        if not is_dup:
            result.append(item)
    return result
