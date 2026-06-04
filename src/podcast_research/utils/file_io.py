"""Safe file I/O with encoding fallback for Obsidian vault files.

Covers the common encoding situations in Chinese/English vaults:
- UTF-8 (modern default)
- UTF-8 with BOM (Windows Notepad)
- GB18030 / GBK (legacy Chinese Windows encoding)
- CP1252 (Western European legacy)
- UTF-8 with error replacement (last resort)

Usage:
    from podcast_research.utils.file_io import read_text_safe, write_text_utf8
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Ordered from most-likely to least-likely
_READ_ENCODINGS = ["utf-8", "utf-8-sig", "gb18030", "cp1252"]


def read_text_safe(path: Path) -> str:
    """Read a text file with encoding fallback.

    Tries encodings in order:
        1. utf-8           (modern default)
        2. utf-8-sig       (UTF-8 with BOM, e.g. Windows Notepad)
        3. gb18030         (superset of GBK, common for Chinese files)
        4. cp1252          (Western European legacy)
        5. utf-8 + replace (last resort — replaces invalid bytes)

    Logs a warning when any fallback encoding is used.
    """
    for i, enc in enumerate(_READ_ENCODINGS):
        try:
            if i == 0:
                return path.read_text(encoding=enc)
            else:
                logger.warning(
                    "Encoding fallback: %s read with %s (tried utf-8 first)",
                    path.name,
                    enc,
                )
                return path.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception:
            # Permission errors, file-not-found, etc. — let caller handle
            raise

    # Last resort
    logger.warning(
        "Encoding fallback: %s read with utf-8 errors=replace (all encodings failed)",
        path.name,
    )
    return path.read_text(encoding="utf-8", errors="replace")


def write_text_utf8(path: Path, content: str) -> None:
    """Write text as UTF-8. Parent directories are not auto-created."""
    path.write_text(content, encoding="utf-8")
