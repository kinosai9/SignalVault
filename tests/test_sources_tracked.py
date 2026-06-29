"""P2-S.3.2: Tracked External Source tests.

Tests for tracked source CRUD, refresh, import, and UI routes.
All tests use api_client + tmp_path. No real HTTP calls.
"""

from __future__ import annotations

from urllib.parse import unquote

import pytest

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _setup_vault_for_tracked(monkeypatch, tmp_path):
    """Set a temporary vault path in config_store so tracked source routes work."""
    import podcast_research.config_store as cs

    vault = tmp_path / "test_vault_tracked"
    vault.mkdir(parents=True)
    (vault / "01_Reports").mkdir()

    import json
    settings = {
        "obsidian_vault_path": str(vault),
        "watchlist": {"topics": [], "themes": [], "companies": []},
    }
    settings_path = tmp_path / "user_settings_tracked.json"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    # Override both the path and the function that reads it
    cs._override_settings_path(settings_path)
    monkeypatch.setattr(cs, "_get_settings_path", lambda: settings_path)
    return str(vault)


# ── Mock HTML fixtures ─────────────────────────────────────────────────────

MOCK_ALLIN_HOMEPAGE_HTML = """<!doctype html><html><body>
<div class="episode-list">
<a class="episode-card" href="/allin-podcast-zh-notes/episodes/ep1/notes.visual.html">
<h2 class="episode-title">Test Episode One</h2>
<span class="episode-date">2026-06-20</span></a>
<a class="episode-card" href="/allin-podcast-zh-notes/episodes/ep2/notes.visual.html">
<h2 class="episode-title">Test Episode Two</h2>
<span class="episode-date">2026-06-19</span></a>
<a class="episode-card" href="/allin-podcast-zh-notes/episodes/ep3/notes.visual.html">
<h2 class="episode-title">Test Episode Three</h2>
<span class="episode-date">2026-06-18</span></a>
</div>
</body></html>"""

MOCK_ALLIN_EPISODE_HTML = """<!doctype html><html><head>
<title>Test Episode One — All-In Podcast Chinese Notes</title>
</head><body>
<header class="hero">
<h1>E1: AI Open Source, Trump Tariffs, Market Trends</h1>
<div class="meta">
<span class="episode-date">2026-06-20</span>
<a href="https://www.youtube.com/watch?v=dQw4w9WgXcQ">YouTube</a>
</div>
<div class="meta-strip"><span class="meta-pill">15 min read</span></div>
<div class="summary"><p>A deep dive into the latest AI and market trends.</p></div>
</header>
<section id="takeaways">
<ol>
<li class="takeaway"><p>AI open source is accelerating innovation.</p></li>
<li class="takeaway"><p>Trump tariffs affect supply chains.</p></li>
</ol>
</section>
<section id="timeline">
<article class="timeline-card">
<div class="timeline-marker">01</div>
<div class="timeline-body">
<div class="timeline-range">[00:00 – 10:00]</div>
<h3>Opening Discussion</h3>
<div class="timeline-content">
<h4>核心内容</h4>
<ul><li>Markets overview and AI impact</li></ul>
<h4>背景术语</h4>
<ul><li>AGI：通用人工智能</li></ul>
</div>
</div>
</article>
</section>
<section id="speakers">
<article class="speaker-card">
<p class="speaker-kicker">Host</p>
<h3>Jason Calacanis</h3>
<div><p>Markets are shifting toward AI-native companies.</p></div>
</article>
</section>
<section id="quotes">
<ol>
<li><strong>"AI is the new electricity."</strong></li>
<p>中文：AI 是新的电力。说明：核心比喻</p>
</ol>
</section>
</body></html>"""

MOCK_MINIMAL_EPISODE_HTML = """<!doctype html><html><head>
<title>Broken Episode</title>
</head><body><p>This page is mostly empty.</p></body></html>"""

# ── Helpers ────────────────────────────────────────────────────────────────


def _uuid_hex() -> str:
    import uuid
    return uuid.uuid4().hex[:12]


def _mock_allin_homepage_fetch(monkeypatch, html=None):
    """Mock the _fetch_html method to return AllIn homepage HTML."""

    html = html or MOCK_ALLIN_HOMEPAGE_HTML

    def mock_fetch_html(self, url):
        return html

    monkeypatch.setattr(
        "podcast_research.adapters.external_html_notes.ExternalHTMLNotesAdapter._fetch_html",
        mock_fetch_html,
    )


def _mock_allin_episode_fetch(monkeypatch, episode_html=None):
    """Mock _fetch_html to return episode HTML (for build_import_preview)."""
    html = episode_html or MOCK_ALLIN_EPISODE_HTML

    def mock_fetch_html(self, url):
        # Return episode HTML for episode URLs, homepage HTML otherwise
        if "/episodes/" in url:
            return html
        return MOCK_ALLIN_HOMEPAGE_HTML

    monkeypatch.setattr(
        "podcast_research.adapters.external_html_notes.ExternalHTMLNotesAdapter._fetch_html",
        mock_fetch_html,
    )


def _seed_tracked_source(api_client):
    """Helper: profile an AllIn URL, create tracked source, return its ID.

    P2-S.3.2.1: Uses the two-step profile → create flow.
    """
    # Step 1: Profile the URL
    resp = api_client.post(
        "/sources/tracked/profile",
        data={
            "homepage_url": "https://chirs-ma.github.io/allin-podcast-zh-notes/",
            "name": "Test AllIn Source",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200, f"Profile step: expected 200, got {resp.status_code}: {resp.text[:200]}"

    # Extract profile_id from hidden form field
    import re
    m = re.search(r'name="profile_id"\s+value="([^"]+)"', resp.text)
    assert m, f"Cannot find profile_id in profile page: {resp.text[:300]}"
    profile_id = m.group(1)

    # Step 2: Create tracked source
    resp2 = api_client.post(
        "/sources/tracked/create",
        data={
            "profile_id": profile_id,
            "source_name": "Test AllIn Source",
        },
        follow_redirects=False,
    )
    assert resp2.status_code == 303, f"Create step: expected 303, got {resp2.status_code}: {resp2.text[:200]}"

    location = resp2.headers["location"]
    m2 = re.search(r"/sources/tracked/(\d+)", location)
    assert m2, f"Cannot parse tracked source ID from: {location}"
    return int(m2.group(1))


# ── Test: URL Validation ───────────────────────────────────────────────────


class TestValidateURL:
    """P2-S.3.2 req 2: URL validation for tracking."""

    def test_allin_zh_notes_url_valid(self):
        from podcast_research.sources.tracked_source_service import (
            validate_url_for_tracking,
        )
        is_valid, adapter, provider, msg = validate_url_for_tracking(
            "https://chirs-ma.github.io/allin-podcast-zh-notes/"
        )
        assert is_valid is True
        assert adapter == "AllInZHNotesAdapter"
        assert provider == "allin-podcast-zh-notes"
        assert msg == ""

    def test_allin_in_path_valid(self):
        from podcast_research.sources.tracked_source_service import (
            validate_url_for_tracking,
        )
        is_valid, _, provider, _ = validate_url_for_tracking(
            "https://example.com/allin-podcast-zh-notes/"
        )
        assert is_valid is True
        assert provider == "allin-podcast-zh-notes"

    def test_generic_url_invalid(self):
        from podcast_research.sources.tracked_source_service import (
            validate_url_for_tracking,
        )
        is_valid, adapter, provider, msg = validate_url_for_tracking(
            "https://example.com/blog/"
        )
        assert is_valid is False
        assert "当前不支持" in msg
        assert "单网页导入" in msg

    def test_empty_url_invalid(self):
        from podcast_research.sources.tracked_source_service import (
            validate_url_for_tracking,
        )
        is_valid, _, _, _ = validate_url_for_tracking("")
        assert is_valid is False


# ── Test: CRUD & Pages ─────────────────────────────────────────────────────


class TestTrackedSourceCrud:
    """P2-S.3.2 req 1, 12, 17: CRUD and basic pages."""

    def test_tracked_list_page_loads(self, api_client):
        """GET /sources/tracked returns 200."""
        resp = api_client.get("/sources/tracked")
        assert resp.status_code == 200
        assert "信息源跟踪" in resp.text

    def test_tracked_list_empty_state(self, api_client):
        """Empty state shows hint when no tracked sources."""
        resp = api_client.get("/sources/tracked")
        assert resp.status_code == 200
        assert "还没有添加" in resp.text

    def test_tracked_add_page_loads(self, api_client):
        """GET /sources/tracked/add returns 200."""
        resp = api_client.get("/sources/tracked/add")
        assert resp.status_code == 200
        assert "添加跟踪信息源" in resp.text

    def test_add_valid_allin_source(self, api_client):
        """Two-step flow: profile AllIn URL → create tracked source."""
        # Step 1: Profile — should show supported preview
        resp = api_client.post(
            "/sources/tracked/profile",
            data={
                "homepage_url": "https://chirs-ma.github.io/allin-podcast-zh-notes/",
                "name": "My AllIn Source",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200
        assert "创建跟踪源" in resp.text  # button should be enabled

        # Extract profile_id
        import re
        m = re.search(r'name="profile_id"\s+value="([^"]+)"', resp.text)
        assert m, f"Cannot find profile_id: {resp.text[:300]}"
        profile_id = m.group(1)

        # Step 2: Create
        resp2 = api_client.post(
            "/sources/tracked/create",
            data={"profile_id": profile_id, "source_name": "My AllIn Source"},
            follow_redirects=False,
        )
        assert resp2.status_code == 303
        assert "success" in resp2.headers["location"]

        # Verify it appears in the list
        resp3 = api_client.get("/sources/tracked")
        assert "My AllIn Source" in resp3.text

    def test_add_invalid_url_shows_unsupported(self, api_client, monkeypatch):
        """Generic URL profiles as unsupported — create button disabled."""
        # Mock fetch to return article-like HTML
        def mock_fetch(self, url):
            return "<html><head><title>Test</title></head><body><article><h1>A Post</h1><p>Content here.</p><p>More content.</p><p>Even more.</p></article></body></html>"

        monkeypatch.setattr(
            "podcast_research.adapters.external_html_notes.ExternalHTMLNotesAdapter._fetch_html",
            mock_fetch,
        )

        resp = api_client.post(
            "/sources/tracked/profile",
            data={
                "homepage_url": "https://example.com/blog/post1",
                "name": "Invalid",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200
        assert "不支持" in resp.text or "unsupported" in resp.text.lower()
        # Create button should be disabled
        assert "不可用" in resp.text or "disabled" in resp.text

    def test_tracked_detail_page_loads(self, api_client):
        """GET /sources/tracked/{id} shows source info."""
        ts_id = _seed_tracked_source(api_client)
        resp = api_client.get(f"/sources/tracked/{ts_id}")
        assert resp.status_code == 200
        assert "My AllIn Source" in resp.text or "allin-podcast-zh-notes" in resp.text

    def test_tracked_entries_page_loads(self, api_client):
        """GET /sources/tracked/{id}/entries shows entries list."""
        ts_id = _seed_tracked_source(api_client)
        resp = api_client.get(f"/sources/tracked/{ts_id}/entries")
        assert resp.status_code == 200
        assert "条目" in resp.text

    def test_nonexistent_source_redirects(self, api_client):
        """Detail page for nonexistent ID redirects with error."""
        resp = api_client.get("/sources/tracked/99999", follow_redirects=False)
        assert resp.status_code == 303
        assert "error" in resp.headers["location"]

    def test_delete_removes_source(self, api_client):
        """POST /sources/tracked/{id}/delete removes source."""
        ts_id = _seed_tracked_source(api_client)
        resp = api_client.post(
            f"/sources/tracked/{ts_id}/delete",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "已删除" in resp.headers["location"] or "info" in resp.headers["location"]


# ── Test: Refresh ──────────────────────────────────────────────────────────


class TestTrackedSourceRefresh:
    """P2-S.3.2 req 3-6: Refresh discovers entries, marks new/existing/failed."""

    def test_refresh_discovers_new_entries(self, api_client, monkeypatch):
        """Refresh calls fetch_homepage and creates tracked source entries."""
        _mock_allin_homepage_fetch(monkeypatch)
        _mock_allin_episode_fetch(monkeypatch)

        ts_id = _seed_tracked_source(api_client)
        resp = api_client.post(
            f"/sources/tracked/{ts_id}/refresh",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "success" in resp.headers["location"]

        # Entries should exist
        resp2 = api_client.get(f"/sources/tracked/{ts_id}/entries")
        assert resp2.status_code == 200
        # 3 episodes from homepage, all should be preview_ready after refresh
        assert "待导入" in resp2.text

    def test_refresh_marks_existing_entries(self, api_client, monkeypatch):
        """Second refresh marks previously-discovered entries as existing."""
        _mock_allin_homepage_fetch(monkeypatch)
        _mock_allin_episode_fetch(monkeypatch)

        ts_id = _seed_tracked_source(api_client)

        # First refresh
        api_client.post(f"/sources/tracked/{ts_id}/refresh", follow_redirects=False)

        # Second refresh — same homepage
        _mock_allin_homepage_fetch(monkeypatch)
        resp = api_client.post(
            f"/sources/tracked/{ts_id}/refresh",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        decoded = unquote(resp.headers["location"])
        assert "已存在" in decoded

    def test_refresh_no_duplicate_entries(self, api_client, monkeypatch):
        """Two refreshes shouldn't create duplicate entry rows."""
        _mock_allin_homepage_fetch(monkeypatch)
        _mock_allin_episode_fetch(monkeypatch)

        ts_id = _seed_tracked_source(api_client)

        # Two refreshes
        api_client.post(f"/sources/tracked/{ts_id}/refresh", follow_redirects=False)
        _mock_allin_homepage_fetch(monkeypatch)
        api_client.post(f"/sources/tracked/{ts_id}/refresh", follow_redirects=False)

        # Count entries via DB
        from podcast_research.db.repository import list_tracked_source_entries
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            entries = list_tracked_source_entries(session, ts_id)
            # 3 unique episodes, no duplicates
            urls = [e["url"] for e in entries]
            assert len(urls) == len(set(urls)) == 3
        finally:
            session.close()

    def test_refresh_handles_fetch_failure(self, api_client, monkeypatch):
        """When fetch_homepage throws, source status becomes failed."""
        def mock_fetch_fail(self, url):
            raise RuntimeError("Connection refused")

        monkeypatch.setattr(
            "podcast_research.adapters.external_html_notes.ExternalHTMLNotesAdapter._fetch_html",
            mock_fetch_fail,
        )

        ts_id = _seed_tracked_source(api_client)
        resp = api_client.post(
            f"/sources/tracked/{ts_id}/refresh",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "error" in resp.headers["location"]

        # Verify source status is failed
        from podcast_research.db.repository import get_tracked_source
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            ts = get_tracked_source(session, ts_id)
            assert ts is not None
            assert ts["status"] in ("failed", "degraded")
        finally:
            session.close()

    def test_refresh_generates_previews(self, api_client, monkeypatch):
        """New entries get preview_ready status with preview_id."""
        _mock_allin_homepage_fetch(monkeypatch)
        _mock_allin_episode_fetch(monkeypatch)

        ts_id = _seed_tracked_source(api_client)
        api_client.post(f"/sources/tracked/{ts_id}/refresh", follow_redirects=False)

        from podcast_research.db.repository import list_tracked_source_entries
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            entries = list_tracked_source_entries(session, ts_id)
            for e in entries:
                assert e["status"] == "preview_ready"
                assert e["preview_id"] != ""
                assert len(e["preview_id"]) == 12
        finally:
            session.close()

    def test_single_entry_failure_doesnt_block_others(self, api_client, monkeypatch):
        """When one episode fails to parse, others still succeed.

        build_import_preview catches fetch errors and returns minimal-quality
        preview; the service detects minimal quality and marks the entry as failed.
        """
        def mock_fetch(self, url):
            if "/episodes/" not in url:
                return MOCK_ALLIN_HOMEPAGE_HTML
            # Episode 2 fails (raises, producing minimal-quality preview → failed)
            if "ep2" in url:
                raise RuntimeError("Parse failed for ep2")
            return MOCK_ALLIN_EPISODE_HTML

        monkeypatch.setattr(
            "podcast_research.adapters.external_html_notes.ExternalHTMLNotesAdapter._fetch_html",
            mock_fetch,
        )

        ts_id = _seed_tracked_source(api_client)
        resp = api_client.post(
            f"/sources/tracked/{ts_id}/refresh",
            follow_redirects=False,
        )
        assert resp.status_code == 303

        from podcast_research.db.repository import list_tracked_source_entries
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            entries = list_tracked_source_entries(session, ts_id)
            # All 3 episodes: ep1, ep3 → preview_ready, ep2 → failed (minimal quality)
            assert len(entries) == 3
            statuses = {e["status"] for e in entries}
            assert "preview_ready" in statuses
            assert "failed" in statuses
        finally:
            session.close()


# ── Test: Import ───────────────────────────────────────────────────────────


class TestTrackedSourceImport:
    """P2-S.3.2 req 7-11, 13-16: Import with recommendations."""

    def test_import_single_entry(self, api_client, monkeypatch, tmp_path):
        """Import a single preview_ready entry."""
        _mock_allin_homepage_fetch(monkeypatch)
        _mock_allin_episode_fetch(monkeypatch)

        ts_id = _seed_tracked_source(api_client)
        api_client.post(f"/sources/tracked/{ts_id}/refresh", follow_redirects=False)

        # Get entry IDs
        from podcast_research.db.repository import list_tracked_source_entries
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            entries = list_tracked_source_entries(session, ts_id)
            preview_entries = [e for e in entries if e["status"] == "preview_ready"]
            assert len(preview_entries) > 0
            entry_id = preview_entries[0]["id"]
        finally:
            session.close()

        # Import single entry
        resp = api_client.post(
            f"/sources/tracked/{ts_id}/entries/{entry_id}/import",
            data={"action": "import_as_deep_notes_derived_only"},
            follow_redirects=False,
        )
        assert resp.status_code == 303

        # Check entry status updated
        from podcast_research.db.repository import get_tracked_source_entry
        session = get_session()
        try:
            entry = get_tracked_source_entry(session, entry_id)
            assert entry is not None
            assert entry["status"] == "imported"
        finally:
            session.close()

    def test_batch_import_selected(self, api_client, monkeypatch):
        """Batch import only selected entries."""
        _mock_allin_homepage_fetch(monkeypatch)
        _mock_allin_episode_fetch(monkeypatch)

        ts_id = _seed_tracked_source(api_client)
        api_client.post(f"/sources/tracked/{ts_id}/refresh", follow_redirects=False)

        # Get preview_ready entry IDs
        from podcast_research.db.repository import list_tracked_source_entries
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            entries = list_tracked_source_entries(session, ts_id)
            preview_entries = [e for e in entries if e["status"] == "preview_ready"]
            # Import only the first 2
            ids_to_import = [e["id"] for e in preview_entries[:2]]
            ids_str = ",".join(str(i) for i in ids_to_import)
        finally:
            session.close()

        resp = api_client.post(
            f"/sources/tracked/{ts_id}/import",
            data={
                "entry_ids": ids_str,
                "action": "import_as_deep_notes_derived_only",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303

        # Verify only selected entries are imported
        session = get_session()
        try:
            entries = list_tracked_source_entries(session, ts_id)
            for e in entries:
                if e["id"] in ids_to_import:
                    assert e["status"] == "imported", f"Entry {e['id']} should be imported"
                else:
                    assert e["status"] != "imported", f"Entry {e['id']} should NOT be imported"
        finally:
            session.close()

    def test_skip_entry(self, api_client, monkeypatch):
        """Skip a preview_ready entry."""
        _mock_allin_homepage_fetch(monkeypatch)
        _mock_allin_episode_fetch(monkeypatch)

        ts_id = _seed_tracked_source(api_client)
        api_client.post(f"/sources/tracked/{ts_id}/refresh", follow_redirects=False)

        from podcast_research.db.repository import list_tracked_source_entries
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            entries = list_tracked_source_entries(session, ts_id)
            preview_entries = [e for e in entries if e["status"] == "preview_ready"]
            entry_id = preview_entries[0]["id"]
        finally:
            session.close()

        resp = api_client.post(
            f"/sources/tracked/{ts_id}/entries/{entry_id}/skip",
            follow_redirects=False,
        )
        assert resp.status_code == 303

        from podcast_research.db.repository import get_tracked_source_entry
        session = get_session()
        try:
            entry = get_tracked_source_entry(session, entry_id)
            assert entry["status"] == "skipped"
        finally:
            session.close()

    def test_import_deep_notes_creates_file(self, api_client, monkeypatch, tmp_path):
        """Import actually creates a Deep Notes file via execute_import_action."""
        _mock_allin_homepage_fetch(monkeypatch)
        _mock_allin_episode_fetch(monkeypatch)

        ts_id = _seed_tracked_source(api_client)
        api_client.post(f"/sources/tracked/{ts_id}/refresh", follow_redirects=False)

        from podcast_research.db.repository import list_tracked_source_entries
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            entries = list_tracked_source_entries(session, ts_id)
            preview_entries = [e for e in entries if e["status"] == "preview_ready"]
            entry_id = preview_entries[0]["id"]
        finally:
            session.close()

        # Import
        api_client.post(
            f"/sources/tracked/{ts_id}/entries/{entry_id}/import",
            data={"action": "import_as_deep_notes_derived_only"},
            follow_redirects=False,
        )

        # Check Deep Notes file was created
        import json
        from pathlib import Path
        settings_path = tmp_path / "user_settings_tracked.json"
        settings = json.loads(settings_path.read_text())
        vault = Path(settings["obsidian_vault_path"])
        deep_notes_dir = vault / "01_Reports" / "DeepNotes"
        assert deep_notes_dir.exists()
        md_files = list(deep_notes_dir.glob("*.md"))
        assert len(md_files) >= 1

    def test_batch_import_shows_per_entry_results(self, api_client, monkeypatch):
        """After batch import, entries page shows per-entry results section."""
        _mock_allin_homepage_fetch(monkeypatch)
        _mock_allin_episode_fetch(monkeypatch)

        ts_id = _seed_tracked_source(api_client)
        api_client.post(f"/sources/tracked/{ts_id}/refresh", follow_redirects=False)

        from podcast_research.db.repository import list_tracked_source_entries
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            entries = list_tracked_source_entries(session, ts_id)
            preview_entries = [e for e in entries if e["status"] == "preview_ready"]
            ids_to_import = [e["id"] for e in preview_entries[:2]]
            ids_str = ",".join(str(i) for i in ids_to_import)
        finally:
            session.close()

        # Batch import → should redirect to entries page with results
        resp = api_client.post(
            f"/sources/tracked/{ts_id}/import",
            data={
                "entry_ids": ids_str,
                "action": "import_as_deep_notes_derived_only",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303

        # Follow redirect to entries page
        location = resp.headers["location"]
        resp2 = api_client.get(location)
        assert resp2.status_code == 200
        # Should have the import results section
        assert "导入结果" in resp2.text
        # Should have per-entry success indicators
        assert "✓" in resp2.text


# ── Test: Entry Filters ────────────────────────────────────────────────────


class TestTrackedSourceEntriesFilters:
    """P2-S.3.2 req 12: Filter entries by status."""

    def test_filter_preview_ready(self, api_client, monkeypatch):
        """status=preview_ready filter shows only preview_ready entries."""
        _mock_allin_homepage_fetch(monkeypatch)
        _mock_allin_episode_fetch(monkeypatch)

        ts_id = _seed_tracked_source(api_client)
        api_client.post(f"/sources/tracked/{ts_id}/refresh", follow_redirects=False)

        resp = api_client.get(
            f"/sources/tracked/{ts_id}/entries?status=preview_ready"
        )
        assert resp.status_code == 200
        # All entries should be preview_ready after first refresh
        from podcast_research.db.repository import list_tracked_source_entries
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            entries = list_tracked_source_entries(session, ts_id, status_filter="preview_ready")
            assert all(e["status"] == "preview_ready" for e in entries)
        finally:
            session.close()

    def test_filter_failed(self, api_client, monkeypatch):
        """status=failed shows only failed entries (minimal-quality previews)."""
        # Make second episode fail → minimal quality → failed
        def mock_fetch(self, url):
            if "/episodes/" not in url:
                return MOCK_ALLIN_HOMEPAGE_HTML
            if "ep2" in url:
                raise RuntimeError("Parse failed")
            return MOCK_ALLIN_EPISODE_HTML

        monkeypatch.setattr(
            "podcast_research.adapters.external_html_notes.ExternalHTMLNotesAdapter._fetch_html",
            mock_fetch,
        )

        ts_id = _seed_tracked_source(api_client)
        api_client.post(f"/sources/tracked/{ts_id}/refresh", follow_redirects=False)

        resp = api_client.get(
            f"/sources/tracked/{ts_id}/entries?status=failed"
        )
        assert resp.status_code == 200

        from podcast_research.db.repository import list_tracked_source_entries
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            entries = list_tracked_source_entries(session, ts_id, status_filter="failed")
            assert len(entries) == 1
            assert entries[0]["status"] == "failed"
        finally:
            session.close()

    def test_no_filter_shows_all(self, api_client, monkeypatch):
        """Without filter, all entries are shown across statuses."""
        # Create mix of statuses: ep1,ep3 → preview_ready, ep2 → failed
        def mock_fetch(self, url):
            if "/episodes/" not in url:
                return MOCK_ALLIN_HOMEPAGE_HTML
            if "ep2" in url:
                raise RuntimeError("fail")
            return MOCK_ALLIN_EPISODE_HTML

        monkeypatch.setattr(
            "podcast_research.adapters.external_html_notes.ExternalHTMLNotesAdapter._fetch_html",
            mock_fetch,
        )

        ts_id = _seed_tracked_source(api_client)
        api_client.post(f"/sources/tracked/{ts_id}/refresh", follow_redirects=False)

        resp = api_client.get(f"/sources/tracked/{ts_id}/entries")
        assert resp.status_code == 200

        from podcast_research.db.repository import list_tracked_source_entries
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            entries = list_tracked_source_entries(session, ts_id)
            assert len(entries) == 3
            statuses = {e["status"] for e in entries}
            assert "preview_ready" in statuses
            assert "failed" in statuses
        finally:
            session.close()


# ── Test: Route Smoke ─────────────────────────────────────────────────────


class TestRouteSmoke:
    """P2-S.3.2 req 17: All routes return expected status codes."""

    def test_all_routes_return_200_or_303(self, api_client, monkeypatch):
        """Smoke test: key routes respond without 500 errors."""
        _mock_allin_homepage_fetch(monkeypatch)
        _mock_allin_episode_fetch(monkeypatch)

        # GET routes that should return 200
        routes_200 = ["/sources/tracked", "/sources/tracked/add"]
        for route in routes_200:
            resp = api_client.get(route)
            assert resp.status_code == 200, f"{route} returned {resp.status_code}"

        # POST profile → 200 (renders preview page)
        resp = api_client.post(
            "/sources/tracked/profile",
            data={
                "homepage_url": "https://chirs-ma.github.io/allin-podcast-zh-notes/",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200

    def test_batch_import_without_selection_shows_error(self, api_client, monkeypatch):
        """Batch import with no entry_ids shows error."""
        _mock_allin_homepage_fetch(monkeypatch)
        ts_id = _seed_tracked_source(api_client)

        resp = api_client.post(
            f"/sources/tracked/{ts_id}/import",
            data={"entry_ids": "", "action": "import_as_deep_notes_derived_only"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "error" in resp.headers["location"]


# ── Test: Edge Cases ───────────────────────────────────────────────────────


class TestTrackedSourceEdgeCases:
    """P2-S.3.2 edge cases."""

    def test_refresh_empty_homepage(self, api_client, monkeypatch):
        """Homepage with no episodes returns appropriate message."""
        def mock_fetch(self, url):
            return "<html><body><div class='episode-list'></div></body></html>"

        monkeypatch.setattr(
            "podcast_research.adapters.external_html_notes.ExternalHTMLNotesAdapter._fetch_html",
            mock_fetch,
        )

        ts_id = _seed_tracked_source(api_client)
        resp = api_client.post(
            f"/sources/tracked/{ts_id}/refresh",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        decoded = unquote(resp.headers["location"])
        assert "未发现" in decoded or "无内容" in decoded

    def test_add_empty_url(self, api_client):
        """Empty URL at profile returns error redirect."""
        resp = api_client.post(
            "/sources/tracked/profile",
            data={"homepage_url": " ", "name": ""},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        decoded = unquote(resp.headers["location"])
        assert "error" in decoded

    def test_default_import_for_new_entries(self, api_client, monkeypatch):
        """New entry preview gets appropriate recommendation from build_import_preview."""
        _mock_allin_homepage_fetch(monkeypatch)
        _mock_allin_episode_fetch(monkeypatch)

        ts_id = _seed_tracked_source(api_client)
        api_client.post(f"/sources/tracked/{ts_id}/refresh", follow_redirects=False)

        # Entries page should show available actions for preview_ready entries
        resp = api_client.get(f"/sources/tracked/{ts_id}/entries")
        assert resp.status_code == 200
        # The template should contain import-related content
        assert "导入" in resp.text
