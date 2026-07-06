"""P2-C: Obsidian Markdown export utilities — filename sanitization, frontmatter, wiki links."""

from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path

# Windows illegal filename characters (replaced with hyphen)
_FILENAME_ILLEGAL = re.compile(r'[\\/:*?"<>|]')
# Control characters (removed entirely)
_FILENAME_CONTROL = re.compile(r'[\x00-\x1f\x7f-\x9f]')
# Emoji and other symbols that cause GBK encoding issues on Windows
_NON_FILENAME_SAFE = re.compile(
    r'[\U0001F300-\U0001F9FF'
    r'\U00002600-\U000027BF'
    r'\U0001F000-\U0001F02F'
    r'\U0001F0A0-\U0001F0FF'
    r'\U0001F100-\U0001F64F'
    r'\U0001F680-\U0001F6FF'
    r'\U0001F900-\U0001F9FF'
    r'☀-➿'
    r'⭐⭕'
    r'〰〽'
    r'️'  # Variation selector-16
    r']+'
)
# Windows reserved filenames (cannot be used as file names)
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}

_MAX_FILENAME_LENGTH = 150


def sanitize_filename(name: str, fallback: str = "untitled") -> str:
    """Sanitize a string for use as a Windows filename.

    Rules applied in order:
    1. Replace Windows illegal chars (< > : \" / \\ | ? *) with hyphens
    2. Remove control characters
    3. Remove emoji and non-filename-safe symbols
    4. Collapse multiple hyphens and spaces
    5. Strip leading/trailing whitespace and dots
    6. Limit to _MAX_FILENAME_LENGTH characters
    7. Fallback to video_id/report_id if result is empty
    8. Handle Windows reserved names (CON, PRN, etc.)

    Args:
        name: The raw name to sanitize.
        fallback: Used if the sanitized result is empty (e.g. video_id).

    Returns:
        A safe Windows filename string.
    """
    if not name or not name.strip():
        name = fallback

    sanitized = _FILENAME_CONTROL.sub("", name)
    sanitized = _FILENAME_ILLEGAL.sub("-", sanitized)
    sanitized = _NON_FILENAME_SAFE.sub("", sanitized)
    # Collapse multiple hyphens and spaces
    sanitized = re.sub(r"-{2,}", "-", sanitized)
    sanitized = re.sub(r"\s{2,}", " ", sanitized)
    # Strip leading/trailing whitespace, dots, hyphens
    sanitized = sanitized.strip(" .-")
    # Limit length
    if len(sanitized) > _MAX_FILENAME_LENGTH:
        sanitized = sanitized[:_MAX_FILENAME_LENGTH].rstrip(" .-")
    # Empty after sanitization → use fallback
    if not sanitized:
        sanitized = fallback
    # Windows reserved name → prefix with underscore
    if sanitized.lower() in _WINDOWS_RESERVED:
        sanitized = f"_{sanitized}"
    return sanitized


def unique_filename(directory: Path, base_name: str, suffix: str,
                    video_id: str = "", report_id: int = 0) -> str:
    """Generate a unique filename, appending video_id if collision detected.

    Args:
        directory: Target directory (used to check for existing files).
        base_name: Sanitized base name.
        suffix: File suffix including dot (e.g. '_extraction.json').
        video_id: Optional YouTube video_id for collision disambiguation.
        report_id: Optional report ID for collision disambiguation.
    """
    candidate = f"{base_name}{suffix}"
    path = directory / candidate
    if not path.exists():
        return candidate
    # Try with video_id
    if video_id:
        candidate = f"{base_name}_{video_id}{suffix}"
        path = directory / candidate
        if not path.exists():
            return candidate
    # Try with report_id
    if report_id:
        candidate = f"{base_name}_{report_id}{suffix}"
        return candidate
    # Last resort: timestamp
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base_name}_{ts}{suffix}"


def build_frontmatter(fields: OrderedDict | dict) -> str:
    """Build YAML frontmatter block from key-value dict.

    Args:
        fields: OrderedDict of key-value pairs. Lists are serialized as YAML list.
    """
    lines = ["---"]
    for key, val in fields.items():
        if val is None or val == "":
            lines.append(f"{key}:")
        elif isinstance(val, list):
            if val:
                lines.append(f"{key}:")
                for item in val:
                    lines.append(f"  - {item}")
            else:
                lines.append(f"{key}: []")
        elif isinstance(val, bool):
            lines.append(f"{key}: {str(val).lower()}")
        elif isinstance(val, str) and _needs_quoting(val):
            lines.append(f'{key}: "{val}"')
        else:
            lines.append(f"{key}: {val}")
    lines.append("---")
    return "\n".join(lines)


def _needs_quoting(val: str) -> bool:
    """Check if YAML value needs double-quoting."""
    return any(c in val for c in [":", "#", "{", "}", "[", "]", ",", "&", "*", "?", "|", "-", "<", ">", "=", "!", "%", "@", "`", '"', "'"])


def wiki_link(name: str) -> str:
    """Generate Obsidian wiki link. Empty name returns empty string."""
    if not name or not name.strip():
        return ""
    sanitized = sanitize_filename(name.strip())
    # Avoid empty after sanitization
    if not sanitized:
        return ""
    return f"[[{sanitized}]]"


def wiki_links_from_list(items: list[str]) -> str:
    """Generate space-separated wiki links from a list of names."""
    links = [wiki_link(item) for item in items if item]
    return " ".join(links)


# Entities that should generate wiki links
_WIKI_LINK_ENTITY_TYPES = frozenset({
    "company", "technology", "industry_theme", "product_or_model", "person", "organization"
})
