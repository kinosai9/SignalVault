"""P2-N.1: Display text cleanup utilities.

Removes markdown artifacts from user-facing display text.
No LLM, no external APIs, pure string operations.
"""

import re


def clean_display_text(text: str, max_len: int = 200) -> str:
    """Clean display text by removing markdown artifacts.

    Handles:
        - Markdown bold (**text** → text)
        - Markdown italic (*text* → text)
        - Backtick code (`text` → text)
        - Hashtag display (#tag → tag)
        - Repeated whitespace/newlines
        - Long text truncation at word boundary
        - Preserves technical terms (unchanged)

    Returns cleaned text, suitable for dashboard / brief / summary display.
    """
    if not text:
        return ""

    # 1. Strip markdown bold: **text** → text
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)

    # 2. Strip markdown italic: *text* → text (but not * in lists or technical)
    text = re.sub(r'(?<!\*)\*(?!\*)([^*\n]+?)\*(?!\*)', r'\1', text)

    # 3. Strip backtick code: `text` → text
    text = re.sub(r'`([^`]+)`', r'\1', text)

    # 4. Clean #tag display: remove leading # from standalone tags
    #    But keep # in URLs or version numbers
    text = re.sub(r'(?<!\w)#(\w+)', r'\1', text)

    # 5. Collapse repeated whitespace
    text = re.sub(r'[ \t]+', ' ', text)

    # 6. Collapse multiple newlines (max 2)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 7. Strip leading/trailing whitespace
    text = text.strip()

    # 8. Truncate at word boundary if needed
    if max_len and len(text) > max_len:
        # Find last space within limit
        cut = text[:max_len].rstrip()
        last_space = cut.rfind(' ')
        if last_space > max_len // 2:
            text = cut[:last_space] + "..."
        else:
            text = cut + "..."

    return text


def strip_markdown_inline(text: str) -> str:
    """Aggressive inline markdown stripping for table cells and short text."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'[*_]{1,2}([^*_\n]+?)[*_]{1,2}', r'\1', text)
    text = re.sub(r'(?<!\w)#(\w+)', r'\1', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()
