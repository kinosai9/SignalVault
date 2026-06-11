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


def generate_home_dashboard(snapshot: WorkspaceSnapshot) -> str:
    """Build Home.md managed block content."""
    lines: list[str] = []

    # ── Quick Navigation ──
    lines.extend([
        "## 快速入口",
        "",
        "- [[99_System/Knowledge Map|知识地图]] | [[99_System/Review Queue|审阅队列]]",
        "- [[99_System/Claim Index|Claim Index]] | [[99_System/Signal Index|Signal Index]]",
        "- [[99_System/Topic Taxonomy|Topic Taxonomy]] | [[99_System/Report Index|Report Index]]",
        "- [[99_System/Company Index|Company Index]] | [[99_System/Topic Index|Topic Index]]",
        "",
    ])

    # ── Core Topics ──
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
            cs = t.curation_status or "unknown"
            lines.append(
                f"| {t.name} | {reports_n} | {claims_n} | {signals_n} | "
                f"`{cs}` | [[02_Topics/{t.name}|→]] |"
            )
    else:
        lines.append("| *No core topics yet* ||||||")
    lines.append("")

    # ── Core Companies ──
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
            cs = c.curation_status or "unknown"
            lines.append(
                f"| {c.name} | {reports_n} | {claims_n} | {signals_n} | "
                f"`{cs}` | [[03_Companies/{c.name}|→]] |"
            )
    else:
        lines.append("| *No core companies yet* ||||||")
    lines.append("")

    # ── 待审阅 ──
    pending_n = len(snapshot.pending_patches())
    active_claims_n = len(snapshot.active_claims())
    challenged_claims_n = len(snapshot.challenged_claims())
    open_signals_n = len(snapshot.open_signals())
    watching_signals_n = len(snapshot.watching_signals())

    lines.extend([
        "## 待审阅",
        "",
        f"- **LLM Patches pending review**: {pending_n}",
        f"- **Active claims**: {active_claims_n}",
        f"- **Challenged claims**: {challenged_claims_n}",
        f"- **Open signals**: {open_signals_n}",
        f"- **Watching signals**: {watching_signals_n}",
        "",
    ])

    # ── 最近报告 ──
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
            ch = r.channel or "?"
            lines.append(f"| {date} | {ch} | [[01_Reports/{r.filename}\\|{r.title[:50] or r.filename}]] |")
    else:
        lines.append("| *No reports yet* |||")
    lines.append("")

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
    core = sorted(snapshot.core_topics(), key=lambda t: t.name)
    lines.extend([
        "## Core Topics",
        "",
    ])
    if core:
        for t in core:
            cs = t.curation_status or "unknown"
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
            cs = c.curation_status or "unknown"
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


def generate_review_queue(snapshot: WorkspaceSnapshot) -> str:
    """Build 99_System/Review Queue.md managed block content."""
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

    # ── Claims to Review (Top-10, priority-sorted) ──
    review_claims = _sort_claims_by_priority(snapshot.review_claims())
    total_claims = len(review_claims)
    top_claims = review_claims[:MAX_CLAIMS_IN_REVIEW_QUEUE]
    lines.extend([
        "## Claims to Review",
        "",
    ])
    if top_claims:
        lines.append("| Claim | Status |")
        lines.append("|-------|--------|")
        for c in top_claims:
            lines.append(f"| [[06_Claims/{c.card_id}|{clean_display_text(c.claim, 50)}...]] | `{c.status}` |")
        if total_claims > MAX_CLAIMS_IN_REVIEW_QUEUE:
            lines.append("")
            lines.append(
                f"*{total_claims - MAX_CLAIMS_IN_REVIEW_QUEUE} more claims — "
                f"see [[99_System/Claim Review Backlog|Claim Review Backlog]]*"
            )
    else:
        lines.append("*No claims to review.*")
    lines.append("")

    # ── Signals to Review (Top-10, priority-sorted) ──
    review_signals = _sort_signals_by_priority(snapshot.review_signals())
    total_signals = len(review_signals)
    top_signals = review_signals[:MAX_SIGNALS_IN_REVIEW_QUEUE]
    lines.extend([
        "## Signals to Review",
        "",
    ])
    if top_signals:
        lines.append("| Signal | Status |")
        lines.append("|--------|--------|")
        for s in top_signals:
            lines.append(f"| [[07_Signals/{s.card_id}|{clean_display_text(s.signal, 50)}...]] | `{s.status}` |")
        if total_signals > MAX_SIGNALS_IN_REVIEW_QUEUE:
            lines.append("")
            lines.append(
                f"*{total_signals - MAX_SIGNALS_IN_REVIEW_QUEUE} more signals — "
                f"see [[99_System/Signal Review Backlog|Signal Review Backlog]]*"
            )
    else:
        lines.append("*No signals to review.*")
    lines.append("")

    # ── Tracking Items ──
    tracking = snapshot.tracking_signals()
    lines.extend([
        "## Tracking Items",
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
    """Sort claims: review_priority=high first, challenged first, then by card_id."""
    def _key(c):
        rp = getattr(c, "review_priority", "") or ""
        rp_weight = 0 if rp == "high" else (1 if rp == "normal" else 1)
        st_weight = 0 if c.status == "challenged" else 1  # challenged first
        return (rp_weight, st_weight, c.card_id)
    return sorted(claims, key=_key)


def _sort_signals_by_priority(signals):
    """Sort signals: review_priority=high, tracking=active, watching first, then by card_id."""
    def _key(s):
        rp = getattr(s, "review_priority", "") or ""
        rp_weight = 0 if rp == "high" else (1 if rp == "normal" else 1)
        ts_weight = 0 if getattr(s, "tracking_status", "") == "active" else 1
        st_weight = 0 if s.status == "watching" else 1
        return (rp_weight, ts_weight, st_weight, s.card_id)
    return sorted(signals, key=_key)
