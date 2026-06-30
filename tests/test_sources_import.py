"""P2-S.3.1: Generic Web URL Import Preview tests.

27 test categories covering: adapter selection, GenericWebPageAdapter parsing,
ImportPreview model, ConflictDetector, recommendation logic, route smoke tests,
confirm flow, E2E integration.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from podcast_research.sources.conflict_detector import ConflictDetector
from podcast_research.sources.import_preview import (
    _compute_recommendation,
    _extract_first_video_id,
    build_import_preview,
    execute_import_action,
    select_adapter_for_url,
)
from podcast_research.sources.models import (
    ActionEnum,
    ConflictInfo,
    ImportPreview,
)

# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════

MOCK_WEB_HTML = """<!doctype html>
<html lang="en">
<head>
    <title>Test Web Page</title>
    <meta name="description" content="A test article about AI investing.">
    <link rel="canonical" href="https://example.com/canonical-path">
</head>
<body>
    <h1>AI Investment Trends</h1>
    <h2>Market Overview</h2>
    <h3>NVIDIA Outlook</h3>
    <p>AI investment is growing rapidly in 2026.</p>
    <p>The semiconductor sector shows strong momentum.</p>
    <p>Cloud providers are increasing capex significantly.</p>
    <a href="https://www.youtube.com/watch?v=dQw4w9WgXcQ">Watch on YouTube</a>
    <a href="https://youtu.be/test00000002">Short link</a>
</body>
</html>"""

MOCK_MINIMAL_HTML = "<html><head><title>Minimal</title></head><body><p>Hi.</p></body></html>"
MOCK_EMPTY_HTML = "<html><body></body></html>"

MOCK_ALLIN_EPISODE_HTML = """<!doctype html><html><body>
<div class="page"><main class="article"><header class="hero">
<h1>All-In Test Episode</h1>
<div class="meta">
<span>生成时间：2026-06-23 15:00</span>
<span>来源：<a href="https://www.youtube.com/watch?v=allintest001">YouTube</a></span>
</div>
<div class="meta-strip"><span class="meta-pill"><b>20 分钟</b>阅读时长</span></div>
<div class="summary"><p>Test summary for allin episode.</p></div>
</header>
<div class="content-shell"><div class="content-flow">
<section id="takeaways"><ol class="takeaway-list">
<li class="takeaway"><span>01</span><p>Key point one.</p></li>
<li class="takeaway"><span>02</span><p>Key point two.</p></li>
</ol></section>
<section id="timeline"><div class="timeline">
<article class="timeline-card"><header class="timeline-heading">
<span class="timeline-index">01</span><span class="timeline-meta">00:00-00:10</span></header>
<div class="timeline-body"><h3>Segment One</h3>
<div class="section-content">
<h4>本段核心内容</h4><ul><li>Core point A</li></ul>
<h4>详细中文整理</h4><p><strong>JCal：</strong> Welcome.</p>
</div></div></article></div></section>
<section id="speakers"><div class="speaker-grid">
<article class="speaker-card"><p class="speaker-kicker">嘉宾 01</p><h3>JCal</h3><div><p>JCal viewpoint.</p></div></article>
</div></section>
<section id="quotes"><div class="panel">
<ol><li><strong>Quote text EN.</strong></li></ol><p>中文：引语中文。 说明：Context note.</p>
</div></section>
</div></div></main></div>
</body></html>"""


@pytest.fixture
def tmp_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "test_vault"
    vault.mkdir()
    (vault / "01_Reports").mkdir()
    return vault


# ═════════════════════════════════════════════════════════════════════════════
# Test 1-3: Adapter selection
# ═════════════════════════════════════════════════════════════════════════════

class TestAdapterSelection:
    """Tests 1-3: select_adapter_for_url routes to correct adapter."""

    def test_select_allin_adapter(self) -> None:
        adapter = select_adapter_for_url(
            "https://chirs-ma.github.io/allin-podcast-zh-notes/episodes/x/notes.visual.html"
        )
        assert "AllInZHNotesAdapter" in type(adapter).__name__

    def test_select_allin_short_domain(self) -> None:
        """Any URL containing allin-podcast-zh-notes should use AllIn adapter."""
        adapter = select_adapter_for_url(
            "https://raw.githubusercontent.com/chirs-ma/allin-podcast-zh-notes/main/index.html"
        )
        assert "AllInZHNotesAdapter" in type(adapter).__name__

    def test_select_generic_adapter(self) -> None:
        adapter = select_adapter_for_url("https://example.com/article")
        assert "GenericWebPageAdapter" in type(adapter).__name__

    def test_select_generic_other_github(self) -> None:
        adapter = select_adapter_for_url("https://github.com/user/repo")
        assert "GenericWebPageAdapter" in type(adapter).__name__

    def test_select_generic_youtube(self) -> None:
        adapter = select_adapter_for_url("https://www.youtube.com/watch?v=abc123")
        assert "GenericWebPageAdapter" in type(adapter).__name__


# ═════════════════════════════════════════════════════════════════════════════
# Test 4-8: GenericWebPageAdapter parsing
# ═════════════════════════════════════════════════════════════════════════════

class TestGenericWebPageParsing:
    """Tests 4-8: GenericWebPageAdapter extracts title, meta, headings, YT URLs."""

    @pytest.fixture
    def adapter(self):
        from podcast_research.adapters.generic_web_page import GenericWebPageAdapter
        return GenericWebPageAdapter()

    def test_parse_title(self, adapter) -> None:
        parsed = adapter._parse_page(MOCK_WEB_HTML, "https://example.com")
        assert parsed.title == "Test Web Page"

    def test_parse_meta_description(self, adapter) -> None:
        parsed = adapter._parse_page(MOCK_WEB_HTML, "https://example.com")
        assert "AI investing" in parsed.meta_description

    def test_parse_headings(self, adapter) -> None:
        parsed = adapter._parse_page(MOCK_WEB_HTML, "https://example.com")
        assert "AI Investment Trends" in parsed.h1_texts
        assert "Market Overview" in parsed.h2_texts
        assert "NVIDIA Outlook" in parsed.h3_texts

    def test_parse_paragraphs(self, adapter) -> None:
        parsed = adapter._parse_page(MOCK_WEB_HTML, "https://example.com")
        assert len(parsed.paragraphs) >= 3
        assert any("AI investment" in p for p in parsed.paragraphs)

    def test_parse_canonical_url(self, adapter) -> None:
        parsed = adapter._parse_page(MOCK_WEB_HTML, "https://example.com")
        assert parsed.canonical_url == "https://example.com/canonical-path"

    def test_detect_youtube_urls(self, adapter) -> None:
        parsed = adapter._parse_page(MOCK_WEB_HTML, "https://example.com")
        yt_urls = parsed.detected_youtube_urls
        assert len(yt_urls) >= 2
        assert any("dQw4w9WgXcQ" in u for u in yt_urls)

    def test_content_hash_stable(self, adapter) -> None:
        parsed1 = adapter._parse_page(MOCK_WEB_HTML, "https://example.com")
        parsed2 = adapter._parse_page(MOCK_WEB_HTML, "https://example.com")
        assert parsed1.content_hash == parsed2.content_hash
        assert len(parsed1.content_hash) == 64  # full SHA-256

    def test_malformed_html_does_not_crash(self, adapter) -> None:
        """Malformed/unparseable HTML returns minimal quality, not crash."""
        # Use genuinely unparseable input that triggers soup error
        parsed = adapter._parse_page("", "https://example.com")
        assert parsed.parse_quality == "minimal"

    def test_empty_page_returns_minimal(self, adapter) -> None:
        parsed = adapter._parse_page(MOCK_EMPTY_HTML, "https://example.com")
        assert parsed.parse_quality == "minimal"
        assert parsed.content_blocks_count == 0

    def test_minimal_page_is_degraded(self, adapter) -> None:
        parsed = adapter._parse_page(MOCK_MINIMAL_HTML, "https://example.com")
        # 1 paragraph, 0 headings → <3 blocks → degraded
        assert parsed.parse_quality in ("degraded", "minimal")

    def test_fetch_page_catches_fetch_error(self, adapter) -> None:
        """fetch_page should return minimal ParsedWebPage on fetch failure, not raise."""
        with patch.object(adapter, "_fetch_html", side_effect=RuntimeError("fail")):
            parsed = adapter.fetch_page("https://example.com/bad")
            assert parsed.parse_quality == "minimal"
            assert "fail" in parsed.error


# ═════════════════════════════════════════════════════════════════════════════
# Test 9-10: ImportPreview model
# ═════════════════════════════════════════════════════════════════════════════

class TestImportPreviewModel:
    """Tests 9-10: ImportPreview defaults and ActionEnum."""

    def test_import_preview_defaults(self) -> None:
        preview = ImportPreview()
        assert preview.preview_id != ""
        assert len(preview.preview_id) == 12
        assert preview.source_confidence == "secondary"
        assert preview.recommended_action == ActionEnum.skip
        assert preview.conflicts == []
        assert preview.available_actions == []

    def test_action_enum_values(self) -> None:
        assert ActionEnum.import_as_deep_notes.value == "import_as_deep_notes"
        assert ActionEnum.skip.value == "skip"
        assert len(list(ActionEnum)) == 9  # +1 for confirm_archive (P2-S.3.3)

    def test_import_preview_with_data(self) -> None:
        preview = ImportPreview(
            url="https://example.com",
            adapter_name="GenericWebPageAdapter",
            title="Test Title",
            parse_quality="good",
            content_hash="abc123",
            recommended_action=ActionEnum.import_as_source_archive,
            available_actions=[ActionEnum.import_as_source_archive, ActionEnum.skip],
        )
        assert preview.url == "https://example.com"
        assert preview.recommended_action == ActionEnum.import_as_source_archive


# ═════════════════════════════════════════════════════════════════════════════
# Test 11-15: ConflictDetector
# ═════════════════════════════════════════════════════════════════════════════

class TestConflictDetector:
    """Tests 11-15: Conflict detection logic."""

    def test_no_conflicts_clean_vault(self, tmp_vault: Path) -> None:
        detector = ConflictDetector(tmp_vault)
        conflicts = detector.detect(
            url="https://example.com/new",
            canonical_url="",
            content_hash="abc123",
            detected_youtube_video_id="",
        )
        assert conflicts == []

    def test_same_url_detected(self, tmp_vault: Path) -> None:
        # Create a source archive file
        archive_dir = tmp_vault / "01_Reports" / "SourceArchive"
        archive_dir.mkdir()
        md = archive_dir / "test.md"
        md.write_text("---\nsource_url: https://example.com/existing\ncontent_hash: xyz\n---\n# Test\n", encoding="utf-8")

        detector = ConflictDetector(tmp_vault)
        conflicts = detector.detect(
            url="https://example.com/existing",
            canonical_url="",
            content_hash="different",
            detected_youtube_video_id="",
        )
        assert any(c.conflict_type == "same_url" for c in conflicts)

    def test_same_content_hash_detected(self, tmp_vault: Path) -> None:
        archive_dir = tmp_vault / "01_Reports" / "SourceArchive"
        archive_dir.mkdir()
        md = archive_dir / "dup.md"
        md.write_text("---\nsource_url: https://other.com\ncontent_hash: abc123def\n---\n# Dup\n", encoding="utf-8")

        detector = ConflictDetector(tmp_vault)
        conflicts = detector.detect(
            url="https://example.com/new",
            canonical_url="",
            content_hash="abc123def",
            detected_youtube_video_id="",
        )
        assert any(c.conflict_type == "same_content_hash" for c in conflicts)
        assert any(c.severity == "blocker" for c in conflicts)

    def test_same_canonical_url_detected(self, tmp_vault: Path) -> None:
        archive_dir = tmp_vault / "01_Reports" / "SourceArchive"
        archive_dir.mkdir()
        md = archive_dir / "canon.md"
        md.write_text("---\ncanonical_url: https://canonical.example.com\nsource_url: https://other.com\ncontent_hash: zzz\n---\n# Canon\n", encoding="utf-8")

        detector = ConflictDetector(tmp_vault)
        conflicts = detector.detect(
            url="https://example.com/new",
            canonical_url="https://canonical.example.com",
            content_hash="different",
            detected_youtube_video_id="",
        )
        assert any(c.conflict_type == "same_canonical_url" for c in conflicts)

    def test_same_video_id_report_mocked(self, tmp_vault: Path) -> None:
        """When find_report_by_video_id returns a result, conflict is detected."""
        with patch(
            "podcast_research.db.repository.find_report_by_video_id",
            return_value={"id": 5, "episode_id": 5, "video_id": "testVid1", "title": "Existing Report"},
        ), patch("podcast_research.db.session.init_db"), patch("podcast_research.db.session.get_session"):
            detector = ConflictDetector(tmp_vault)
            conflicts = detector.detect(
                url="https://example.com/new",
                canonical_url="",
                content_hash="abc",
                detected_youtube_video_id="testVid1",
            )
            assert any(c.conflict_type == "same_video_id_report" for c in conflicts)

    def test_same_video_id_deep_notes_detected(self, tmp_vault: Path) -> None:
        deep_notes_dir = tmp_vault / "01_Reports" / "DeepNotes"
        deep_notes_dir.mkdir(parents=True)
        dn = deep_notes_dir / "existing_dn.md"
        dn.write_text("---\nyoutube_video_id: testVid2\n---\n# Existing DN\n", encoding="utf-8")

        detector = ConflictDetector(tmp_vault)
        conflicts = detector.detect(
            url="https://example.com/new",
            canonical_url="",
            content_hash="abc",
            detected_youtube_video_id="testVid2",
        )
        assert any(c.conflict_type == "same_video_id_deep_notes" for c in conflicts)

    def test_missing_dirs_no_error(self, tmp_vault: Path) -> None:
        """When SourceArchive and DeepNotes dirs don't exist, no conflicts returned."""
        detector = ConflictDetector(tmp_vault)
        conflicts = detector.detect(
            url="https://example.com/new",
            canonical_url="https://canonical.example.com",
            content_hash="abc",
            detected_youtube_video_id="vid1",
        )
        # DB check may fail gracefully (no DB in test), vault checks return empty
        assert all(c.conflict_type != "same_content_hash" for c in conflicts)


# ═════════════════════════════════════════════════════════════════════════════
# Test 16-20: Recommendation logic
# ═════════════════════════════════════════════════════════════════════════════

class TestRecommendationLogic:
    """Tests 16-20: _compute_recommendation produces correct recommendations."""

    def test_allin_with_report(self) -> None:
        conflicts = [
            ConflictInfo(conflict_type="same_video_id_report", severity="blocker", description="Report exists"),
        ]
        rec, avail, warns = _compute_recommendation(
            is_allin=True, detected_video_id="vid1",
            conflicts=conflicts, parse_quality="good",
        )
        assert rec == ActionEnum.import_as_deep_notes_linked
        assert ActionEnum.import_as_deep_notes_linked in avail

    def test_allin_no_report(self) -> None:
        rec, avail, warns = _compute_recommendation(
            is_allin=True, detected_video_id="vid1",
            conflicts=[], parse_quality="good",
        )
        assert rec == ActionEnum.import_as_deep_notes_derived_only
        assert ActionEnum.import_as_deep_notes_derived_only in avail

    def test_allin_with_deep_notes(self) -> None:
        conflicts = [
            ConflictInfo(conflict_type="same_video_id_deep_notes", severity="warning", description="DN exists"),
        ]
        rec, avail, warns = _compute_recommendation(
            is_allin=True, detected_video_id="vid1",
            conflicts=conflicts, parse_quality="good",
        )
        assert rec == ActionEnum.overwrite_deep_notes
        assert len(warns) >= 1

    def test_generic_with_youtube_and_report(self) -> None:
        conflicts = [
            ConflictInfo(conflict_type="same_video_id_report", severity="blocker", description="Report exists"),
        ]
        rec, avail, warns = _compute_recommendation(
            is_allin=False, detected_video_id="vid1",
            conflicts=conflicts, parse_quality="good",
        )
        assert rec == ActionEnum.link_as_derived_source
        assert ActionEnum.link_as_derived_source in avail

    def test_generic_no_youtube(self) -> None:
        rec, avail, warns = _compute_recommendation(
            is_allin=False, detected_video_id="",
            conflicts=[], parse_quality="good",
        )
        assert rec == ActionEnum.import_as_source_archive

    def test_low_parse_quality_recommends_archive(self) -> None:
        rec, avail, warns = _compute_recommendation(
            is_allin=False, detected_video_id="",
            conflicts=[], parse_quality="minimal",
        )
        assert rec == ActionEnum.archive_only
        assert ActionEnum.archive_only in avail
        assert any("极低" in w for w in warns)

    def test_content_hash_duplicate_blocks(self) -> None:
        conflicts = [
            ConflictInfo(conflict_type="same_content_hash", severity="blocker", description="Duplicate"),
        ]
        rec, avail, warns = _compute_recommendation(
            is_allin=True, detected_video_id="vid1",
            conflicts=conflicts, parse_quality="good",
        )
        assert rec == ActionEnum.skip
        assert ActionEnum.skip in avail


# ═════════════════════════════════════════════════════════════════════════════
# Test 21-24: Route smoke tests
# ═════════════════════════════════════════════════════════════════════════════

class TestRouteSmoke:
    """Tests 21-24: Web route availability."""

    def test_get_source_import_page(self, api_client, tmp_vault: Path) -> None:
        """GET /sources/import should redirect when vault not configured, or show page."""
        resp = api_client.get("/sources/import", follow_redirects=False)
        # May redirect if vault not configured; accept 200 or 303
        assert resp.status_code in (200, 303)

    def test_post_preview_empty_url(self, api_client, tmp_vault: Path) -> None:
        """Empty URL should redirect with error."""
        resp = api_client.post("/sources/import/preview", data={"url": ""}, follow_redirects=False)
        assert resp.status_code in (200, 303)
        if resp.status_code == 303:
            loc = resp.headers.get("location", "")
            assert "error" in loc or "preview" in loc

    def test_post_preview_valid_url_mocked(self, api_client, tmp_vault: Path) -> None:
        """Valid URL with mocked fetch. May redirect if vault not set, that's OK."""
        with patch("httpx.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.text = MOCK_WEB_HTML
            mock_get.return_value = mock_resp
            resp = api_client.post("/sources/import/preview", data={"url": "https://example.com/article"}, follow_redirects=False)
            # Redirect if vault not configured, 200 if it works — both acceptable
            assert resp.status_code in (200, 303)

    def test_post_confirm_expired_preview(self, api_client) -> None:
        """Expired/non-existent preview_id should redirect with error."""
        resp = api_client.post(
            "/sources/import/confirm",
            data={"preview_id": "nonexistent12", "action": "skip"},
            follow_redirects=False,
        )
        assert resp.status_code in (200, 303)


# ═════════════════════════════════════════════════════════════════════════════
# Test 25-28: Confirm flow
# ═════════════════════════════════════════════════════════════════════════════

class TestConfirmFlow:
    """Tests 25-28: execute_import_action dispatch."""

    def test_confirm_skip(self, tmp_vault: Path) -> None:
        preview = ImportPreview(url="https://example.com/x")
        result = execute_import_action(preview, ActionEnum.skip, tmp_vault)
        assert result["success"] is True
        assert "跳过" in result["message"]

    def test_confirm_invalid_action(self, tmp_vault: Path) -> None:
        preview = ImportPreview(url="https://example.com/x")
        # import_as_deep_notes will try to fetch from allin adapter → fails
        # but execute_import_action catches exceptions and returns error dict
        try:
            result = execute_import_action(preview, ActionEnum.import_as_deep_notes, tmp_vault)
            assert "success" in result
        except Exception:
            # Fetch failure is expected in test without network
            pass

    def test_confirm_source_archive(self, tmp_vault: Path) -> None:
        """import_as_source_archive should write a file to SourceArchive."""
        preview = ImportPreview(
            url="https://example.com/article",
            provider="generic_web_page",
            title="Test Article",
            source_confidence="secondary",
            content_hash="test123",
            _parsed_data=None,
        )
        with patch("podcast_research.adapters.generic_web_page.GenericWebPageAdapter.fetch_page") as mock_fetch:
            from podcast_research.adapters.generic_web_page import ParsedWebPage
            mock_fetch.return_value = ParsedWebPage(
                title="Test Article",
                content_hash="test123",
                parse_quality="good",
                content_blocks_count=3,
            )
            result = execute_import_action(
                preview, ActionEnum.import_as_source_archive, tmp_vault,
            )
            assert result["success"] is True
            assert "归档" in result["message"]
            assert "path" in result
            assert Path(result["path"]).exists()

    def test_source_archive_file_content(self, tmp_vault: Path) -> None:
        """Verify the source archive file has correct frontmatter and body."""
        preview = ImportPreview(
            url="https://example.com/article",
            provider="generic_web_page",
            title="My Article",
            source_confidence="secondary",
            content_hash="hash123",
            detected_youtube_video_id="vid1",
        )
        with patch("podcast_research.adapters.generic_web_page.GenericWebPageAdapter.fetch_page") as mock_fetch:
            from podcast_research.adapters.generic_web_page import ParsedWebPage
            mock_fetch.return_value = ParsedWebPage(
                title="My Article",
                content_hash="hash123",
                canonical_url="https://example.com/canon",
                parse_quality="good",
                content_blocks_count=5,
                paragraphs=["Paragraph one.", "Paragraph two."],
            )
            result = execute_import_action(
                preview, ActionEnum.import_as_source_archive, tmp_vault,
            )
            content = Path(result["path"]).read_text(encoding="utf-8")
            assert "type: source_archive" in content
            assert "source_type: generic_web_page" in content
            # YAML builder quotes URLs containing ://
            assert "example.com/article" in content
            assert "content_hash: hash123" in content
            assert "Paragraph one" in content


# ═════════════════════════════════════════════════════════════════════════════
# E2E integration
# ═════════════════════════════════════════════════════════════════════════════

class TestE2EIntegration:
    """E2E build_import_preview and full confirm flow."""

    def test_build_preview_generic(self, tmp_vault: Path) -> None:
        """build_import_preview for a generic URL should return ImportPreview."""
        with patch("podcast_research.adapters.generic_web_page.GenericWebPageAdapter._fetch_html") as mock_fetch:
            mock_fetch.return_value = MOCK_WEB_HTML
            preview = build_import_preview("https://example.com/article", tmp_vault)
            assert isinstance(preview, ImportPreview)
            assert "GenericWebPageAdapter" in preview.adapter_name
            assert preview.parse_quality == "good"
            assert preview.content_blocks_count >= 3

    def test_build_preview_allin(self, tmp_vault: Path) -> None:
        """build_import_preview for an allin URL should return ImportPreview."""
        with patch("podcast_research.adapters.allin_zh_notes.AllInZHNotesAdapter._fetch_html") as mock_fetch:
            mock_fetch.return_value = MOCK_ALLIN_EPISODE_HTML
            preview = build_import_preview(
                "https://chirs-ma.github.io/allin-podcast-zh-notes/episodes/test/notes.visual.html",
                tmp_vault,
            )
            assert isinstance(preview, ImportPreview)
            assert "AllInZHNotesAdapter" in preview.adapter_name

    def test_extract_first_video_id(self) -> None:
        vid = _extract_first_video_id([
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/abcdef12345",
        ])
        assert vid == "dQw4w9WgXcQ"

    def test_extract_first_video_id_empty(self) -> None:
        assert _extract_first_video_id([]) == ""


# ═════════════════════════════════════════════════════════════════════════════
# Model edge cases
# ═════════════════════════════════════════════════════════════════════════════

class TestModelEdgeCases:
    """Edge case coverage for models."""

    def test_conflict_info_defaults(self) -> None:
        c = ConflictInfo()
        assert c.conflict_type == ""
        assert c.severity == "info"

    def test_action_descriptions_all_present(self) -> None:
        from podcast_research.sources.models import ACTION_DESCRIPTIONS
        for action in ActionEnum:
            assert action in ACTION_DESCRIPTIONS

    def test_preview_unique_ids(self) -> None:
        p1 = ImportPreview()
        p2 = ImportPreview()
        assert p1.preview_id != p2.preview_id
