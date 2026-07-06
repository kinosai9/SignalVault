"""Relation backfill: populate related_topics / related_companies on Claim and Signal cards.

Scans 06_Claims/*.md and 07_Signals/*.md, extracts topic/company references from
body text and frontmatter, normalises via taxonomy maps, and updates frontmatter.

Deterministic. No LLM. No external APIs. Read-only unless --apply.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from signalvault.claim_signal.review import (
    _ensure_frontmatter_field,
    _parse_frontmatter,
)
from signalvault.llm_wiki.taxonomy import (
    KNOWN_NON_COMPANY,
    TOPIC_CANONICAL_MAP,
)
from signalvault.utils.file_io import read_text_safe

logger = logging.getLogger(__name__)

# Limits
MAX_TOPICS_PER_CARD = 8
MAX_COMPANIES_PER_CARD = 8


def backfill_relations(
    vault_path: Path,
    *,
    dry_run: bool = True,
    apply: bool = False,
) -> dict:
    """Backfill related_topics and related_companies on Claim and Signal cards.

    Args:
        vault_path: Path to Obsidian vault root.
        dry_run: If True, scan and report but don't write.
        apply: If True, actually update frontmatter files.

    Returns:
        dict with 'results' list and 'stats' summary.
    """
    if not dry_run and not apply:
        raise ValueError("Must specify --dry-run or --apply")

    # Pre-load known cards
    known_topics = _load_known_names(vault_path / "02_Topics")
    known_companies = _load_known_names(vault_path / "03_Companies")

    # Build alias → canonical map (lowercase variant → canonical name)
    # Also add direct canonical names
    alias_to_canonical: dict[str, str] = {}
    for alias, canonical in TOPIC_CANONICAL_MAP.items():
        alias_to_canonical[alias.lower()] = canonical
    # Add canonical names themselves
    for name in known_topics:
        alias_to_canonical[name.lower()] = name

    results: list[dict] = []
    stats = {
        "claims_scanned": 0,
        "signals_scanned": 0,
        "claims_updated": 0,
        "signals_updated": 0,
        "topics_added": 0,
        "companies_added": 0,
    }

    # Process claims
    claims_dir = vault_path / "06_Claims"
    if claims_dir.exists():
        for p in sorted(claims_dir.glob("*.md")):
            try:
                content = read_text_safe(p)
            except Exception:
                logger.warning(f"Cannot read claim: {p}")
                continue
            stats["claims_scanned"] += 1
            result = _process_card(
                p, content, known_topics, known_companies,
                alias_to_canonical, dry_run, apply
            )
            results.append(result)
            if result.get("updated"):
                stats["claims_updated"] += 1
                stats["topics_added"] += len(result.get("new_topics", []))
                stats["companies_added"] += len(result.get("new_companies", []))

    # Process signals
    signals_dir = vault_path / "07_Signals"
    if signals_dir.exists():
        for p in sorted(signals_dir.glob("*.md")):
            try:
                content = read_text_safe(p)
            except Exception:
                logger.warning(f"Cannot read signal: {p}")
                continue
            stats["signals_scanned"] += 1
            result = _process_card(
                p, content, known_topics, known_companies,
                alias_to_canonical, dry_run, apply
            )
            results.append(result)
            if result.get("updated"):
                stats["signals_updated"] += 1
                stats["topics_added"] += len(result.get("new_topics", []))
                stats["companies_added"] += len(result.get("new_companies", []))

    # Write log
    if apply and (stats["claims_updated"] > 0 or stats["signals_updated"] > 0):
        _write_backfill_log(vault_path, stats, results)

    return {"results": results, "stats": stats}


# ── Internal helpers ──────────────────────────────────────────────


def _load_known_names(directory: Path) -> set[str]:
    """Load all card names from a vault directory (filename stems)."""
    names: set[str] = set()
    if not directory.exists():
        return names
    for p in directory.glob("*.md"):
        names.add(p.stem)
    return names


def _process_card(
    card_path: Path,
    content: str,
    known_topics: set[str],
    known_companies: set[str],
    alias_to_canonical: dict[str, str],
    dry_run: bool,
    apply: bool,
) -> dict:
    """Process a single claim or signal card."""
    fm = _parse_frontmatter(content)

    existing_topics = fm.get("related_topics", [])
    if not isinstance(existing_topics, list):
        existing_topics = []
    existing_companies = fm.get("related_companies", [])
    if not isinstance(existing_companies, list):
        existing_companies = []

    # Extract body text (below frontmatter)
    body = _extract_body(content)

    # Extract topic references
    new_topics = _extract_topic_refs(
        body, existing_topics, known_topics, alias_to_canonical
    )

    # Extract company references
    new_companies = _extract_company_refs(
        body, existing_companies, known_companies
    )

    result = {
        "card_id": card_path.stem,
        "card_type": "claim" if "06_Claims" in str(card_path) else "signal",
        "existing_topics": existing_topics,
        "existing_companies": existing_companies,
        "new_topics": new_topics,
        "new_companies": new_companies,
        "updated": False,
    }

    if new_topics or new_companies:
        result["updated"] = True
        if apply:
            _apply_backfill(card_path, content, new_topics, new_companies, existing_topics, existing_companies)

    return result


def _extract_body(content: str) -> str:
    """Extract body text below YAML frontmatter."""
    if not content.startswith("---"):
        return content
    end_idx = content.find("---", 3)
    if end_idx == -1:
        return content
    return content[end_idx + 3:]


def _extract_topic_refs(
    body: str,
    existing_topics: list[str],
    known_topics: set[str],
    alias_to_canonical: dict[str, str],
) -> list[str]:
    """Extract topic references from card body text.

    Strategies (in order):
    1. Parse [[wiki_links]] from ## Related Topics section
    2. Scan body text for topic names / aliases
    """
    found: set[str] = set(existing_topics)

    # Strategy 1: wiki links in ## Related Topics section
    rt_section = _extract_section(body, "Related Topics")
    if rt_section:
        for link in _extract_wiki_links(rt_section):
            if link in known_topics:
                found.add(link)
            else:
                # Try canonical mapping
                canonical = alias_to_canonical.get(link.lower(), "")
                if canonical and canonical in known_topics:
                    found.add(canonical)

    # Strategy 2: scan statement/signal text for topic names
    text_sections = _extract_section(body, "Statement") or ""
    if not text_sections:
        text_sections = _extract_section(body, "What to Watch") or ""
    if not text_sections:
        text_sections = body

    # Also include Why It Matters and Evidence
    wim = _extract_section(body, "Why It Matters") or ""
    evidence = _extract_section(body, "Evidence") or ""
    scan_text = f"{text_sections}\n{wim}\n{evidence}"

    # Direct match: check if any known topic name appears in the text
    for topic_name in sorted(known_topics, key=lambda x: -len(x)):  # longest first
        if len(found) >= MAX_TOPICS_PER_CARD:
            break
        if topic_name in found:
            continue
        if _name_in_text(topic_name, scan_text):
            found.add(topic_name)

    # Alias match: check TOPIC_CANONICAL_MAP aliases against text
    if len(found) < MAX_TOPICS_PER_CARD:
        for alias, canonical in sorted(alias_to_canonical.items(), key=lambda x: -len(x[0])):
            if len(found) >= MAX_TOPICS_PER_CARD:
                break
            if canonical in found:
                continue
            if len(alias) < 3:
                continue  # skip very short aliases to avoid false matches
            if _name_in_text(alias, scan_text) and canonical in known_topics:
                found.add(canonical)

    # Remove existing topics from the "new" list
    new = [t for t in found if t not in set(existing_topics)]
    return new[:MAX_TOPICS_PER_CARD]


def _extract_company_refs(
    body: str,
    existing_companies: list[str],
    known_companies: set[str],
) -> list[str]:
    """Extract company references from card body text."""
    found: set[str] = set(existing_companies)

    # Strategy 1: wiki links in ## Related Companies section
    rc_section = _extract_section(body, "Related Companies")
    if rc_section:
        for link in _extract_wiki_links(rc_section):
            if link in known_companies and link not in KNOWN_NON_COMPANY:
                found.add(link)

    # Strategy 2: direct company name match in body text
    text_sections = _extract_section(body, "Statement") or ""
    if not text_sections:
        text_sections = _extract_section(body, "What to Watch") or ""
    wim = _extract_section(body, "Why It Matters") or ""
    evidence = _extract_section(body, "Evidence") or ""
    scan_text = f"{text_sections}\n{wim}\n{evidence}"

    for company_name in sorted(known_companies, key=lambda x: -len(x)):
        if len(found) >= MAX_COMPANIES_PER_CARD:
            break
        if company_name in found:
            continue
        if company_name.lower() in KNOWN_NON_COMPANY:
            continue
        if _name_in_text(company_name, scan_text):
            found.add(company_name)

    new = [c for c in found if c not in set(existing_companies)]
    return new[:MAX_COMPANIES_PER_CARD]


def _name_in_text(name: str, text: str) -> bool:
    """Check if a name appears as a word/phrase in the text.

    Uses case-insensitive whole-word matching for short names,
    substring matching for longer names (3+ words or 10+ chars).
    """
    text_lower = text.lower()
    name_lower = name.lower()

    if len(name_lower) < 3:
        return False

    # For multi-word or long names, use substring match (less strict)
    if " " in name_lower or len(name_lower) >= 10:
        return name_lower in text_lower

    # For short single-word names, use word-boundary match
    pattern = re.compile(r'\b' + re.escape(name_lower) + r'\b', re.IGNORECASE)
    return bool(pattern.search(text))


def _extract_section(body: str, section_name: str) -> str | None:
    """Extract content of a named ## section from markdown body."""
    # Find the section header
    pattern = re.compile(
        rf'^##\s+{re.escape(section_name)}\s*$',
        re.MULTILINE | re.IGNORECASE,
    )
    match = pattern.search(body)
    if not match:
        return None

    start = match.end()
    # Find next ## section or end of text
    next_section = re.search(r'^##\s+', body[start:], re.MULTILINE)
    if next_section:
        end = start + next_section.start()
    else:
        end = len(body)

    return body[start:end].strip()


def _extract_wiki_links(text: str) -> list[str]:
    """Extract Obsidian wiki link targets from text.

    Returns display text or target for [[target]] and [[target|display]].
    """
    links: list[str] = []
    for match in re.finditer(r'\[\[([^\]]+)\]\]', text):
        target = match.group(1)
        # Handle [[target|display]]
        if "|" in target:
            target = target.split("|")[0].strip()
        # Handle [[path/target]]
        if "/" in target:
            target = target.rsplit("/", 1)[-1]
        # Remove .md extension if present
        if target.endswith(".md"):
            target = target[:-3]
        links.append(target.strip())
    return links


def _apply_backfill(
    card_path: Path,
    content: str,
    new_topics: list[str],
    new_companies: list[str],
    existing_topics: list[str],
    existing_companies: list[str],
) -> None:
    """Update frontmatter with new related_topics / related_companies."""
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    updated = content
    all_topics = existing_topics + new_topics
    all_companies = existing_companies + new_companies

    # Update related_topics as a YAML list
    updated = _replace_frontmatter_list(updated, "related_topics", all_topics)
    # Update related_companies
    updated = _replace_frontmatter_list(updated, "related_companies", all_companies)
    # Update timestamp
    updated = _ensure_frontmatter_field(updated, "updated_at", f'"{now_iso}"')

    card_path.write_text(updated, encoding="utf-8")


def _replace_frontmatter_list(content: str, field: str, values: list[str]) -> str:
    """Replace a list-valued frontmatter field entirely.

    Handles both empty list (field: []) and populated list formats.
    """
    lines = content.split("\n")
    result: list[str] = []
    in_fm = False
    fm_closed = False
    field_found = False
    skip_until_next_field = False

    for _i, line in enumerate(lines):
        stripped = line.strip()

        if stripped == "---" and not fm_closed:
            if not in_fm:
                in_fm = True
                result.append(line)
                continue
            else:
                # Closing ---
                fm_closed = True
                # If field wasn't found, insert before closing ---
                if not field_found:
                    result.append(_format_list_field(field, values))
                result.append(line)
                continue

        if in_fm and not fm_closed:
            if field_found and skip_until_next_field:
                # We're in the old list items; skip until next field or closing ---
                if ":" in stripped and not stripped.startswith("-") or stripped == "---":
                    skip_until_next_field = False
                    result.append(line)
                continue

            if stripped.startswith(f"{field}:"):
                field_found = True
                # Check if next line is a list item or if value is inline
                rest = stripped[len(f"{field}:"):].strip()
                if rest and rest != "[]":
                    # Single-line value (unlikely for list but handle)
                    result.append(_format_list_field(field, values))
                elif rest == "[]":
                    # Empty list marker - replace with new list
                    result.append(_format_list_field(field, values))
                else:
                    # Empty value - multi-line list follows
                    result.append(_format_list_field(field, values))
                    skip_until_next_field = True
            else:
                result.append(line)
        else:
            result.append(line)

    if not field_found:
        # Field doesn't exist - use _ensure_frontmatter_field
        return _ensure_frontmatter_field(content, field, "")

    return "\n".join(result)


def _format_list_field(field: str, values: list[str]) -> str:
    """Format a frontmatter list field."""
    if not values:
        return f"{field}: []"
    lines = [f"{field}:"]
    for v in values:
        lines.append(f"  - {v}")
    return "\n".join(lines)


# ── Logging ───────────────────────────────────────────────────────


def _write_backfill_log(
    vault_path: Path,
    stats: dict,
    results: list[dict],
) -> None:
    """Write Relation_Backfill_Log.md to 99_System/."""
    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    log_path = system_dir / "Relation_Backfill_Log.md"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# Relation Backfill Log",
        "",
        f"## {now}",
        "",
        f"- Claims scanned: {stats['claims_scanned']}",
        f"- Signals scanned: {stats['signals_scanned']}",
        f"- Claims updated: {stats['claims_updated']}",
        f"- Signals updated: {stats['signals_updated']}",
        f"- Topics added: {stats['topics_added']}",
        f"- Companies added: {stats['companies_added']}",
        "",
    ]

    # Detail for updated cards
    updated = [r for r in results if r.get("updated")]
    if updated:
        lines.append("### Updated Cards")
        lines.append("")
        for r in updated:
            new_t = r.get("new_topics", [])
            new_c = r.get("new_companies", [])
            parts = []
            if new_t:
                parts.append(f"topics: {', '.join(new_t)}")
            if new_c:
                parts.append(f"companies: {', '.join(new_c)}")
            lines.append(f"- **{r['card_id']}** ({r['card_type']}): {'; '.join(parts)}")
        lines.append("")

    # Append to existing log (or create new)
    if log_path.exists():
        existing = read_text_safe(log_path)
        # Insert after the first # heading line
        header_end = existing.find("\n\n", existing.find("# Relation Backfill Log"))
        if header_end > 0:
            new_entry = "\n".join(lines[2:])  # skip duplicate title
            updated_content = existing[:header_end + 2] + new_entry + "\n" + existing[header_end + 2:]
            log_path.write_text(updated_content, encoding="utf-8")
            return

    log_path.write_text("\n".join(lines), encoding="utf-8")
