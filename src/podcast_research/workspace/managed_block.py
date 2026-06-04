"""Managed block utility for Obsidian vault files.

Inserts or updates marker-delimited content blocks in markdown files
without touching user-edited content outside the managed block.
"""

from __future__ import annotations

import re
from pathlib import Path

from podcast_research.utils.file_io import read_text_safe

MARKER_PREFIX = "<!-- PODCAST-RESEARCH:BEGIN"
MARKER_SUFFIX = "<!-- PODCAST-RESEARCH:END"


def _upsert_managed_block(file_path: Path, block_name: str, content: str) -> None:
    """Insert or update a managed block in a markdown file.

    The block is wrapped with:
        <!-- PODCAST-RESEARCH:BEGIN <block_name> -->
        <content>
        <!-- PODCAST-RESEARCH:END <block_name> -->

    - File does not exist: create with block content only.
    - File exists with existing block: replace block content.
    - File exists without block: append block at end.
    - Content outside the managed block is never modified.
    """
    begin = f"{MARKER_PREFIX} {block_name} -->"
    end = f"{MARKER_SUFFIX} {block_name} -->"

    if file_path.exists():
        existing = read_text_safe(file_path)
    else:
        existing = ""

    # Remove any existing block with this name (including surrounding newlines)
    pattern = re.compile(
        r"\n*" + re.escape(begin) + r".*?" + re.escape(end) + r"\n*",
        re.DOTALL,
    )
    cleaned = pattern.sub("\n", existing).rstrip() + "\n"

    # Append new block
    block = f"\n{begin}\n\n{content}\n\n{end}\n"
    new_content = cleaned.rstrip() + block

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(new_content, encoding="utf-8")


def _remove_managed_block(file_path: Path, block_name: str) -> bool:
    """Remove a managed block from a file. Returns True if a block was removed."""
    begin = f"{MARKER_PREFIX} {block_name} -->"
    end = f"{MARKER_SUFFIX} {block_name} -->"

    if not file_path.exists():
        return False

    existing = read_text_safe(file_path)
    pattern = re.compile(
        r"\n*" + re.escape(begin) + r".*?" + re.escape(end) + r"\n*",
        re.DOTALL,
    )
    new_content = pattern.sub("\n", existing).rstrip() + "\n"

    if new_content != existing.rstrip() + "\n":
        file_path.write_text(new_content, encoding="utf-8")
        return True
    return False


def _has_managed_block(file_path: Path, block_name: str) -> bool:
    """Check if a file contains a managed block with the given name."""
    if not file_path.exists():
        return False
    begin = f"{MARKER_PREFIX} {block_name} -->"
    return begin in read_text_safe(file_path)
