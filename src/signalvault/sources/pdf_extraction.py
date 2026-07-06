"""P4-A: PDF text extraction — pdfplumber-based, page-level, graceful degrade.

Provides:
  - PdfPage, PdfMetadata, PdfExtractionResult dataclasses
  - extract_pdf(): main entry point for text-based PDF extraction
  - Quality assessment with needs_ocr detection
  - Graceful degradation for encrypted/corrupt/empty PDFs

No OCR dependency required. When text extraction yields minimal content,
needs_ocr=True is set; the caller can decide to invoke OCR or write a
review item.

OCR skeleton: try_ocr_pdf() is provided as an optional path. If
pytesseract/pdf2image are not installed, it returns a result with
needs_ocr=True and an error message — never crashes.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Data classes ────────────────────────────────────────────────────────────


@dataclass
class PdfPage:
    """Single page extraction result."""
    page_number: int              # 1-indexed
    text: str = ""                # extracted text content
    char_count: int = 0           # character count (incl. spaces)
    extraction_method: str = "pdfplumber"  # "pdfplumber" | "ocr" | "none"
    quality: str = "good"         # "good" | "partial" | "empty" | "failed"


@dataclass
class PdfMetadata:
    """PDF document metadata extracted from file properties."""
    title: str = ""
    author: str = ""
    subject: str = ""
    creator: str = ""
    producer: str = ""
    creation_date: str = ""       # raw string from PDF metadata
    modification_date: str = ""
    page_count: int = 0
    file_size_bytes: int = 0
    is_encrypted: bool = False


@dataclass
class PdfExtractionResult:
    """Full PDF extraction result — all pages + metadata.

    This is the single return value from extract_pdf(). Callers check
    .quality and .needs_ocr to decide next steps.
    """
    source_path: str = ""         # absolute path to the PDF file
    file_name: str = ""           # original filename
    file_size: int = 0            # file size in bytes
    content_hash: str = ""        # SHA256 of raw bytes (first 16 chars)
    page_count: int = 0
    pages: list[PdfPage] = field(default_factory=list)
    full_text: str = ""           # concatenated text with [Page N] markers
    metadata: PdfMetadata = field(default_factory=PdfMetadata)
    quality: str = "good"         # "good" | "degraded" | "minimal" | "failed"
    needs_ocr: bool = False       # True when text extraction yields minimal content
    error_message: str = ""       # non-empty only when quality == "failed"


# ── Public API ──────────────────────────────────────────────────────────────


def extract_pdf(file_path: str | Path) -> PdfExtractionResult:
    """Extract text from a PDF file page by page using pdfplumber.

    This is the main entry point for P4-A text-based extraction.

    Args:
        file_path: Path to the PDF file.

    Returns:
        PdfExtractionResult with all pages, full_text, metadata, and quality
        assessment. Never raises — errors are captured in .error_message and
        .quality = "failed".
    """
    fp = Path(file_path)
    result_base = PdfExtractionResult(
        source_path=str(fp.resolve()),
        file_name=fp.name,
    )

    # ── Guard 1: File existence ──────────────────────────────────────────
    if not fp.exists():
        result_base.quality = "failed"
        result_base.error_message = f"File not found: {fp}"
        return result_base
    if not fp.is_file():
        result_base.quality = "failed"
        result_base.error_message = f"Not a file: {fp}"
        return result_base

    # ── Read raw bytes + hash ────────────────────────────────────────────
    try:
        raw_bytes = fp.read_bytes()
    except Exception as e:
        result_base.quality = "failed"
        result_base.error_message = f"Cannot read file: {e}"
        return result_base

    result_base.file_size = len(raw_bytes)
    result_base.content_hash = hashlib.sha256(raw_bytes).hexdigest()[:16]

    # ── Guard 2: Empty file ──────────────────────────────────────────────
    if len(raw_bytes) == 0:
        result_base.quality = "minimal"
        result_base.error_message = "File is empty (0 bytes)."
        return result_base

    # ── Open PDF ─────────────────────────────────────────────────────────
    try:
        import pdfplumber
    except ImportError:
        result_base.quality = "failed"
        result_base.error_message = "pdfplumber is not installed."
        return result_base

    try:
        pdf = pdfplumber.open(fp)
    except Exception as e:
        err = str(e)
        err_lower = err.lower()
        exc_name = type(e).__name__.lower()
        # Detect encryption: explicit password/encrypt keywords, or
        # pdfminer exceptions with empty message (encrypted PDF hallmark)
        if ("password" in err_lower or "encrypt" in err_lower
                or "pdfminer" in exc_name or err == ""):
            result_base.metadata = PdfMetadata(is_encrypted=True)
            result_base.quality = "failed"
            result_base.error_message = (
                "PDF is encrypted/password-protected."
                + (f" {err}" if err else "")
            )
        else:
            result_base.quality = "failed"
            result_base.error_message = f"Cannot open PDF: {err}"
        return result_base

    try:
        return _extract_pages(pdf, result_base)
    finally:
        with __import__("contextlib").suppress(Exception):
            pdf.close()


# ── Internal extraction ─────────────────────────────────────────────────────


def _extract_pages(pdf, result: PdfExtractionResult) -> PdfExtractionResult:
    """Iterate all pages, extract text, assess quality."""

    total = len(pdf.pages)
    result.page_count = total
    result.metadata = _extract_metadata(pdf, result.file_size)

    pages: list[PdfPage] = []
    total_chars = 0
    empty_count = 0
    failed_count = 0
    partial_count = 0

    for i, page in enumerate(pdf.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as e:
            logger.warning("Page %d extraction failed: %s", i, e)
            pages.append(PdfPage(
                page_number=i,
                text="",
                char_count=0,
                extraction_method="pdfplumber",
                quality="failed",
            ))
            failed_count += 1
            continue

        char_count = len(text)
        total_chars += char_count

        if char_count == 0:
            pages.append(PdfPage(
                page_number=i, text="", char_count=0,
                extraction_method="pdfplumber", quality="empty",
            ))
            empty_count += 1
        elif char_count < 50:
            pages.append(PdfPage(
                page_number=i, text=text, char_count=char_count,
                extraction_method="pdfplumber", quality="partial",
            ))
            partial_count += 1
        else:
            pages.append(PdfPage(
                page_number=i, text=text, char_count=char_count,
                extraction_method="pdfplumber", quality="good",
            ))

    result.pages = pages
    result.full_text = _build_full_text(pages)

    # ── Overall quality assessment ───────────────────────────────────────
    non_empty = total - empty_count - failed_count
    avg_chars = total_chars / max(total, 1)

    if total == 0:
        result.quality = "minimal"
        result.error_message = "PDF has 0 pages."
    elif failed_count == total:
        result.quality = "failed"
        result.error_message = "All pages failed extraction."
        result.needs_ocr = True
    elif total_chars < 200 or avg_chars < 30:
        result.quality = "minimal"
        result.needs_ocr = True
    elif avg_chars < 100:
        result.quality = "degraded"
        result.needs_ocr = non_empty > 0 and avg_chars < 50
    else:
        result.quality = "good"
        result.needs_ocr = False

    return result


def _build_full_text(pages: list[PdfPage]) -> str:
    """Concatenate page texts with [Page N] markers."""
    parts: list[str] = []
    for page in pages:
        if page.text.strip():
            parts.append(f"[Page {page.page_number}]\n{page.text.strip()}")
    return "\n\n".join(parts)


def _extract_metadata(pdf, file_size: int) -> PdfMetadata:
    """Extract PDF document metadata."""
    meta = PdfMetadata(file_size_bytes=file_size)
    try:
        info = pdf.metadata or {}
        meta.title = _safe_str(info.get("Title", ""))
        meta.author = _safe_str(info.get("Author", ""))
        meta.subject = _safe_str(info.get("Subject", ""))
        meta.creator = _safe_str(info.get("Creator", ""))
        meta.producer = _safe_str(info.get("Producer", ""))
        meta.creation_date = _safe_str(info.get("CreationDate", ""))
        meta.modification_date = _safe_str(info.get("ModDate", ""))
        meta.page_count = len(pdf.pages)
    except Exception as e:
        logger.warning("Metadata extraction failed: %s", e)
        meta.page_count = len(pdf.pages)
    return meta


def _safe_str(value) -> str:
    """Decode pdfplumber metadata value (may be bytes or raw string)."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return value.decode("latin-1")
            except UnicodeDecodeError:
                return ""
    return str(value)


# ── OCR skeleton ────────────────────────────────────────────────────────────


def try_ocr_pdf(file_path: str | Path) -> PdfExtractionResult:
    """Attempt OCR on a scanned PDF. Graceful degrade if deps unavailable.

    This is a skeleton for P4-B. In P4-A, it always returns a result with
    needs_ocr=True and a message indicating whether OCR deps are available.

    When pytesseract + pdf2image ARE installed, it performs OCR. Otherwise
    it returns a minimal result without crashing.
    """
    fp = Path(file_path)

    result_base = PdfExtractionResult(
        source_path=str(fp.resolve()),
        file_name=fp.name,
        quality="minimal",
        needs_ocr=True,
    )

    if not fp.exists():
        result_base.quality = "failed"
        result_base.error_message = f"File not found: {fp}"
        return result_base

    try:
        raw_bytes = fp.read_bytes()
    except Exception as e:
        result_base.quality = "failed"
        result_base.error_message = f"Cannot read file: {e}"
        return result_base

    result_base.file_size = len(raw_bytes)
    result_base.content_hash = hashlib.sha256(raw_bytes).hexdigest()[:16]

    # Check OCR dependencies
    try:
        import pytesseract  # noqa: F401
        from pdf2image import convert_from_path  # noqa: F401
    except ImportError as e:
        result_base.error_message = (
            f"OCR dependencies not available: {e}. "
            "Install pytesseract and pdf2image for OCR support."
        )
        return result_base

    # Verify tesseract binary
    import shutil
    if shutil.which("tesseract") is None:
        result_base.error_message = (
            "Tesseract OCR engine not found in PATH. "
            "Install tesseract and ensure it is on PATH."
        )
        return result_base

    # ── Perform OCR ──────────────────────────────────────────────────────
    try:
        images = convert_from_path(fp, dpi=300)
    except Exception as e:
        result_base.quality = "failed"
        result_base.error_message = f"PDF to image conversion failed: {e}"
        return result_base

    result_base.page_count = len(images)
    pages: list[PdfPage] = []
    total_chars = 0

    for i, image in enumerate(images, start=1):
        try:
            text = pytesseract.image_to_string(image, lang="chi_sim+eng")
            char_count = len(text)
            total_chars += char_count

            if char_count == 0:
                quality = "empty"
            elif char_count < 50:
                quality = "partial"
            else:
                quality = "good"

            pages.append(PdfPage(
                page_number=i, text=text.strip(), char_count=char_count,
                extraction_method="ocr", quality=quality,
            ))
        except Exception as e:
            logger.warning("OCR page %d failed: %s", i, e)
            pages.append(PdfPage(
                page_number=i, text="", char_count=0,
                extraction_method="ocr", quality="failed",
            ))

    result_base.pages = pages
    result_base.full_text = _build_full_text(pages)

    avg_chars = total_chars / max(len(pages), 1)
    if total_chars < 200 or avg_chars < 30:
        result_base.quality = "minimal"
    elif avg_chars < 100:
        result_base.quality = "degraded"
    else:
        result_base.quality = "good"

    result_base.needs_ocr = False  # OCR was performed
    return result_base


# ── Review item helpers ─────────────────────────────────────────────────────


def build_pdf_review_findings(result: PdfExtractionResult) -> list[dict]:
    """Build review item findings from a PdfExtractionResult.

    Returns a list of finding dicts suitable for
    ReviewItemManager.create_from_lint_findings().

    Called by CLI when --write-review is passed.
    """
    findings: list[dict] = []

    if result.quality == "failed":
        findings.append({
            "rule": "pdf_extraction_failed",
            "severity": "error",
            "file_path": result.file_name,
            "message": f"PDF extraction failed: {result.error_message}",
            "detail": f"file: {result.source_path}, size: {result.file_size}",
        })
        return findings

    if result.needs_ocr:
        findings.append({
            "rule": "pdf_needs_ocr",
            "severity": "warning",
            "file_path": result.file_name,
            "message": (
                f"PDF '{result.file_name}' may need OCR. "
                f"Extracted {sum(p.char_count for p in result.pages)} chars "
                f"from {result.page_count} pages."
            ),
            "detail": (
                f"quality={result.quality}, "
                f"avg_chars_per_page={_avg_chars(result):.0f}"
            ),
        })

    # Check for quality issues per page
    low_quality_pages = [
        p for p in result.pages
        if p.quality in ("partial", "empty", "failed")
    ]
    if low_quality_pages and not result.needs_ocr:
        page_nums = [str(p.page_number) for p in low_quality_pages[:10]]
        page_list = ", ".join(page_nums)
        if len(low_quality_pages) > 10:
            page_list += f" ... and {len(low_quality_pages) - 10} more"
        findings.append({
            "rule": "pdf_quality_issue",
            "severity": "warning" if result.quality == "degraded" else "info",
            "file_path": result.file_name,
            "message": (
                f"{len(low_quality_pages)}/{result.page_count} pages "
                f"have low text quality: pages {page_list}"
            ),
            "detail": f"overall quality={result.quality}",
        })

    return findings


def _avg_chars(result: PdfExtractionResult) -> float:
    if not result.pages:
        return 0.0
    return sum(p.char_count for p in result.pages) / len(result.pages)
