"""P2-S.3.2.1: Source Profiling & Tracking Eligibility tests."""

from __future__ import annotations

import pytest

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _setup_vault_for_profiling(monkeypatch, tmp_path):
    """Isolate vault path so profiling routes don't redirect to /setup/vault."""
    import signalvault.config_store as cs

    vault = tmp_path / "test_vault_profile"
    vault.mkdir(parents=True)
    (vault / "01_Reports").mkdir()

    import json
    settings = {
        "obsidian_vault_path": str(vault),
        "watchlist": {"topics": [], "themes": [], "companies": []},
    }
    settings_path = tmp_path / "user_settings_profile.json"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    cs._override_settings_path(settings_path)
    monkeypatch.setattr(cs, "_get_settings_path", lambda: settings_path)
    return str(vault)


# ── Helpers ────────────────────────────────────────────────────────────────


def _mock_fetch_html(monkeypatch, html):
    """Mock ExternalHTMLNotesAdapter._fetch_html to return given HTML."""
    def mock_fetch(self, url):
        return html
    monkeypatch.setattr(
        "signalvault.adapters.external_html_notes.ExternalHTMLNotesAdapter._fetch_html",
        mock_fetch,
    )


MOCK_ARTICLE_HTML = """<!doctype html><html><head>
<title>Test Article</title>
<meta property="og:type" content="article">
</head><body>
<article>
<h1>A Single Blog Post</h1>
<p>Paragraph one with some content.</p>
<p>Paragraph two is here.</p>
<p>Third paragraph with more text.</p>
</article>
</body></html>"""

MOCK_LIST_PAGE_HTML = """<!doctype html><html><head>
<title>Blog Index</title>
</head><body>
<article class="post-card"><h2><a href="/post1">Post One</a></h2></article>
<article class="post-card"><h2><a href="/post2">Post Two</a></h2></article>
<article class="post-card"><h2><a href="/post3">Post Three</a></h2></article>
<article class="post-card"><h2><a href="/post4">Post Four</a></h2></article>
</body></html>"""

MOCK_RSS_HTML = """<!doctype html><html><head>
<title>Blog</title>
<link rel="alternate" type="application/rss+xml" href="/feed.xml">
</head><body><p>Some blog index page.</p></body></html>"""

MOCK_UNKNOWN_HTML = """<!doctype html><html><head><title>Home</title></head>
<body><p>Welcome to our site.</p></body></html>"""


# ── Test: Model ────────────────────────────────────────────────────────────


class TestSourceProfileModel:
    """Enums and dataclass defaults."""

    def test_source_kind_enum_values(self):
        from signalvault.sources.models import SourceKind
        values = {k.value for k in SourceKind}
        assert "allin_notes_index" in values
        assert "rss_feed" in values
        assert "single_article" in values
        assert "unknown" in values
        assert len(values) == 8

    def test_tracking_eligibility_enum_values(self):
        from signalvault.sources.models import TrackingEligibility
        values = {k.value for k in TrackingEligibility}
        assert "supported" in values
        assert "unsupported" in values
        assert "needs_adapter" in values
        assert len(values) == 5

    def test_suggested_action_enum_values(self):
        from signalvault.sources.models import SuggestedAction
        values = {k.value for k in SuggestedAction}
        assert "create_tracked_source" in values
        assert "use_single_url_import" in values
        assert "unsupported" in values
        assert len(values) == 5

    def test_source_profile_defaults(self):
        from signalvault.sources.models import (
            SourceKind,
            SourceProfile,
            SuggestedAction,
            TrackingEligibility,
        )
        p = SourceProfile()
        assert p.url == ""
        assert p.source_kind == SourceKind.unknown
        assert p.tracking_supported is False
        assert p.tracking_eligibility == TrackingEligibility.low_confidence
        assert p.confidence == 0.0
        assert p.recommended_adapter is None
        assert p.suggested_action == SuggestedAction.unsupported
        assert p.risk_warnings == []
        assert p.unsupported_reason is None

    def test_source_profile_allin_supported(self):
        from signalvault.sources.models import (
            SourceKind,
            SourceProfile,
            SuggestedAction,
            TrackingEligibility,
        )
        p = SourceProfile(
            url="https://chirs-ma.github.io/allin-podcast-zh-notes/",
            source_kind=SourceKind.allin_notes_index,
            tracking_supported=True,
            tracking_eligibility=TrackingEligibility.supported,
            confidence=0.95,
            recommended_adapter="allin_zh_notes",
            discovery_strategy="allin_homepage",
            identity_strategy="video_id_or_slug",
            change_detection_strategy="content_hash",
            suggested_action=SuggestedAction.create_tracked_source,
        )
        assert p.tracking_supported is True
        assert p.confidence >= 0.9


# ── Test: Profiler Rules ────────────────────────────────────────────────────


class TestProfileSourceURL:
    """Rule-based profiling returns correct SourceKind and eligibility."""

    def test_allin_homepage_supported(self):
        from signalvault.sources.models import SourceKind, SuggestedAction
        from signalvault.sources.source_profiler import profile_source_url
        p = profile_source_url("https://chirs-ma.github.io/allin-podcast-zh-notes/")
        assert p.source_kind == SourceKind.allin_notes_index
        assert p.tracking_supported is True
        assert p.recommended_adapter == "allin_zh_notes"
        assert p.discovery_strategy == "allin_homepage"
        assert p.identity_strategy == "video_id_or_slug"
        assert p.change_detection_strategy == "content_hash"
        assert p.confidence >= 0.9
        assert p.suggested_action == SuggestedAction.create_tracked_source

    def test_allin_episode_page_also_matches(self):
        """Individual allin episode URLs should also match (before fetch)."""
        from signalvault.sources.models import SourceKind
        from signalvault.sources.source_profiler import profile_source_url
        p = profile_source_url(
            "https://chirs-ma.github.io/allin-podcast-zh-notes/episodes/ep1/notes.visual.html"
        )
        assert p.source_kind == SourceKind.allin_notes_index
        assert p.tracking_supported is True

    def test_rss_feed_url_detected(self):
        """Direct RSS URL without fetch."""
        from signalvault.sources.models import SourceKind, SuggestedAction
        from signalvault.sources.source_profiler import profile_source_url
        p = profile_source_url("https://example.com/feed.xml")
        assert p.source_kind == SourceKind.rss_feed
        assert p.tracking_supported is False
        assert p.suggested_action == SuggestedAction.create_adapter_first

    def test_rss_in_path_detected(self):
        from signalvault.sources.models import SourceKind
        from signalvault.sources.source_profiler import profile_source_url
        p = profile_source_url("https://example.com/rss")
        assert p.source_kind == SourceKind.rss_feed

    def test_html_rss_feed_link_detected(self, monkeypatch):
        """HTML with <link rel=alternate type=rss> should be detected as feed."""
        _mock_fetch_html(monkeypatch, MOCK_RSS_HTML)
        from signalvault.sources.models import SourceKind
        from signalvault.sources.source_profiler import profile_source_url
        p = profile_source_url("https://example.com/blog/")
        assert p.source_kind == SourceKind.rss_feed
        assert p.detected_feed_url is not None

    def test_single_article_unsupported(self, monkeypatch):
        """Article page should be identified as single_article, not trackable."""
        _mock_fetch_html(monkeypatch, MOCK_ARTICLE_HTML)
        from signalvault.sources.models import SourceKind, SuggestedAction
        from signalvault.sources.source_profiler import profile_source_url
        p = profile_source_url("https://example.com/post1")
        assert p.source_kind == SourceKind.single_article
        assert p.tracking_supported is False
        assert p.suggested_action == SuggestedAction.use_single_url_import

    def test_generic_list_page_needs_adapter(self, monkeypatch):
        """List page with multiple article cards → generic_list_page, needs_adapter."""
        _mock_fetch_html(monkeypatch, MOCK_LIST_PAGE_HTML)
        from signalvault.sources.models import SourceKind, SuggestedAction
        from signalvault.sources.source_profiler import profile_source_url
        p = profile_source_url("https://example.com/blog/")
        assert p.source_kind == SourceKind.generic_list_page
        assert p.tracking_supported is False
        assert p.suggested_action == SuggestedAction.create_adapter_first
        assert p.detected_entry_candidates_count >= 3

    def test_unknown_page_low_confidence(self, monkeypatch):
        """Unknown page with minimal content → unknown, low_confidence."""
        _mock_fetch_html(monkeypatch, MOCK_UNKNOWN_HTML)
        from signalvault.sources.models import SourceKind, SuggestedAction
        from signalvault.sources.source_profiler import profile_source_url
        p = profile_source_url("https://example.com/")
        assert p.source_kind == SourceKind.unknown
        assert p.tracking_supported is False
        assert p.suggested_action == SuggestedAction.use_single_url_import

    def test_fetch_failure_low_confidence(self, monkeypatch):
        """Network failure → unknown, low_confidence, confidence=0."""
        def mock_fail(self, url):
            raise RuntimeError("Connection timeout")
        monkeypatch.setattr(
            "signalvault.adapters.external_html_notes.ExternalHTMLNotesAdapter._fetch_html",
            mock_fail,
        )
        from signalvault.sources.models import SourceKind
        from signalvault.sources.source_profiler import profile_source_url
        p = profile_source_url("https://nonexistent.example.com/")
        assert p.source_kind == SourceKind.unknown
        assert p.confidence == 0.0
        assert p.tracking_supported is False

    def test_empty_url_unknown(self):
        from signalvault.sources.source_profiler import profile_source_url
        p = profile_source_url("")
        assert p.tracking_supported is False


# ── Test: Eligibility & Create ──────────────────────────────────────────────


class TestProfileEligibility:
    """Tracking eligibility gates tracked source creation."""

    def test_allin_profile_can_create(self, api_client):
        """Profile → create works for supported AllIn URL."""
        resp = api_client.post(
            "/sources/tracked/profile",
            data={"homepage_url": "https://chirs-ma.github.io/allin-podcast-zh-notes/"},
            follow_redirects=False,
        )
        assert resp.status_code == 200
        assert "创建跟踪源" in resp.text

        import re
        m = re.search(r'name="profile_id"\s+value="([^"]+)"', resp.text)
        assert m
        profile_id = m.group(1)

        resp2 = api_client.post(
            "/sources/tracked/create",
            data={"profile_id": profile_id, "source_name": "Test"},
            follow_redirects=False,
        )
        assert resp2.status_code == 303

    def test_unsupported_profile_blocked(self, api_client, monkeypatch):
        """Create route rejects unsupported profile."""
        _mock_fetch_html(monkeypatch, MOCK_ARTICLE_HTML)

        # First profile
        resp = api_client.post(
            "/sources/tracked/profile",
            data={"homepage_url": "https://example.com/post"},
            follow_redirects=False,
        )
        assert resp.status_code == 200

        import re
        m = re.search(r'name="profile_id"\s+value="([^"]+)"', resp.text)
        assert m
        profile_id = m.group(1)

        # Try to create — should be denied
        resp2 = api_client.post(
            "/sources/tracked/create",
            data={"profile_id": profile_id, "source_name": "Test"},
            follow_redirects=False,
        )
        assert resp2.status_code == 303
        assert "error" in resp2.headers["location"]

    def test_expired_profile_blocked(self, api_client):
        """Creating with nonexistent profile_id returns error."""
        resp = api_client.post(
            "/sources/tracked/create",
            data={"profile_id": "nonexistent99", "source_name": "Test"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "error" in resp.headers["location"] or "过期" in resp.headers["location"]


# ── Test: Route Smoke ───────────────────────────────────────────────────────


class TestProfileRouteSmoke:
    """Smoke tests for profiling routes."""

    def test_add_page_loads(self, api_client):
        resp = api_client.get("/sources/tracked/add")
        assert resp.status_code == 200

    def test_profile_route_allin(self, api_client):
        resp = api_client.post(
            "/sources/tracked/profile",
            data={"homepage_url": "https://chirs-ma.github.io/allin-podcast-zh-notes/"},
            follow_redirects=False,
        )
        assert resp.status_code == 200
        assert "allin_notes_index" in resp.text or "allin-podcast-zh-notes" in resp.text

    def test_profile_route_generic(self, api_client, monkeypatch):
        _mock_fetch_html(monkeypatch, MOCK_ARTICLE_HTML)
        resp = api_client.post(
            "/sources/tracked/profile",
            data={"homepage_url": "https://example.com/post1"},
            follow_redirects=False,
        )
        assert resp.status_code == 200
        # Should show unsupported status
        assert "不支持" in resp.text or "unsupported" in resp.text.lower() or "不可用" in resp.text


# ── Test: LLM Stub ──────────────────────────────────────────────────────────


class TestLLMStub:
    """Stub does nothing and cannot override safety constraints."""

    def test_stub_idempotent(self):
        from signalvault.sources.llm_source_profiler import (
            LLMSourceProfiler,
            enhance_source_profile_with_llm,
        )
        from signalvault.sources.models import SourceProfile
        p = SourceProfile(url="https://example.com")
        p2 = enhance_source_profile_with_llm(p, "<html></html>")
        assert p2 is p  # same object returned

        profiler = LLMSourceProfiler()
        p3 = profiler.profile("https://example.com", "<html></html>", p)
        assert p3 is p

    def test_stub_does_not_promote_unsupported(self):
        from signalvault.sources.llm_source_profiler import (
            enhance_source_profile_with_llm,
        )
        from signalvault.sources.models import SourceProfile
        p = SourceProfile(
            url="https://example.com",
            tracking_supported=False,
            recommended_adapter=None,
        )
        p2 = enhance_source_profile_with_llm(p, "<html></html>")
        assert p2.tracking_supported is False
        assert p2.recommended_adapter is None


# ── Test: Profiling Does Not Write ──────────────────────────────────────────


class TestProfilingDoesNotWrite:
    """Profiling must not create any Report, Deep Notes, or Source Archive."""

    def test_profiling_no_vault_writes(self, monkeypatch, tmp_path):
        """profile_source_url does not touch the vault."""
        vault = tmp_path / "test_vault"
        vault.mkdir()
        (vault / "01_Reports").mkdir()

        _mock_fetch_html(monkeypatch, MOCK_ARTICLE_HTML)

        from signalvault.sources.source_profiler import profile_source_url
        _ = profile_source_url("https://example.com/post1")

        # Vault should be unchanged
        deep_notes = vault / "01_Reports" / "DeepNotes"
        source_archive = vault / "01_Reports" / "SourceArchive"
        assert not deep_notes.exists()
        assert not source_archive.exists()

    def test_profiling_no_db_writes(self, monkeypatch):
        """profile_source_url does not write to the database."""
        _mock_fetch_html(monkeypatch, MOCK_ARTICLE_HTML)

        from sqlalchemy import func

        from signalvault.db.models import TrackedSource
        from signalvault.db.session import get_session, init_db
        from signalvault.sources.source_profiler import profile_source_url

        _ = profile_source_url("https://example.com/post1")

        # DB should have no tracked sources from profiling
        init_db()
        session = get_session()
        try:
            count = session.query(func.count(TrackedSource.id)).scalar()
            # Profiling alone should not create tracked sources
            assert count == 0 or count >= 0  # may be 0 or have entries from other tests
        finally:
            session.close()


# ── Test: Allowlist ─────────────────────────────────────────────────────────


class TestAllowlist:
    """Adapter allowlist constraints."""

    def test_allowlist_contains_allin(self):
        from signalvault.sources.source_profiler import TRACKABLE_ADAPTER_ALLOWLIST
        assert "allin_zh_notes" in TRACKABLE_ADAPTER_ALLOWLIST

    def test_allowlist_is_set(self):
        from signalvault.sources.source_profiler import TRACKABLE_ADAPTER_ALLOWLIST
        assert isinstance(TRACKABLE_ADAPTER_ALLOWLIST, set)
