"""P4-B: PDF analysis pipeline — feed extracted PDF text into the existing
LLM analysis pipeline with page-level evidence tracking.

Key design:
  - Converts PdfExtractionResult pages into SubtitleSegment-like objects
    where segment_id="page_N" and timestamps carry page numbers.
  - Passes through existing _run_pipeline() without modifying it.
  - Quality checks prevent analysis of minimal/failed PDFs.
  - Page numbers propagate through investment_views as evidence_page.
"""

from __future__ import annotations

import logging
from pathlib import Path

from signalvault.analysis.models import SubtitleSegment
from signalvault.config import REPORT_DIR, ensure_dirs
from signalvault.sources.pdf_extraction import (
    PdfExtractionResult,
    build_pdf_review_findings,
    extract_pdf,
)

logger = logging.getLogger(__name__)


# ── PDF Source Profile ──────────────────────────────────────────────────────


def build_pdf_source_profile(result: PdfExtractionResult) -> dict:
    """Build a standardized source profile dict from a PdfExtractionResult.

    This profile is consistent with the existing YouTube/source profile style
    and can be written to ingest_jobs payload_json or used as source_info.
    """
    total_chars = sum(p.char_count for p in result.pages)
    non_empty_pages = [p for p in result.pages if p.quality != "empty"]
    page_summaries = [
        {
            "page_number": p.page_number,
            "char_count": p.char_count,
            "extraction_method": p.extraction_method,
            "quality": p.quality,
        }
        for p in result.pages
    ]

    return {
        "source_type": "pdf_upload",
        "source_path": result.source_path,
        "file_name": result.file_name,
        "file_size": result.file_size,
        "content_hash": result.content_hash,
        "page_count": result.page_count,
        "quality": result.quality,
        "needs_ocr": result.needs_ocr,
        "extraction_method": "pdfplumber",
        "total_chars": total_chars,
        "non_empty_pages": len(non_empty_pages),
        "page_summaries": page_summaries,
        "metadata": {
            "title": result.metadata.title,
            "author": result.metadata.author,
            "subject": result.metadata.subject,
            "creator": result.metadata.creator,
            "producer": result.metadata.producer,
            "creation_date": result.metadata.creation_date,
        },
        "error_message": result.error_message,
    }


# ── Page-to-Segment Conversion ──────────────────────────────────────────────


def _pages_to_segments(result: PdfExtractionResult) -> list[SubtitleSegment]:
    """Convert PdfExtractionResult pages to SubtitleSegment objects.

    Each non-empty page becomes one segment:
      - segment_id = "page_N"
      - start_time = "p.{N}"  (carries page number through the pipeline)
      - end_time = "p.{N}"
      - text = page text content

    Empty pages are skipped.
    """
    segments: list[SubtitleSegment] = []
    for page in result.pages:
        if not page.text.strip():
            continue
        segments.append(SubtitleSegment(
            segment_id=f"page_{page.page_number}",
            start_time=f"p.{page.page_number}",
            end_time=f"p.{page.page_number}",
            text=page.text.strip(),
        ))
    return segments


# ── Quality Gating ──────────────────────────────────────────────────────────


def _check_analysis_eligibility(result: PdfExtractionResult) -> tuple[bool, str, list[dict]]:
    """Determine whether a PDF is eligible for LLM analysis.

    Returns:
        (eligible, reason, review_findings)
    """
    findings = build_pdf_review_findings(result)

    if result.quality == "failed":
        return False, f"PDF extraction failed: {result.error_message}", findings

    if result.quality == "minimal" and result.needs_ocr:
        # Minimal quality + needs OCR: too little text to analyze
        findings.append({
            "rule": "pdf_analysis_skipped",
            "severity": "warning",
            "file_path": result.file_name,
            "message": "PDF 文本质量不足以进行分析。建议使用 OCR 后再试。",
            "detail": f"quality={result.quality}, needs_ocr={result.needs_ocr}",
        })
        return False, "文本质量不足，需要 OCR", findings

    total_chars = sum(p.char_count for p in result.pages)
    if total_chars < 200:
        findings.append({
            "rule": "pdf_analysis_skipped",
            "severity": "warning",
            "file_path": result.file_name,
            "message": f"PDF 全文字符数仅 {total_chars}，不足以进行有效分析。",
            "detail": f"quality={result.quality}",
        })
        return False, f"文本量不足 ({total_chars} chars)", findings

    if result.needs_ocr and result.quality == "degraded":
        # Degraded + needs_ocr: allow analysis but warn
        return True, "degraded_ocr_recommended", findings

    return True, "ok", findings


# ── PDF Analysis Entry Point ────────────────────────────────────────────────


def analyze_pdf(
    file_path: str | Path,
    provider_name: str = "mock",
    output_dir: Path | None = None,
    focus_areas: list[str] | None = None,
    analysis_depth: str = "standard",
    write_review: bool = False,
    db_path: str | None = None,
) -> dict:
    """Extract and analyze a PDF, producing a research report.

    This is the main entry point for P4-B. It:
      1. Extracts text from the PDF (reuses P4-A)
      2. Checks quality eligibility
      3. Converts pages to segments
      4. Passes through the existing _run_pipeline()
      5. Writes review items if quality is low

    Args:
        file_path: Path to the PDF file.
        provider_name: LLM provider ("mock" or "openai-compatible").
        output_dir: Output directory for reports.
        focus_areas: List of focus areas.
        analysis_depth: "standard" or "deep".
        write_review: If True, write quality findings to review_items.
        db_path: Optional DB path override.

    Returns:
        dict with keys: success, report_id, report_path, view_count,
        entity_count, source_profile, quality, eligible, reason
    """
    fp = Path(file_path)
    ensure_dirs()

    if focus_areas is None:
        focus_areas = ["通用投资研究"]

    # 1. Extract PDF text (P4-A)
    result = extract_pdf(fp)

    # 2. Build source profile
    source_profile = build_pdf_source_profile(result)

    # 3. Quality check
    eligible, reason, review_findings = _check_analysis_eligibility(result)

    # 4. Write review items if requested
    if write_review and review_findings:
        from signalvault.db.session import init_db
        from signalvault.sources.review_items import ReviewItemManager
        if db_path:
            init_db(db_path)
        else:
            init_db()
        ReviewItemManager.create_from_lint_findings(review_findings)

    if not eligible:
        logger.warning("PDF not eligible for analysis: %s — %s", fp.name, reason)
        return {
            "success": False,
            "report_id": 0,
            "report_path": "",
            "view_count": 0,
            "entity_count": 0,
            "source_profile": source_profile,
            "quality": result.quality,
            "eligible": False,
            "reason": reason,
            "needs_ocr": result.needs_ocr,
        }

    # 5. Convert pages to segments
    segments = _pages_to_segments(result)
    logger.info(
        "PDF '%s': %d pages → %d segments, %d total chars, quality=%s",
        result.file_name, result.page_count, len(segments),
        sum(s.text.count("") + len(s.text) for s in segments),
        result.quality,
    )

    # 6. Build source_info and episode_extra for the pipeline
    pdf_title = result.metadata.title or fp.stem

    source_info = {
        "source_type": "pdf_upload",
        "source_path": str(fp.resolve()),
        "source_url": str(fp.resolve()),
        "title": pdf_title,
        "pdf_file_name": result.file_name,
        "pdf_page_count": result.page_count,
        "pdf_quality": result.quality,
        "pdf_extraction_method": "pdfplumber",
        "pdf_content_hash": result.content_hash,
        "pdf_needs_ocr": result.needs_ocr,
        "pdf_author": result.metadata.author,
        "pdf_creation_date": result.metadata.creation_date,
    }

    episode_extra = {
        "source": "pdf_upload",
        "source_url": str(fp.resolve()),
        "video_id": "",  # PDFs don't have video IDs
        "language": "zh",
    }

    # 7. Run the existing pipeline
    from signalvault.analysis.pipeline import _run_pipeline

    output_path = output_dir or REPORT_DIR

    pipeline_result = _run_pipeline(
        segments=segments,
        episode_title=pdf_title,
        source_path=str(fp.resolve()),
        subtitle_format="pdf",
        subtitle_hash=result.content_hash,
        provider_name=provider_name,
        output_dir=output_path,
        focus_areas=focus_areas,
        analysis_depth=analysis_depth,
        source_info=source_info,
        episode_extra=episode_extra,
    )

    return {
        "success": True,
        "report_id": pipeline_result.get("report_id", 0),
        "report_path": pipeline_result.get("report_path", ""),
        "extraction_path": pipeline_result.get("extraction_path", ""),
        "view_count": pipeline_result.get("view_count", 0),
        "entity_count": pipeline_result.get("entity_count", 0),
        "source_profile": source_profile,
        "quality": result.quality,
        "eligible": True,
        "reason": reason,
        "needs_ocr": result.needs_ocr,
    }
