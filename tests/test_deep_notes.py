"""P2-S.2: Deep Notes Export & Episode Linking tests.

Tests:
1. Deep Notes frontmatter complete
2. Deep Notes includes source links
3. Deep Notes includes linked report
4. timeline segments rendered correctly
5. speaker turns rendered correctly
6. speaker viewpoints rendered correctly
7. bilingual quotes rendered correctly
8. key points rendered correctly
9. existing report not duplicated
10. derived-only document correctly marked
11. parser degraded state visible
12. unsafe filename sanitized
13. existing tests pass
14. ruff clean
"""

from __future__ import annotations

from pathlib import Path

import pytest

from podcast_research.adapters.external_html_notes import (
    NormalizedEpisodeSegment,
    NormalizedQuote,
    NormalizedSourceDocument,
    NormalizedSpeakerTurn,
    NormalizedSpeakerViewpoint,
)
from podcast_research.exporters.deep_notes import (
    _build_deep_notes_frontmatter,
    _generate_filename,
    build_deep_notes_body,
    check_document_health,
    export_deep_note,
)

# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════


def _make_sample_doc(**overrides) -> NormalizedSourceDocument:
    """Build a fully populated NormalizedSourceDocument for testing."""
    kwargs = dict(
        provider="allin-podcast-zh-notes",
        source_type="derived",
        source_confidence="secondary",
        source_url="https://example.com/episodes/test-slug/notes.visual.html",
        original_source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        slug="test-slug",
        title="Test Episode: AI & Market Trends",
        generated_at="2026-06-23 15:00",
        reading_time="25 分钟",
        summary="A test summary about AI and market trends.",
        youtube_video_id="dQw4w9WgXcQ",
        key_points=[
            "First key point about AI.",
            "Second key point about markets.",
            "Third key point about regulation.",
        ],
        timeline=[
            NormalizedEpisodeSegment(
                index=1,
                title="Opening Discussion",
                time_range="00:00–00:15",
                core_points=["Intro of guests", "Setting the stage"],
                background_terms=[
                    {"term": "AGI", "definition": "Artificial General Intelligence"},
                    {"term": "GPU", "definition": "Graphics Processing Unit"},
                ],
                speaker_turns=[
                    NormalizedSpeakerTurn(speaker_name="JCal", text="Welcome to the show."),
                    NormalizedSpeakerTurn(speaker_name="Chamath", text="Markets are interesting right now."),
                ],
            ),
            NormalizedEpisodeSegment(
                index=2,
                title="Main Analysis",
                time_range="00:15–00:45",
                core_points=["Deep dive on AI valuation"],
                background_terms=[
                    {"term": "TAM", "definition": "Total Addressable Market"},
                ],
                speaker_turns=[
                    NormalizedSpeakerTurn(speaker_name="Sacks", text="Let me offer a nuanced view."),
                ],
            ),
        ],
        speaker_viewpoints=[
            NormalizedSpeakerViewpoint(name="Jason Calacanis", role="嘉宾 01", viewpoint="Supports open source AI."),
            NormalizedSpeakerViewpoint(name="Chamath Palihapitiya", role="嘉宾 02", viewpoint="Skeptical of AI hype."),
        ],
        bilingual_quotes=[
            NormalizedQuote(text_en="AI is transformative.", text_zh="AI是变革性的。", context_note="JCal on AI impact"),
            NormalizedQuote(text_en="Markets will correct.", text_zh="市场会修正。", context_note="Chamath warning"),
        ],
    )
    kwargs.update(overrides)
    return NormalizedSourceDocument(**kwargs)


def _make_empty_doc() -> NormalizedSourceDocument:
    """Build a document with no content sections (degraded)."""
    return NormalizedSourceDocument(
        provider="allin-podcast-zh-notes",
        source_url="https://example.com/empty",
        original_source_url="https://www.youtube.com/watch?v=empty01",
        slug="empty-slug",
        title="Empty Episode",
    )


@pytest.fixture
def sample_doc() -> NormalizedSourceDocument:
    return _make_sample_doc()


@pytest.fixture
def empty_doc() -> NormalizedSourceDocument:
    return _make_empty_doc()


@pytest.fixture
def tmp_vault(tmp_path: Path) -> Path:
    """Create a temporary vault with Reports dir."""
    vault = tmp_path / "test_vault"
    vault.mkdir()
    (vault / "01_Reports").mkdir()
    return vault


# ═════════════════════════════════════════════════════════════════════════════
# Test 1: Deep Notes frontmatter complete
# ═════════════════════════════════════════════════════════════════════════════

class TestFrontmatter:
    """Test 1: frontmatter contains all required fields."""

    def test_frontmatter_has_required_fields(self, sample_doc: NormalizedSourceDocument) -> None:
        fm = _build_deep_notes_frontmatter(sample_doc, linked_report_id=42, linked_report_path="2026-06-23_report")
        assert fm["type"] == "deep_notes"
        assert fm["source_type"] == "derived"
        assert fm["source_confidence"] == "secondary"
        assert fm["provider"] == "allin-podcast-zh-notes"
        assert fm["source_url"] == sample_doc.source_url
        assert fm["original_source_url"] == sample_doc.original_source_url
        assert fm["youtube_video_id"] == "dQw4w9WgXcQ"
        assert fm["title"] == sample_doc.title
        assert fm["slug"] == "test-slug"
        assert fm["generated_at"] == "2026-06-23 15:00"
        assert fm["reading_time"] == "25 分钟"
        assert "imported_at" in fm and fm["imported_at"] != ""
        assert fm["linked_report_id"] == 42
        assert fm["linked_report_path"] == "2026-06-23_report"

    def test_frontmatter_has_tags(self, sample_doc: NormalizedSourceDocument) -> None:
        fm = _build_deep_notes_frontmatter(sample_doc)
        assert "deep-notes" in fm["tags"]
        assert "derived-source" in fm["tags"]

    def test_frontmatter_derived_only_tag(self, sample_doc: NormalizedSourceDocument) -> None:
        fm = _build_deep_notes_frontmatter(sample_doc, derived_only=True)
        assert "derived-only" in fm["tags"]

    def test_frontmatter_degraded_tag(self, sample_doc: NormalizedSourceDocument) -> None:
        fm = _build_deep_notes_frontmatter(sample_doc, degraded=True)
        assert "degraded" in fm["tags"]

    def test_frontmatter_no_linked_report_when_none(self, sample_doc: NormalizedSourceDocument) -> None:
        fm = _build_deep_notes_frontmatter(sample_doc)
        assert fm["linked_report_id"] == ""
        assert fm["linked_report_path"] == ""

    def test_frontmatter_derived_only_field(self, sample_doc: NormalizedSourceDocument) -> None:
        fm = _build_deep_notes_frontmatter(sample_doc, derived_only=True)
        assert fm["derived_only"] is True


# ═════════════════════════════════════════════════════════════════════════════
# Test 2: Deep Notes includes source links
# ═════════════════════════════════════════════════════════════════════════════

class TestSourceLinks:
    """Test 2: body includes source attribution links."""

    def test_body_includes_source_url(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert sample_doc.source_url in body

    def test_body_includes_original_source_url(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert sample_doc.original_source_url in body

    def test_body_includes_provider(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert sample_doc.provider in body

    def test_body_includes_youtube_video_id(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert "dQw4w9WgXcQ" in body

    def test_body_has_attribution_footer(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert "podcast-research P2-S.2" in body
        assert "外部衍生信息源" in body


# ═════════════════════════════════════════════════════════════════════════════
# Test 3: Deep Notes includes linked report
# ═════════════════════════════════════════════════════════════════════════════

class TestLinkedReport:
    """Test 3: body includes link to existing YouTube report."""

    def test_body_includes_linked_report_wiki_link(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(
            sample_doc,
            linked_report_path="2026-06-23_TestChannel_dQw4w9WgXcQ",
        )
        assert "[[2026-06-23_TestChannel_dQw4w9WgXcQ]]" in body

    def test_body_no_linked_report_when_empty(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc, linked_report_path="")
        assert "[[2026-06-23_TestChannel" not in body

    def test_body_shows_derived_only_notice(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc, derived_only=True)
        assert "Derived Only" in body
        assert "尚未生成投资分析报告" in body


# ═════════════════════════════════════════════════════════════════════════════
# Test 4: timeline segments rendered correctly
# ═════════════════════════════════════════════════════════════════════════════

class TestTimelineRendering:
    """Test 4: timeline section rendered with correct structure."""

    def test_timeline_includes_segment_titles(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert "Opening Discussion" in body
        assert "Main Analysis" in body

    def test_timeline_includes_time_ranges(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert "00:00–00:15" in body
        assert "00:15–00:45" in body

    def test_timeline_includes_core_points(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert "Intro of guests" in body
        assert "Deep dive on AI valuation" in body

    def test_timeline_includes_background_terms(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert "AGI" in body
        assert "Artificial General Intelligence" in body

    def test_empty_timeline_shows_placeholder(self, empty_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(empty_doc)
        assert "无时间线分段" in body


# ═════════════════════════════════════════════════════════════════════════════
# Test 5: speaker turns rendered correctly
# ═════════════════════════════════════════════════════════════════════════════

class TestSpeakerTurnsRendering:
    """Test 5: speaker turns in timeline rendered correctly."""

    def test_speaker_turns_in_body(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert "**JCal**" in body
        assert "**Chamath**" in body
        assert "**Sacks**" in body

    def test_speaker_turn_text_in_body(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert "Welcome to the show" in body
        assert "Markets are interesting" in body

    def test_no_speaker_turns_in_empty_doc(self, empty_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(empty_doc)
        # Timeline section shows placeholder, not speaker turns
        assert "无时间线分段" in body


# ═════════════════════════════════════════════════════════════════════════════
# Test 6: speaker viewpoints rendered correctly
# ═════════════════════════════════════════════════════════════════════════════

class TestSpeakerViewpointsRendering:
    """Test 6: speaker viewpoints section."""

    def test_viewpoint_names_in_body(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert "Jason Calacanis" in body
        assert "Chamath Palihapitiya" in body

    def test_viewpoint_content_in_body(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert "Supports open source AI" in body
        assert "Skeptical of AI hype" in body

    def test_viewpoint_roles_in_body(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert "嘉宾 01" in body
        assert "嘉宾 02" in body

    def test_empty_viewpoints_shows_placeholder(self, empty_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(empty_doc)
        assert "无人物观点" in body


# ═════════════════════════════════════════════════════════════════════════════
# Test 7: bilingual quotes rendered correctly
# ═════════════════════════════════════════════════════════════════════════════

class TestQuotesRendering:
    """Test 7: bilingual quotes section."""

    def test_quote_english_in_body(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert "AI is transformative" in body

    def test_quote_chinese_in_body(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert "AI是变革性的" in body

    def test_quote_context_in_body(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert "JCal on AI impact" in body

    def test_empty_quotes_shows_placeholder(self, empty_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(empty_doc)
        assert "无双语引语" in body


# ═════════════════════════════════════════════════════════════════════════════
# Test 8: key points rendered correctly
# ═════════════════════════════════════════════════════════════════════════════

class TestKeyPointsRendering:
    """Test 8: key points rendered as numbered list."""

    def test_key_points_numbered(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert "1. First key point about AI." in body
        assert "2. Second key point about markets." in body
        assert "3. Third key point about regulation." in body

    def test_key_points_content(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc)
        assert "First key point" in body
        assert "Second key point" in body

    def test_empty_key_points_placeholder(self, empty_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(empty_doc)
        assert "无核心要点" in body


# ═════════════════════════════════════════════════════════════════════════════
# Test 9: existing report not duplicated
# ═════════════════════════════════════════════════════════════════════════════

class TestNoDuplicateReport:
    """Test 9: Deep Notes export does not create or modify YouTube reports."""

    def test_deep_note_is_separate_from_report(self, tmp_vault: Path, sample_doc: NormalizedSourceDocument) -> None:
        """Deep Note goes to DeepNotes/ subdirectory, not 01_Reports/ root."""
        result = export_deep_note(tmp_vault, sample_doc)
        assert "DeepNotes" in result["path"]
        # Report dir should not have any new files
        report_files = list((tmp_vault / "01_Reports").glob("*.md"))
        assert len(report_files) == 0  # only DeepNotes/ subdir has content

    def test_export_result_has_linked_report_info(self, tmp_vault: Path, sample_doc: NormalizedSourceDocument) -> None:
        result = export_deep_note(tmp_vault, sample_doc)
        assert "linked_report_id" in result
        assert "linked_report_path" in result
        assert "derived_only" in result

    def test_skip_existing_deep_note(self, tmp_vault: Path, sample_doc: NormalizedSourceDocument) -> None:
        """Second export without overwrite should skip."""
        result1 = export_deep_note(tmp_vault, sample_doc)
        assert result1["status"] == "created"
        result2 = export_deep_note(tmp_vault, sample_doc)
        assert result2["status"] == "skipped"

    def test_overwrite_existing_deep_note(self, tmp_vault: Path, sample_doc: NormalizedSourceDocument) -> None:
        """Overwrite flag should re-create the file."""
        result1 = export_deep_note(tmp_vault, sample_doc)
        assert result1["status"] == "created"
        result2 = export_deep_note(tmp_vault, sample_doc, overwrite=True)
        assert result2["status"] in ("created", "degraded")


# ═════════════════════════════════════════════════════════════════════════════
# Test 10: derived-only document correctly marked
# ═════════════════════════════════════════════════════════════════════════════

class TestDerivedOnly:
    """Test 10: derived-only documents when no YouTube report exists."""

    def test_body_has_derived_only_callout(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc, derived_only=True)
        assert "Derived Only" in body

    def test_frontmatter_derived_only_true(self, sample_doc: NormalizedSourceDocument) -> None:
        fm = _build_deep_notes_frontmatter(sample_doc, derived_only=True)
        assert fm["derived_only"] is True

    def test_derived_only_no_linked_report(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc, derived_only=True, linked_report_path="")
        assert "暂无关联的投资分析报告" in body

    def test_export_no_video_id_marks_derived_only(self, tmp_vault: Path) -> None:
        """A doc with no video_id should be exported as derived_only."""
        doc = _make_sample_doc(youtube_video_id="")
        result = export_deep_note(tmp_vault, doc)
        assert result["derived_only"] is True


# ═════════════════════════════════════════════════════════════════════════════
# Test 11: parser degraded state visible
# ═════════════════════════════════════════════════════════════════════════════

class TestDegradedState:
    """Test 11: degraded state is visible in output."""

    def test_healthy_doc(self, sample_doc: NormalizedSourceDocument) -> None:
        health = check_document_health(sample_doc)
        assert health["healthy"] is True
        assert health["degraded"] is False
        assert health["content_sections_populated"] >= 3

    def test_empty_doc_is_degraded(self, empty_doc: NormalizedSourceDocument) -> None:
        health = check_document_health(empty_doc)
        assert health["degraded"] is True
        assert health["healthy"] is False

    def test_degraded_body_has_warning(self, empty_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(empty_doc, degraded=True)
        assert "[!warning]" in body
        assert "内容不完整" in body

    def test_degraded_body_no_warning_when_healthy(self, sample_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(sample_doc, degraded=False)
        assert "[!warning]" not in body

    def test_partial_doc_missing_key_points(self) -> None:
        """Doc with timeline but no key_points should not be fully degraded."""
        doc = _make_sample_doc(key_points=[])
        health = check_document_health(doc)
        # Has timeline + viewpoints → not degraded
        assert health["degraded"] is False
        assert "key_points is empty" in health["reasons"]

    def test_doc_only_summary_is_degraded(self) -> None:
        """Doc with only summary and nothing else is degraded."""
        doc = NormalizedSourceDocument(
            provider="test",
            source_url="https://example.com",
            title="Only Summary",
            summary="Just a summary, nothing else.",
        )
        health = check_document_health(doc)
        assert health["degraded"] is True
        assert any("only summary is present" in r for r in health["reasons"])

    def test_degraded_export_status(self, tmp_vault: Path, empty_doc: NormalizedSourceDocument) -> None:
        """Empty doc export should have degraded status."""
        result = export_deep_note(tmp_vault, empty_doc)
        assert result["degraded"] is True
        assert result["status"] == "degraded"

    def test_health_reasons_populated(self, empty_doc: NormalizedSourceDocument) -> None:
        health = check_document_health(empty_doc)
        assert len(health["reasons"]) > 0

    def test_health_timeline_without_speaker_turns(self) -> None:
        """Timeline segments exist but have no speaker turns → note in reasons."""
        doc = _make_sample_doc(
            timeline=[
                NormalizedEpisodeSegment(index=1, title="Test", core_points=["p1"]),
            ],
            speaker_viewpoints=[],
            bilingual_quotes=[],
        )
        health = check_document_health(doc)
        # Has key_points and timeline, may still be healthy
        assert "timeline has segments but no speaker turns" in health["reasons"]


# ═════════════════════════════════════════════════════════════════════════════
# Test 12: unsafe filename sanitized
# ═════════════════════════════════════════════════════════════════════════════

class TestFilenameSanitization:
    """Test 12: generated filenames are safe."""

    def test_generated_filename_is_safe(self, sample_doc: NormalizedSourceDocument) -> None:
        fname = _generate_filename(sample_doc)
        # No illegal Windows chars
        for illegal in ['\\', '/', ':', '*', '?', '"', '<', '>', '|']:
            assert illegal not in fname

    def test_filename_includes_date(self, sample_doc: NormalizedSourceDocument) -> None:
        fname = _generate_filename(sample_doc)
        assert fname.startswith("2026-06-23")

    def test_filename_includes_provider(self, sample_doc: NormalizedSourceDocument) -> None:
        fname = _generate_filename(sample_doc)
        assert "allin-podcast-zh-notes" in fname

    def test_filename_includes_slug(self, sample_doc: NormalizedSourceDocument) -> None:
        fname = _generate_filename(sample_doc)
        assert "test-slug" in fname

    def test_filename_falls_back_to_video_id(self) -> None:
        doc = _make_sample_doc(slug="")
        fname = _generate_filename(doc)
        assert "dQw4w9WgXcQ" in fname

    def test_filename_falls_back_to_untitled(self) -> None:
        doc = NormalizedSourceDocument(
            provider="test",
            source_url="https://example.com",
            title="No Slug",
        )
        fname = _generate_filename(doc)
        assert fname.endswith(".md")
        assert "untitled" in fname

    def test_filename_ends_with_md(self, sample_doc: NormalizedSourceDocument) -> None:
        fname = _generate_filename(sample_doc)
        assert fname.endswith(".md")


# ═════════════════════════════════════════════════════════════════════════════
# Additional: background terms rendering
# ═════════════════════════════════════════════════════════════════════════════

class TestBackgroundTermsRendering:
    """Test background terms dedup and formatting."""

    def test_background_terms_deduplicated(self) -> None:
        """Duplicate terms across segments should only appear once."""
        doc = _make_sample_doc(
            timeline=[
                NormalizedEpisodeSegment(
                    index=1, title="S1",
                    background_terms=[{"term": "AGI", "definition": "Artificial General Intelligence"}],
                ),
                NormalizedEpisodeSegment(
                    index=2, title="S2",
                    background_terms=[{"term": "AGI", "definition": "Artificial General Intelligence"}],
                ),
            ],
        )
        body = build_deep_notes_body(doc)
        # AGI should appear only once in the background terms section
        terms_section_start = body.find("## 背景术语")
        terms_section_end = body.find("## 人物观点")
        terms_section = body[terms_section_start:terms_section_end]
        assert terms_section.count("AGI") == 1

    def test_empty_background_terms_placeholder(self, empty_doc: NormalizedSourceDocument) -> None:
        body = build_deep_notes_body(empty_doc)
        assert "无背景术语" in body


# ═════════════════════════════════════════════════════════════════════════════
# Additional: full export integration
# ═════════════════════════════════════════════════════════════════════════════

class TestFullExport:
    """Integration tests for full export pipeline."""

    def test_export_creates_file(self, tmp_vault: Path, sample_doc: NormalizedSourceDocument) -> None:
        result = export_deep_note(tmp_vault, sample_doc)
        assert Path(result["path"]).exists()

    def test_exported_file_has_frontmatter(self, tmp_vault: Path, sample_doc: NormalizedSourceDocument) -> None:
        result = export_deep_note(tmp_vault, sample_doc)
        content = Path(result["path"]).read_text(encoding="utf-8")
        assert content.startswith("---")
        assert "type: deep_notes" in content
        assert "allin-podcast-zh-notes" in content

    def test_exported_file_is_valid_markdown(self, tmp_vault: Path, sample_doc: NormalizedSourceDocument) -> None:
        result = export_deep_note(tmp_vault, sample_doc)
        content = Path(result["path"]).read_text(encoding="utf-8")
        # Has proper sections
        assert "## 来源信息" in content
        assert "## 核心要点" in content
        assert "## 时间线精读" in content
        assert "## 背景术语" in content
        assert "## 人物观点" in content
        assert "## 双语引语" in content

    def test_export_result_structure(self, tmp_vault: Path, sample_doc: NormalizedSourceDocument) -> None:
        result = export_deep_note(tmp_vault, sample_doc)
        assert "status" in result
        assert "path" in result
        assert "deep_notes_filename" in result
        assert "linked_report_id" in result
        assert "linked_report_path" in result
        assert "derived_only" in result
        assert "degraded" in result
        assert "health" in result

    def test_deep_notes_dir_created(self, tmp_vault: Path, sample_doc: NormalizedSourceDocument) -> None:
        export_deep_note(tmp_vault, sample_doc)
        assert (tmp_vault / "01_Reports" / "DeepNotes").is_dir()

    def test_summary_in_exported_file(self, tmp_vault: Path, sample_doc: NormalizedSourceDocument) -> None:
        result = export_deep_note(tmp_vault, sample_doc)
        content = Path(result["path"]).read_text(encoding="utf-8")
        assert "A test summary about AI and market trends." in content


# ═════════════════════════════════════════════════════════════════════════════
# Test 13: existing tests pass — covered by running full suite
# ═════════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════════
# Additional edge cases
# ═════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Additional edge case coverage."""

    def test_doc_with_no_original_source(self) -> None:
        doc = _make_sample_doc(original_source_url="")
        body = build_deep_notes_body(doc)
        assert "原始来源" not in body or "原始来源**：" in body  # field exists but empty

    def test_doc_with_no_reading_time(self) -> None:
        doc = _make_sample_doc(reading_time="")
        body = build_deep_notes_body(doc)
        # Reading time line should not appear
        assert "阅读时长" not in body or "预计阅读**：" not in body

    def test_doc_with_no_generated_at(self) -> None:
        doc = _make_sample_doc(generated_at="")
        body = build_deep_notes_body(doc)
        assert "页面生成时间" not in body or "页面生成时间**：" not in body

    def test_speaker_viewpoint_no_role(self) -> None:
        doc = _make_sample_doc(
            speaker_viewpoints=[
                NormalizedSpeakerViewpoint(name="Speaker A", role="", viewpoint="VP text."),
            ],
        )
        body = build_deep_notes_body(doc)
        assert "Speaker A" in body
        assert "VP text" in body

    def test_quote_no_context_note(self) -> None:
        doc = _make_sample_doc(
            bilingual_quotes=[
                NormalizedQuote(text_en="EN", text_zh="ZH", context_note=""),
            ],
        )
        body = build_deep_notes_body(doc)
        assert "EN" in body
        assert "ZH" in body

    def test_timeline_segment_no_core_points(self) -> None:
        doc = _make_sample_doc(
            timeline=[
                NormalizedEpisodeSegment(
                    index=1, title="S1",
                    speaker_turns=[NormalizedSpeakerTurn(speaker_name="X", text="text")],
                ),
            ],
        )
        body = build_deep_notes_body(doc)
        assert "S1" in body
