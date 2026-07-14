"""P2-S.3.3: Tests for user text file upload preview & archive."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest

# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════


def _make_temp_file(suffix: str, content: str, encoding: str = "utf-8") -> Path:
    """Create a temporary file with the given content and return its path."""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content.encode(encoding))
        return Path(tmp.name)


def _content_hash(text: str, encoding: str = "utf-8") -> str:
    """Compute the same hash as file_profile does."""
    return hashlib.sha256(text.encode(encoding)).hexdigest()[:32]


# ═════════════════════════════════════════════════════════════════════════════
# profile_uploaded_file tests
# ═════════════════════════════════════════════════════════════════════════════


class TestProfileUploadedFile:
    """Tests for profile_uploaded_file()."""

    def test_txt_file_supported(self):
        from signalvault.sources.file_profile import profile_uploaded_file

        path = _make_temp_file(".txt", "Hello world. " * 50)
        try:
            profile = profile_uploaded_file(path, "test.txt")
            assert profile.supported is True
            assert profile.extension == ".txt"
            assert profile.unsupported_reason is None
        finally:
            path.unlink(missing_ok=True)

    def test_md_file_supported(self):
        from signalvault.sources.file_profile import profile_uploaded_file

        path = _make_temp_file(".md", "# Title\n\nSome content. " * 30)
        try:
            profile = profile_uploaded_file(path, "test.md")
            assert profile.supported is True
            assert profile.extension == ".md"
        finally:
            path.unlink(missing_ok=True)

    def test_html_file_supported(self):
        from signalvault.sources.file_profile import profile_uploaded_file

        content = "<html><body><h1>Title</h1><p>Paragraph. " * 20 + "</p></body></html>"
        path = _make_temp_file(".html", content)
        try:
            profile = profile_uploaded_file(path, "test.html")
            assert profile.supported is True
            assert profile.extension == ".html"
        finally:
            path.unlink(missing_ok=True)

    def test_pdf_file_rejected_by_text_profiler(self):
        from signalvault.sources.file_profile import profile_uploaded_file

        path = _make_temp_file(".pdf", "%PDF-1.4 fake content")
        try:
            profile = profile_uploaded_file(path, "test.pdf")
            # profile_uploaded_file only checks ALLOWED_TEXT_EXTENSIONS, so PDF is unsupported here
            # (PDF handling is done at the web route level, not in the text profiler)
            assert profile.supported is False
            assert profile.unsupported_reason is not None
            assert profile.parse_quality == "minimal"
        finally:
            path.unlink(missing_ok=True)

    def test_unknown_extension_rejected(self):
        from signalvault.sources.file_profile import profile_uploaded_file

        path = _make_temp_file(".xyz", "some content here")
        try:
            profile = profile_uploaded_file(path, "test.xyz")
            assert profile.supported is False
            assert profile.unsupported_reason is not None
        finally:
            path.unlink(missing_ok=True)

    def test_oversized_file_rejected(self):
        from signalvault.sources.file_profile import (
            MAX_UPLOAD_BYTES,
            profile_uploaded_file,
        )

        # Create content larger than max
        content = "x" * (MAX_UPLOAD_BYTES + 100)
        path = _make_temp_file(".txt", content)
        try:
            profile = profile_uploaded_file(path, "large.txt")
            assert profile.supported is False
            assert "超过限制" in profile.unsupported_reason
        finally:
            path.unlink(missing_ok=True)

    def test_content_hash_stable(self):
        from signalvault.sources.file_profile import profile_uploaded_file

        text = "This is stable content for hashing." * 10
        path = _make_temp_file(".txt", text)
        try:
            profile1 = profile_uploaded_file(path, "test.txt")
            profile2 = profile_uploaded_file(path, "test.txt")
            assert profile1.content_hash is not None
            assert profile1.content_hash == profile2.content_hash
            assert len(profile1.content_hash) == 32
        finally:
            path.unlink(missing_ok=True)

    def test_parse_quality_good_for_sufficient_text(self):
        from signalvault.sources.file_profile import profile_uploaded_file

        text = "A" * 1200 + "\n\nB" * 100 + "\n\nC" * 100 + "\n\nD" * 100
        path = _make_temp_file(".txt", text)
        try:
            profile = profile_uploaded_file(path, "test.txt")
            assert profile.parse_quality == "good"
        finally:
            path.unlink(missing_ok=True)

    def test_parse_quality_degraded_for_short_text(self):
        from signalvault.sources.file_profile import profile_uploaded_file

        # Between 50 and 200 chars → degraded
        text = "A" * 80 + "\n" + "B" * 60
        path = _make_temp_file(".txt", text)
        try:
            profile = profile_uploaded_file(path, "test.txt")
            assert profile.parse_quality == "degraded"
        finally:
            path.unlink(missing_ok=True)

    def test_parse_quality_minimal_for_very_short_text(self):
        from signalvault.sources.file_profile import profile_uploaded_file

        text = "hi"
        path = _make_temp_file(".txt", text)
        try:
            profile = profile_uploaded_file(path, "test.txt")
            assert profile.parse_quality == "minimal"
        finally:
            path.unlink(missing_ok=True)


# ═════════════════════════════════════════════════════════════════════════════
# Encoding tests
# ═════════════════════════════════════════════════════════════════════════════


class TestEncodingDetection:
    """Tests for encoding detection in file profiling."""

    def test_utf8_text_extraction(self):
        from signalvault.sources.file_profile import profile_uploaded_file

        text = "中文字符测试 Content extraction test. " * 30
        path = _make_temp_file(".txt", text, encoding="utf-8")
        try:
            profile = profile_uploaded_file(path, "test.txt")
            assert profile.supported is True
            assert profile.detected_encoding in ("utf-8", "utf-8-sig")
            assert profile.extracted_text_length > 0
        finally:
            path.unlink(missing_ok=True)

    def test_utf8sig_text_extraction(self):
        from signalvault.sources.file_profile import profile_uploaded_file

        text = "BOM test content. " * 40
        path = _make_temp_file(".txt", "﻿" + text, encoding="utf-8-sig")
        try:
            profile = profile_uploaded_file(path, "test.txt")
            assert profile.supported is True
            # UTF-8 can also decode UTF-8-SIG content (BOM becomes U+FEFF)
            assert profile.detected_encoding in ("utf-8", "utf-8-sig")
        finally:
            path.unlink(missing_ok=True)

    def test_gb18030_text_extraction(self):
        from signalvault.sources.file_profile import profile_uploaded_file

        text = "GB18030 编码的中文测试文本。" * 40
        # Write using gb18030 encoding (binary mode)
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp.write(text.encode("gb18030"))
            path = Path(tmp.name)
        try:
            profile = profile_uploaded_file(path, "test.txt")
            assert profile.supported is True
            assert profile.detected_encoding in ("gb18030", "utf-8")
        finally:
            path.unlink(missing_ok=True)


# ═════════════════════════════════════════════════════════════════════════════
# extract_text_from_uploaded_file tests
# ═════════════════════════════════════════════════════════════════════════════


class TestContentExtraction:
    """Tests for extract_text_from_uploaded_file()."""

    def test_txt_content_extraction(self):
        from signalvault.sources.file_content_extractor import (
            extract_text_from_uploaded_file,
        )

        text = "Line one\nLine two\nLine three\n" * 50
        path = _make_temp_file(".txt", text)
        try:
            ch = _content_hash(text)
            result = extract_text_from_uploaded_file(path, "test.txt", ch, "utf-8")
            assert result.text == text
            assert result.extension == ".txt"
            assert result.content_hash == ch
            assert result.blocks_count > 0
        finally:
            path.unlink(missing_ok=True)

    def test_md_first_h1_as_title(self):
        from signalvault.sources.file_content_extractor import (
            extract_text_from_uploaded_file,
        )

        text = "# Investment Analysis Report\n\n## Section 1\n\nSome analysis content here. " * 30
        path = _make_temp_file(".md", text)
        try:
            ch = _content_hash(text)
            result = extract_text_from_uploaded_file(path, "test.md", ch, "utf-8")
            assert result.title == "Investment Analysis Report"
            assert result.parse_quality == "good"
        finally:
            path.unlink(missing_ok=True)

    def test_md_title_from_filename_fallback(self):
        from signalvault.sources.file_content_extractor import (
            extract_text_from_uploaded_file,
        )

        text = "Just some content without a heading. " * 30
        path = _make_temp_file(".md", text)
        try:
            ch = _content_hash(text)
            result = extract_text_from_uploaded_file(path, "my_research_note.md", ch, "utf-8")
            assert result.title == "my research note"
        finally:
            path.unlink(missing_ok=True)

    def test_html_title_extraction(self):
        from signalvault.sources.file_content_extractor import (
            extract_text_from_uploaded_file,
        )

        html = """<!DOCTYPE html>
<html><head><title>AI Market Analysis 2025</title></head>
<body>
    <h1>Market Overview</h1>
    <p>Paragraph one with enough content to make it meaningful for extraction.</p>
    <p>Paragraph two also contains substantial text for testing purposes.</p>
    <p>Third paragraph with more meaningful content for extraction testing.</p>
</body></html>"""
        path = _make_temp_file(".html", html)
        try:
            ch = _content_hash(html)
            result = extract_text_from_uploaded_file(path, "test.html", ch, "utf-8")
            assert "AI Market Analysis" in result.title
            assert result.blocks_count >= 3
            assert result.parse_quality == "good"
        finally:
            path.unlink(missing_ok=True)

    def test_html_script_style_removed(self):
        from signalvault.sources.file_content_extractor import (
            extract_text_from_uploaded_file,
        )

        html = """<!DOCTYPE html>
<html><head><title>Test</title>
<style>body { color: red; } .hidden { display: none; }</style>
<script>console.log("should not appear"); alert("no scripts");</script>
</head><body>
    <h1>Real Content</h1>
    <p>This should be kept in the extraction output.</p>
    <p>Another valid paragraph for testing.</p>
    <p>Third paragraph for block counting tests.</p>
    <noscript>JavaScript is required</noscript>
</body></html>"""
        path = _make_temp_file(".html", html)
        try:
            ch = _content_hash(html)
            result = extract_text_from_uploaded_file(path, "test.html", ch, "utf-8")
            assert "console.log" not in result.text
            assert "should not appear" not in result.text
            assert "body { color: red" not in result.text
            assert "Real Content" in result.text
            assert "valid paragraph" in result.text
            assert "JavaScript is required" not in result.text
        finally:
            path.unlink(missing_ok=True)

    def test_html_header_nav_footer_removed(self):
        from signalvault.sources.file_content_extractor import (
            extract_text_from_uploaded_file,
        )

        html = """<!DOCTYPE html>
<html><head><title>Page With Nav</title></head>
<body>
    <nav><a href="/">Home</a></nav>
    <header><h1>Site Header</h1></header>
    <main><h1>Article Title</h1>
    <p>Actual article content here for extraction.</p>
    <p>Second paragraph of meaningful content.</p>
    <p>Third paragraph for testing extraction blocks.</p>
    </main>
    <footer>Copyright 2025</footer>
</body></html>"""
        path = _make_temp_file(".html", html)
        try:
            ch = _content_hash(html)
            result = extract_text_from_uploaded_file(path, "test.html", ch, "utf-8")
            # Site Header from <header> should NOT appear as the title
            assert "Article Title" in result.title or "Page With Nav" in result.title
            assert "Copyright 2025" not in result.text
        finally:
            path.unlink(missing_ok=True)


# ═════════════════════════════════════════════════════════════════════════════
# Import eligibility tests
# ═════════════════════════════════════════════════════════════════════════════


class TestFileImportEligibility:
    """Tests for evaluate_file_import_eligibility()."""

    def test_short_content_not_eligible(self):
        from signalvault.sources.file_content_extractor import ExtractedFileContent
        from signalvault.sources.file_import_preview import (
            evaluate_file_import_eligibility,
        )
        from signalvault.sources.models import UploadedFileProfile

        profile = UploadedFileProfile(
            original_filename="short.txt",
            extension=".txt",
            supported=True,
            content_hash="abc123",
            extracted_text_length=50,
            parse_quality="minimal",
        )
        content = ExtractedFileContent(
            text="short",
            title="Short",
            content_hash="abc123",
            extension=".txt",
            parse_quality="minimal",
        )
        eligibility = evaluate_file_import_eligibility(profile, content)
        assert eligibility.import_eligible is False
        assert eligibility.ineligible_reason is not None

    def test_normal_text_eligible(self):
        from signalvault.sources.file_content_extractor import ExtractedFileContent
        from signalvault.sources.file_import_preview import (
            evaluate_file_import_eligibility,
        )
        from signalvault.sources.models import UploadedFileProfile

        profile = UploadedFileProfile(
            original_filename="report.md",
            extension=".md",
            supported=True,
            content_hash="def456",
            extracted_text_length=2000,
            parse_quality="good",
        )
        content = ExtractedFileContent(
            text="x" * 2000,
            title="Report",
            content_hash="def456",
            extension=".md",
            parse_quality="good",
        )
        eligibility = evaluate_file_import_eligibility(profile, content)
        assert eligibility.import_eligible is True
        assert eligibility.ineligible_reason is None
        assert eligibility.recommended_archive_type.value == "source_archive"  # FileArchiveType enum

    def test_unsupported_file_not_eligible(self):
        from signalvault.sources.file_content_extractor import ExtractedFileContent
        from signalvault.sources.file_import_preview import (
            evaluate_file_import_eligibility,
        )
        from signalvault.sources.models import UploadedFileProfile

        profile = UploadedFileProfile(
            original_filename="test.pdf",
            extension=".pdf",
            supported=False,
            unsupported_reason="PDF not supported",
            parse_quality="minimal",
        )
        content = ExtractedFileContent()
        eligibility = evaluate_file_import_eligibility(profile, content)
        assert eligibility.import_eligible is False

    def test_no_hash_not_eligible(self):
        from signalvault.sources.file_content_extractor import ExtractedFileContent
        from signalvault.sources.file_import_preview import (
            evaluate_file_import_eligibility,
        )
        from signalvault.sources.models import UploadedFileProfile

        profile = UploadedFileProfile(
            original_filename="test.txt",
            extension=".txt",
            supported=True,
            content_hash=None,
            extracted_text_length=500,
            parse_quality="good",
        )
        content = ExtractedFileContent()
        eligibility = evaluate_file_import_eligibility(profile, content)
        assert eligibility.import_eligible is False

    def test_minimal_quality_not_eligible(self):
        from signalvault.sources.file_content_extractor import ExtractedFileContent
        from signalvault.sources.file_import_preview import (
            evaluate_file_import_eligibility,
        )
        from signalvault.sources.models import UploadedFileProfile

        profile = UploadedFileProfile(
            original_filename="test.txt",
            extension=".txt",
            supported=True,
            content_hash="xyz789",
            extracted_text_length=300,
            parse_quality="minimal",
        )
        content = ExtractedFileContent()
        eligibility = evaluate_file_import_eligibility(profile, content)
        assert eligibility.import_eligible is False


# ═════════════════════════════════════════════════════════════════════════════
# Conflict detection tests
# ═════════════════════════════════════════════════════════════════════════════


class TestFileConflictDetection:
    """Tests for ConflictDetector.detect_for_file()."""

    def test_no_conflicts_in_empty_vault(self, tmp_path):
        from signalvault.sources.conflict_detector import ConflictDetector

        # tmp_path is an empty directory
        conflicts = ConflictDetector(tmp_path).detect_for_file(
            content_hash="abc123",
            filename="test.txt",
            title="Some Title",
        )
        assert conflicts == []

    def test_same_content_hash_detected(self, tmp_path):
        from signalvault.sources.conflict_detector import (
            ConflictDetector,
        )

        # Create a SourceArchive with known content_hash
        archive_dir = tmp_path / "01_Reports" / "SourceArchive"
        archive_dir.mkdir(parents=True)
        existing = archive_dir / "2025-01-01_existing.md"
        existing.write_text(
            "---\ncontent_hash: abc123def456\n---\n# Some content\n",
            encoding="utf-8",
        )

        conflicts = ConflictDetector(tmp_path).detect_for_file(
            content_hash="abc123def456",
            filename="different_name.txt",
            title="Different Title",
        )
        assert len(conflicts) >= 1
        assert any(c.conflict_type == "same_content_hash" for c in conflicts)
        assert any(c.severity == "blocker" for c in conflicts)

    def test_same_filename_detected(self, tmp_path):
        from signalvault.sources.conflict_detector import (
            ConflictDetector,
        )

        archive_dir = tmp_path / "01_Reports" / "SourceArchive"
        archive_dir.mkdir(parents=True)
        # Conflict detector scans for *.md files in scan dirs
        existing = archive_dir / "my_report.md"
        existing.write_text("---\ntitle: Some report\n---\n# Content\n", encoding="utf-8")

        conflicts = ConflictDetector(tmp_path).detect_for_file(
            content_hash="different_hash_12345",
            filename="my_report.md",
            title="Some report",
        )
        assert any(c.conflict_type == "same_filename" for c in conflicts)

    def test_same_title_detected(self, tmp_path):
        from signalvault.sources.conflict_detector import (
            ConflictDetector,
        )

        archive_dir = tmp_path / "01_Reports" / "ReportMaterial"
        archive_dir.mkdir(parents=True)
        existing = archive_dir / "some_file.md"
        existing.write_text(
            "---\ntitle: AI Market Analysis 2025\n---\n# AI Market Analysis 2025\n\nContent.\n",
            encoding="utf-8",
        )

        conflicts = ConflictDetector(tmp_path).detect_for_file(
            content_hash="unique_hash_999",
            filename="new_file.md",
            title="AI Market Analysis 2025",
        )
        assert any(c.conflict_type == "same_title" for c in conflicts)

    def test_duplicate_content_recommends_skip(self, tmp_path):
        from signalvault.sources.file_content_extractor import ExtractedFileContent
        from signalvault.sources.file_import_preview import (
            build_file_import_preview,
        )
        from signalvault.sources.models import UploadedFileProfile

        # Create existing file with known hash
        archive_dir = tmp_path / "01_Reports" / "SourceArchive"
        archive_dir.mkdir(parents=True)
        existing = archive_dir / "2025-01-01_dup.md"
        existing.write_text(
            "---\ncontent_hash: dup_hash_11111\n---\n# Duplicate\n",
            encoding="utf-8",
        )

        profile = UploadedFileProfile(
            original_filename="report.md",
            extension=".md",
            supported=True,
            content_hash="dup_hash_11111",
            extracted_text_length=500,
            parse_quality="good",
        )
        content = ExtractedFileContent(
            text="Some content " * 60,
            title="Duplicate",
            content_hash="dup_hash_11111",
            extension=".md",
            parse_quality="good",
        )

        preview = build_file_import_preview(profile, content, tmp_path)
        assert preview.recommended_action.value == "skip"
        assert not any(a.value == "confirm_archive" for a in preview.available_actions)

    def test_non_duplicate_defaults_to_source_archive(self, tmp_path):
        from signalvault.sources.file_content_extractor import ExtractedFileContent
        from signalvault.sources.file_import_preview import (
            build_file_import_preview,
        )
        from signalvault.sources.models import UploadedFileProfile

        profile = UploadedFileProfile(
            original_filename="unique.md",
            extension=".md",
            supported=True,
            content_hash="unique_hash_22222",
            extracted_text_length=2000,
            parse_quality="good",
        )
        content = ExtractedFileContent(
            text="Unique content " * 200,
            title="Unique Report",
            content_hash="unique_hash_22222",
            extension=".md",
            parse_quality="good",
        )

        preview = build_file_import_preview(profile, content, tmp_path)
        assert preview.recommended_action.value == "confirm_archive"
        assert any(a.value == "confirm_archive" for a in preview.available_actions)


# ═════════════════════════════════════════════════════════════════════════════
# Preview generation tests
# ═════════════════════════════════════════════════════════════════════════════


class TestFileImportPreview:
    """Tests for build_file_import_preview()."""

    def test_preview_no_vault_writes(self, tmp_path):
        from signalvault.sources.file_content_extractor import ExtractedFileContent
        from signalvault.sources.file_import_preview import (
            build_file_import_preview,
        )
        from signalvault.sources.models import UploadedFileProfile

        profile = UploadedFileProfile(
            original_filename="test.txt",
            extension=".txt",
            supported=True,
            content_hash="preview_hash_test",
            extracted_text_length=500,
            parse_quality="good",
            file_size_bytes=1024,
        )
        content = ExtractedFileContent(
            text="Content for preview. " * 50,
            title="Preview Test",
            content_hash="preview_hash_test",
            extension=".txt",
            blocks_count=5,
            excerpt="Content for preview...",
            parse_quality="good",
        )

        # Count files before
        archive_dir = tmp_path / "01_Reports" / "SourceArchive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        before_files = list(archive_dir.glob("*.md"))

        preview = build_file_import_preview(profile, content, tmp_path)

        # No new files should be created
        after_files = list(archive_dir.glob("*.md"))
        assert len(after_files) == len(before_files)

        # Preview fields should be populated
        assert preview.preview_id
        assert preview.filename == "test.txt"
        assert preview.extension == ".txt"
        assert preview.content_hash == "preview_hash_test"
        assert preview.title == "Preview Test"
        assert preview.extracted_text_length == 500
        assert preview.parse_quality == "good"
        assert preview.import_eligible is True
        assert len(preview.available_actions) >= 1

    def test_unsupported_preview_disables_confirm(self, tmp_path):
        from signalvault.sources.file_content_extractor import ExtractedFileContent
        from signalvault.sources.file_import_preview import (
            build_file_import_preview,
        )
        from signalvault.sources.models import UploadedFileProfile

        profile = UploadedFileProfile(
            original_filename="test.pdf",
            extension=".pdf",
            supported=False,
            unsupported_reason="PDF not supported",
            parse_quality="minimal",
        )
        content = ExtractedFileContent()

        preview = build_file_import_preview(profile, content, tmp_path)
        assert preview.import_eligible is False
        assert not any(a.value == "confirm_archive" for a in preview.available_actions)
        assert any(a.value == "skip" for a in preview.available_actions)


# ═════════════════════════════════════════════════════════════════════════════
# Confirm execution tests
# ═════════════════════════════════════════════════════════════════════════════


class TestConfirmFileImport:
    """Tests for confirm_file_import()."""

    def test_confirm_writes_to_source_archive(self, tmp_path):
        from signalvault.sources.file_import_preview import (
            confirm_file_import,
        )
        from signalvault.sources.models import ActionEnum, FileImportPreview

        text = "Content to be archived. " * 50
        preview = FileImportPreview(
            filename="research_note.txt",
            extension=".txt",
            file_size_bytes=1024,
            content_hash="confirm_test_hash",
            title="Research Note",
            extracted_text_excerpt=text[:200],
            extracted_text_length=len(text),
            parse_quality="good",
            import_eligible=True,
            recommended_action=ActionEnum.confirm_archive,
            _extracted_text=text,
        )

        result = confirm_file_import(preview, tmp_path)
        assert result["success"] is True
        assert "filename" in result

        # Verify file was created
        archive_dir = tmp_path / "01_Reports" / "SourceArchive"
        files = list(archive_dir.glob("*.md"))
        assert len(files) >= 1
        written = files[0].read_text(encoding="utf-8")
        assert "source_archive" in written
        assert "uploaded_text_file" in written
        assert "research_note.txt" in written
        assert "confirm_test_hash" in written

    def test_confirm_frontmatter_has_required_fields(self, tmp_path):
        from signalvault.sources.file_import_preview import (
            confirm_file_import,
        )
        from signalvault.sources.models import FileImportPreview

        preview = FileImportPreview(
            filename="analysis.md",
            extension=".md",
            file_size_bytes=2048,
            content_hash="fm_test_hash_123",
            title="Market Analysis",
            extracted_text_excerpt="Market analysis excerpt.",
            extracted_text_length=600,
            parse_quality="good",
            import_eligible=True,
            _extracted_text="Full market analysis content. " * 30,
        )

        result = confirm_file_import(preview, tmp_path)
        assert result["success"]

        archive_dir = tmp_path / "01_Reports" / "SourceArchive"
        files = list(archive_dir.glob("*.md"))
        assert len(files) >= 1

        content = files[0].read_text(encoding="utf-8")

        # Check required frontmatter fields
        required_fields = [
            "type:",
            "source_type:",
            "archive_type:",
            "original_filename:",
            "file_extension:",
            "file_size_bytes:",
            "content_hash:",
            "imported_at:",
            "parse_quality:",
            "source_confidence:",
        ]
        for field in required_fields:
            assert field in content, f"Missing frontmatter field: {field}"

    def test_filename_sanitized(self, tmp_path):
        from signalvault.sources.file_import_preview import (
            confirm_file_import,
        )
        from signalvault.sources.models import FileImportPreview

        preview = FileImportPreview(
            filename="evil<script>.md",
            extension=".md",
            file_size_bytes=500,
            content_hash="sanitize_hash",
            title="Safe Title",
            extracted_text_length=300,
            parse_quality="good",
            import_eligible=True,
            _extracted_text="Safe content. " * 30,
        )

        result = confirm_file_import(preview, tmp_path)
        assert result["success"]

        archive_dir = tmp_path / "01_Reports" / "SourceArchive"
        files = list(archive_dir.glob("*.md"))
        assert len(files) >= 1

        filename = files[0].name
        # The sanitized filename should not contain angle brackets
        assert "<" not in filename
        assert ">" not in filename

        # Content should contain the original filename (not as path)
        content = files[0].read_text(encoding="utf-8")
        assert "evil<script>.md" in content  # preserved in frontmatter as metadata


# ═════════════════════════════════════════════════════════════════════════════
# Web route smoke tests
# ═════════════════════════════════════════════════════════════════════════════


class TestFileImportWebRoutes:
    """Smoke tests for file upload web routes.

    Uses the api_client fixture from conftest.py which provides a properly
    configured TestClient with isolated config store and database.
    """

    @pytest.fixture
    def configured_vault(self, tmp_path, monkeypatch):
        """Configure a vault path for testing. Uses short name to avoid MAX_PATH issues.

        Uses env var instead of config_store to avoid fixture ordering issues
        with the autouse _isolate_config_store monkeypatch.
        """
        vault = tmp_path / "v"
        vault.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
        yield vault

    def test_get_upload_page(self, api_client, configured_vault):
        """GET /sources/files/import returns the upload form."""
        response = api_client.get("/sources/files/import")
        assert response.status_code == 200
        html = response.text
        assert "上传文件" in html or "upload" in html.lower()
        assert 'type="file"' in html or "multipart" in html.lower()

    def test_preview_no_file_redirects(self, api_client, configured_vault):
        """POST /sources/files/preview without file returns error."""
        response = api_client.post("/sources/files/preview", data={}, follow_redirects=False)
        assert response.status_code in (302, 303, 422)

    def test_preview_unsupported_extension(self, api_client, configured_vault):
        """POST /sources/files/preview with .xyz returns error."""
        response = api_client.post(
            "/sources/files/preview",
            files={"file": ("test.xyz", b"fake content", "application/octet-stream")},
            follow_redirects=False,
        )
        assert response.status_code in (302, 303)

    def test_preview_supported_txt(self, api_client, configured_vault):
        """POST /sources/files/preview with .txt returns preview page."""
        text = b"Test content for upload preview. " * 50
        response = api_client.post(
            "/sources/files/preview",
            files={"file": ("test.txt", text, "text/plain")},
            follow_redirects=False,
        )
        # Should render preview page
        assert response.status_code == 200
        html = response.text
        assert "预览" in html or "preview" in html.lower()

    def test_preview_supported_md(self, api_client, configured_vault):
        """POST /sources/files/preview with .md returns preview."""
        text = b"# My Research\n\nResearch content here. " * 40
        response = api_client.post(
            "/sources/files/preview",
            files={"file": ("research.md", text, "text/markdown")},
            follow_redirects=False,
        )
        assert response.status_code == 200
        html = response.text
        assert "My Research" in html

    def test_confirm_without_preview_fails(self, api_client, configured_vault):
        """POST /sources/files/confirm without valid preview_id returns error."""
        response = api_client.post(
            "/sources/files/confirm",
            data={"preview_id": "nonexistent_id", "action": "confirm_archive"},
            follow_redirects=False,
        )
        assert response.status_code in (302, 303)

    def test_full_flow_preview_then_confirm(self, api_client, monkeypatch):
        """End-to-end: upload txt → preview → confirm → file written to SourceArchive.

        P2-S.3.5: Uses monkeypatch.setenv directly (not configured_vault) to keep
        the vault path short enough to avoid Windows MAX_PATH issues with long
        test function names + archive subdirectories.
        """
        import tempfile
        td = Path(tempfile.mkdtemp(prefix="v_"))
        try:
            monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(td))
            text = b"Full flow test content for archive. " * 60

            # Step 1: Upload file, get preview
            preview_resp = api_client.post(
                "/sources/files/preview",
                files={"file": ("fullflow.txt", text, "text/plain")},
                follow_redirects=False,
            )
            assert preview_resp.status_code == 200
            html = preview_resp.text
            assert "预览" in html or "preview" in html.lower()

            import re
            m = re.search(r'name="preview_id"\s+value="([^"]+)"', html)
            assert m, "preview_id not found in preview page"
            preview_id = m.group(1)

            # Step 2: Confirm with archive action
            confirm_resp = api_client.post(
                "/sources/files/confirm",
                data={"preview_id": preview_id, "action": "confirm_archive"},
                follow_redirects=False,
            )
            assert confirm_resp.status_code in (302, 303)
            redirect_url = confirm_resp.headers.get("location", "")
            assert "error" not in redirect_url, \
                f"Confirm redirected with error: {redirect_url}"

            # Step 3: Verify file was written to SourceArchive
            archive_dir = td / "01_Reports" / "SourceArchive"
            md_files = list(archive_dir.glob("*.md"))
            assert len(md_files) >= 1, "No .md file created in SourceArchive"

            # Step 4: Verify archived content
            content = md_files[0].read_text(encoding="utf-8")
            assert "Full flow test content" in content
        finally:
            import shutil
            shutil.rmtree(td, ignore_errors=True)

    def test_skip_action_no_vault_write(self, api_client, configured_vault):
        """Skip action should not write to vault."""
        vault = configured_vault
        text = b"Skip test content for the vault write check. " * 30
        preview_resp = api_client.post(
            "/sources/files/preview",
            files={"file": ("skiptest.txt", text, "text/plain")},
            follow_redirects=False,
        )
        assert preview_resp.status_code == 200

        import re
        m = re.search(r'name="preview_id"\s+value="([^"]+)"', preview_resp.text)
        assert m
        preview_id = m.group(1)

        # Count files before skip
        archive_dir = vault / "01_Reports" / "SourceArchive"
        before = len(list(archive_dir.glob("*.md"))) if archive_dir.exists() else 0

        # Skip
        confirm_resp = api_client.post(
            "/sources/files/confirm",
            data={"preview_id": preview_id, "action": "skip"},
            follow_redirects=False,
        )
        assert confirm_resp.status_code in (302, 303)

        # No new files
        after = len(list(archive_dir.glob("*.md"))) if archive_dir.exists() else 0
        assert after == before


# ═════════════════════════════════════════════════════════════════════════════
# Regression: existing source import tests pass
# ═════════════════════════════════════════════════════════════════════════════


class TestExistingSourceImportsUnaffected:
    """Ensure existing source import functionality is not broken."""

    def test_models_import_unchanged(self):
        """All existing model classes are still importable."""
        from signalvault.sources.models import (
            ConflictInfo,
            ImportPreview,
        )
        # Instantiation smoke test
        c = ConflictInfo(conflict_type="test", severity="info", description="test")
        assert c.conflict_type == "test"

        p = ImportPreview(url="https://example.com")
        assert p.url == "https://example.com"

    def test_exports_unchanged(self):
        """Existing exports in sources.__init__ are still accessible."""
        from signalvault.sources import (
            TRACKABLE_ADAPTER_ALLOWLIST,
            ActionEnum,
            ConflictDetector,
            ConflictInfo,
            ImportPreview,
            SourceKind,
            SourceProfile,
            SuggestedAction,
            TrackingEligibility,
            build_import_preview,
            execute_import_action,
            profile_source_url,
            select_adapter_for_url,
        )
        # These should all be truthy
        assert ActionEnum
        assert ConflictDetector
        assert ConflictInfo
        assert ImportPreview
        assert SourceKind
        assert SourceProfile
        assert SuggestedAction
        assert TrackingEligibility
        assert build_import_preview
        assert execute_import_action
        assert profile_source_url
        assert select_adapter_for_url
        assert TRACKABLE_ADAPTER_ALLOWLIST

    def test_new_exports_available(self):
        """New P2-S.3.3 exports are accessible."""
        from signalvault.sources import (
            ALLOWED_TEXT_EXTENSIONS,
            MAX_UPLOAD_BYTES,
            ConflictDetector,
            ExtractedFileContent,
            FileArchiveType,
            FileImportEligibility,
            FileImportPreview,
            UploadedFileProfile,
            build_file_import_preview,
            confirm_file_import,
            evaluate_file_import_eligibility,
            extract_text_from_uploaded_file,
            profile_uploaded_file,
        )
        assert {".md", ".txt", ".html", ".htm"} == ALLOWED_TEXT_EXTENSIONS
        assert MAX_UPLOAD_BYTES == 5 * 1024 * 1024
        assert FileArchiveType
        assert FileImportEligibility
        assert FileImportPreview
        assert UploadedFileProfile
        assert ExtractedFileContent
        assert build_file_import_preview
        assert confirm_file_import
        assert ConflictDetector
        assert evaluate_file_import_eligibility
        assert extract_text_from_uploaded_file
        assert profile_uploaded_file
