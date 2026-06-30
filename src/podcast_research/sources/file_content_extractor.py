"""P2-S.3.3: File content extraction — decode text from supported file types."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ExtractedFileContent:
    """Result of text extraction from an uploaded file.

    Built by extract_text_from_uploaded_file(). Contains the decoded text
    and metadata — no vault writes, no side effects.
    """
    text: str = ""
    title: str = ""
    encoding: str = ""
    content_hash: str = ""
    extension: str = ""
    blocks_count: int = 0
    excerpt: str = ""  # first ~500 chars for preview
    parse_quality: str = "minimal"
    quality_warnings: list[str] = field(default_factory=list)


# ── Public API ───────────────────────────────────────────────────────────────


def extract_text_from_uploaded_file(
    file_path: Path,
    original_filename: str,
    content_hash: str,
    detected_encoding: str,
) -> ExtractedFileContent:
    """Extract and decode text from a supported file type.

    Supported: .txt, .md, .html, .htm

    Args:
        file_path: Path to the saved temporary file.
        original_filename: Original upload filename (used for extension detection).
        content_hash: Pre-computed SHA256 hash of the raw bytes.
        detected_encoding: Encoding detected by the profiling step.

    Returns:
        ExtractedFileContent with decoded text, title, excerpt, etc.
    """
    ext = Path(original_filename).suffix.lower()

    # Read and decode
    try:
        raw_bytes = file_path.read_bytes()
    except Exception as e:
        logger.error("Failed to read uploaded file %s: %s", file_path, e)
        return ExtractedFileContent(
            content_hash=content_hash,
            extension=ext,
            parse_quality="minimal",
            quality_warnings=[f"无法读取文件: {e}"],
        )

    try:
        text = raw_bytes.decode(detected_encoding)
    except (UnicodeDecodeError, LookupError):
        # Fallback: try all encodings
        for enc in ["utf-8", "utf-8-sig", "gb18030"]:
            try:
                text = raw_bytes.decode(enc)
                detected_encoding = enc
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            return ExtractedFileContent(
                content_hash=content_hash,
                extension=ext,
                parse_quality="minimal",
                quality_warnings=["无法解码文件内容。"],
            )

    # Route to type-specific extractor
    if ext == ".txt":
        return _extract_txt(text, content_hash, ext, detected_encoding)
    elif ext == ".md":
        return _extract_md(text, content_hash, ext, detected_encoding, original_filename)
    elif ext in (".html", ".htm"):
        return _extract_html(text, content_hash, ext, detected_encoding, original_filename)
    else:
        return ExtractedFileContent(
            content_hash=content_hash,
            extension=ext,
            parse_quality="minimal",
            quality_warnings=[f"不支持的文件类型: {ext}"],
        )


# ── Type-specific extractors ─────────────────────────────────────────────────


def _extract_txt(
    text: str,
    content_hash: str,
    ext: str,
    encoding: str,
) -> ExtractedFileContent:
    """Extract from plain text (.txt)."""
    text_length = len(text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    blocks_count = len(lines)

    # Use first non-empty line as title
    title = lines[0][:120] if lines else ""

    # Quality assessment
    if text_length < 50:
        return ExtractedFileContent(
            text=text, title=title, encoding=encoding,
            content_hash=content_hash, extension=ext,
            blocks_count=blocks_count,
            excerpt=text[:500],
            parse_quality="minimal",
            quality_warnings=["文本内容过短。"],
        )
    if text_length < 200:
        return ExtractedFileContent(
            text=text, title=title, encoding=encoding,
            content_hash=content_hash, extension=ext,
            blocks_count=blocks_count,
            excerpt=text[:500],
            parse_quality="degraded",
            quality_warnings=["文本内容较短（不足 200 字）。"],
        )

    return ExtractedFileContent(
        text=text, title=title, encoding=encoding,
        content_hash=content_hash, extension=ext,
        blocks_count=blocks_count,
        excerpt=text[:500],
        parse_quality="good",
    )


def _extract_md(
    text: str,
    content_hash: str,
    ext: str,
    encoding: str,
    original_filename: str,
) -> ExtractedFileContent:
    """Extract from Markdown (.md).

    - Preserves full markdown body.
    - Extracts first `# Title` as the title.
    - Frontmatter is preserved in text but title is extracted from H1.
    """
    # Extract title from first H1 heading
    title = ""
    content_start = 0

    # Skip frontmatter if present
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            content_start = end + 3
        else:
            content_start = 0

    # Find first H1
    for line in text[content_start:].splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            title = stripped[2:].strip()[:200]
            break

    # If no H1, try to derive from filename
    if not title:
        stem = Path(original_filename).stem
        # Clean up common separators
        title = stem.replace("_", " ").replace("-", " ").strip()[:200]

    # Count blocks
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    blocks_count = len(lines)

    # Quality
    text_length = len(text)
    if text_length < 50:
        return ExtractedFileContent(
            text=text, title=title, encoding=encoding,
            content_hash=content_hash, extension=ext,
            blocks_count=blocks_count,
            excerpt=text[:500],
            parse_quality="minimal",
            quality_warnings=["Markdown 内容过短。"],
        )
    if text_length < 200:
        return ExtractedFileContent(
            text=text, title=title, encoding=encoding,
            content_hash=content_hash, extension=ext,
            blocks_count=blocks_count,
            excerpt=text[:500],
            parse_quality="degraded",
            quality_warnings=["Markdown 内容较短（不足 200 字）。"],
        )

    return ExtractedFileContent(
        text=text, title=title, encoding=encoding,
        content_hash=content_hash, extension=ext,
        blocks_count=blocks_count,
        excerpt=text[:500],
        parse_quality="good",
    )


def _extract_html(
    html_text: str,
    content_hash: str,
    ext: str,
    encoding: str,
    original_filename: str,
) -> ExtractedFileContent:
    """Extract text from HTML (.html/.htm).

    - Strips script, style, nav, footer, header elements.
    - Extracts <title>, <h1>-<h3>, <p> text.
    - Does NOT render HTML — only text extraction.
    - Does NOT execute any scripts.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        # Fallback: simple regex-based extraction
        return _extract_html_regex_fallback(
            html_text, content_hash, ext, encoding, original_filename,
        )

    try:
        soup = BeautifulSoup(html_text, "html.parser")
    except Exception:
        return _extract_html_regex_fallback(
            html_text, content_hash, ext, encoding, original_filename,
        )

    # Remove non-content elements
    for tag_name in ("script", "style", "nav", "footer", "header", "noscript"):
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Extract title
    title = ""
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        title = title_tag.get_text(strip=True)[:200]
    if not title:
        h1_tag = soup.find("h1")
        if h1_tag and h1_tag.get_text(strip=True):
            title = h1_tag.get_text(strip=True)[:200]
    if not title:
        stem = Path(original_filename).stem
        title = stem.replace("_", " ").replace("-", " ").strip()[:200]

    # Extract structured content
    headings: list[str] = []
    for h in soup.find_all(["h1", "h2", "h3"]):
        t = h.get_text(strip=True)
        if t:
            headings.append(t)

    paragraphs: list[str] = []
    for p in soup.find_all("p"):
        t = p.get_text(strip=True)
        if t and len(t) >= 10:
            paragraphs.append(t)

    # Build readable text
    sections: list[str] = []
    if title:
        sections.append(f"# {title}\n")
    if headings:
        sections.append("## 标题\n")
        for h in headings[:20]:
            sections.append(f"- {h}")
        sections.append("")
    if paragraphs:
        sections.append("## 正文\n")
        for i, p in enumerate(paragraphs[:50], 1):
            sections.append(f"{i}. {p}")
        sections.append("")

    extracted_text = "\n".join(sections)
    blocks_count = len(headings) + len(paragraphs)
    excerpt = extracted_text[:500]

    # Quality assessment
    if not extracted_text.strip() or blocks_count == 0:
        return ExtractedFileContent(
            text="", title=title, encoding=encoding,
            content_hash=content_hash, extension=ext,
            blocks_count=0,
            excerpt="",
            parse_quality="minimal",
            quality_warnings=["HTML 中未提取到有效文本内容。"],
        )

    if blocks_count < 3:
        return ExtractedFileContent(
            text=extracted_text, title=title, encoding=encoding,
            content_hash=content_hash, extension=ext,
            blocks_count=blocks_count,
            excerpt=excerpt,
            parse_quality="degraded",
            quality_warnings=["HTML 中可提取的文本块较少。"],
        )

    return ExtractedFileContent(
        text=extracted_text, title=title, encoding=encoding,
        content_hash=content_hash, extension=ext,
        blocks_count=blocks_count,
        excerpt=excerpt,
        parse_quality="good",
    )


def _extract_html_regex_fallback(
    html_text: str,
    content_hash: str,
    ext: str,
    encoding: str,
    original_filename: str,
) -> ExtractedFileContent:
    """Fallback HTML extraction using regex (no BeautifulSoup dependency)."""
    import re

    # Remove script, style, and other non-content tags
    cleaned = html_text
    for tag in ("script", "style", "nav", "footer", "header", "noscript"):
        cleaned = re.sub(
            rf"<\s*{tag}\b.*?</\s*{tag}\s*>",
            "", cleaned, flags=re.DOTALL | re.IGNORECASE,
        )
    # Also remove self-closing script/style
    cleaned = re.sub(r"<\s*(?:script|style)\b[^>]*/>", "", cleaned, flags=re.IGNORECASE)
    # Remove remaining HTML tags
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Extract title
    title_m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    title = title_m.group(1).strip()[:200] if title_m else ""
    if not title:
        stem = Path(original_filename).stem
        title = stem.replace("_", " ").replace("-", " ").strip()[:200]

    text_length = len(cleaned)
    excerpt = cleaned[:500]
    # Approximate block count by paragraph-like splits
    blocks = [b.strip() for b in re.split(r"\n\s*\n|\r\n\s*\r\n", cleaned) if b.strip()]
    blocks_count = len(blocks)

    if text_length < 50:
        return ExtractedFileContent(
            text=cleaned, title=title, encoding=encoding,
            content_hash=content_hash, extension=ext,
            blocks_count=blocks_count,
            excerpt=excerpt,
            parse_quality="minimal",
            quality_warnings=["HTML 中未提取到有效文本内容。"],
        )

    if text_length < 200:
        return ExtractedFileContent(
            text=cleaned, title=title, encoding=encoding,
            content_hash=content_hash, extension=ext,
            blocks_count=blocks_count,
            excerpt=excerpt,
            parse_quality="degraded",
            quality_warnings=["HTML 提取内容较短。"],
        )

    return ExtractedFileContent(
        text=cleaned, title=title, encoding=encoding,
        content_hash=content_hash, extension=ext,
        blocks_count=blocks_count,
        excerpt=excerpt,
        parse_quality="good",
    )
