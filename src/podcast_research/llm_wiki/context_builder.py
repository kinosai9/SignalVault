"""Build context for LLM-WIKI patch generation.

Scans Topic cards, reads source reports, and extracts relevant sections
to build context for LLM patch generation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SourceReport:
    """A single source report referenced by a topic card."""
    filename: str
    path: Path | None
    channel: str = ""
    video_id: str = ""
    title: str = ""
    # Extracted sections
    summary: str = ""
    core_investment_views: str = ""
    tech_insights: str = ""
    risks: str = ""
    tracking_signals: str = ""
    entities: str = ""
    source_quotes: str = ""


@dataclass
class TopicContext:
    """Context for generating a topic patch."""
    topic_name: str
    topic_card_path: Path
    current_card_content: str
    source_reports: list[SourceReport] = field(default_factory=list)
    status: str = "core"  # core / emerging / long_tail
    related_companies: list[str] = field(default_factory=list)
    related_topics: list[str] = field(default_factory=list)


def find_core_topics(vault_path: Path) -> list[Path]:
    """Find all topic cards with status: core in 02_Topics/.

    Returns:
        List of Path objects for core topic card files.
    """
    topics_dir = vault_path / "02_Topics"
    if not topics_dir.exists():
        return []

    core_topics = []
    for card_path in sorted(topics_dir.glob("*.md")):
        content = card_path.read_text(encoding="utf-8")
        # Check if frontmatter contains status: core
        if _has_status_core(content):
            core_topics.append(card_path)

    return core_topics


def _has_status_core(content: str) -> bool:
    """Check if card frontmatter has status: core."""
    if not content.startswith("---"):
        return False
    end_idx = content.find("---", 3)
    if end_idx == -1:
        return False
    frontmatter = content[3:end_idx]
    # Match "status: core" (case-insensitive)
    return bool(re.search(r"^status:\s*core\s*$", frontmatter, re.MULTILINE | re.IGNORECASE))


def build_topic_context(
    vault_path: Path,
    topic_card_path: Path,
    max_reports: int = 5,
) -> TopicContext:
    """Build context for a topic by reading its card and source reports.

    Args:
        vault_path: Path to vault root
        topic_card_path: Path to the topic card file
        max_reports: Maximum number of source reports to include

    Returns:
        TopicContext with card content and extracted report sections
    """
    topic_name = topic_card_path.stem
    content = topic_card_path.read_text(encoding="utf-8")

    # Extract source reports from card
    source_report_refs = _extract_source_reports(content)

    # Limit to max_reports
    source_report_refs = source_report_refs[:max_reports]

    # Read each source report
    reports_dir = vault_path / "01_Reports"
    source_reports = []
    for ref in source_report_refs:
        report_path = reports_dir / f"{ref}.md"
        if report_path.exists():
            report = _read_source_report(report_path)
            source_reports.append(report)

    # Extract status from frontmatter
    status = _extract_status(content)

    # Extract related companies and topics from card
    related_companies = _extract_related_entities(content, "## Related Companies")
    related_topics = _extract_related_entities(content, "## Related Topics")

    return TopicContext(
        topic_name=topic_name,
        topic_card_path=topic_card_path,
        current_card_content=content,
        source_reports=source_reports,
        status=status,
        related_companies=related_companies,
        related_topics=related_topics,
    )


def _extract_source_reports(content: str) -> list[str]:
    """Extract source report filenames from ## Source Reports section."""
    lines = content.split("\n")
    in_section = False
    reports = []

    for line in lines:
        if line.strip() == "## Source Reports":
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.strip().startswith("- [["):
            # Extract filename from [[filename]]
            match = re.search(r"\[\[([^\]]+)\]\]", line)
            if match:
                reports.append(match.group(1))

    return reports


def _read_source_report(report_path: Path) -> SourceReport:
    """Read a source report and extract relevant sections."""
    content = report_path.read_text(encoding="utf-8")
    filename = report_path.stem

    # Parse frontmatter
    fm = _parse_frontmatter(content)
    channel = fm.get("channel", "")
    video_id = fm.get("video_id", "")
    title = fm.get("title", filename)

    # Extract sections
    summary = _extract_section(content, "## Summary")
    core_views = _extract_section(content, "## Core Investment Views")
    tech_insights = _extract_section(content, "## Tech / Industry Insights")
    risks = _extract_section(content, "## Risks")
    signals = _extract_section(content, "## Tracking Signals")
    entities = _extract_section(content, "## Entities")
    quotes = _extract_section(content, "## Source Quotes")

    return SourceReport(
        filename=filename,
        path=report_path,
        channel=channel,
        video_id=video_id,
        title=title,
        summary=summary,
        core_investment_views=core_views,
        tech_insights=tech_insights,
        risks=risks,
        tracking_signals=signals,
        entities=entities,
        source_quotes=quotes,
    )


def _parse_frontmatter(content: str) -> dict[str, str]:
    """Parse YAML frontmatter into a dict."""
    if not content.startswith("---"):
        return {}
    end_idx = content.find("---", 3)
    if end_idx == -1:
        return {}

    fm_text = content[3:end_idx].strip()
    result = {}
    for line in fm_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip()

    return result


def _extract_section(content: str, section_header: str) -> str:
    """Extract a markdown section by header."""
    lines = content.split("\n")
    in_section = False
    section_lines = []

    for line in lines:
        if line.strip() == section_header:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            section_lines.append(line)

    return "\n".join(section_lines).strip()


def _extract_status(content: str) -> str:
    """Extract status from frontmatter."""
    fm = _parse_frontmatter(content)
    return fm.get("status", "core")


def _extract_related_entities(content: str, section_header: str) -> list[str]:
    """Extract wiki links from a section."""
    section = _extract_section(content, section_header)
    # Find all [[Entity]] patterns
    return re.findall(r"\[\[([^\]]+)\]\]", section)


# ---------------------------------------------------------------------------
# Company Card context building
# ---------------------------------------------------------------------------


@dataclass
class CompanyContext:
    """Context for generating a company patch."""
    company_name: str
    company_card_path: Path
    current_card_content: str
    source_reports: list[SourceReport] = field(default_factory=list)
    related_companies: list[str] = field(default_factory=list)
    related_topics: list[str] = field(default_factory=list)


# High-value companies: prioritised for patch generation
HIGH_VALUE_COMPANIES = {
    "NVIDIA", "OpenAI", "Anthropic", "Microsoft", "Alphabet",
    "Meta", "TSMC", "CoreWeave", "Perplexity", "Mistral",
    "Vercel", "BlackRock", "Vanguard", "Shopify", "Salesforce", "Zendesk",
}


def find_companies(
    vault_path: Path,
    company_name: str | None = None,
    max_companies: int | None = None,
) -> list[Path]:
    """Find company cards in 03_Companies/.

    Args:
        vault_path: Path to vault root
        company_name: Specific company to find (exact match on filename stem)
        max_companies: Maximum number of companies to return (None = all)

    Returns:
        List of Path objects for company card files
    """
    companies_dir = vault_path / "03_Companies"
    if not companies_dir.exists():
        return []

    if company_name:
        card_path = companies_dir / f"{company_name}.md"
        if card_path.exists():
            return [card_path]
        return []

    # Collect all, prioritise high-value companies with source reports
    all_cards = sorted(companies_dir.glob("*.md"))
    if not max_companies:
        return all_cards

    # Prioritise: high-value + has source reports first
    priority = []
    rest = []
    for card_path in all_cards:
        content = card_path.read_text(encoding="utf-8")
        fm = _parse_frontmatter(content)
        card_type = fm.get("type", "")
        if card_type != "company":
            continue
        name = fm.get("company", card_path.stem)
        has_reports = bool(_extract_source_reports(content))
        if name in HIGH_VALUE_COMPANIES and has_reports:
            priority.append(card_path)
        else:
            rest.append(card_path)

    result = priority[:max_companies]
    remaining = max_companies - len(result)
    if remaining > 0:
        result += rest[:remaining]
    return result


def build_company_context(
    vault_path: Path,
    company_card_path: Path,
    max_reports: int = 5,
) -> CompanyContext:
    """Build context for a company by reading its card and source reports.

    Args:
        vault_path: Path to vault root
        company_card_path: Path to the company card file
        max_reports: Maximum number of source reports to include

    Returns:
        CompanyContext with card content and extracted report sections
    """
    company_name = company_card_path.stem
    content = company_card_path.read_text(encoding="utf-8")

    # Extract source reports from card
    source_report_refs = _extract_source_reports(content)
    source_report_refs = source_report_refs[:max_reports]

    # Read each source report
    reports_dir = vault_path / "01_Reports"
    source_reports = []
    for ref in source_report_refs:
        report_path = reports_dir / f"{ref}.md"
        if report_path.exists():
            report = _read_source_report(report_path)
            source_reports.append(report)

    # Extract related companies and topics from card
    related_companies = _extract_related_entities(content, "## Related Companies")
    related_topics = _extract_related_entities(content, "## Related Topics")

    return CompanyContext(
        company_name=company_name,
        company_card_path=company_card_path,
        current_card_content=content,
        source_reports=source_reports,
        related_companies=related_companies,
        related_topics=related_topics,
    )
