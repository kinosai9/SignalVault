"""P4-A: PDF extraction tests — text extraction, metadata, quality, edge cases.

Covers:
  - Text-based PDF extraction (reportlab-generated fixtures)
  - Multi-page PDF with page markers
  - Empty PDF / blank page quality marking
  - Corrupt PDF graceful degrade
  - Encrypted PDF graceful degrade
  - Content hash stability
  - ingest_jobs integration (pdf_upload)
  - Duplicate PDF dedup
  - needs_ocr → review_items
  - CLI smoke test
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from signalvault.sources.pdf_extraction import (
    PdfExtractionResult,
    PdfMetadata,
    PdfPage,
    build_pdf_review_findings,
    extract_pdf,
    try_ocr_pdf,
)

# ── PDF fixture helpers ─────────────────────────────────────────────────────


def _make_text_pdf(path: str, pages: int = 2, title: str = "Test Report",
                   author: str = "Test Author") -> str:
    """Generate a text-based PDF with reportlab. Returns the file path."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(path, pagesize=A4)
    c.setFont("Helvetica", 12)

    for i in range(1, pages + 1):
        c.drawString(72, 750, f"Page {i} Title")
        c.drawString(72, 720, f"This is the content of page {i}.")
        c.drawString(72, 700, f"Investment view: Company XYZ shows strong growth in Q{i}.")
        c.drawString(72, 680, f"Additional analysis data for page {i} with more context.")
        c.showPage()

    c.setTitle(title)
    c.setAuthor(author)
    c.save()
    return path


def _make_empty_pdf(path: str) -> str:
    """Generate a PDF with 0 pages (edge case)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(path, pagesize=A4)
    # Don't call showPage() — PDF with no pages
    c.setTitle("Empty PDF")
    c.save()
    return path


def _make_blank_page_pdf(path: str) -> str:
    """Generate a PDF with one fully blank page."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(path, pagesize=A4)
    # Draw nothing on the page
    c.showPage()
    c.setTitle("Blank Page PDF")
    c.save()
    return path


def _make_encrypted_pdf(path: str) -> str:
    """Generate an encrypted PDF using reportlab's StandardEncryption."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.pdfencrypt import StandardEncryption
    from reportlab.pdfgen import canvas

    encrypt = StandardEncryption(userPassword="userpass", ownerPassword="ownerpass")
    c = canvas.Canvas(path, pagesize=A4, encrypt=encrypt)
    c.setFont("Helvetica", 12)
    c.drawString(72, 750, "Secret content")
    c.showPage()
    c.setTitle("Encrypted PDF")
    c.save()
    return path


@pytest.fixture
def text_pdf_2page():
    """A 2-page text-based PDF with metadata."""
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    _make_text_pdf(path, pages=2)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def text_pdf_5page():
    """A 5-page text-based PDF."""
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    _make_text_pdf(path, pages=5)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def empty_pdf():
    """A PDF with 0 pages."""
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    _make_empty_pdf(path)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def blank_page_pdf():
    """A PDF with one blank page."""
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    _make_blank_page_pdf(path)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def encrypted_pdf():
    """An encrypted PDF."""
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    _make_encrypted_pdf(path)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


# ═════════════════════════════════════════════════════════════════════════════
# Data class tests
# ═════════════════════════════════════════════════════════════════════════════


class TestPdfPage:
    def test_defaults(self):
        p = PdfPage(page_number=1)
        assert p.page_number == 1
        assert p.text == ""
        assert p.char_count == 0
        assert p.extraction_method == "pdfplumber"
        assert p.quality == "good"

    def test_full_creation(self):
        p = PdfPage(
            page_number=3, text="Hello World", char_count=11,
            extraction_method="pdfplumber", quality="good",
        )
        assert p.page_number == 3
        assert p.text == "Hello World"
        assert p.char_count == 11


class TestPdfMetadata:
    def test_defaults(self):
        m = PdfMetadata()
        assert m.title == ""
        assert m.is_encrypted is False

    def test_with_data(self):
        m = PdfMetadata(title="Test", author="Author", page_count=10)
        assert m.title == "Test"
        assert m.author == "Author"
        assert m.page_count == 10


class TestPdfExtractionResult:
    def test_defaults(self):
        r = PdfExtractionResult()
        assert r.source_path == ""
        assert r.quality == "good"
        assert r.needs_ocr is False
        assert r.pages == []
        assert r.full_text == ""


# ═════════════════════════════════════════════════════════════════════════════
# Text extraction tests
# ═════════════════════════════════════════════════════════════════════════════


class TestExtractPdf:
    def test_extract_text_pdf_success(self, text_pdf_2page):
        result = extract_pdf(text_pdf_2page)
        assert result.quality == "good"
        assert result.page_count == 2
        assert len(result.pages) == 2
        assert result.error_message == ""
        assert result.needs_ocr is False

    def test_extract_pages_have_page_numbers(self, text_pdf_2page):
        result = extract_pdf(text_pdf_2page)
        assert result.pages[0].page_number == 1
        assert result.pages[1].page_number == 2

    def test_extract_pages_have_text(self, text_pdf_2page):
        result = extract_pdf(text_pdf_2page)
        assert len(result.pages[0].text) > 0
        assert len(result.pages[1].text) > 0
        assert "Company XYZ" in result.pages[0].text

    def test_full_text_has_page_markers(self, text_pdf_2page):
        result = extract_pdf(text_pdf_2page)
        assert "[Page 1]" in result.full_text
        assert "[Page 2]" in result.full_text

    def test_multi_page_preserves_all_pages(self, text_pdf_5page):
        result = extract_pdf(text_pdf_5page)
        assert result.page_count == 5
        assert len(result.pages) == 5
        for i, p in enumerate(result.pages, start=1):
            assert p.page_number == i
            assert p.quality == "good"

    def test_content_hash_stable(self, text_pdf_2page):
        """Same file → same content_hash across extractions."""
        r1 = extract_pdf(text_pdf_2page)
        r2 = extract_pdf(text_pdf_2page)
        assert r1.content_hash == r2.content_hash
        assert len(r1.content_hash) == 16

    def test_content_hash_different_for_different_content(self, text_pdf_2page, text_pdf_5page):
        r2 = extract_pdf(text_pdf_2page)
        r5 = extract_pdf(text_pdf_5page)
        assert r2.content_hash != r5.content_hash

    def test_metadata_extraction(self, text_pdf_2page):
        result = extract_pdf(text_pdf_2page)
        assert result.metadata.title == "Test Report"
        assert result.metadata.author == "Test Author"
        assert result.metadata.page_count == 2
        assert result.metadata.file_size_bytes > 0

    def test_file_name_and_path(self, text_pdf_2page):
        result = extract_pdf(text_pdf_2page)
        assert result.file_name.endswith(".pdf")
        assert result.source_path == str(Path(text_pdf_2page).resolve())


# ═════════════════════════════════════════════════════════════════════════════
# Edge cases
# ═════════════════════════════════════════════════════════════════════════════


class TestExtractPdfEdgeCases:
    def test_file_not_found(self):
        result = extract_pdf("/nonexistent/path/file.pdf")
        assert result.quality == "failed"
        assert "not found" in result.error_message.lower()

    def test_not_a_file(self, tmp_path):
        result = extract_pdf(str(tmp_path))  # directory, not file
        assert result.quality == "failed"

    def test_empty_pdf(self, empty_pdf):
        result = extract_pdf(empty_pdf)
        # 0-page PDF — quality should be minimal or failed
        assert result.quality in ("minimal", "failed")
        assert result.page_count == 0

    def test_blank_page_pdf(self, blank_page_pdf):
        result = extract_pdf(blank_page_pdf)
        assert result.page_count == 1
        # Blank page should be marked empty/partial
        assert result.pages[0].quality in ("empty", "partial")
        assert result.pages[0].char_count < 50
        # Should trigger needs_ocr
        assert result.needs_ocr is True

    def test_encrypted_pdf_graceful_degrade(self, encrypted_pdf):
        result = extract_pdf(encrypted_pdf)
        assert result.quality == "failed"
        assert result.metadata.is_encrypted is True
        assert "encrypt" in result.error_message.lower()

    def test_non_pdf_file(self, tmp_path):
        """Non-PDF file should still be processed by pdfplumber (will fail gracefully)."""
        txt_file = tmp_path / "not_a_pdf.pdf"
        txt_file.write_text("This is not a PDF file")
        result = extract_pdf(str(txt_file))
        # pdfplumber will reject it — should be graceful
        assert result.quality in ("failed", "minimal")
        assert result.error_message or result.quality == "failed"


# ═════════════════════════════════════════════════════════════════════════════
# OCR skeleton tests
# ═════════════════════════════════════════════════════════════════════════════


class TestOcrSkeleton:
    def test_try_ocr_returns_result_without_crashing(self, text_pdf_2page):
        """try_ocr_pdf should return a result even without OCR deps."""
        result = try_ocr_pdf(text_pdf_2page)
        assert isinstance(result, PdfExtractionResult)
        # May succeed if tesseract IS installed, or may report needs_ocr
        assert result.quality in ("good", "degraded", "minimal", "failed")

    def test_try_ocr_file_not_found(self):
        result = try_ocr_pdf("/nonexistent/file.pdf")
        assert result.quality == "failed"
        assert "not found" in result.error_message.lower()

    def test_try_ocr_encrypted_pdf(self, encrypted_pdf):
        """try_ocr should handle encrypted PDF gracefully."""
        result = try_ocr_pdf(encrypted_pdf)
        # Should return a result, not crash
        assert isinstance(result, PdfExtractionResult)


# ═════════════════════════════════════════════════════════════════════════════
# Review item findings
# ═════════════════════════════════════════════════════════════════════════════


class TestBuildPdfReviewFindings:
    def test_good_quality_no_findings(self, text_pdf_2page):
        result = extract_pdf(text_pdf_2page)
        findings = build_pdf_review_findings(result)
        assert findings == []

    def test_minimal_quality_generates_findings(self, blank_page_pdf):
        result = extract_pdf(blank_page_pdf)
        findings = build_pdf_review_findings(result)
        # Blank page PDF → minimal quality → needs_ocr or quality_issue
        assert len(findings) > 0
        rules = {f["rule"] for f in findings}
        assert rules.intersection({"pdf_needs_ocr", "pdf_quality_issue", "pdf_extraction_failed"})

    def test_failed_extraction_findings(self, encrypted_pdf):
        result = extract_pdf(encrypted_pdf)
        findings = build_pdf_review_findings(result)
        assert len(findings) > 0
        assert any(f["rule"] == "pdf_extraction_failed" for f in findings)

    def test_finding_structure(self, blank_page_pdf):
        result = extract_pdf(blank_page_pdf)
        findings = build_pdf_review_findings(result)
        for f in findings:
            assert "rule" in f
            assert "severity" in f
            assert "file_path" in f
            assert "message" in f
            assert "detail" in f
            assert f["severity"] in ("error", "warning", "info")


# ═════════════════════════════════════════════════════════════════════════════
# ingest_jobs integration
# ═════════════════════════════════════════════════════════════════════════════


class TestIngestJobsPdf:
    def test_pdf_upload_job_key_format(self):
        """pdf_upload job_key uses content_hash."""
        from signalvault.sources.ingest_jobs import _make_job_key
        key = _make_job_key("pdf_upload", source_hash="abc123def456")
        assert key.startswith("pdf_upload:")
        assert "abc123def456" in key

    def test_create_pdf_upload_job(self, text_pdf_2page, db_session):
        """Create an ingest job for a PDF upload."""
        from signalvault.sources.ingest_jobs import IngestJobManager

        result = extract_pdf(text_pdf_2page)

        import json as _json
        payload = _json.dumps({
            "source_path": result.source_path,
            "file_name": result.file_name,
            "file_size": result.file_size,
            "page_count": result.page_count,
            "quality": result.quality,
            "needs_ocr": result.needs_ocr,
        }, ensure_ascii=False)

        job = IngestJobManager.create_job(
            source_type="pdf_upload",
            source_hash=result.content_hash,
            source_name=result.file_name,
            preview_data=payload,
            session=db_session,
        )
        assert job is not None
        assert job["source_type"] == "pdf_upload"
        assert job["status"] == "pending_preview"
        assert job["source_hash"] == result.content_hash

    def test_duplicate_pdf_no_duplicate_job(self, text_pdf_2page, db_session):
        """Same PDF hash → second create_job fails due to unique index."""
        from signalvault.sources.ingest_jobs import IngestJobManager

        result = extract_pdf(text_pdf_2page)

        # First creation
        job1 = IngestJobManager.create_job(
            source_type="pdf_upload",
            source_hash=result.content_hash,
            source_name=result.file_name,
            session=db_session,
        )
        assert job1 is not None

        # Second creation with same hash → should fail (unique constraint)
        job2 = IngestJobManager.create_job(
            source_type="pdf_upload",
            source_hash=result.content_hash,
            source_name=result.file_name,
            session=db_session,
        )
        # Second create should fail due to partial unique index
        assert job2 is None

    def test_pdf_upload_job_listable(self, text_pdf_2page, db_session):
        """Created PDF job appears in list_jobs."""
        from signalvault.sources.ingest_jobs import IngestJobManager

        result = extract_pdf(text_pdf_2page)
        IngestJobManager.create_job(
            source_type="pdf_upload",
            source_hash=result.content_hash,
            source_name=result.file_name,
            session=db_session,
        )

        jobs = IngestJobManager.list_jobs(source_type="pdf_upload", session=db_session)
        assert len(jobs) == 1
        assert jobs[0]["source_type"] == "pdf_upload"


# ═════════════════════════════════════════════════════════════════════════════
# Review Queue integration
# ═════════════════════════════════════════════════════════════════════════════


class TestReviewItemsPdf:
    def test_pdf_needs_ocr_creates_review_item(self, blank_page_pdf, db_session):
        """When needs_ocr=True, review item should be created."""
        from signalvault.sources.review_items import ReviewItemManager

        result = extract_pdf(blank_page_pdf)
        findings = build_pdf_review_findings(result)
        if findings:
            created = ReviewItemManager.create_from_lint_findings(
                findings, session=db_session,
            )
            assert created > 0

            # Verify items are in the list
            items = ReviewItemManager.list_items(
                item_type="pdf_needs_ocr", session=db_session,
            )
            assert len(items) >= 1

    def test_pdf_extraction_failed_creates_review_item(self, encrypted_pdf, db_session):
        """Failed extraction → review item with pdf_extraction_failed."""
        from signalvault.sources.review_items import ReviewItemManager

        result = extract_pdf(encrypted_pdf)
        findings = build_pdf_review_findings(result)
        assert len(findings) > 0
        created = ReviewItemManager.create_from_lint_findings(
            findings, session=db_session,
        )
        assert created > 0

    def test_valid_item_types_include_pdf(self):
        """VALID_ITEM_TYPES includes the 3 new PDF types."""
        from signalvault.sources.review_items import VALID_ITEM_TYPES
        assert "pdf_needs_ocr" in VALID_ITEM_TYPES
        assert "pdf_quality_issue" in VALID_ITEM_TYPES
        assert "pdf_extraction_failed" in VALID_ITEM_TYPES


# ═════════════════════════════════════════════════════════════════════════════
# CLI smoke tests
# ═════════════════════════════════════════════════════════════════════════════


class TestCliPdf:
    def test_preview_command_exists(self):
        """pdf preview command is registered."""
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        app = cli_mod.app
        # Check that typer group 'pdf' is in the registered groups
        # (sub-groups don't appear in registered_commands, but we can invoke them)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(app, ["pdf", "--help"])
        assert result.exit_code == 0

    def test_preview_help(self):
        """pdf preview --help works."""
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["pdf", "preview", "--help"])
        assert result.exit_code == 0
        assert "PDF" in result.stdout

    def test_extract_help(self):
        """pdf extract --help works."""
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["pdf", "extract", "--help"])
        assert result.exit_code == 0
        assert "PDF" in result.stdout

    def test_preview_text_pdf(self, text_pdf_2page):
        """pdf preview on a valid text PDF."""
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["pdf", "preview", text_pdf_2page])
        assert result.exit_code == 0
        assert "PDF Preview" in result.stdout
        assert "Pages: 2" in result.stdout
        assert "Quality:" in result.stdout

    def test_preview_json_output(self, text_pdf_2page):
        """pdf preview --json returns structured output."""
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["pdf", "preview", text_pdf_2page, "--json"])
        assert result.exit_code == 0
        # Verify key fields are present in the JSON-like output
        assert '"page_count": 2' in result.stdout
        assert '"quality": "good"' in result.stdout
        assert '"full_text"' in result.stdout
        assert '"pages"' in result.stdout
        assert '"file_name"' in result.stdout

    def test_extract_json_output(self, text_pdf_2page):
        """pdf extract --json returns structured output."""
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["pdf", "extract", text_pdf_2page, "--json"])
        assert result.exit_code == 0
        assert '"full_text"' in result.stdout
        assert '"page_count": 2' in result.stdout

    def test_extract_output_file(self, text_pdf_2page, tmp_path):
        """pdf extract --output writes to file."""
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        output_file = tmp_path / "extracted.txt"
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, [
            "pdf", "extract", text_pdf_2page, "--output", str(output_file),
        ])
        assert result.exit_code == 0
        assert output_file.exists()
        content = output_file.read_text(encoding="utf-8")
        assert "[Page 1]" in content

    def test_preview_nonexistent_file(self):
        """pdf preview on nonexistent file → error."""
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["pdf", "preview", "/nonexistent/file.pdf"])
        assert result.exit_code == 1
        assert "不存在" in result.stdout

    def test_preview_write_review(self, blank_page_pdf, db_session):
        """pdf preview --write-review writes review items."""
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, [
            "pdf", "preview", blank_page_pdf, "--write-review",
        ])
        assert result.exit_code == 0
        assert "review" in result.stdout.lower() or "写入" in result.stdout

    def test_extract_write_review(self, blank_page_pdf, db_session):
        """pdf extract --write-review writes review items."""
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, [
            "pdf", "extract", blank_page_pdf, "--write-review", "--json",
        ])
        assert result.exit_code == 0


# ═════════════════════════════════════════════════════════════════════════════
# Full-text format
# ═════════════════════════════════════════════════════════════════════════════


class TestFullTextFormat:
    def test_full_text_non_empty(self, text_pdf_2page):
        result = extract_pdf(text_pdf_2page)
        assert len(result.full_text) > 0

    def test_full_text_page_separators(self, text_pdf_5page):
        result = extract_pdf(text_pdf_5page)
        for i in range(1, 6):
            assert f"[Page {i}]" in result.full_text


# ═════════════════════════════════════════════════════════════════════════════
# PdfExtractionResult serialization
# ═════════════════════════════════════════════════════════════════════════════


class TestResultSerialization:
    def test_result_is_serializable(self, text_pdf_2page):
        """PdfExtractionResult can be serialized to JSON-safe dict."""
        from signalvault.cli import _serialize_result
        result = extract_pdf(text_pdf_2page)
        data = _serialize_result(result)
        assert data["page_count"] == 2
        assert isinstance(data["pages"], list)
        assert len(data["pages"]) == 2
        # Verify it's JSON-serializable
        encoded = json.dumps(data, ensure_ascii=False)
        decoded = json.loads(encoded)
        assert decoded["quality"] == "good"
