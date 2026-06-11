"""Vault scanner: reads Obsidian vault filesystem and builds WorkspaceSnapshot.

Pure read-only. No LLM, no external APIs, no file writes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from podcast_research.claim_signal.review import _parse_frontmatter
from podcast_research.llm_wiki.context_builder import HIGH_VALUE_COMPANIES

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
}

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
from podcast_research.utils.file_io import read_text_safe

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
    curation_status: str = ""  # raw / indexed / reviewed / enhanced / archived
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
    curation_status: str = ""  # raw / indexed / reviewed / enhanced / archived


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
        """Companies that are high-value OR have >= 2 source reports.

        P2-N.1: Excludes names in _NOT_A_COMPANY (concepts misclassified as companies).
        """
        result = []
        for c in self.companies:
            if c.name.lower() in _NOT_A_COMPANY:
                continue  # Skip: this is a concept, not a company
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
        """Count claims that reference a topic/company by wiki-link name."""
        count = 0
        for c in self.claims:
            # Check related_topics / related_companies from frontmatter
            if wiki_name in c.related_topics or wiki_name in c.related_companies:
                count += 1
                continue
            # Also check source_reports for matching wiki-link
            for sr in c.source_reports:
                if wiki_name in sr:
                    count += 1
                    break
        return count

    def signals_count_for(self, wiki_name: str) -> int:
        """Count signals that reference a topic/company by wiki-link name."""
        count = 0
        for s in self.signals:
            if wiki_name in s.related_topics or wiki_name in s.related_companies:
                count += 1
                continue
            for sr in s.source_reports:
                if wiki_name in sr:
                    count += 1
                    break
        return count

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
