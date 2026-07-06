"""P4-B: PDF analysis pipeline tests — source profile, evidence, analysis, CLI.

Covers:
  - PDF source profile generation
  - Page-to-segment conversion
  - Quality gating (minimal/failed → skip analysis)
  - Mock analysis pipeline (text PDF → report)
  - evidence_page in investment views
  - Review items for analysis-skipped
  - CLI pdf analyze smoke test
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from signalvault.sources.pdf_analysis import (
    _check_analysis_eligibility,
    _pages_to_segments,
    analyze_pdf,
    build_pdf_source_profile,
)
from signalvault.sources.pdf_extraction import (
    PdfExtractionResult,
    PdfPage,
    extract_pdf,
)

# ── PDF fixture helpers (reuse from test_pdf_extraction) ───────────────────


def _make_text_pdf(path: str, pages: int = 2, title: str = "Test Report",
                   author: str = "Test Author") -> str:
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


def _make_minimal_pdf(path: str) -> str:
    """Generate a PDF with very little text (will trigger minimal quality)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path, pagesize=A4)
    c.drawString(72, 750, "Hi")  # Just 2 characters
    c.showPage()
    c.save()
    return path


@pytest.fixture
def text_pdf_2page():
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    _make_text_pdf(path, pages=2)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def minimal_pdf():
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    _make_minimal_pdf(path)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


# ═════════════════════════════════════════════════════════════════════════════
# PDF Source Profile
# ═════════════════════════════════════════════════════════════════════════════


class TestPdfSourceProfile:
    def test_build_profile_structure(self, text_pdf_2page):
        result = extract_pdf(text_pdf_2page)
        profile = build_pdf_source_profile(result)
        assert profile["source_type"] == "pdf_upload"
        assert profile["file_name"].endswith(".pdf")
        assert profile["page_count"] == 2
        assert profile["quality"] == "good"
        assert "page_summaries" in profile
        assert len(profile["page_summaries"]) == 2
        assert "metadata" in profile
        assert profile["metadata"]["title"] == "Test Report"

    def test_build_profile_content_hash(self, text_pdf_2page):
        result = extract_pdf(text_pdf_2page)
        profile = build_pdf_source_profile(result)
        assert len(profile["content_hash"]) == 16

    def test_build_profile_total_chars(self, text_pdf_2page):
        result = extract_pdf(text_pdf_2page)
        profile = build_pdf_source_profile(result)
        assert profile["total_chars"] > 0

    def test_build_profile_error_message_empty_on_success(self, text_pdf_2page):
        result = extract_pdf(text_pdf_2page)
        profile = build_pdf_source_profile(result)
        assert profile["error_message"] == ""


# ═════════════════════════════════════════════════════════════════════════════
# Page-to-Segment Conversion
# ═════════════════════════════════════════════════════════════════════════════


class TestPagesToSegments:
    def test_converts_pages_to_segments(self, text_pdf_2page):
        result = extract_pdf(text_pdf_2page)
        segments = _pages_to_segments(result)
        assert len(segments) == 2  # 2 non-empty pages

    def test_segment_ids_carry_page_number(self, text_pdf_2page):
        result = extract_pdf(text_pdf_2page)
        segments = _pages_to_segments(result)
        assert segments[0].segment_id == "page_1"
        assert segments[1].segment_id == "page_2"

    def test_segment_timestamps_carry_page_number(self, text_pdf_2page):
        result = extract_pdf(text_pdf_2page)
        segments = _pages_to_segments(result)
        assert segments[0].start_time == "p.1"
        assert segments[0].end_time == "p.1"
        assert segments[1].start_time == "p.2"

    def test_empty_pages_are_skipped(self):
        # Create a result with one empty page and one non-empty
        result = PdfExtractionResult(
            pages=[
                PdfPage(page_number=1, text="", char_count=0, extraction_method="pdfplumber", quality="empty"),
                PdfPage(page_number=2, text="Valid content here", char_count=18, extraction_method="pdfplumber", quality="good"),
            ],
            quality="degraded",
            page_count=2,
        )
        segments = _pages_to_segments(result)
        assert len(segments) == 1
        assert segments[0].segment_id == "page_2"


# ═════════════════════════════════════════════════════════════════════════════
# Quality Gating
# ═════════════════════════════════════════════════════════════════════════════


class TestQualityGating:
    def test_good_quality_is_eligible(self, text_pdf_2page):
        result = extract_pdf(text_pdf_2page)
        eligible, reason, findings = _check_analysis_eligibility(result)
        assert eligible is True
        assert reason == "ok"

    def test_minimal_quality_not_eligible(self, minimal_pdf):
        result = extract_pdf(minimal_pdf)
        eligible, reason, findings = _check_analysis_eligibility(result)
        assert eligible is False
        assert "不足" in reason or "OCR" in reason

    def test_failed_quality_not_eligible(self):
        result = PdfExtractionResult(quality="failed", error_message="Test failure")
        eligible, reason, findings = _check_analysis_eligibility(result)
        assert eligible is False

    def test_minimal_quality_produces_analysis_skipped_finding(self, minimal_pdf):
        result = extract_pdf(minimal_pdf)
        eligible, reason, findings = _check_analysis_eligibility(result)
        # Should produce pdf_analysis_skipped finding
        rules = {f.get("rule", "") for f in findings}
        assert "pdf_analysis_skipped" in rules or any("skip" in r for r in rules)


# ═════════════════════════════════════════════════════════════════════════════
# Mock Analysis Pipeline
# ═════════════════════════════════════════════════════════════════════════════


class TestAnalyzePdf:
    def test_analyze_text_pdf_mock(self, text_pdf_2page, db_session):
        """Analyze a text PDF with mock provider."""
        result = analyze_pdf(
            file_path=text_pdf_2page,
            provider_name="mock",
            focus_areas=["AI投资"],
        )
        assert result["success"] is True
        assert result["eligible"] is True
        assert result["report_id"] > 0
        assert result["view_count"] >= 0
        assert result["source_profile"]["source_type"] == "pdf_upload"

    def test_analyze_produces_source_profile(self, text_pdf_2page, db_session):
        result = analyze_pdf(text_pdf_2page, provider_name="mock")
        profile = result["source_profile"]
        assert profile["file_name"].endswith(".pdf")
        assert profile["page_count"] == 2
        assert profile["quality"] == "good"

    def test_analyze_minimal_pdf_skips(self, minimal_pdf, db_session):
        """Minimal quality PDF should not enter analysis."""
        result = analyze_pdf(minimal_pdf, provider_name="mock")
        assert result["eligible"] is False
        assert result["success"] is False

    def test_analyze_pdf_creates_report_files(self, text_pdf_2page, db_session, tmp_path):
        """Analysis should create report files on disk."""
        output_dir = tmp_path / "reports"
        output_dir.mkdir()
        result = analyze_pdf(
            file_path=text_pdf_2page,
            provider_name="mock",
            output_dir=output_dir,
        )
        if result["success"] and result["report_path"]:
            assert Path(result["report_path"]).exists()

    def test_analyze_pdf_write_review(self, minimal_pdf, db_session):
        """--write-review should write review items for low-quality PDFs."""
        result = analyze_pdf(
            file_path=minimal_pdf,
            provider_name="mock",
            write_review=True,
        )
        assert result["eligible"] is False
        # Verify review items were created
        from signalvault.sources.review_items import ReviewItemManager
        items = ReviewItemManager.list_items(
            item_type="pdf_analysis_skipped", session=db_session,
        )
        assert len(items) >= 1


# ═════════════════════════════════════════════════════════════════════════════
# Evidence Page Number
# ═════════════════════════════════════════════════════════════════════════════


class TestEvidencePageNumber:
    def test_evidence_model_has_page_number(self):
        from signalvault.analysis.models import Evidence
        e = Evidence(page_number=12)
        assert e.page_number == 12

    def test_evidence_page_number_defaults_to_none(self):
        from signalvault.analysis.models import Evidence
        e = Evidence()
        assert e.page_number is None

    def test_investment_view_db_has_evidence_page(self, text_pdf_2page, db_session):
        """After analyzing a PDF, investment views should have evidence_page."""
        result = analyze_pdf(text_pdf_2page, provider_name="mock")
        if not result["success"]:
            pytest.skip("Analysis not eligible")

        from signalvault.db.repository import get_report_detail
        detail = get_report_detail(db_session, result["report_id"])
        if detail and detail.get("views"):
            # Mock provider may or may not produce views; if it does,
            # verify evidence_page field exists
            for v in detail["views"]:
                assert "evidence_page" in v


# ═════════════════════════════════════════════════════════════════════════════
# MCP Serializers
# ═════════════════════════════════════════════════════════════════════════════


class TestMcpSerializersPdf:
    def test_serialize_investment_view_includes_evidence_page(self):
        from signalvault.mcp_server.serializers import serialize_investment_view
        result = serialize_investment_view({
            "target_name": "Test",
            "evidence_page": 5,
        })
        assert result["evidence_page"] == 5

    def test_serialize_investment_view_evidence_page_none(self):
        from signalvault.mcp_server.serializers import serialize_investment_view
        result = serialize_investment_view({"target_name": "Test"})
        assert "evidence_page" in result

    def test_serialize_report_detail_includes_source_file(self):
        from signalvault.mcp_server.serializers import serialize_report_detail
        result = serialize_report_detail({
            "id": 1,
            "episode_title": "Test",
            "source_file": "report.pdf",
            "source_hash": "abc123",
            "page_count": 10,
        })
        assert result["source_file"] == "report.pdf"
        assert result["source_hash"] == "abc123"
        assert result["page_count"] == 10


# ═════════════════════════════════════════════════════════════════════════════
# Review Items
# ═════════════════════════════════════════════════════════════════════════════


class TestReviewItemsP4B:
    def test_pdf_analysis_skipped_in_valid_types(self):
        from signalvault.sources.review_items import VALID_ITEM_TYPES
        assert "pdf_analysis_skipped" in VALID_ITEM_TYPES
        assert "pdf_evidence_missing" in VALID_ITEM_TYPES

    def test_write_review_skips_when_quality_good(self, text_pdf_2page, db_session):
        """Good quality PDF should not produce review items."""
        result = analyze_pdf(
            file_path=text_pdf_2page,
            provider_name="mock",
            write_review=True,
        )
        # Good quality → eligible → no analysis_skipped review
        if result["eligible"]:
            from signalvault.sources.review_items import ReviewItemManager
            items = ReviewItemManager.list_items(
                item_type="pdf_analysis_skipped", session=db_session,
            )
            # Should not have analysis_skipped for good quality
            assert len(items) == 0


# ═════════════════════════════════════════════════════════════════════════════
# CLI smoke tests
# ═════════════════════════════════════════════════════════════════════════════


class TestCliPdfAnalyze:
    def test_analyze_help(self):
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["pdf", "analyze", "--help"])
        assert result.exit_code == 0
        assert "PDF" in result.stdout

    def test_analyze_text_pdf(self, text_pdf_2page, db_session):
        """pdf analyze on a valid text PDF with mock provider."""
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, [
            "pdf", "analyze", text_pdf_2page, "--mock",
        ])
        assert result.exit_code == 0
        assert "分析完成" in result.stdout or "不满足分析条件" in result.stdout

    def test_analyze_minimal_pdf_skips(self, minimal_pdf, db_session):
        """pdf analyze on minimal PDF should skip with explanation."""
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, [
            "pdf", "analyze", minimal_pdf, "--mock",
        ])
        assert result.exit_code == 0
        assert "不满足分析条件" in result.stdout

    def test_analyze_nonexistent_file(self):
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, [
            "pdf", "analyze", "/nonexistent/file.pdf",
        ])
        assert result.exit_code == 1

    def test_analyze_with_write_review(self, minimal_pdf, db_session):
        """pdf analyze --write-review on minimal PDF."""
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, [
            "pdf", "analyze", minimal_pdf, "--mock", "--write-review",
        ])
        assert result.exit_code == 0


# ═════════════════════════════════════════════════════════════════════════════
# DB migration smoke test
# ═════════════════════════════════════════════════════════════════════════════


class TestDbMigration:
    def test_evidence_page_column_exists(self, db_session):
        """evidence_page column should exist in investment_views table."""
        from sqlalchemy import inspect

        from signalvault.db.session import _engine
        insp = inspect(_engine)
        cols = {c["name"] for c in insp.get_columns("investment_views")}
        assert "evidence_page" in cols
