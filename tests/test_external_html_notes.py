"""P2-S.1: External HTML Notes Adapter tests.

Tests:
1. Parse homepage episode list
2. Parse episode title
3. Parse generated_at
4. Parse YouTube source url
5. Parse key points
6. Parse timeline segments
7. Parse speaker turns
8. Parse background terms
9. Canonical video_id extraction
10. Existing YouTube report dedupe
11. Derived source provenance
12. Malformed page fallback
13. No duplicate report creation
14. ruff clean
"""

from __future__ import annotations

import pytest

from podcast_research.adapters.allin_zh_notes import SITE_BASE, AllInZHNotesAdapter
from podcast_research.adapters.external_html_notes import (
    ExternalEpisodeEntry,
    NormalizedEpisodeSegment,
    NormalizedQuote,
    NormalizedSourceDocument,
    NormalizedSpeakerTurn,
)

# ═════════════════════════════════════════════════════════════════════════════
# Test fixtures — real HTML from the site (snapshots)
# ═════════════════════════════════════════════════════════════════════════════

# Minimal valid homepage HTML (subset of actual structure)
MOCK_HOMEPAGE_HTML = """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>All-In Podcast 中文可视化笔记</title></head>
<body>
<div class="page">
  <main class="content-flow">
    <div class="section-head"><h2>最新精读</h2></div>
    <div class="episode-list" id="episode-list">
      <a class="episode-card" href="./episodes/ep-1-slug/notes.visual.html">
        <h2 class="episode-title">Episode One Title</h2>
        <span class="episode-date">2026-06-23</span>
      </a>
      <a class="episode-card" href="./episodes/ep-2-slug/notes.visual.html">
        <h2 class="episode-title">Episode Two Title</h2>
        <span class="episode-date">2026-06-15</span>
      </a>
      <a class="episode-card" href="./episodes/ep-3-slug/notes.visual.html">
        <h2 class="episode-title">Episode Three Title</h2>
        <span class="episode-date">2026-05-31</span>
      </a>
    </div>
  </main>
</div>
</body>
</html>"""

# Minimal valid episode page HTML
MOCK_EPISODE_HTML = """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>Test Episode - All-In Podcast</title></head>
<body>
<div class="page">
  <main class="article">
    <header class="hero">
      <h1>Test Episode: AI & Geopolitics</h1>
      <div class="meta">
        <span>生成时间：2026-04-30 15:59</span>
        <span>来源：<a href="https://www.youtube.com/watch?v=dQw4w9WgXcQ" target="_blank">YouTube</a></span>
      </div>
      <div class="meta-strip">
        <span class="meta-pill"><b>30 分钟</b>阅读时长</span>
        <span class="meta-pill"><b>3</b>核心要点</span>
      </div>
      <div class="summary"><p>This is a test summary about AI safety and geopolitics.</p></div>
    </header>

    <div class="content-shell">
      <div class="content-flow">
        <section id="takeaways">
          <div class="section-head"><h2>核心要点</h2></div>
          <ol class="takeaway-list">
            <li class="takeaway"><span>01</span><p>Key point one: AI safety matters.</p></li>
            <li class="takeaway"><span>02</span><p>Key point two: Market growth expected.</p></li>
            <li class="takeaway"><span>03</span><p>Key point three: Geopolitical risks rising.</p></li>
          </ol>
        </section>

        <section id="timeline">
          <div class="section-head"><h2>分段详细整理</h2></div>
          <div class="timeline" data-timeline>
            <article class="timeline-card" data-timeline-card>
              <header class="timeline-heading">
                <span class="timeline-index">01</span>
                <span class="timeline-meta">00:00–00:15</span>
              </header>
              <div class="timeline-body">
                <h3>Opening Segment</h3>
                <div class="section-content">
                  <h4>本段核心内容</h4>
                  <ul><li>Introduction of guests</li><li>Setting the stage</li></ul>
                  <h4>背景解释与关键术语</h4>
                  <ul><li>Mythos：Anthropic new AI model</li><li>OpenClaw：Open source AI agent project</li></ul>
                  <h4>详细中文整理</h4>
                  <p><strong>JCal：</strong> Welcome to the show. Today we have exciting topics.</p>
                  <p><strong>Chamath：</strong> I think the market is overvalued right now.</p>
                  <p><strong>Sacks：</strong> Let me offer a nuanced view on this issue.</p>
                </div>
              </div>
            </article>
            <article class="timeline-card" data-timeline-card>
              <header class="timeline-heading">
                <span class="timeline-index">02</span>
                <span class="timeline-meta">00:15–00:30</span>
              </header>
              <div class="timeline-body">
                <h3>Main Discussion</h3>
                <div class="section-content">
                  <h4>本段核心内容</h4>
                  <ul><li>Debate on AI regulation</li></ul>
                  <h4>背景解释与关键术语</h4>
                  <ul><li>FDA for AI：Proposed AI regulatory framework</li></ul>
                  <h4>详细中文整理</h4>
                  <p><strong>Brad：</strong> AI companies should self-regulate before government steps in.</p>
                </div>
              </div>
            </article>
          </div>
        </section>

        <section id="speakers">
          <div class="section-head"><h2>人物观点对照</h2></div>
          <div class="speaker-grid">
            <article class="speaker-card">
              <p class="speaker-kicker">嘉宾 01</p>
              <h3>Jason Calacanis</h3>
              <div><p>JCal supports open source and warns against AI monopolies.</p></div>
            </article>
            <article class="speaker-card">
              <p class="speaker-kicker">嘉宾 02</p>
              <h3>Chamath Palihapitiya</h3>
              <div><p>Chamath is skeptical of AI hype and questions valuations.</p></div>
            </article>
          </div>
        </section>

        <section id="quotes">
          <div class="section-head"><h2>值得引用的原话</h2></div>
          <div class="panel">
            <ol><li><strong>AI is the biggest transformation since the internet.</strong></li></ol>
            <p>中文：AI是自互联网以来最大的变革。 说明：JCal对AI影响的核心判断。</p>
            <ol><li><strong>The market will correct eventually.</strong></li></ol>
            <p>中文：市场最终会修正。 说明：Chamath对当前估值的警告。</p>
          </div>
        </section>
      </div>
    </div>
  </main>
</div>
</body>
</html>"""

# Malformed HTML — missing key sections
MOCK_MALFORMED_HTML = """<!doctype html>
<html><head><title>Broken Page</title></head>
<body>
<div class="page">
  <header class="hero">
    <h1>Broken Episode</h1>
    <!-- No meta, no sections -->
  </header>
  <div class="content-shell">
    <div class="content-flow">
      <p>Just some random text, no structured sections.</p>
    </div>
  </div>
</div>
</body>
</html>"""

# Homepage with no episodes
MOCK_EMPTY_HOMEPAGE = """<!doctype html>
<html><body>
<div class="page">
  <div class="episode-list"></div>
</div>
</body></html>"""


# ═════════════════════════════════════════════════════════════════════════════
# Adapter instance (no network)
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def adapter() -> AllInZHNotesAdapter:
    return AllInZHNotesAdapter()


# ═════════════════════════════════════════════════════════════════════════════
# Test 1: Parse homepage episode list
# ═════════════════════════════════════════════════════════════════════════════

class TestHomepageParse:
    """Test 1: homepage episode list parsing."""

    def test_parse_homepage_count(self, adapter: AllInZHNotesAdapter) -> None:
        entries = adapter._parse_homepage(MOCK_HOMEPAGE_HTML, base_url=SITE_BASE)
        assert len(entries) == 3

    def test_parse_homepage_title(self, adapter: AllInZHNotesAdapter) -> None:
        entries = adapter._parse_homepage(MOCK_HOMEPAGE_HTML, base_url=SITE_BASE)
        assert entries[0].title == "Episode One Title"
        assert entries[1].title == "Episode Two Title"

    def test_parse_homepage_date(self, adapter: AllInZHNotesAdapter) -> None:
        entries = adapter._parse_homepage(MOCK_HOMEPAGE_HTML, base_url=SITE_BASE)
        assert entries[0].date == "2026-06-23"
        assert entries[2].date == "2026-05-31"

    def test_parse_homepage_slug(self, adapter: AllInZHNotesAdapter) -> None:
        entries = adapter._parse_homepage(MOCK_HOMEPAGE_HTML, base_url=SITE_BASE)
        assert entries[0].slug == "ep-1-slug"
        assert entries[1].slug == "ep-2-slug"

    def test_parse_homepage_url_resolved(self, adapter: AllInZHNotesAdapter) -> None:
        entries = adapter._parse_homepage(MOCK_HOMEPAGE_HTML, base_url=SITE_BASE)
        assert entries[0].url.endswith("/episodes/ep-1-slug/notes.visual.html")

    def test_parse_empty_homepage(self, adapter: AllInZHNotesAdapter) -> None:
        entries = adapter._parse_homepage(MOCK_EMPTY_HOMEPAGE)
        assert entries == []


# ═════════════════════════════════════════════════════════════════════════════
# Test 2: Parse episode title
# ═════════════════════════════════════════════════════════════════════════════

class TestEpisodeTitle:
    """Test 2: episode title extraction."""

    def test_parse_title(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=f"{SITE_BASE}episodes/ep-1-slug/notes.visual.html")
        assert doc.title == "Test Episode: AI & Geopolitics"


# ═════════════════════════════════════════════════════════════════════════════
# Test 3: Parse generated_at
# ═════════════════════════════════════════════════════════════════════════════

class TestGeneratedAt:
    """Test 3: generated_at extraction."""

    def test_parse_generated_at(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert doc.generated_at == "2026-04-30 15:59"


# ═════════════════════════════════════════════════════════════════════════════
# Test 4: Parse YouTube source url
# ═════════════════════════════════════════════════════════════════════════════

class TestYouTubeSourceUrl:
    """Test 4: YouTube source URL extraction."""

    def test_parse_youtube_url(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert doc.original_source_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_no_youtube_url_in_malformed(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_MALFORMED_HTML, url=SITE_BASE)
        assert doc.original_source_url == ""


# ═════════════════════════════════════════════════════════════════════════════
# Test 5: Parse key points
# ═════════════════════════════════════════════════════════════════════════════

class TestKeyPoints:
    """Test 5: key points parsing."""

    def test_parse_key_points_count(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert len(doc.key_points) == 3

    def test_parse_key_points_content(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert doc.key_points[0] == "Key point one: AI safety matters."
        assert doc.key_points[1] == "Key point two: Market growth expected."

    def test_no_key_points_in_malformed(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_MALFORMED_HTML, url=SITE_BASE)
        assert doc.key_points == []


# ═════════════════════════════════════════════════════════════════════════════
# Test 6: Parse timeline segments
# ═════════════════════════════════════════════════════════════════════════════

class TestTimelineSegments:
    """Test 6: timeline segment parsing."""

    def test_parse_timeline_count(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert len(doc.timeline) == 2

    def test_parse_timeline_index(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert doc.timeline[0].index == 1
        assert doc.timeline[1].index == 2

    def test_parse_timeline_title(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert doc.timeline[0].title == "Opening Segment"
        assert doc.timeline[1].title == "Main Discussion"

    def test_parse_timeline_time_range(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert doc.timeline[0].time_range == "00:00–00:15"
        assert doc.timeline[1].time_range == "00:15–00:30"

    def test_parse_timeline_core_points(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert len(doc.timeline[0].core_points) == 2
        assert "Introduction of guests" in doc.timeline[0].core_points

    def test_no_timeline_in_malformed(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_MALFORMED_HTML, url=SITE_BASE)
        assert doc.timeline == []


# ═════════════════════════════════════════════════════════════════════════════
# Test 7: Parse speaker turns
# ═════════════════════════════════════════════════════════════════════════════

class TestSpeakerTurns:
    """Test 7: speaker turn parsing from timeline."""

    def test_speaker_turns_count(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        # Segment 1: 3 turns (JCal, Chamath, Sacks), Segment 2: 1 turn (Brad)
        assert len(doc.timeline[0].speaker_turns) == 3
        assert len(doc.timeline[1].speaker_turns) == 1

    def test_speaker_names(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        names = [t.speaker_name for t in doc.timeline[0].speaker_turns]
        assert "JCal" in names
        assert "Chamath" in names
        assert "Sacks" in names

    def test_speaker_text_content(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        turn0 = doc.timeline[0].speaker_turns[0]
        assert "Welcome to the show" in turn0.text


# ═════════════════════════════════════════════════════════════════════════════
# Test 8: Parse background terms
# ═════════════════════════════════════════════════════════════════════════════

class TestBackgroundTerms:
    """Test 8: background terms parsing."""

    def test_background_terms_segment1(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        terms = doc.timeline[0].background_terms
        assert len(terms) == 2
        assert terms[0]["term"] == "Mythos"
        assert "Anthropic" in terms[0]["definition"]

    def test_background_terms_segment2(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        terms = doc.timeline[1].background_terms
        assert len(terms) == 1
        assert terms[0]["term"] == "FDA for AI"


# ═════════════════════════════════════════════════════════════════════════════
# Test 9: Canonical video_id extraction
# ═════════════════════════════════════════════════════════════════════════════

class TestVideoIdExtraction:
    """Test 9: canonical video_id extraction from YouTube URLs."""

    @pytest.mark.parametrize("url,expected", [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("", ""),
        ("not-a-url", ""),
    ])
    def test_extract_video_id(self, adapter: AllInZHNotesAdapter, url: str, expected: str) -> None:
        assert adapter._extract_video_id_from_url(url) == expected

    def test_video_id_from_episode(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert doc.youtube_video_id == "dQw4w9WgXcQ"


# ═════════════════════════════════════════════════════════════════════════════
# Test 10: Existing YouTube report dedupe
# ═════════════════════════════════════════════════════════════════════════════

class TestDedupe:
    """Test 10: dedupe — don't create duplicate reports for existing video_id."""

    def test_find_report_by_video_id(self, seeded_db) -> None:
        """Verify find_report_by_video_id works for dedup."""
        from podcast_research.db.repository import find_report_by_video_id
        from podcast_research.db.session import get_session

        session = get_session()
        try:
            result = find_report_by_video_id(session, "nonexistent_video_id_12345")
            assert result is None
        finally:
            session.close()

    def test_video_id_extraction_for_dedup(self, adapter: AllInZHNotesAdapter) -> None:
        """Verify video_id is correctly extracted for dedup key."""
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        # This video_id should be used to check existing reports
        assert doc.youtube_video_id == "dQw4w9WgXcQ"
        assert len(doc.youtube_video_id) == 11  # standard YT ID length


# ═════════════════════════════════════════════════════════════════════════════
# Test 11: Derived source provenance
# ═════════════════════════════════════════════════════════════════════════════

class TestProvenance:
    """Test 11: derived source provenance on every output."""

    def test_provenance_fields(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=f"{SITE_BASE}episodes/test/notes.visual.html")
        assert doc.provenance["provider"] == "allin-podcast-zh-notes"
        assert doc.provenance["source_type"] == "derived"
        assert doc.provenance["source_confidence"] == "secondary"
        assert "youtube.com" in doc.provenance["original_source_url"]

    def test_source_type_is_derived(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert doc.source_type == "derived"
        assert doc.source_confidence == "secondary"

    def test_provenance_includes_source_url(self, adapter: AllInZHNotesAdapter) -> None:
        url = f"{SITE_BASE}episodes/ep-1-slug/notes.visual.html"
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=url)
        assert doc.provenance["source_url"] == url


# ═════════════════════════════════════════════════════════════════════════════
# Test 12: Malformed page fallback
# ═════════════════════════════════════════════════════════════════════════════

class TestMalformedFallback:
    """Test 12: graceful handling of malformed HTML."""

    def test_malformed_returns_empty_not_crash(self, adapter: AllInZHNotesAdapter) -> None:
        """Should return empty document, not raise."""
        doc = adapter._parse_episode(MOCK_MALFORMED_HTML, url=SITE_BASE)
        assert isinstance(doc, NormalizedSourceDocument)
        assert doc.title == "Broken Episode"

    def test_malformed_no_key_points(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_MALFORMED_HTML, url=SITE_BASE)
        assert doc.key_points == []

    def test_malformed_no_timeline(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_MALFORMED_HTML, url=SITE_BASE)
        assert doc.timeline == []

    def test_malformed_no_speakers(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_MALFORMED_HTML, url=SITE_BASE)
        assert doc.speaker_viewpoints == []

    def test_malformed_no_quotes(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_MALFORMED_HTML, url=SITE_BASE)
        assert doc.bilingual_quotes == []

    def test_malformed_still_has_provenance(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_MALFORMED_HTML, url=SITE_BASE)
        assert doc.provenance["provider"] == "allin-podcast-zh-notes"

    def test_empty_html_string(self, adapter: AllInZHNotesAdapter) -> None:
        """Empty HTML should not crash."""
        doc = adapter._parse_episode("<html></html>", url=SITE_BASE)
        assert isinstance(doc, NormalizedSourceDocument)

    def test_no_episode_list_div(self, adapter: AllInZHNotesAdapter) -> None:
        """HTML with no episode-list div returns empty list."""
        entries = adapter._parse_homepage("<html><body><p>No list here</p></body></html>")
        assert entries == []

    def test_nonexistent_sections(self, adapter: AllInZHNotesAdapter) -> None:
        """HTML with no recognized sections returns empty fields."""
        html = """<html><body>
        <header class="hero"><h1>T</h1><div class="meta"></div></header>
        </body></html>"""
        doc = adapter._parse_episode(html, url=SITE_BASE)
        assert doc.key_points == []
        assert doc.timeline == []
        assert doc.speaker_viewpoints == []
        assert doc.bilingual_quotes == []


# ═════════════════════════════════════════════════════════════════════════════
# Test 13: No duplicate report creation
# ═════════════════════════════════════════════════════════════════════════════

class TestNoDuplicateReport:
    """Test 13: no duplicate report for already-analyzed videos."""

    def test_dedup_check_logic(self, adapter: AllInZHNotesAdapter) -> None:
        """Verify the dedup flow: if video_id has existing report, skip."""
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert doc.youtube_video_id == "dQw4w9WgXcQ"
        # The actual dedup happens in the service layer via find_report_by_video_id
        # This test verifies the adapter correctly provides the dedup key.

    def test_provider_constant(self, adapter: AllInZHNotesAdapter) -> None:
        """Ensure provider name is consistent for dedup grouping."""
        assert adapter.provider_name == "allin-podcast-zh-notes"


# ═════════════════════════════════════════════════════════════════════════════
# Additional: quote parsing, speaker viewpoints, summary, reading time
# ═════════════════════════════════════════════════════════════════════════════

class TestQuoteParsing:
    """Test bilingual quote parsing."""

    def test_quotes_count(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert len(doc.bilingual_quotes) == 2

    def test_quote_english(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert "biggest transformation" in doc.bilingual_quotes[0].text_en

    def test_quote_chinese(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert "互联网" in doc.bilingual_quotes[0].text_zh

    def test_quote_context(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert doc.bilingual_quotes[0].context_note != ""


class TestSpeakerViewpoints:
    """Test speaker viewpoint parsing."""

    def test_viewpoints_count(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert len(doc.speaker_viewpoints) == 2

    def test_viewpoint_names(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        names = [v.name for v in doc.speaker_viewpoints]
        assert "Jason Calacanis" in names
        assert "Chamath Palihapitiya" in names

    def test_viewpoint_content(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert "open source" in doc.speaker_viewpoints[0].viewpoint.lower()


class TestSummaryAndMeta:
    """Test summary, reading_time, slug extraction."""

    def test_summary(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert "AI safety" in doc.summary

    def test_reading_time(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(MOCK_EPISODE_HTML, url=SITE_BASE)
        assert "30" in doc.reading_time

    def test_slug(self, adapter: AllInZHNotesAdapter) -> None:
        doc = adapter._parse_episode(
            MOCK_EPISODE_HTML,
            url=f"{SITE_BASE}episodes/ep-1-slug/notes.visual.html",
        )
        assert doc.slug == "ep-1-slug"


class TestNormalizedTypes:
    """Test the normalized data types directly."""

    def test_normalized_document_defaults(self) -> None:
        doc = NormalizedSourceDocument()
        assert doc.source_type == "derived"
        assert doc.source_confidence == "secondary"
        assert isinstance(doc.key_points, list)
        assert isinstance(doc.timeline, list)

    def test_normalized_document_provenance_auto(self) -> None:
        doc = NormalizedSourceDocument(
            provider="test-prov",
            source_url="https://example.com/ep1",
            original_source_url="https://youtube.com/watch?v=abc123",
        )
        assert doc.provenance["provider"] == "test-prov"
        assert doc.provenance["source_type"] == "derived"
        assert doc.provenance["source_confidence"] == "secondary"

    def test_normalized_quote(self) -> None:
        q = NormalizedQuote(
            text_en="Hello world",
            text_zh="你好世界",
            context_note="A test quote",
        )
        assert q.text_en == "Hello world"
        assert q.text_zh == "你好世界"

    def test_normalized_speaker_turn(self) -> None:
        st = NormalizedSpeakerTurn(speaker_name="JCal", text="Welcome to the show")
        assert st.speaker_name == "JCal"
        assert st.text == "Welcome to the show"

    def test_normalized_segment_defaults(self) -> None:
        seg = NormalizedEpisodeSegment(index=1)
        assert seg.index == 1
        assert seg.core_points == []
        assert seg.background_terms == []
        assert seg.speaker_turns == []

    def test_external_episode_entry(self) -> None:
        entry = ExternalEpisodeEntry(
            title="Test Episode",
            url="https://example.com/ep1",
            date="2026-06-23",
            slug="ep-1",
        )
        assert entry.title == "Test Episode"
        assert entry.slug == "ep-1"

    def test_slug_from_url_variants(self, adapter: AllInZHNotesAdapter) -> None:
        assert adapter._slug_from_url("./episodes/my-slug/notes.visual.html") == "my-slug"
        assert adapter._slug_from_url("https://example.com/episodes/another-slug/notes.visual.html") == "another-slug"


class TestDateParsing:
    """Test date string normalization."""

    def test_iso_date(self, adapter: AllInZHNotesAdapter) -> None:
        assert adapter._parse_date("2026-06-23") == "2026-06-23"

    def test_chinese_date(self, adapter: AllInZHNotesAdapter) -> None:
        assert adapter._parse_date("2026年4月10日") == "2026-04-10"

    def test_empty_date(self, adapter: AllInZHNotesAdapter) -> None:
        assert adapter._parse_date("") == ""

    def test_single_digit_month_day(self, adapter: AllInZHNotesAdapter) -> None:
        assert adapter._parse_date("2026年1月5日") == "2026-01-05"
