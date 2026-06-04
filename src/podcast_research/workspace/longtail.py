"""Long-tail topic cleanup: alias map, rename, merge, and quality tagging.

Scans 02_Topics/ for long-tail topics, applies an extended alias map
to normalize names, merges duplicates, and tags topic_quality.
Never deletes files — old files go to 99_System/LongTail_Cleanup_Backup/.
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from podcast_research.claim_signal.review import (
    _parse_frontmatter,
    _ensure_frontmatter_field,
)
from podcast_research.utils.file_io import read_text_safe

logger = logging.getLogger(__name__)

# Extended alias map for long-tail cleanup
LONGTAIL_ALIAS_MAP: dict[str, str] = {
    # Abbreviations → full names
    "cicd": "CI/CD",
    "ci cd": "CI/CD",
    "ci/cd": "CI/CD",
    "egc": "Employee Generated Content",
    "employee generated content": "Employee Generated Content",
    "plg": "Product-Led Growth",
    "product led growth": "Product-Led Growth",
    "gtm": "Go-to-Market",
    "go to market": "Go-to-Market",
    "go-to-market": "Go-to-Market",
    "gtm strategy": "Go-to-Market",
    "mcp": "Model Context Protocol",
    "model context protocol": "Model Context Protocol",
    "rl": "Reinforcement Learning",
    "reinforcement learning": "Reinforcement Learning",
    # Case normalization
    "chatgpt": "ChatGPT",
    "gpt": "GPT",
    "gpt 5": "GPT-5",
    "gpt-5": "GPT-5",
    "arxiv": "arXiv",
    # AI prefix fixes
    "ai coding": "AI Coding",
    "ai engineering": "AI Engineering",
    "interactive ai": "Interactive AI",
    "conversational ui": "Conversational UI",
    # SaaS / B2B
    "b2b saas": "B2B SaaS",
    "e commerce": "E-Commerce",
    "e-commerce": "E-Commerce",
    # Hardware / OS
    "mac os": "macOS",
    "macbook pro": "MacBook Pro",
    "cpu supply": "CPU Supply",
    "apple silicon": "Apple Silicon",
    "m5 max": "M5 Max",
    # Compound terms
    "outcome based": "Outcome-Based Pricing",
    "usage based": "Usage-Based Pricing",
    "usage-based": "Usage-Based Pricing",
    "chief customer officer": "Chief Customer Officer",
    # Tools
    "devtools": "Developer Tools",
    "cicd pipeline": "CI/CD",
    # Misc
    "spdr": "SPDR",
    "etf": "ETF",
    "index fund": "Index Funds",
}

# Thresholds for topic_quality
NOISY_NAME_MIN_LENGTH = 4
NOISY_MAX_SOURCE_REPORTS = 0


def cleanup_long_tail_topics(
    vault_path: Path,
    *,
    dry_run: bool = True,
    apply: bool = False,
) -> dict:
    """Clean up long-tail topic names and merge duplicates.

    Args:
        vault_path: Path to Obsidian vault root.
        dry_run: Preview changes without writing.
        apply: Actually write changes.

    Returns:
        dict with 'results' list and 'stats' summary.
    """
    if not dry_run and not apply:
        raise ValueError("Must specify --dry-run or --apply")

    results: list[dict] = []
    stats = {"topics_scanned": 0, "renamed": 0, "merged": 0,
             "quality_tagged": 0, "manual_review": 0}

    topics_dir = vault_path / "02_Topics"
    if not topics_dir.exists():
        return {"results": results, "stats": stats}

    backup_dir = vault_path / "99_System" / "LongTail_Cleanup_Backup"
    if apply:
        backup_dir.mkdir(parents=True, exist_ok=True)

    # Collect all topic files
    topic_files: dict[str, Path] = {}
    for p in sorted(topics_dir.glob("*.md")):
        topic_files[p.stem] = p

    # Build a lowercase→filename map for duplicate detection
    lc_map: dict[str, str] = {k.lower(): k for k in topic_files}

    processed: set[str] = set()

    for name, path in sorted(topic_files.items()):
        if name in processed:
            continue

        try:
            content = read_text_safe(path)
        except Exception:
            logger.warning(f"Cannot read topic: {path}")
            continue

        stats["topics_scanned"] += 1
        fm = _parse_frontmatter(content)
        status = fm.get("status", "")

        result = {
            "topic": name,
            "current_name": name,
            "suggested_name": name,
            "action": "skip",
            "quality": "",
            "reason": "",
        }

        # Check alias map
        canonical = _resolve_alias(name)
        if canonical and canonical != name:
            result["suggested_name"] = canonical
            if canonical in topic_files:
                # Merge into existing canonical card
                result["action"] = "merge_topic"
                result["reason"] = f"alias → existing '{canonical}'"
                result["quality"] = "alias"
            else:
                # Rename to canonical
                result["action"] = "rename_topic"
                result["reason"] = f"alias → new '{canonical}'"
                result["quality"] = "useful"
        else:
            # Check for case-insensitive duplicates (e.g., macOS vs Mac Os)
            lc = name.lower()
            if lc in lc_map and lc_map[lc] != name:
                # There's another file with same lowercase name
                other = lc_map[lc]
                if other not in processed:
                    # Pick the better-cased one as canonical
                    if _is_better_casing(name, other):
                        canonical = name
                        old = other
                    else:
                        canonical = other
                        old = name
                    result["suggested_name"] = canonical
                    result["action"] = "merge_topic"
                    result["reason"] = f"case duplicate → '{canonical}'"
                    result["quality"] = "alias"

            if result["action"] == "skip":
                # Determine topic_quality for untouched topics
                result["quality"] = _determine_quality(name, fm)

        if not result["quality"]:
            result["quality"] = _determine_quality(
                result["suggested_name"], fm
            )

        # Apply
        if apply:
            if result["action"] == "rename_topic":
                _rename_topic(path, result["suggested_name"], topics_dir)
                stats["renamed"] += 1
                if result["quality"]:
                    _tag_quality(topics_dir / f"{result['suggested_name']}.md", result["quality"])
            elif result["action"] == "merge_topic":
                canonical_path = topics_dir / f"{result['suggested_name']}.md"
                if canonical_path.exists() and path != canonical_path:
                    _merge_source_reports(path, canonical_path)
                    _move_to_backup(path, backup_dir)
                    stats["merged"] += 1
                    # Tag quality on canonical
                    _tag_quality(canonical_path, result["quality"])
            elif result["quality"]:
                _tag_quality(path, result["quality"])
                stats["quality_tagged"] += 1
        else:
            # dry-run: just update stats
            if result["action"] == "rename_topic":
                stats["renamed"] += 1
            elif result["action"] == "merge_topic":
                stats["merged"] += 1
            if result["quality"]:
                stats["quality_tagged"] += 1

        if result.get("quality") == "manual_review":
            stats["manual_review"] += 1

        processed.add(name)
        if result["action"] == "merge_topic":
            processed.add(result["suggested_name"])

        results.append(result)

    return {"results": results, "stats": stats}


# ── Alias resolution ──────────────────────────────────────────────


def _resolve_alias(name: str) -> str | None:
    """Check if a topic name has a canonical form via the alias map."""
    lower = name.lower().strip()
    if lower in LONGTAIL_ALIAS_MAP:
        return LONGTAIL_ALIAS_MAP[lower]
    # Try normalized (spaces collapsed)
    normalized = re.sub(r'\s+', ' ', lower)
    if normalized != lower and normalized in LONGTAIL_ALIAS_MAP:
        return LONGTAIL_ALIAS_MAP[normalized]
    return None


# ── Quality determination ─────────────────────────────────────────


def _determine_quality(name: str, fm: dict) -> str:
    """Determine topic_quality for a long-tail topic."""
    source_reports = fm.get("source_reports", [])
    if not isinstance(source_reports, list):
        source_reports = []

    has_reports = len(source_reports) > 0
    status = fm.get("status", "")

    # Core topics are always useful
    if status == "core":
        return "useful"

    # Very short names with no reports → noisy
    clean = name.strip()
    if len(clean) < NOISY_NAME_MIN_LENGTH and not has_reports:
        return "noisy"

    # All lowercase abbreviation-like names → noisy
    if clean.islower() and not has_reports and " " not in clean and len(clean) <= 6:
        return "noisy"

    # Has source reports → useful
    if has_reports:
        return "useful"

    return "long_tail"


def _is_better_casing(a: str, b: str) -> bool:
    """Return True if name 'a' has better casing than 'b'."""
    # Prefer names with uppercase (proper nouns)
    a_has_upper = any(c.isupper() for c in a)
    b_has_upper = any(c.isupper() for c in b)
    if a_has_upper and not b_has_upper:
        return True
    if b_has_upper and not a_has_upper:
        return False
    # Prefer shorter names
    return len(a) < len(b)


# ── File operations ───────────────────────────────────────────────


def _rename_topic(path: Path, new_name: str, topics_dir: Path) -> None:
    """Rename a topic card file and update its frontmatter."""
    content = read_text_safe(path)
    fm = _parse_frontmatter(content)
    old_name = fm.get("topic", path.stem)

    # Sanitize filename: replace / and other problematic chars
    safe_name = new_name.replace("/", "-").replace("\\", "-")

    # Update frontmatter topic field
    updated = _ensure_frontmatter_field(content, "topic", new_name)
    # Fix H1
    updated = re.sub(
        rf'^# {re.escape(old_name)}\s*$',
        f'# {new_name}',
        updated,
        flags=re.MULTILINE,
    )
    # Fix tag slug
    old_slug = old_name.lower().replace(" ", "-")
    new_slug = new_name.lower().replace(" ", "-")
    updated = updated.replace(f"topic/{old_slug}", f"topic/{new_slug}")

    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    updated = _ensure_frontmatter_field(updated, "updated_at", f'"{now_iso}"')

    # Write to new path (using safe filename)
    new_path = topics_dir / f"{safe_name}.md"
    new_path.write_text(updated, encoding="utf-8")

    # Remove old file if different
    if new_path != path:
        path.unlink()


def _merge_source_reports(from_path: Path, to_path: Path) -> None:
    """Merge source reports from from_path into to_path."""
    from_content = read_text_safe(from_path)
    to_content = read_text_safe(to_path)

    from_fm = _parse_frontmatter(from_content)
    to_fm = _parse_frontmatter(to_content)

    from_sr = from_fm.get("source_reports", [])
    if not isinstance(from_sr, list):
        from_sr = []
    to_sr = to_fm.get("source_reports", [])
    if not isinstance(to_sr, list):
        to_sr = []

    # Merge unique
    existing = set(to_sr)
    new_reports = [r for r in from_sr if r not in existing]

    if new_reports:
        all_sr = to_sr + new_reports
        # Update frontmatter source_reports
        updated = _replace_list_field(to_content, "source_reports", all_sr)
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        updated = _ensure_frontmatter_field(updated, "updated_at", f'"{now_iso}"')

        # Append to body ## Source Reports section
        if "## Source Reports" in updated:
            new_links = "\n".join(f"- [[{r}]]" for r in new_reports)
            updated = updated.replace(
                "## Source Reports\n",
                f"## Source Reports\n{new_links}\n",
            )

        to_path.write_text(updated, encoding="utf-8")


def _replace_list_field(content: str, field: str, values: list[str]) -> str:
    """Replace a list-valued frontmatter field."""
    lines = content.split("\n")
    result = []
    in_fm = False
    fm_closed = False
    field_found = False
    skip = False

    for line in lines:
        stripped = line.strip()
        if stripped == "---" and not fm_closed:
            if not in_fm:
                in_fm = True
                result.append(line)
                continue
            else:
                fm_closed = True
                if not field_found:
                    result.append(_format_list(field, values))
                result.append(line)
                continue
        if in_fm and not fm_closed:
            if field_found and skip:
                if ":" in stripped and not stripped.startswith("-"):
                    skip = False
                    result.append(line)
                continue
            if stripped.startswith(f"{field}:"):
                field_found = True
                result.append(_format_list(field, values))
                skip = True
            else:
                result.append(line)
        else:
            result.append(line)

    return "\n".join(result)


def _format_list(field: str, values: list[str]) -> str:
    if not values:
        return f"{field}: []"
    return f"{field}:\n" + "\n".join(f"  - {v}" for v in values)


def _move_to_backup(path: Path, backup_dir: Path) -> None:
    """Move a file to the backup directory (never delete)."""
    dest = backup_dir / path.name
    if dest.exists():
        # Append timestamp to avoid collision
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = backup_dir / f"{path.stem}_{ts}{path.suffix}"
    shutil.move(str(path), str(dest))


def _tag_quality(path: Path, quality: str) -> None:
    """Add topic_quality field to a topic card frontmatter."""
    if not path.exists():
        return
    content = read_text_safe(path)
    updated = _ensure_frontmatter_field(content, "topic_quality", quality)
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    updated = _ensure_frontmatter_field(updated, "updated_at", f'"{now_iso}"')
    path.write_text(updated, encoding="utf-8")
