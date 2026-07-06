"""P2-J.1: Rule-based Research Brief generator.

Generates structured research insights from WorkspaceSnapshot.
No LLM, no external APIs, pure deterministic rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from signalvault.workspace.scanner import WorkspaceSnapshot


@dataclass
class TopicInsight:
    name: str
    score: float
    reports: int
    claims: int
    signals: int
    summary: str = ""


@dataclass
class CompanyInsight:
    name: str
    score: float
    reports: int
    claims: int
    signals: int
    summary: str = ""


@dataclass
class ResearchBrief:
    generated_at: str
    summary: list[str] = field(default_factory=list)
    active_topics: list[TopicInsight] = field(default_factory=list)
    active_companies: list[CompanyInsight] = field(default_factory=list)
    reinforced_claims: list[str] = field(default_factory=list)
    new_signals: list[str] = field(default_factory=list)
    recommended_reports: list[dict] = field(default_factory=list)
    total_reports: int = 0
    total_claims: int = 0
    total_signals: int = 0


def generate_brief(snapshot: WorkspaceSnapshot) -> ResearchBrief:
    """Generate a research brief from vault snapshot. Pure rules, no LLM."""

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    brief = ResearchBrief(generated_at=now)
    brief.total_reports = len(snapshot.reports)
    brief.total_claims = len(snapshot.claims)
    brief.total_signals = len(snapshot.signals)

    # ── Active Topics (weighted scoring) ──
    topic_scores = []
    for t in snapshot.topics:
        c_count = snapshot.claims_count_for(t.name)
        s_count = snapshot.signals_count_for(t.name)
        r_count = len(t.source_reports)
        score = c_count * 2.0 + s_count * 1.5 + r_count * 1.0
        if score > 0 or t.status == "core":
            topic_scores.append(TopicInsight(
                name=t.name, score=score,
                reports=r_count, claims=c_count, signals=s_count,
            ))

    topic_scores.sort(key=lambda x: x.score, reverse=True)
    brief.active_topics = topic_scores[:5]

    # ── Active Companies (weighted scoring) ──
    # P2-N.4.3.2: Use filtered core_companies() to exclude non-company entities
    company_scores = []
    for c in snapshot.core_companies():
        c_count = snapshot.claims_count_for(c.name)
        s_count = snapshot.signals_count_for(c.name)
        r_count = len(c.source_reports)
        score = c_count * 2.0 + s_count * 1.5 + r_count * 1.0
        if score > 0:
            company_scores.append(CompanyInsight(
                name=c.name, score=score,
                reports=r_count, claims=c_count, signals=s_count,
            ))

    company_scores.sort(key=lambda x: x.score, reverse=True)
    brief.active_companies = company_scores[:5]

    # ── Reinforced Claims (claims tied to multiple reports or core topics) ──
    # P2-N.4.4: Canonical dedup — only show canonical claim per duplicate group
    from signalvault.workspace.canonicalize import (
        group_duplicate_claims,
        normalize_claim_text,
    )
    core_topic_names = {t.name for t in snapshot.core_topics()}
    claim_groups = group_duplicate_claims(snapshot.claims)
    reinforced = []
    seen_fingerprints: set[str] = set()
    for cg in claim_groups:
        c = cg.canonical
        sr_count = len(c.source_reports)
        has_core_topic = any(t in core_topic_names for t in c.related_topics)
        if sr_count >= 2 or (has_core_topic and sr_count >= 1):
            # P2-N.4.4: Use normalized clean text for display
            text = normalize_claim_text(c.claim)[:120] if c.claim else c.card_id
            fp = text[:80]  # fingerprint prefix
            if fp not in seen_fingerprints:
                seen_fingerprints.add(fp)
                reinforced.append(text)
    brief.reinforced_claims = reinforced[:5]

    # ── New Signals (recently updated watching/open) ──
    watching = [s for s in snapshot.signals if s.status in ("watching", "open")]
    watching.sort(key=lambda s: s.updated_at or "", reverse=True)
    new_signals = []
    for s in watching[:5]:
        text = s.signal[:120] if s.signal else s.card_id
        new_signals.append(text)
    brief.new_signals = new_signals

    # ── Recommended Reports (most recent, rich in claims/signals) ──
    recs = []
    for r in snapshot.recent_reports(5):
        recs.append({
            "title": r.title or r.filename,
            "filename": r.filename,
            "channel": r.channel or "",
            "video_id": r.video_id or "",
        })
    brief.recommended_reports = recs

    # ── Summary bullets (natural language, rule-generated) ──
    summary = _build_summary(brief, snapshot)
    brief.summary = summary

    return brief


def _build_summary(brief: ResearchBrief, snapshot: WorkspaceSnapshot) -> list[str]:
    """Build 3-5 explanatory summary bullets. Rule-based, no LLM.

    P2-N.2: Upgraded from statistical counting to contextual explanation.
    Each bullet now explains WHY a topic/company matters, not just HOW MANY.
    """
    from signalvault.utils.display import clean_display_text

    # P2-N.4.3.2: Generic topic names that shouldn't be sole subjects
    _GENERIC_TOPICS = frozenset({
        "ai", "market", "model", "technology", "tech",
        "investment", "investing", "finance", "business",
    })

    bullets = []

    # 1. Most active non-generic topic — explain what changed and why it matters
    active_topics = [t for t in brief.active_topics
                     if t.name.lower() not in _GENERIC_TOPICS]
    if active_topics and active_topics[0].score > 0:
        t = active_topics[0]
        related_companies = _find_related_companies(t.name, snapshot)
        context_phrase = _derive_topic_context(t.name, snapshot)
        # P2-N.4.3.2: Explain change, not just "most active"
        if context_phrase:
            bullets.append(f"{t.name} 方面，讨论聚焦{context_phrase}。"
                          f"涉及 {t.claims} 条判断。")
        elif related_companies:
            bullets.append(f"{t.name} 在本轮报告中活跃，"
                          f"相关公司包括 {'、'.join(related_companies[:3])}。"
                          f"涉及 {t.claims} 条判断。")
        else:
            bullets.append(f"{t.name} 在本轮报告中活跃，涉及 {t.claims} 条判断。")

    # 2. Most active company (watchlist priority)
    active_companies = brief.active_companies
    if active_companies and active_companies[0].score > 0:
        c = active_companies[0]
        related_topics = _find_related_topics(c.name, snapshot)[:3]
        if related_topics:
            bullets.append(f"{c.name} 在近期报告中讨论集中，"
                          f"主要涉及 {'、'.join(related_topics)}。")
        elif c.claims > 0:
            bullets.append(f"{c.name} 在近期报告中受到关注，"
                          f"涵盖 {c.claims} 条判断。")

    # 3. Coverage summary — compact
    channels = snapshot.channels or []
    bullets.append(f"知识库共 {brief.total_reports} 份报告（"
                  f"{', '.join(ch.name for ch in channels[:3])} 等），"
                  f"{brief.total_claims} 条判断，{brief.total_signals} 个观察点。")

    # 4. Reinforced claims — what's gaining confidence
    if brief.reinforced_claims:
        cleaned = [clean_display_text(c, 40) for c in brief.reinforced_claims[:1]]
        snippets = "；".join(cleaned)
        bullets.append(f"{len(brief.reinforced_claims)} 条判断被多份报告交叉验证，可信度较高。"
                      f"如：{snippets}")

    return bullets[:5]


def _find_related_companies(topic_name: str, snapshot: WorkspaceSnapshot) -> list[str]:
    """Find companies that appear alongside this topic in claims."""
    companies = set()
    for claim in snapshot.claims:
        if topic_name in claim.related_topics:
            for comp in claim.related_companies:
                companies.add(comp)
    return sorted(companies)[:5]


def _find_related_topics(company_name: str, snapshot: WorkspaceSnapshot) -> list[str]:
    """Find topics that appear alongside this company in claims."""
    topics = set()
    for claim in snapshot.claims:
        if company_name in claim.related_companies:
            for t in claim.related_topics:
                topics.add(t)
    return sorted(topics)[:5]


def _derive_topic_context(topic_name: str, snapshot: WorkspaceSnapshot) -> str:
    """Extract a short context phrase from claims related to this topic."""
    related_claims = [
        c for c in snapshot.claims
        if topic_name in c.related_topics
    ]
    if not related_claims:
        return ""

    # Use the first few words from the highest-quality claim
    from signalvault.utils.display import clean_display_text
    for claim in related_claims[:5]:
        text = clean_display_text(claim.claim, 120)
        # Try to extract the subject matter
        if "模型" in text or "model" in text.lower():
            return "模型能力演进和竞争格局"
        if "Agent" in text or "agent" in text.lower():
            return "Agent 应用和企业自动化"
        if "infra" in text.lower() or "基础设施" in text:
            return "算力基础设施和投资周期"
        if "企业" in text or "enterprise" in text.lower():
            return "企业采用和商业落地"
        if "市场" in text or "market" in text.lower() or "估值" in text:
            return "市场趋势和估值变化"
        if "安全" in text or "safety" in text.lower():
            return "AI 安全和治理"

    # Fallback: use first 40 chars of first claim
    if related_claims:
        return clean_display_text(related_claims[0].claim, 40)

    return ""
