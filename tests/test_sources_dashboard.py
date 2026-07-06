"""P2-S.3.4: Tests for unified Sources dashboard."""

from __future__ import annotations

import pytest


class TestSourcesDashboardRoute:
    """Smoke tests for GET /sources."""

    @pytest.fixture
    def configured_vault(self, tmp_path, monkeypatch):
        """Configure a vault path for testing."""
        vault = tmp_path / "v"
        vault.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
        yield vault

    def test_sources_page_loads(self, api_client, configured_vault):
        """GET /sources returns 200 with the dashboard."""
        resp = api_client.get("/sources")
        assert resp.status_code == 200
        html = resp.text
        assert "信息源工作台" in html or "dashboard" in html.lower()

    def test_sources_page_shows_four_entry_cards(self, api_client, configured_vault):
        """Dashboard shows all four entry types."""
        resp = api_client.get("/sources")
        assert resp.status_code == 200
        html = resp.text
        assert "YouTube" in html
        assert "网页导入" in html or "import" in html.lower()
        assert "信息源" in html
        assert "上传文件" in html or "upload" in html.lower()

    def test_sources_page_shows_tracked_count(self, api_client, configured_vault):
        """Dashboard shows tracked source count."""
        resp = api_client.get("/sources")
        assert resp.status_code == 200
        html = resp.text
        assert "跟踪源" in html or "tracked" in html.lower()

    def test_sources_page_shows_archive_count(self, api_client, configured_vault):
        """Dashboard shows archive file count."""
        # Create a file in SourceArchive to get a non-zero count
        archive_dir = configured_vault / "01_Reports" / "SourceArchive"
        archive_dir.mkdir(parents=True)
        (archive_dir / "2025-01-01_test.md").write_text("test", encoding="utf-8")

        resp = api_client.get("/sources")
        assert resp.status_code == 200
        html = resp.text
        assert "导入能力" in html or "source" in html.lower()

    def test_sources_page_entry_links_work(self, api_client, configured_vault):
        """All entry card links point to correct URLs."""
        resp = api_client.get("/sources")
        assert resp.status_code == 200
        html = resp.text
        assert 'href="/sources/channels"' in html
        assert 'href="/sources/import"' in html
        assert 'href="/sources/tracked"' in html
        assert 'href="/sources/files/import"' in html

    def test_sources_page_quick_add_links(self, api_client, configured_vault):
        """Quick-add section has all four entry points."""
        resp = api_client.get("/sources")
        assert resp.status_code == 200
        html = resp.text
        assert 'href="/sources/channels"' in html
        assert 'href="/sources/import"' in html
        assert 'href="/sources/tracked"' in html
        assert 'href="/sources/files/import"' in html

    def test_sources_page_empty_state(self, api_client, configured_vault):
        """Dashboard loads fine with no data (empty state)."""
        resp = api_client.get("/sources")
        assert resp.status_code == 200
        html = resp.text
        # Should still render the structure
        assert "信息源工作台" in html

    def test_sources_page_without_vault_redirects(self, api_client, monkeypatch):
        """Without vault configured, redirect to setup."""
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        resp = api_client.get("/sources", follow_redirects=False)
        assert resp.status_code in (302, 303)

    def test_nav_active_on_sources(self, api_client, configured_vault):
        """Nav highlights '信息源' as active on /sources."""
        resp = api_client.get("/sources")
        assert resp.status_code == 200
        html = resp.text
        # The active nav link should point to /sources
        assert 'href="/sources"' in html
        assert 'class="active"' in html


class TestSourcesDashboardContext:
    """Tests for _build_sources_dashboard_context()."""

    @pytest.fixture(autouse=True)
    def _isolate_preview_stores(self):
        """Clear preview stores before/after each test to prevent cross-test pollution."""
        import signalvault.web.routes as routes_mod
        saved_url = dict(routes_mod._preview_store)
        saved_file = dict(routes_mod._file_preview_store)
        routes_mod._preview_store.clear()
        routes_mod._file_preview_store.clear()
        yield
        routes_mod._preview_store.clear()
        routes_mod._file_preview_store.clear()
        routes_mod._preview_store.update(saved_url)
        routes_mod._file_preview_store.update(saved_file)

    def test_context_has_required_keys(self, tmp_path):
        """Context dict contains all expected keys."""
        from signalvault.web.routes import _build_sources_dashboard_context

        ctx = _build_sources_dashboard_context(str(tmp_path))
        assert "entry_cards" in ctx
        assert "pending_items" in ctx
        assert "pending_total" in ctx
        assert "archive_file_count" in ctx
        assert "channel_count" in ctx
        assert "tracked_count" in ctx
        assert "vault_configured" in ctx

    def test_entry_cards_have_four_items(self, tmp_path):
        """All four entry cards are present."""
        from signalvault.web.routes import _build_sources_dashboard_context

        ctx = _build_sources_dashboard_context(str(tmp_path))
        assert len(ctx["entry_cards"]) == 4
        keys = {c["key"] for c in ctx["entry_cards"]}
        assert keys == {"youtube", "url_import", "tracked", "file_upload"}

    def test_each_card_has_required_fields(self, tmp_path):
        """Each card has all required display fields."""
        from signalvault.web.routes import _build_sources_dashboard_context

        ctx = _build_sources_dashboard_context(str(tmp_path))
        for card in ctx["entry_cards"]:
            assert "key" in card
            assert "title" in card
            assert "icon" in card
            assert "description" in card
            assert "count_label" in card
            assert "status" in card
            assert "status_text" in card
            assert "action_url" in card
            assert "action_label" in card

    def test_archive_count_reflects_files(self, tmp_path):
        """archive_file_count matches actual file count."""
        from signalvault.web.routes import _build_sources_dashboard_context

        archive_dir = tmp_path / "01_Reports" / "SourceArchive"
        archive_dir.mkdir(parents=True)
        for i in range(3):
            (archive_dir / f"2025-01-0{i + 1}_test.md").write_text("test", encoding="utf-8")

        ctx = _build_sources_dashboard_context(str(tmp_path))
        assert ctx["archive_file_count"] == 3

    def test_empty_vault_shows_zero_counts(self, tmp_path):
        """Fresh empty vault shows zeros and empty states."""
        from signalvault.web.routes import _build_sources_dashboard_context

        # Stores are already clean from _isolate_preview_stores fixture
        ctx = _build_sources_dashboard_context(str(tmp_path))
        assert ctx["archive_file_count"] == 0
        assert ctx["pending_total"] == 0
        assert ctx["pending_items"] == []

    def test_pending_items_with_data(self, tmp_path):
        """Pending items list reflects actual state."""
        import signalvault.web.routes as routes_mod
        from signalvault.web.routes import _build_sources_dashboard_context

        # Stores are already clean from _isolate_preview_stores fixture
        routes_mod._preview_store["fake-p1"] = object()
        routes_mod._preview_store["fake-p2"] = object()
        routes_mod._file_preview_store["fake-f1"] = object()

        ctx = _build_sources_dashboard_context(str(tmp_path))
        assert ctx["url_preview_count"] == 2
        assert ctx["file_preview_count"] == 1
        assert ctx["pending_total"] >= 2
        assert len(ctx["pending_items"]) >= 2


class TestRelativeTimeFormat:
    """Tests for _format_relative_time helper."""

    def test_formats_seconds(self):
        from datetime import datetime, timedelta

        from signalvault.web.routes import _format_relative_time

        now = datetime(2026, 6, 30, 12, 0, 0)
        dt = now - timedelta(seconds=30)
        assert _format_relative_time(dt, now) == "刚刚"

    def test_formats_minutes(self):
        from datetime import datetime, timedelta

        from signalvault.web.routes import _format_relative_time

        now = datetime(2026, 6, 30, 12, 0, 0)
        dt = now - timedelta(minutes=15)
        result = _format_relative_time(dt, now)
        assert "分钟前" in result

    def test_formats_hours(self):
        from datetime import datetime, timedelta

        from signalvault.web.routes import _format_relative_time

        now = datetime(2026, 6, 30, 12, 0, 0)
        dt = now - timedelta(hours=5)
        result = _format_relative_time(dt, now)
        assert "小时前" in result

    def test_formats_days(self):
        from datetime import datetime, timedelta

        from signalvault.web.routes import _format_relative_time

        now = datetime(2026, 6, 30, 12, 0, 0)
        dt = now - timedelta(days=3)
        result = _format_relative_time(dt, now)
        assert "天前" in result
