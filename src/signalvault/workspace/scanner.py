"""Vault scanner: reads Obsidian vault filesystem and builds WorkspaceSnapshot.

Pure read-only. No LLM, no external APIs, no file writes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from signalvault.claim_signal.review import _parse_frontmatter
from signalvault.llm_wiki.context_builder import HIGH_VALUE_COMPANIES

# ── P2-N.1: Entity hygiene guards ────────────────────────────────────

# Names that look like companies but are actually topics/concepts
# (lowercased for case-insensitive matching)
_NOT_A_COMPANY: set[str] = {
    "agent", "agents", "ai agent", "ai agents",
    "model", "models", "ai models",
    "enterprise", "market", "capital market",
    "infrastructure", "ai infrastructure",
    "application", "applications",
    "developer tools", "open source",
    "security", "safety",
    # P2-N.4.3: Non-company entities that end up in 03_Companies/
    "claude", "chatgpt", "gpt", "gpt-4", "gpt-5", "gemini", "sonnet", "sora",
    "sam altman", "satya nadella", "donald trump",
    "ai regulation", "ai compute infrastructure", "ai semiconductors",
    "agentic ai", "enterprise ai", "venture capital", "vibe coding",
    "gpu", "api", "sdk",
    # Generic concepts that shouldn't be companies
    "edge computing", "robotics", "quantum computing",
    "saas", "platform", "data center",
    # P2-N.4.3.2: Leaking non-company entities
    "artificial intelligence", "codex", "deep research",
    "enterprise ai adoption", "github copilot", "grok",
    "mai models", "mcp", "microsoft 365", "microsoft azure",
    "model context protocol", "opus", "reasoning models",
    "美国科技公司", "ai数据中心电力基础设施",
    "ai-washing companies", "cod ex",
}

# Entity types that are NOT companies — used for core_companies() filtering
_NON_COMPANY_ENTITY_TYPES: frozenset[str] = frozenset({
    "product", "model", "person", "topic", "macro",
    "technology", "concept", "product_or_model",
    "industry_theme", "policy_or_regulation", "metric",
    "tool", "ide", "framework", "protocol", "platform",
    "os", "hardware",
})

# Names that are definitely companies, not topics
# (lowercased for case-insensitive matching)
_NOT_A_TOPIC: set[str] = {
    "anthropic", "openai", "nvidia", "microsoft", "meta", "google",
    "alphabet", "tsmc", "amd", "intel", "broadcom", "apple",
    "amazon", "tesla", "spacex", "oracle", "salesforce",
    "coreweave", "perplexity", "mistral", "deepseek",
    "blackrock", "vanguard", "vercel", "shopify", "github",
    "cloudflare", "stripe", "palantir",
}
from signalvault.utils.file_io import read_text_safe

logger = logging.getLogger(__name__)


def _extract_source_reports(content: str, fm: dict) -> list[str]:
    """Extract source report filenames from frontmatter OR markdown body.

    Priority: frontmatter source_reports field. Fallback: parse ## Source Reports
    section from markdown body for wikilinks like [[filename]].
    """
    # Frontmatter takes priority
    fm_reports = fm.get("source_reports", [])
    if isinstance(fm_reports, list) and fm_reports:
        return fm_reports

    # Fallback: parse body
    reports: list[str] = []
    in_section = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped == "## Source Reports":
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if in_section and "[[" in stripped:
            # Extract filename from [[filename]] or [[filename|alias]]
            start = stripped.find("[[")
            end = stripped.find("]]", start)
            if start >= 0 and end > start:
                link = stripped[start + 2:end]
                filename = link.split("|")[0].split("#")[0]
                reports.append(filename)
    return reports


# ── Info dataclasses ──────────────────────────────────────────────


@dataclass
class ReportInfo:
    """Parsed info from a single report in 01_Reports/."""
    filename: str              # stem, e.g. "2026-05-29_Acquired_d6EMk6dyrOU"
    path: Path
    channel: str = ""
    video_id: str = ""
    title: str = ""
    analyzed_at: str = ""      # e.g. "2026-05-29 17:00"
    focus_areas: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class TopicInfo:
    """Parsed info from a topic card in 02_Topics/."""
    name: str                  # filename stem (display name)
    path: Path
    status: str = ""           # core / emerging / long_tail / (missing)
    topic: str = ""            # display name from frontmatter
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    source_reports: list[str] = field(default_factory=list)
    updated_at: str = ""
    curation_status: str = ""  # user_curation: raw / indexed / reviewed / enhanced / archived
    system_curation: str = ""  # P2-N.4.3: auto-computed curation tier
    topic_quality: str = ""    # useful / noisy / alias / manual_review / long_tail


@dataclass
class CompanyInfo:
    """Parsed info from a company card in 03_Companies/."""
    name: str                  # filename stem (display name)
    path: Path
    company: str = ""          # display name from frontmatter
    aliases: list[str] = field(default_factory=list)
    ticker: str = ""
    sector: str = ""
    tags: list[str] = field(default_factory=list)
    source_reports: list[str] = field(default_factory=list)
    updated_at: str = ""
    curation_status: str = ""  # user_curation: raw / indexed / reviewed / enhanced / archived
    system_curation: str = ""  # P2-N.4.3: auto-computed curation tier
    entity_type: str = ""      # P2-N.4.3: company / organization / product / model / person / etc.


@dataclass
class ClaimInfo:
    """Parsed info from a claim card in 06_Claims/."""
    card_id: str               # filename stem
    path: Path
    status: str = ""           # active / verified / challenged / outdated / archived
    claim: str = ""            # statement text (truncated for display)
    source_reports: list[str] = field(default_factory=list)
    related_topics: list[str] = field(default_factory=list)
    related_companies: list[str] = field(default_factory=list)
    updated_at: str = ""
    curation_status: str = ""  # raw / indexed / reviewed / enhanced / archived
    review_priority: str = ""  # P2-N.4.3: critical / high / normal / low / auto_accepted
    quality: str = ""          # high / medium / low
    granularity: str = ""      # atomic / broad / duplicate / unclear


@dataclass
class SignalInfo:
    """Parsed info from a signal card in 07_Signals/."""
    card_id: str               # filename stem
    path: Path
    status: str = ""           # open / watching / resolved / invalidated / archived
    signal: str = ""           # statement text
    source_reports: list[str] = field(default_factory=list)
    related_topics: list[str] = field(default_factory=list)
    related_companies: list[str] = field(default_factory=list)
    tracking_status: str = ""  # from frontmatter if present
    updated_at: str = ""
    curation_status: str = ""  # raw / indexed / reviewed / enhanced / archived
    review_priority: str = ""  # P2-N.4.3: critical / high / normal / low / auto_accepted
    quality: str = ""          # high / medium / low
    signal_type: str = ""      # competition / regulation / technology_bottleneck / etc.


@dataclass
class ChannelInfo:
    """Parsed info from a channel card in 05_Channels/."""
    name: str                  # filename stem
    path: Path
    channel: str = ""
    url: str = ""
    tags: list[str] = field(default_factory=list)
    priority: str = ""         # core / secondary / archive
    updated_at: str = ""


@dataclass
class LWPatchInfo:
    """Parsed info from an LLM-WIKI patch in 00_Inbox/LLM_Patches/."""
    patch_id: str              # filename stem
    path: Path
    target_type: str = ""      # topic / company
    target: str = ""           # target name
    status: str = ""           # pending_review / approved / rejected / applied / rolled_back
    source_reports: list[str] = field(default_factory=list)
    generated_at: str = ""


# ── Workspace Snapshot ────────────────────────────────────────────


@dataclass
class WorkspaceSnapshot:
    """Complete snapshot of Obsidian vault state for dashboard generation."""
    vault_path: Path
    scanned_at: datetime = field(default_factory=datetime.now)

    reports: list[ReportInfo] = field(default_factory=list)
    topics: list[TopicInfo] = field(default_factory=list)
    companies: list[CompanyInfo] = field(default_factory=list)
    claims: list[ClaimInfo] = field(default_factory=list)
    signals: list[SignalInfo] = field(default_factory=list)
    channels: list[ChannelInfo] = field(default_factory=list)
    llm_patches: list[LWPatchInfo] = field(default_factory=list)

    # ── Topic helpers ──

    def core_topics(self) -> list[TopicInfo]:
        return [t for t in self.topics
                if t.status == "core"
                and t.name.lower() not in _NOT_A_TOPIC]

    def long_tail_topics(self) -> list[TopicInfo]:
        return [t for t in self.topics if t.status not in ("core", "")]

    def topics_without_status(self) -> list[TopicInfo]:
        return [t for t in self.topics if not t.status]

    # ── Company helpers ──

    def core_companies(self) -> list[CompanyInfo]:
        """Companies filtered for Home display.

        P2-N.4.3.2: Filters non-company entities, applies minimum criteria,
        and caps at 15 items sorted by importance.
        Criteria:
          - Not in _NOT_A_COMPANY
          - entity_type not in _NON_COMPANY_ENTITY_TYPES (if set)
          - reports >= 2 AND (claims > 0 OR signals > 0 OR in watchlist)
        """
        # Gather watchlist (check lazily for caching)
        watchlist_set: set[str] = set()
        try:
            from signalvault.workspace.watchlist import load_watchlist
            wl = load_watchlist(self.vault_path)
            watchlist_set = set(wl.companies)
        except Exception:
            pass

        candidates = []
        for c in self.companies:
            if c.name.lower() in _NOT_A_COMPANY:
                continue
            if c.entity_type and c.entity_type.lower() in _NON_COMPANY_ENTITY_TYPES:
                continue
            reports_n = len(c.source_reports)
            if reports_n < 2:
                continue
            claims_n = self.claims_count_for(c.name)
            signals_n = self.signals_count_for(c.name)
            in_wl = c.name in watchlist_set
            is_high_value = c.name in HIGH_VALUE_COMPANIES
            if not (claims_n > 0 or signals_n > 0 or in_wl or is_high_value):
                continue
            # Priority score: watchlist > signals > claims > reports
            priority = (1 if in_wl else 0) * 1000 + signals_n * 10 + claims_n * 3 + reports_n
            candidates.append((priority, c))

        # Sort by priority descending, take top 15
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in candidates[:15]]

    def all_core_companies_unfiltered(self) -> list[CompanyInfo]:
        """Return all companies that pass the legacy filter (for debugging)."""
        result = []
        for c in self.companies:
            if c.name.lower() in _NOT_A_COMPANY:
                continue
            if c.name in HIGH_VALUE_COMPANIES or len(c.source_reports) >= 2:
                result.append(c)
        return result

    # ── Patch helpers ──

    def pending_patches(self) -> list[LWPatchInfo]:
        return [p for p in self.llm_patches if p.status == "pending_review"]

    # ── Claim / Signal helpers ──

    def active_claims(self) -> list[ClaimInfo]:
        return [c for c in self.claims if c.status == "active"]

    def challenged_claims(self) -> list[ClaimInfo]:
        return [c for c in self.claims if c.status == "challenged"]

    def review_claims(self) -> list[ClaimInfo]:
        """Claims needing review: active or challenged."""
        return [c for c in self.claims if c.status in ("active", "challenged")]

    def open_signals(self) -> list[SignalInfo]:
        return [s for s in self.signals if s.status == "open"]

    def watching_signals(self) -> list[SignalInfo]:
        return [s for s in self.signals if s.status == "watching"]

    def review_signals(self) -> list[SignalInfo]:
        """Signals needing review: open or watching."""
        return [s for s in self.signals if s.status in ("open", "watching")]

    def tracking_signals(self) -> list[SignalInfo]:
        """Signals with active tracking status."""
        return [s for s in self.signals if s.tracking_status in ("active", "tracking")]

    # ── Cross-referencing helpers ──

    def claims_count_for(self, wiki_name: str) -> int:
        """Count claims that reference a topic/company by wiki-link name.

        P2-N.4.3: Also matches by scanning claim text for the topic/company name.
        """
        count = 0
        name_lower = wiki_name.lower()
        for c in self.claims:
            # Direct frontmatter match
            if wiki_name in c.related_topics or wiki_name in c.related_companies:
                count += 1
                continue
            # Check source_reports for matching wiki-link
            for sr in c.source_reports:
                if wiki_name in sr:
                    count += 1
                    break
            else:
                # Fallback: scan claim text for name
                if name_lower in c.claim.lower():
                    count += 1
        return count

    def signals_count_for(self, wiki_name: str) -> int:
        """Count signals referencing a topic/company. 3-pass aggregation.

        P2-N.4.3.2: Three-pass system to catch signals even without backfill:
          1. Direct: signal.related_topics frontmatter match
          2. Alias: topic/company aliases match in signal text + related fields
          3. Company-inferred: signal mentions a company that co-occurs with
             this topic in claims (for topics only)

        Only counts non-archived signals (archived already excluded at scan time).
        """
        # Pass 1: direct frontmatter match
        count = 0
        matched_signal_ids: set[str] = set()
        for s in self.signals:
            if wiki_name in s.related_topics or wiki_name in s.related_companies:
                count += 1
                matched_signal_ids.add(s.card_id)

        # Pass 2: alias match
        topic_aliases = self._get_topic_aliases(wiki_name)
        if topic_aliases:
            name_lower = wiki_name.lower()
            for s in self.signals:
                if s.card_id in matched_signal_ids:
                    continue
                text = (s.signal + " " + " ".join(s.related_topics) +
                        " " + " ".join(s.related_companies)).lower()
                if name_lower in text:
                    count += 1
                    matched_signal_ids.add(s.card_id)
                    continue
                for alias in topic_aliases:
                    if alias.lower() in text:
                        count += 1
                        matched_signal_ids.add(s.card_id)
                        break

        # Pass 3: company-inferred (for topics only)
        # Signal → related companies → claims where company+topic co-occur
        if self._is_topic_name(wiki_name):
            company_topic_map = self._get_company_topic_map()
            topic_companies = company_topic_map.get(wiki_name, set())
            if topic_companies:
                for s in self.signals:
                    if s.card_id in matched_signal_ids:
                        continue
                    signal_companies = set(s.related_companies)
                    if signal_companies & topic_companies:
                        count += 1
                        matched_signal_ids.add(s.card_id)

        return count

    # ── Internal caching for aggregation ──

    def _get_topic_aliases(self, wiki_name: str) -> list[str]:
        """Get aliases for a topic by name."""
        for t in self.topics:
            if t.name == wiki_name:
                return t.aliases
        return []

    def _is_topic_name(self, wiki_name: str) -> bool:
        """Check if wiki_name is a topic (not a company)."""
        return any(t.name == wiki_name for t in self.topics)

    def _get_company_topic_map(self) -> dict[str, set[str]]:
        """Build map: topic_name → set of companies that co-occur in claims.

        Cached as WorkspaceSnapshot._company_topic_cache for performance.
        """
        if not hasattr(self, '_company_topic_cache'):
            self._company_topic_cache: dict[str, set[str]] = {}
        cache: dict[str, set[str]] = self._company_topic_cache  # type: ignore
        if cache:
            return cache
        for claim in self.claims:
            for topic in claim.related_topics:
                if topic not in cache:
                    cache[topic] = set()
                for company in claim.related_companies:
                    cache[topic].add(company)
        self._company_topic_cache = cache
        return cache

    def reports_count_for(self, wiki_name: str) -> int:
        """Count reports related to a topic/company based on card source_reports."""
        # We look at the topic/company card's source_reports count
        for t in self.topics:
            if t.name == wiki_name:
                return len(t.source_reports)
        for c in self.companies:
            if c.name == wiki_name:
                return len(c.source_reports)
        return 0

    # ── Recent helpers ──

    def recent_reports(self, n: int = 10) -> list[ReportInfo]:
        """Return the N most recent reports, sorted by analyzed_at desc."""
        def _sort_key(r: ReportInfo) -> str:
            return r.analyzed_at or "0000-00-00"
        return sorted(self.reports, key=_sort_key, reverse=True)[:n]

    def recent_log_entries(self, n: int = 10) -> list[str]:
        """Extract recent timestamped entries from 99_System log files."""
        log_dir = self.vault_path / "99_System"
        if not log_dir.exists():
            return []

        entries: list[tuple[str, str]] = []  # (datetime_str, text)
        for log_path in sorted(log_dir.glob("*Log*.md")):
            try:
                content = read_text_safe(log_path)
            except Exception:
                continue
            # Extract lines like "## 2026-05-30 20:07" or "## 2026-05-30T20:07:34"
            for line in content.split("\n"):
                stripped = line.strip()
                if stripped.startswith("## ") and len(stripped) > 4:
                    timestamp_candidate = stripped[3:].strip()
                    # Accept various date formats
                    if (
                        timestamp_candidate[:4].isdigit()
                        and len(timestamp_candidate) >= 10
                    ):
                        source_name = log_path.stem.replace("_", " ")
                        entries.append((
                            timestamp_candidate,
                            f"{timestamp_candidate} — {source_name}",
                        ))
        # Sort descending, take first n
        entries.sort(key=lambda x: x[0], reverse=True)
        return [text for _, text in entries[:n]]

    def curation_summary(self) -> dict[str, int]:
        """Count cards by curation_status across all card types."""
        summary: dict[str, int] = {}
        for collection in [self.topics, self.companies, self.claims, self.signals]:
            for item in collection:
                cs = getattr(item, "curation_status", "") or "unknown"
                summary[cs] = summary.get(cs, 0) + 1
        return summary


# ── VaultScanner ──────────────────────────────────────────────────


class VaultScanner:
    """Scan Obsidian vault filesystem and build a WorkspaceSnapshot."""

    def __init__(self, vault_path: Path) -> None:
        self.vault_path = vault_path

    def scan(self) -> WorkspaceSnapshot:
        """Scan all vault directories and return a complete snapshot."""
        snapshot = WorkspaceSnapshot(
            vault_path=self.vault_path,
            scanned_at=datetime.now(),
        )
        snapshot.reports = self._scan_reports()
        snapshot.topics = self._scan_topics()
        snapshot.companies = self._scan_companies()
        snapshot.claims = self._scan_claims()
        snapshot.signals = self._scan_signals()
        snapshot.channels = self._scan_channels()
        snapshot.llm_patches = self._scan_llm_patches()
        return snapshot

    # ── Directory scanners ──

    def _scan_reports(self) -> list[ReportInfo]:
        results = []
        reports_dir = self.vault_path / "01_Reports"
        if not reports_dir.exists():
            return results
        for p in sorted(reports_dir.glob("*.md")):
            try:
                content = read_text_safe(p)
            except Exception:
                logger.warning(f"Cannot read report: {p}")
                continue
            fm = _parse_frontmatter(content)
            title = ""
            for line in content.split("\n"):
                if line.startswith("# ") and not line.startswith("## "):
                    title = line[2:].strip()
                    break
            results.append(ReportInfo(
                filename=p.stem,
                path=p,
                channel=fm.get("channel", ""),
                video_id=fm.get("video_id", ""),
                title=title,
                analyzed_at=fm.get("analyzed_at", ""),
                focus_areas=fm.get("focus_areas", []),
                tags=fm.get("tags", []),
            ))
        return results

    def _scan_topics(self) -> list[TopicInfo]:
        results = []
        topics_dir = self.vault_path / "02_Topics"
        if not topics_dir.exists():
            return results
        for p in sorted(topics_dir.glob("*.md")):
            try:
                content = read_text_safe(p)
            except Exception:
                logger.warning(f"Cannot read topic: {p}")
                continue
            fm = _parse_frontmatter(content)
            source_reports = _extract_source_reports(content, fm)
            results.append(TopicInfo(
                name=p.stem,
                path=p,
                status=fm.get("status", ""),
                topic=fm.get("topic", p.stem),
                aliases=fm.get("aliases", []),
                tags=fm.get("tags", []),
                source_reports=source_reports,
                updated_at=fm.get("updated_at", ""),
                curation_status=fm.get("curation_status", ""),
                system_curation=fm.get("system_curation", ""),
                topic_quality=fm.get("topic_quality", ""),
            ))
        return results

    def _scan_companies(self) -> list[CompanyInfo]:
        results = []
        companies_dir = self.vault_path / "03_Companies"
        if not companies_dir.exists():
            return results
        for p in sorted(companies_dir.glob("*.md")):
            try:
                content = read_text_safe(p)
            except Exception:
                logger.warning(f"Cannot read company: {p}")
                continue
            fm = _parse_frontmatter(content)
            source_reports = _extract_source_reports(content, fm)
            results.append(CompanyInfo(
                name=p.stem,
                path=p,
                company=fm.get("company", p.stem),
                aliases=fm.get("aliases", []),
                ticker=fm.get("ticker", ""),
                sector=fm.get("sector", ""),
                tags=fm.get("tags", []),
                source_reports=source_reports,
                updated_at=fm.get("updated_at", ""),
                curation_status=fm.get("curation_status", ""),
                system_curation=fm.get("system_curation", ""),
                entity_type=fm.get("entity_type", ""),
            ))
        return results

    def _scan_claims(self) -> list[ClaimInfo]:
        results = []
        claims_dir = self.vault_path / "06_Claims"
        if not claims_dir.exists():
            return results
        for p in sorted(claims_dir.glob("*.md")):
            try:
                content = read_text_safe(p)
            except Exception:
                logger.warning(f"Cannot read claim: {p}")
                continue
            fm = _parse_frontmatter(content)
            source_reports = fm.get("source_reports", [])
            if not isinstance(source_reports, list):
                source_reports = []
            related_topics = fm.get("related_topics", [])
            if not isinstance(related_topics, list):
                related_topics = []
            related_companies = fm.get("related_companies", [])
            if not isinstance(related_companies, list):
                related_companies = []
            # P2-M.3: skip archived claims
            if fm.get("status", "") == "archived":
                continue
            results.append(ClaimInfo(
                card_id=p.stem,
                path=p,
                status=fm.get("status", ""),
                claim=fm.get("claim", "") if fm.get("claim") else p.stem,
                source_reports=source_reports,
                related_topics=related_topics,
                related_companies=related_companies,
                updated_at=fm.get("updated_at", ""),
                curation_status=fm.get("curation_status", ""),
                review_priority=fm.get("review_priority", ""),
                quality=fm.get("quality", ""),
                granularity=fm.get("granularity", ""),
            ))
        return results

    def _scan_signals(self) -> list[SignalInfo]:
        results = []
        signals_dir = self.vault_path / "07_Signals"
        if not signals_dir.exists():
            return results
        for p in sorted(signals_dir.glob("*.md")):
            try:
                content = read_text_safe(p)
            except Exception:
                logger.warning(f"Cannot read signal: {p}")
                continue
            fm = _parse_frontmatter(content)
            source_reports = fm.get("source_reports", [])
            if not isinstance(source_reports, list):
                source_reports = []
            related_topics = fm.get("related_topics", [])
            if not isinstance(related_topics, list):
                related_topics = []
            related_companies = fm.get("related_companies", [])
            if not isinstance(related_companies, list):
                related_companies = []
            # P2-M.3: skip archived signals
            if fm.get("status", "") == "archived":
                continue
            results.append(SignalInfo(
                card_id=p.stem,
                path=p,
                status=fm.get("status", ""),
                signal=fm.get("signal", "") if fm.get("signal") else p.stem,
                source_reports=source_reports,
                related_topics=related_topics,
                related_companies=related_companies,
                tracking_status=fm.get("tracking_status", ""),
                updated_at=fm.get("updated_at", ""),
                curation_status=fm.get("curation_status", ""),
                review_priority=fm.get("review_priority", ""),
                quality=fm.get("quality", ""),
                signal_type=fm.get("signal_type", ""),
            ))
        return results

    def _scan_channels(self) -> list[ChannelInfo]:
        results = []
        channels_dir = self.vault_path / "05_Channels"
        if not channels_dir.exists():
            return results
        for p in sorted(channels_dir.glob("*.md")):
            try:
                content = read_text_safe(p)
            except Exception:
                logger.warning(f"Cannot read channel: {p}")
                continue
            fm = _parse_frontmatter(content)
            results.append(ChannelInfo(
                name=p.stem,
                path=p,
                channel=fm.get("channel", p.stem),
                url=fm.get("url", ""),
                tags=fm.get("tags", []),
                priority=fm.get("priority", ""),
                updated_at=fm.get("updated_at", ""),
            ))
        return results

    def _scan_llm_patches(self) -> list[LWPatchInfo]:
        results = []
        patches_dir = self.vault_path / "00_Inbox" / "LLM_Patches"
        if not patches_dir.exists():
            return results
        for p in sorted(patches_dir.glob("*.md")):
            try:
                content = read_text_safe(p)
            except Exception:
                logger.warning(f"Cannot read patch: {p}")
                continue
            fm = _parse_frontmatter(content)
            source_reports = fm.get("source_reports", [])
            if not isinstance(source_reports, list):
                source_reports = []
            results.append(LWPatchInfo(
                patch_id=p.stem,
                path=p,
                target_type=fm.get("target_type", ""),
                target=fm.get("target", ""),
                status=fm.get("status", ""),
                source_reports=source_reports,
                generated_at=fm.get("generated_at", ""),
            ))
        return results
