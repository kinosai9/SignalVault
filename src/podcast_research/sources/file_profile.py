"""P2-S.3.3: Uploaded file profiling — validate type, size, encoding; build UploadedFileProfile."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from podcast_research.sources.models import UploadedFileProfile

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_TEXT_EXTENSIONS: set[str] = {".md", ".txt", ".html", ".htm"}
# Optional future support: .csv, .json (text archive only, no structured analysis)
# OPTIONAL_EXTENSIONS: set[str] = {".csv", ".json"}

UNSUPPORTED_MESSAGE = (
    "当前仅支持 .md / .txt / .html / .htm 文本类型文件。"
    "其他格式将在后续版本支持。"
)

# ── Encoding detection order ────────────────────────────────────────────────

_ENCODING_CANDIDATES = ["utf-8", "utf-8-sig", "gb18030"]


# ── Public API ───────────────────────────────────────────────────────────────


def profile_uploaded_file(
    file_path: Path,
    original_filename: str,
    raw_bytes: bytes | None = None,
) -> UploadedFileProfile:
    """Validate an uploaded file and build an UploadedFileProfile.

    Performs:
      1. Extension check → supported / unsupported
      2. Size check → reject if over MAX_UPLOAD_BYTES
      3. Encoding detection → try UTF-8, UTF-8-SIG, GB18030
      4. Content hash computation
      5. Text extraction + block count
      6. Parse quality assessment

    Returns an UploadedFileProfile — no vault writes, no side effects.

    Args:
        file_path: Path to the saved temporary file on disk.
        original_filename: The original filename as provided by the uploader.
        raw_bytes: Optional pre-read bytes (avoids re-reading the file).
    """
    ext = _normalize_extension(original_filename)

    # ── Guard 1: Extension check ───────────────────────────────────────
    if ext not in ALLOWED_TEXT_EXTENSIONS:
        return UploadedFileProfile(
            filename=file_path.name,
            original_filename=original_filename,
            extension=ext,
            file_size_bytes=file_path.stat().st_size if file_path.exists() else 0,
            supported=False,
            unsupported_reason=UNSUPPORTED_MESSAGE,
            parse_quality="minimal",
        )

    # ── Guard 2: Size check ────────────────────────────────────────────
    try:
        file_size = file_path.stat().st_size
    except OSError:
        file_size = len(raw_bytes) if raw_bytes else 0

    if file_size > MAX_UPLOAD_BYTES:
        size_mb = file_size / (1024 * 1024)
        return UploadedFileProfile(
            filename=file_path.name,
            original_filename=original_filename,
            extension=ext,
            file_size_bytes=file_size,
            supported=False,
            unsupported_reason=(
                f"文件大小 ({size_mb:.1f} MB) 超过限制 "
                f"({MAX_UPLOAD_BYTES // (1024 * 1024)} MB)。请压缩或分割后重试。"
            ),
            parse_quality="minimal",
        )

    # ── Read bytes ──────────────────────────────────────────────────────
    if raw_bytes is None:
        try:
            raw_bytes = file_path.read_bytes()
        except Exception as e:
            return UploadedFileProfile(
                filename=file_path.name,
                original_filename=original_filename,
                extension=ext,
                file_size_bytes=file_size,
                supported=False,
                unsupported_reason=f"无法读取文件: {e}",
                parse_quality="minimal",
            )

    # ── Content hash ────────────────────────────────────────────────────
    content_hash = hashlib.sha256(raw_bytes).hexdigest()[:32]

    # ── Encoding detection + text extraction ────────────────────────────
    text = ""
    detected_encoding = None
    for enc in _ENCODING_CANDIDATES:
        try:
            text = raw_bytes.decode(enc)
            detected_encoding = enc
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if text is None or detected_encoding is None:
        return UploadedFileProfile(
            filename=file_path.name,
            original_filename=original_filename,
            extension=ext,
            file_size_bytes=file_size,
            supported=False,
            unsupported_reason="无法识别文件编码。已尝试 UTF-8、UTF-8-SIG、GB18030。",
            content_hash=content_hash,
            parse_quality="minimal",
        )

    # ── Text metrics ────────────────────────────────────────────────────
    text_length = len(text)
    blocks = _count_text_blocks(text, ext)

    # ── Parse quality ───────────────────────────────────────────────────
    parse_quality, quality_warnings = _assess_parse_quality(
        ext=ext,
        text=text,
        text_length=text_length,
        blocks=blocks,
    )

    return UploadedFileProfile(
        filename=file_path.name,
        original_filename=original_filename,
        extension=ext,
        file_size_bytes=file_size,
        supported=True,
        unsupported_reason=None,
        detected_encoding=detected_encoding,
        content_hash=content_hash,
        extracted_text_length=text_length,
        extracted_blocks_count=blocks,
        parse_quality=parse_quality,
        quality_warnings=quality_warnings,
    )


# ── Helpers ─────────────────────────────────────────────────────────────────


def _normalize_extension(filename: str) -> str:
    """Normalize file extension to lowercase with leading dot."""
    ext = Path(filename).suffix.lower()
    return ext


def _count_text_blocks(text: str, extension: str) -> int:
    """Count meaningful text blocks based on file type.

    - .txt: non-empty lines
    - .md: non-empty lines (paragraphs, headings, list items)
    - .html/.htm: approximated by paragraph/heading count from simple regex
    """
    if extension in (".html", ".htm"):
        import re
        # Count <p>, <h1>-<h6>, <li> as content blocks
        block_count = 0
        block_count += len(re.findall(r'<\s*p\b', text, re.IGNORECASE))
        block_count += len(re.findall(r'<\s*h[1-6]\b', text, re.IGNORECASE))
        block_count += len(re.findall(r'<\s*li\b', text, re.IGNORECASE))
        return block_count

    # .txt, .md: count non-empty non-whitespace lines
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return len(lines)


def _assess_parse_quality(
    ext: str,
    text: str,
    text_length: int,
    blocks: int,
) -> tuple[str, list[str]]:
    """Assess parse quality for a text file.

    Returns:
        (parse_quality, quality_warnings)
        parse_quality is one of: "good", "degraded", "minimal"
    """
    warnings: list[str] = []

    # Absolute minimum: text must exist and have some length
    if text_length < 50:
        return "minimal", ["文本内容过短，几乎无法提取有效信息。"]

    # HTML-specific checks
    if ext in (".html", ".htm"):
        if blocks < 2:
            warnings.append("HTML 文件中可提取的文本块极少（可能为纯脚本页面）。")
            return "minimal", warnings
        if blocks < 5:
            warnings.append("HTML 文件中可提取的文本块较少。")
            return "degraded", warnings
        if text_length < 500:
            warnings.append("HTML 提取内容较短。")
            return "degraded", warnings
        return "good", warnings

    # .txt / .md
    if text_length < 200:
        return "degraded", ["提取的文本内容较短（不足 200 字）。"]

    if blocks < 3:
        warnings.append("文本块数量较少，可能为碎片化内容。")
        return "degraded", warnings

    if text_length < 1000:
        warnings.append("提取的文本内容较短（不足 1000 字）。")
        return "degraded", warnings

    return "good", warnings
