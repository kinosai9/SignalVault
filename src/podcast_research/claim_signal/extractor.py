"""Claim and Signal candidate extraction from reports and patches.

Deterministic rule-based extraction. No LLM calls.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from podcast_research.utils.file_io import read_text_safe

# Keywords that indicate investment advice — skip these
_INVESTMENT_ADVICE_KEYWORDS = [
    "买入", "卖出", "推荐", "目标价", "配置", "增持", "减持",
    "buy", "sell", "target price", "overweight", "underweight",
    "long recommendation", "short recommendation",
]

# Sections to scan for claims
_CLAIM_SECTIONS = [
    "## Key Claims",
    "## Proposed Key Claims",
    "## Core Investment Views",
    "## Tech / Industry Insights",
    "## Tech/Industry Insights",
]

# Sections to scan for signals
_SIGNAL_SECTIONS = [
    "## Open Questions",
    "## Proposed Open Questions",
    "## Tracking Signals",
    "## Risks",
    "## Proposed Risks",
]

# Sections from reports that may contain evidence
_EVIDENCE_SECTIONS = [
    "## Source Quotes",
]


@dataclass
class ClaimCandidate:
    """A claim extracted from a report or patch."""
    statement: str
    source_type: str  # "report" or "patch"
    source_file: str
    source_section: str
    evidence: str = ""
    evidence_quote: str = ""
    evidence_timestamp: str = ""
    related_topics: list[str] = field(default_factory=list)
    related_companies: list[str] = field(default_factory=list)
    slug: str = ""

    def __post_init__(self):
        if not self.slug:
            self.slug = _make_slug(self.statement)


@dataclass
class SignalCandidate:
    """A signal extracted from a report or patch."""
    statement: str
    source_type: str  # "report" or "patch"
    source_file: str
    source_section: str
    related_topics: list[str] = field(default_factory=list)
    related_companies: list[str] = field(default_factory=list)
    tracking_reason: str = ""
    slug: str = ""

    def __post_init__(self):
        if not self.slug:
            self.slug = _make_slug(self.statement)


def _make_slug(text: str) -> str:
    """Generate a safe slug from a statement (first 80 chars)."""
    short = text.strip()[:80]
    # Replace non-alphanumeric chars with underscore
    slug = re.sub(r'[^\w]', '_', short)
    # Collapse multiple underscores
    slug = re.sub(r'_+', '_', slug).strip('_')
    # Truncate to reasonable length
    if len(slug) > 100:
        slug = slug[:100]
    return f"claim_{slug}" if slug else f"claim_{hashlib.md5(text.encode()).hexdigest()[:12]}"


def _make_signal_slug(text: str) -> str:
    """Generate a safe slug from a signal statement."""
    short = text.strip()[:80]
    slug = re.sub(r'[^\w]', '_', short)
    slug = re.sub(r'_+', '_', slug).strip('_')
    if len(slug) > 100:
        slug = slug[:100]
    return f"signal_{slug}" if slug else f"signal_{hashlib.md5(text.encode()).hexdigest()[:12]}"


def _extract_wiki_links(text: str) -> list[str]:
    """Extract [[Entity]] links from text."""
    return re.findall(r"\[\[([^\]]+)\]\]", text)


def _is_investment_advice(text: str) -> bool:
    """Check if text contains investment advice keywords."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in _INVESTMENT_ADVICE_KEYWORDS)


def _extract_bullet_items(content: str, section_header: str) -> list[dict]:
    """Extract bullet items from a markdown section.

    Returns list of dicts with 'text', 'evidence', 'quote', 'timestamp'.
    """
    # Find the section
    lines = content.split("\n")
    in_section = False
    items = []
    current_item = {"text": "", "evidence": "", "quote": "", "timestamp": ""}
    current_key = None

    for line in lines:
        stripped = line.strip()

        if stripped == section_header:
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if not in_section:
            continue

        # Bullet or sub-bullet
        if stripped.startswith("- ") or stripped.startswith("* "):
            bullet_text = stripped[2:].strip()
            if bullet_text and not bullet_text.startswith("Source:") and not bullet_text.startswith("Evidence:"):
                # Save previous item if it has content
                if current_item["text"]:
                    items.append(current_item)
                current_item = {"text": bullet_text, "evidence": "", "quote": "", "timestamp": ""}
                current_key = "text"
            elif "source:" in bullet_text.lower():
                current_item["evidence"] = bullet_text
                current_key = "evidence"
            elif "quote:" in bullet_text.lower() or bullet_text.startswith(">"):
                current_item["quote"] = bullet_text.lstrip(">").strip()
                current_key = "quote"
            elif "timestamp:" in bullet_text.lower():
                current_item["timestamp"] = bullet_text
                current_key = "timestamp"
        elif current_key and stripped:
            # Continuation of previous bullet
            if current_key == "text":
                current_item["text"] += " " + stripped
            elif current_key == "evidence":
                current_item["evidence"] += " " + stripped
            elif current_key == "quote":
                current_item["quote"] += " " + stripped

    if current_item["text"]:
        items.append(current_item)

    return items


def _extract_bullet_texts(content: str, section_header: str) -> list[str]:
    """Extract simple bullet texts from a section."""
    lines = content.split("\n")
    in_section = False
    items = []

    for line in lines:
        stripped = line.strip()
        if stripped == section_header:
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if not in_section:
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            text = stripped[2:].strip()
            if text and not text.lower().startswith("source:") and not text.lower().startswith("evidence:"):
                items.append(text)

    return items


def _extract_patch_marker_content(content: str, patch_id: str, section: str) -> str:
    """Extract the content of a specific section from within a patch marker block."""
    begin = f"<!-- LLM-WIKI:BEGIN {patch_id} -->"
    end = f"<!-- LLM-WIKI:END {patch_id} -->"

    # Find all marker blocks
    pattern = re.compile(
        re.escape(begin) + r'(.*?)' + re.escape(end),
        re.DOTALL,
    )

    for match in pattern.finditer(content):
        block = match.group(1)
        # Check if this block is within the target section
        # Extract the section content
        if section in content:
            section_start = content.find(section)
            if section_start < match.start():
                # This block is after the section header
                bullets = _extract_bullet_texts(block, "dummy")  # Block has bullets directly
                return "\n".join(bullets)

    return ""


def extract_claims(
    vault_path: Path,
    source: str = "all",
    limit: int = 50,
) -> list[ClaimCandidate]:
    """Extract claim candidates from reports and/or applied patches.

    Args:
        vault_path: Path to vault root
        source: "reports", "patches", or "all"
        limit: Max number of claims to return

    Returns:
        List of ClaimCandidate objects
    """
    claims: list[ClaimCandidate] = []
    seen_slugs: set[str] = set()

    # --- Source 1: Reports ---
    if source in ("reports", "all"):
        reports_dir = vault_path / "01_Reports"
        if reports_dir.exists():
            for report_path in sorted(reports_dir.glob("*.md")):
                content = read_text_safe(report_path)
                for section in _CLAIM_SECTIONS:
                    items = _extract_bullet_items(content, section)
                    for item in items:
                        text = item["text"].strip()
                        if len(text) < 20:
                            continue
                        if _is_investment_advice(text):
                            continue

                        candidate = ClaimCandidate(
                            statement=text,
                            source_type="report",
                            source_file=report_path.name,
                            source_section=section,
                            evidence=item["evidence"],
                            evidence_quote=item["quote"],
                            evidence_timestamp=item["timestamp"],
                        )
                        if candidate.slug not in seen_slugs:
                            seen_slugs.add(candidate.slug)
                            claims.append(candidate)
                        if len(claims) >= limit:
                            return claims

    # --- Source 2: Applied Patches ---
    if source in ("patches", "all"):
        patches_dir = vault_path / "00_Inbox" / "LLM_Patches"
        if patches_dir.exists():
            for patch_path in sorted(patches_dir.glob("*.md")):
                content = read_text_safe(patch_path)
                # Only process applied patches
                if "status: applied" not in content[:500]:
                    continue

                for section in _CLAIM_SECTIONS:
                    items = _extract_bullet_items(content, section)
                    for item in items:
                        text = item["text"].strip()
                        if len(text) < 20:
                            continue
                        if _is_investment_advice(text):
                            continue

                        candidate = ClaimCandidate(
                            statement=text,
                            source_type="patch",
                            source_file=patch_path.name,
                            source_section=section,
                            evidence=item["evidence"],
                            evidence_quote=item["quote"],
                            evidence_timestamp=item["timestamp"],
                        )
                        if candidate.slug not in seen_slugs:
                            seen_slugs.add(candidate.slug)
                            claims.append(candidate)
                        if len(claims) >= limit:
                            return claims

    return claims


def extract_signals(
    vault_path: Path,
    source: str = "all",
    limit: int = 50,
) -> list[SignalCandidate]:
    """Extract signal candidates from reports and/or applied patches.

    Args:
        vault_path: Path to vault root
        source: "reports", "patches", or "all"
        limit: Max number of signals to return

    Returns:
        List of SignalCandidate objects
    """
    signals: list[SignalCandidate] = []
    seen_slugs: set[str] = set()

    # --- Source 1: Reports ---
    if source in ("reports", "all"):
        reports_dir = vault_path / "01_Reports"
        if reports_dir.exists():
            for report_path in sorted(reports_dir.glob("*.md")):
                content = read_text_safe(report_path)
                # Also extract related entities from the report for context
                entities_text = ""
                for es in _EVIDENCE_SECTIONS:
                    entities_text += _extract_section(content, es)

                for section in _SIGNAL_SECTIONS:
                    items = _extract_bullet_texts(content, section)
                    for text in items:
                        text = text.strip()
                        if len(text) < 15:
                            continue
                        if _is_investment_advice(text):
                            continue
                        # Skip generic questions
                        if text.lower().startswith("what is") and "?" not in text:
                            continue

                        candidate = SignalCandidate(
                            statement=text,
                            source_type="report",
                            source_file=report_path.name,
                            source_section=section,
                            related_topics=_extract_wiki_links(entities_text),
                            related_companies=_extract_wiki_links(entities_text),
                            tracking_reason=section,
                            slug=_make_signal_slug(text),
                        )
                        if candidate.slug not in seen_slugs:
                            seen_slugs.add(candidate.slug)
                            signals.append(candidate)
                        if len(signals) >= limit:
                            return signals

    # --- Source 2: Applied Patches ---
    if source in ("patches", "all"):
        patches_dir = vault_path / "00_Inbox" / "LLM_Patches"
        if patches_dir.exists():
            for patch_path in sorted(patches_dir.glob("*.md")):
                content = read_text_safe(patch_path)
                if "status: applied" not in content[:500]:
                    continue

                for section in _SIGNAL_SECTIONS:
                    items = _extract_bullet_texts(content, section)
                    for text in items:
                        text = text.strip()
                        if len(text) < 15:
                            continue
                        if _is_investment_advice(text):
                            continue

                        candidate = SignalCandidate(
                            statement=text,
                            source_type="patch",
                            source_file=patch_path.name,
                            source_section=section,
                            slug=_make_signal_slug(text),
                            tracking_reason=section,
                        )
                        if candidate.slug not in seen_slugs:
                            seen_slugs.add(candidate.slug)
                            signals.append(candidate)
                        if len(signals) >= limit:
                            return signals

    return signals


def _extract_section(content: str, section_header: str) -> str:
    """Extract a markdown section by header."""
    lines = content.split("\n")
    in_section = False
    section_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped == section_header:
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if in_section:
            section_lines.append(line)
    return "\n".join(section_lines).strip()
