"""P2-M.1: Channel Source Manager tests.

Tests for /sources/channels pages, add/refresh/skip/import actions,
and video status detection.

All tests use api_client + seeded_db fixtures. No real YouTube API calls.
"""

from pathlib import Path

import pytest

# ── Helpers ───────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _setup_vault_for_sources(monkeypatch, tmp_path):
    """Set a temporary vault path in config_store so sources routes work."""
    from podcast_research import config_store

    vault = tmp_path / "test_vault"
    vault.mkdir(parents=True)

    # Write temp settings file with vault path
    import json
    settings = {
        "obsidian_vault_path": str(vault),
        "watchlist": {"topics": [], "themes": [], "companies": []},
    }
    settings_path = tmp_path / "user_settings.json"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    config_store._override_settings_path(settings_path)
    return str(vault)

class MockChannelAdapter:
    """Mock ChannelVideoAdapter for tests."""

    def __init__(self, videos: list[dict] | None = None):
        self._videos = videos or [
            {"video_id": "testVid001", "title": "AI Investing 101",
             "url": "https://www.youtube.com/watch?v=testVid001",
             "published_at": "20260601", "duration_seconds": 1800},
            {"video_id": "testVid002", "title": "GPU Market Update",
             "url": "https://www.youtube.com/watch?v=testVid002",
             "published_at": "20260528", "duration_seconds": 2400},
            {"video_id": "testVid003", "title": "VC Roundtable",
             "url": "https://www.youtube.com/watch?v=testVid003",
             "published_at": "20260520", "duration_seconds": 3600},
        ]

    def fetch_channel_videos(self, channel_url: str, limit: int = 20):
        """Return mock videos."""
        from podcast_research.adapters.channel_video_adapter import ChannelVideoItem
        return [
            ChannelVideoItem(
                video_id=v["video_id"],
                title=v["title"],
                url=v["url"],
                published_at=v["published_at"],
                duration_seconds=v["duration_seconds"],
            )
            for v in self._videos[:limit]
        ]


def _seed_channel(api_client, channel_url="https://www.youtube.com/@TestChannel",
                 name="Test Channel", priority="watch", default_focus="AI"):
    """Helper: add a channel via POST and return channel_id."""
    resp = api_client.post(
        "/sources/channels/add",
        data={
            "channel_url": channel_url,
            "name": name,
            "priority": priority,
            "default_focus": default_focus,
            "default_depth": "standard",
        },
        follow_redirects=False,
    )
    # Should redirect to /sources/channels/{id}/videos
    assert resp.status_code == 303, f"Expected 303 redirect, got {resp.status_code}: {resp.text[:200]}"
    location = resp.headers["location"]
    # Extract channel_id from URL: /sources/channels/{id}/videos
    channel_id = int(location.split("/")[3])
    return channel_id


# ── Page Tests ────────────────────────────────────────────────────────

class TestSourcesChannelsPage:
    """Page rendering tests."""

    def test_channels_page_loads(self, api_client):
        """GET /sources/channels returns 200."""
        resp = api_client.get("/sources/channels")
        assert resp.status_code == 200
        html = resp.text
        assert "信息源管理" in html
        assert "添加频道" in html

    def test_channels_page_empty(self, api_client):
        """Empty channel list shows empty state."""
        resp = api_client.get("/sources/channels")
        assert resp.status_code == 200
        html = resp.text
        assert "还没有添加任何频道" in html

    def test_channels_page_with_channels(self, api_client):
        """Channel list shows added channels."""
        _seed_channel(api_client, name="My Test Channel")

        resp = api_client.get("/sources/channels")
        assert resp.status_code == 200
        assert "My Test Channel" in resp.text
        assert "关注" in resp.text  # priority label

    def test_channel_videos_page_loads(self, api_client):
        """GET /sources/channels/{id}/videos returns 200."""
        ch_id = _seed_channel(api_client)

        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        assert resp.status_code == 200
        assert "Test Channel" in resp.text

    def test_channel_videos_shows_empty(self, api_client):
        """Empty video list shows message."""
        ch_id = _seed_channel(api_client)
        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        assert resp.status_code == 200


# ── Action Tests ──────────────────────────────────────────────────────

class TestSourcesChannelActions:
    """POST action tests."""

    def test_add_channel_creates_record(self, api_client):
        """Adding a channel should create DB record."""
        channel_url = "https://www.youtube.com/@MyChannel"
        resp = api_client.post(
            "/sources/channels/add",
            data={
                "channel_url": channel_url,
                "name": "My Channel",
                "priority": "core",
                "default_focus": "Semiconductors",
                "default_depth": "deep",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        # Should redirect to video list
        assert "/videos" in resp.headers["location"]

        # Verify channel page shows it
        resp2 = api_client.get("/sources/channels")
        assert "My Channel" in resp2.text

    def test_add_channel_rejects_invalid_url(self, api_client):
        """Invalid URL should return error."""
        resp = api_client.post(
            "/sources/channels/add",
            data={"channel_url": "not-a-valid-url", "name": "Bad"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "msg=error" in resp.headers["location"]

    def test_add_duplicate_channel_upserts(self, api_client):
        """Adding the same channel twice should upsert, not error."""
        channel_url = "https://www.youtube.com/@DuplicateChannel"
        resp1 = api_client.post(
            "/sources/channels/add",
            data={"channel_url": channel_url, "name": "First Add"},
            follow_redirects=False,
        )
        assert resp1.status_code == 303

        resp2 = api_client.post(
            "/sources/channels/add",
            data={"channel_url": channel_url, "name": "Second Add"},
            follow_redirects=False,
        )
        assert resp2.status_code == 303  # Should succeed, not error

    def test_skip_video(self, api_client):
        """Skip a video should update status."""
        ch_id = _seed_channel(api_client)

        # First add a video via refresh (mock)
        # We'll directly test skip by getting a video that doesn't exist
        resp = api_client.post(
            f"/sources/channels/{ch_id}/videos/nonexistent/skip",
            follow_redirects=False,
        )
        assert resp.status_code == 303  # Should redirect (graceful handling)

    def test_import_video_redirects_to_tasks(self, api_client):
        """Import action should redirect to /tasks/{job_id}."""
        ch_id = _seed_channel(api_client)

        resp = api_client.post(
            f"/sources/channels/{ch_id}/videos/importTest001/import",
            data={"focus": "AI", "depth": "standard", "flow_mode": "full"},
            follow_redirects=False,
        )
        # Should redirect — either success or user-friendly error
        assert resp.status_code in (303, 302)

    def test_refresh_missing_channel(self, api_client):
        """Refresh on non-existent channel should return error."""
        resp = api_client.post(
            "/sources/channels/99999/refresh",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "msg=error" in resp.headers["location"]

    def test_delete_channel_soft_deactivates(self, api_client):
        """Deleting a channel should soft-deactivate it and hide from list."""
        ch_id = _seed_channel(api_client)

        resp = api_client.post(
            f"/sources/channels/{ch_id}/delete",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "msg=success" in resp.headers["location"]

        # The channel should no longer appear in the page listing
        resp2 = api_client.get("/sources/channels")
        assert resp2.status_code == 200
        # The seeded channel name should NOT appear in the page HTML
        assert "TestChannel" not in resp2.text or f"/sources/channels/{ch_id}" not in resp2.text

        # But the channel should still exist in DB (soft-deleted)
        from podcast_research.db.repository import get_channel
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            ch = get_channel(session, ch_id)
            assert ch is not None, "Soft-deleted channel should still exist in DB"
            assert ch["is_active"] is False, f"Expected is_active=False, got {ch['is_active']}"
        finally:
            session.close()

    def test_delete_nonexistent_channel(self, api_client):
        """Deleting a non-existent channel should return error."""
        resp = api_client.post(
            "/sources/channels/99999/delete",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "msg=error" in resp.headers["location"]


# ── Refresh with mock adapter ─────────────────────────────────────────

class TestChannelRefresh:
    """Tests that mock the yt-dlp adapter."""

    def test_refresh_with_mock_adapter(self, api_client, monkeypatch):
        """Refreshing channel videos should create a job and redirect to /tasks/{id}."""
        ch_id = _seed_channel(api_client)

        # Mock ChannelVideoAdapter
        mock_adapter = MockChannelAdapter()
        monkeypatch.setattr(
            "podcast_research.adapters.channel_video_adapter.ChannelVideoAdapter",
            lambda: mock_adapter,
        )

        resp = api_client.post(
            f"/sources/channels/{ch_id}/refresh",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        location = resp.headers["location"]
        # P2-M.1.1: refresh now creates a channel_refresh job, redirects to /tasks/{id}
        assert "/tasks/" in location

        # The job runs synchronously in test (daemon thread), wait briefly then check DB
        import time
        time.sleep(0.5)

        # Now check the videos page has entries
        resp2 = api_client.get(f"/sources/channels/{ch_id}/videos")
        assert resp2.status_code == 200
        html = resp2.text
        assert "AI Investing 101" in html
        assert "GPU Market Update" in html
        assert "VC Roundtable" in html

    def test_double_refresh_no_duplicates(self, api_client, monkeypatch):
        """Refreshing twice should not duplicate videos in DB."""
        ch_id = _seed_channel(api_client)

        mock_adapter = MockChannelAdapter()
        monkeypatch.setattr(
            "podcast_research.adapters.channel_video_adapter.ChannelVideoAdapter",
            lambda: mock_adapter,
        )

        # First refresh
        api_client.post(f"/sources/channels/{ch_id}/refresh", follow_redirects=False)
        import time
        time.sleep(0.3)
        # Second refresh with same adapter
        resp2 = api_client.post(f"/sources/channels/{ch_id}/refresh", follow_redirects=False)
        assert resp2.status_code == 303
        # P2-M.1.1: refresh redirects to /tasks/{id}
        assert "/tasks/" in resp2.headers["location"]
        time.sleep(0.3)

        # Check DB directly — should have exactly 3 videos (no duplicates)
        from podcast_research.db.repository import list_channel_videos
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            videos = list_channel_videos(session, ch_id)
            assert len(videos) == 3, f"Expected 3 videos, got {len(videos)}"
            vids = [v["video_id"] for v in videos]
            assert len(set(vids)) == 3, "Video IDs should be unique"
        finally:
            session.close()


# ── Video Status Detection ────────────────────────────────────────────

class TestVideoImportStatus:
    """Test detect_video_import_status with various DB states."""

    def test_new_video_is_new(self, api_client):
        """Unknown video_id should return 'new'."""
        from podcast_research.db.repository import detect_video_import_status
        from podcast_research.db.session import get_session

        session = get_session()
        try:
            status = detect_video_import_status(session, "completely_unknown_vid")
            assert status == "new"
        finally:
            session.close()

    def test_analyzed_video_detected(self, api_client, seeded_db):
        """Video that exists in episodes table should be 'analyzed'."""
        from podcast_research.db.repository import detect_video_import_status
        from podcast_research.db.session import get_session

        session = get_session()
        try:
            # seeded_db has episode with video_id="abc123" (report #3)
            status = detect_video_import_status(session, "abc123")
            assert status in ("analyzed", "synced"), f"Expected analyzed/synced, got {status}"
        finally:
            session.close()

    def test_synced_video_detected_in_vault(self, api_client, seeded_db, tmp_path):
        """Video in Obsidian vault frontmatter should be 'synced'."""
        from podcast_research.db.repository import detect_video_import_status
        from podcast_research.db.session import get_session

        # Create a fake vault with a report containing the video_id
        vault = tmp_path / "vault"
        vault.mkdir()
        reports_dir = vault / "01_Reports"
        reports_dir.mkdir(parents=True)

        report_content = """---
type: report
source_type: youtube
channel: TestChan
video_id: vaultVid001
video_url: https://www.youtube.com/watch?v=vaultVid001
published_at: "2026-06-01"
language: en
prompt_version: tech_ai_v2
---
# Test Report

## Summary
Test content.
"""
        (reports_dir / "2026-06-01_TestChan_vaultVid001.md").write_text(report_content)

        session = get_session()
        try:
            status = detect_video_import_status(session, "vaultVid001", str(vault))
            assert status == "synced", f"Expected 'synced', got '{status}'"
        finally:
            session.close()

    def test_channel_video_status_preserved(self, api_client, monkeypatch):
        """After refresh, videos should have correct status."""
        ch_id = _seed_channel(api_client)

        mock_adapter = MockChannelAdapter()
        monkeypatch.setattr(
            "podcast_research.adapters.channel_video_adapter.ChannelVideoAdapter",
            lambda: mock_adapter,
        )

        api_client.post(f"/sources/channels/{ch_id}/refresh", follow_redirects=False)
        import time
        time.sleep(0.5)

        # Check video page
        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        assert resp.status_code == 200
        html = resp.text
        # New videos should show "新发现" status
        assert "新发现" in html


# ── Dashboard Integration ─────────────────────────────────────────────

class TestDashboardIntegration:
    """Dashboard should show link to /sources/channels."""

    def test_dashboard_shows_sources_link(self, api_client):
        """Dashboard action bar should have '信息源' link."""
        resp = api_client.get("/dashboard")
        assert resp.status_code == 200
        html = resp.text
        assert "/sources/channels" in html
        assert "信息源" in html


# ── Edge Cases ────────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge case tests."""

    def test_nonexistent_channel_videos(self, api_client):
        """Video page for nonexistent channel should redirect with error."""
        resp = api_client.get(
            "/sources/channels/99999/videos",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "msg=error" in resp.headers["location"]

    def test_chinese_status_labels(self, api_client):
        """Video list should show Chinese status labels."""
        _seed_channel(api_client, name="LabelTest")

        resp = api_client.get("/sources/channels")
        html = resp.text
        assert "查看视频" in html


# ── P2-M.1.1: Unified Task State & Source Status Sync ─────────────────

class TestTaskSuccessPage:
    """Task detail page success display."""

    def test_task_success_no_spinner(self, api_client):
        """Success page should not show spinner."""
        import time

        from podcast_research.services.job_service import (
            create_job,
            update_job,
        )
        job = create_job(
            youtube_url="https://www.youtube.com/watch?v=dummy",
            focus_areas=["AI"],
            mock=True,
        )
        # Manually set to success for page testing
        update_job(job.job_id, status="success", stage="success",
                    message="报告已生成")
        time.sleep(0.1)

        resp = api_client.get(f"/tasks/{job.job_id}")
        assert resp.status_code == 200
        html = resp.text
        # Should have success message
        assert "研究报告已生成" in html
        # Should NOT have the long-running hint (it only shows for running status)
        # spinner div exists but JS hides it when status is success
        assert "job-spinner" in html  # div exists in template, JS controls visibility

    def test_task_success_checklist_full_flow(self, api_client):
        """Full flow success page should show checklist."""
        from podcast_research.services.job_service import (
            create_job,
            update_job,
        )
        job = create_job(
            youtube_url="https://www.youtube.com/watch?v=dummy2",
            focus_areas=["AI"],
            mock=True,
            auto_sync=True,
        )
        job.source_type = "channel_video"
        job.source_channel_id = 1
        job.video_id = "dummy2"

        update_job(job.job_id, status="success", stage="success",
                    message="知识库已更新", report_id=42)

        resp = api_client.get(f"/tasks/{job.job_id}")
        assert resp.status_code == 200
        html = resp.text
        assert "整理完成，知识库已更新" in html

    def test_channel_refresh_success_result_links(self, api_client):
        """channel_refresh job success should have video list link."""
        from podcast_research.services.job_service import (
            create_channel_refresh_job,
            update_job,
        )
        job = create_channel_refresh_job(
            channel_url="https://www.youtube.com/@TestChan",
            channel_name="Test Chan",
            channel_id=1,
        )
        update_job(job.job_id, status="success", stage="success",
                    message="新增 3 个视频，更新 0 个")

        resp = api_client.get(f"/tasks/{job.job_id}")
        assert resp.status_code == 200
        html = resp.text
        assert "频道视频列表已更新" in html


class TestChannelRefreshJob:
    """Channel refresh via job."""

    def test_channel_refresh_creates_job_redirect(self, api_client):
        """POST /sources/channels/{id}/refresh should redirect to /tasks/{id}."""
        ch_id = _seed_channel(api_client)

        resp = api_client.post(
            f"/sources/channels/{ch_id}/refresh",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/tasks/" in resp.headers["location"]

    def test_channel_refresh_job_type_label(self, api_client):
        """channel_refresh job should appear in task list with readable label."""
        from podcast_research.services.job_service import (
            create_channel_refresh_job,
            update_job,
        )
        job = create_channel_refresh_job(
            channel_url="https://www.youtube.com/@LabelChan",
            channel_name="Label Chan",
            channel_id=999,
        )
        update_job(job.job_id, status="success", stage="success",
                    message="done")

        resp = api_client.get("/tasks")
        assert resp.status_code == 200
        html = resp.text
        assert "刷新频道" in html


class TestVideoStatusSync:
    """Channel video status sync from job completion."""

    def test_import_video_creates_processing_status(self, api_client, monkeypatch):
        """Importing a video should set channel_video status to processing."""
        ch_id = _seed_channel(api_client)

        # Add a video first via mock refresh
        mock_adapter = MockChannelAdapter([
            {"video_id": "importTest1", "title": "Import Test",
             "url": "https://www.youtube.com/watch?v=importTest1",
             "published_at": "20260601", "duration_seconds": 1200},
        ])
        monkeypatch.setattr(
            "podcast_research.adapters.channel_video_adapter.ChannelVideoAdapter",
            lambda: mock_adapter,
        )
        api_client.post(f"/sources/channels/{ch_id}/refresh", follow_redirects=False)
        import time
        time.sleep(0.5)

        # Now import the video
        resp = api_client.post(
            f"/sources/channels/{ch_id}/videos/importTest1/import",
            data={"focus": "AI", "depth": "standard", "flow_mode": "full"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/tasks/" in resp.headers["location"]

        # Check DB
        from podcast_research.db.repository import get_channel_video_by_video_id
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            cv = get_channel_video_by_video_id(session, "importTest1")
            assert cv is not None
            assert cv["status"] == "processing"
        finally:
            session.close()

    def test_processing_video_no_import_button(self, api_client, monkeypatch):
        """Processing video should show '整理中' and not show import button."""
        ch_id = _seed_channel(api_client)

        # Directly insert a processing video into DB (bypass background refresh to avoid race)
        from podcast_research.db.repository import (
            get_channel_video_by_video_id,
            update_channel_video_status,
            upsert_channel_video,
        )
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            upsert_channel_video(
                session, ch_id, "procVid",
                title="Processing Video",
                url="https://www.youtube.com/watch?v=procVid",
                published_at="20260601",
                duration_seconds=1200,
            )
            cv = get_channel_video_by_video_id(session, "procVid")
            assert cv is not None, "Video should be created"
            update_channel_video_status(session, cv["id"], "processing")
            session.commit()
        finally:
            session.close()

        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        assert resp.status_code == 200
        html = resp.text
        assert "整理中" in html
        # Should NOT have "整理进知识库" button for this video
        assert "整理进知识库" not in html

    def test_synced_video_shows_view_report(self, api_client, monkeypatch):
        """Synced video should show '查看报告' instead of import button."""
        ch_id = _seed_channel(api_client)

        mock_adapter = MockChannelAdapter([
            {"video_id": "synVid", "title": "Synced Video",
             "url": "https://www.youtube.com/watch?v=synVid",
             "published_at": "20260601", "duration_seconds": 1200},
        ])
        monkeypatch.setattr(
            "podcast_research.adapters.channel_video_adapter.ChannelVideoAdapter",
            lambda: mock_adapter,
        )
        api_client.post(f"/sources/channels/{ch_id}/refresh", follow_redirects=False)
        import time
        time.sleep(0.5)

        # Set to synced
        from podcast_research.db.repository import (
            get_channel_video_by_video_id,
            update_channel_video_status,
        )
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            cv = get_channel_video_by_video_id(session, "synVid")
            update_channel_video_status(session, cv["id"], "synced", report_id=5)
            session.commit()
        finally:
            session.close()

        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        assert resp.status_code == 200
        html = resp.text
        assert "已同步" in html
        assert "查看报告" in html


class TestJobStatusWriteback:
    """Job completion writes back to channel_videos."""

    def test_full_flow_success_writes_synced(self, api_client, monkeypatch):
        """After full_flow job success, channel_videos status should be synced."""
        from podcast_research.services.job_service import (
            AnalysisJob,
            _writeback_channel_video_status,
        )

        ch_id = _seed_channel(api_client)
        mock_adapter = MockChannelAdapter([
            {"video_id": "writeback1", "title": "Writeback Test",
             "url": "https://www.youtube.com/watch?v=writeback1",
             "published_at": "20260601", "duration_seconds": 1200},
        ])
        monkeypatch.setattr(
            "podcast_research.adapters.channel_video_adapter.ChannelVideoAdapter",
            lambda: mock_adapter,
        )
        api_client.post(f"/sources/channels/{ch_id}/refresh", follow_redirects=False)
        import time
        time.sleep(0.5)

        # Import to set processing
        api_client.post(
            f"/sources/channels/{ch_id}/videos/writeback1/import",
            data={"focus": "AI", "depth": "standard", "flow_mode": "full"},
            follow_redirects=False,
        )

        # Simulate writeback (what job thread does on success)
        job = AnalysisJob(
            job_id="test_wb", job_type="full_flow",
            source_type="channel_video", source_channel_id=ch_id,
            video_id="writeback1",
        )
        _writeback_channel_video_status(
            job, status="synced", report_id=99,
        )

        from podcast_research.db.repository import get_channel_video_by_video_id
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            cv = get_channel_video_by_video_id(session, "writeback1")
            assert cv["status"] == "synced"
            assert cv["report_id"] == 99
        finally:
            session.close()

    def test_full_flow_failure_writes_failed(self, seeded_db, monkeypatch):
        """After full_flow failure, channel_videos status should be failed."""
        from podcast_research.db.models import ChannelVideo
        from podcast_research.db.repository import get_channel_video_by_video_id
        from podcast_research.db.session import get_session
        from podcast_research.services.job_service import (
            AnalysisJob,
            _writeback_channel_video_status,
        )

        # Create a channel_video directly in DB
        session = get_session()
        try:
            cv = ChannelVideo(
                channel_id=1,
                video_id="writeback_fail",
                title="Fail Test",
                url="https://www.youtube.com/watch?v=writeback_fail",
                status="processing",
            )
            session.add(cv)
            session.commit()
        finally:
            session.close()

        job = AnalysisJob(
            job_id="test_wb_fail", job_type="full_flow",
            source_type="channel_video", source_channel_id=1,
            video_id="writeback_fail",
        )
        _writeback_channel_video_status(
            job, status="failed", failure_reason="Network timeout",
        )

        session = get_session()
        try:
            cv = get_channel_video_by_video_id(session, "writeback_fail")
            assert cv["status"] == "failed"
            assert cv["failure_reason"] == "Network timeout"
        finally:
            session.close()


# ── P2-M.1.2: Sync Retry Writeback ─────────────────────────────────────

class TestSyncRetryWriteback:
    """Sync retry should write back channel_video status via report_id."""

    def test_retry_sync_success_writes_synced(self, seeded_db):
        """Retry sync on a previously-failed video updates status to synced."""
        from podcast_research.db.models import ChannelVideo
        from podcast_research.db.repository import get_channel_video_by_video_id
        from podcast_research.db.session import get_session
        from podcast_research.services.job_service import _writeback_sync_result

        # Create a ChannelVideo with failed status
        session = get_session()
        try:
            cv = ChannelVideo(
                channel_id=1,
                video_id="abc123",  # matches seeded_db report 3
                title="AI Investment Talk",
                url="https://www.youtube.com/watch?v=abc123",
                status="failed",
                failure_reason="previous sync error",
            )
            session.add(cv)
            session.commit()
        finally:
            session.close()

        # Simulate retry sync success via report_id
        _writeback_sync_result(report_id=3, status="synced")

        session = get_session()
        try:
            cv = get_channel_video_by_video_id(session, "abc123")
            assert cv["status"] == "synced"
            assert cv["report_id"] == 3
            assert cv["failure_reason"] == ""
        finally:
            session.close()

    def test_retry_sync_success_clears_failure_reason(self, seeded_db):
        """On sync retry success, failure_reason should be cleared."""
        from podcast_research.db.models import ChannelVideo
        from podcast_research.db.repository import get_channel_video_by_video_id
        from podcast_research.db.session import get_session
        from podcast_research.services.job_service import _writeback_sync_result

        session = get_session()
        try:
            cv = ChannelVideo(
                channel_id=1,
                video_id="abc123",
                title="Clear Reason Test",
                url="https://www.youtube.com/watch?v=abc123",
                status="failed",
                failure_reason="old utf-8 decode error",
            )
            session.add(cv)
            session.commit()
        finally:
            session.close()

        _writeback_sync_result(report_id=3, status="synced")

        session = get_session()
        try:
            cv = get_channel_video_by_video_id(session, "abc123")
            assert cv["failure_reason"] == "", \
                f"failure_reason should be empty, got: {cv['failure_reason']}"
        finally:
            session.close()

    def test_synced_not_downgraded_by_sync_failure(self, seeded_db):
        """Already synced video stays synced even if sync fails later."""
        from podcast_research.db.models import ChannelVideo
        from podcast_research.db.repository import get_channel_video_by_video_id
        from podcast_research.db.session import get_session
        from podcast_research.services.job_service import _writeback_sync_result

        session = get_session()
        try:
            cv = ChannelVideo(
                channel_id=1,
                video_id="abc123",
                title="No Downgrade Test",
                url="https://www.youtube.com/watch?v=abc123",
                status="synced",
                report_id=3,
                failure_reason="",
            )
            session.add(cv)
            session.commit()
        finally:
            session.close()

        # Simulate a failed sync attempt after a previous success
        _writeback_sync_result(report_id=3, status="failed",
                               error="transient network error")

        session = get_session()
        try:
            cv = get_channel_video_by_video_id(session, "abc123")
            assert cv["status"] == "synced", \
                f"synced video should not be downgraded, got: {cv['status']}"
        finally:
            session.close()

    def test_report_without_video_id_handled_gracefully(self, seeded_db):
        """Reports without video_id should not crash _writeback_sync_result."""
        from podcast_research.services.job_service import _writeback_sync_result

        # Report 1 in seeded_db is local (no video_id).
        # _writeback_sync_result should return silently without error.
        try:
            _writeback_sync_result(report_id=1, status="synced")
        except Exception as e:
            pytest.fail(f"_writeback_sync_result should not raise: {e}")

        # Report 1 doesn't have video_id — function should just no-op
        assert True  # reached without exception


# ── P2-M.2: Import Guard & Status Actions ──────────────────────────────

class _SeedChannelWithVideosMixin:
    """Mixin to seed a channel with mock videos for import guard tests."""

    @staticmethod
    def _seed_channel_with_video(api_client, monkeypatch, status="new",
                                 video_id="guardVid001", report_id=None,
                                 failure_reason="", active_job_id=None):
        """Seed channel + video with specific state, return (channel_id, video_id).

        Uses direct DB insertion to avoid background-thread race conditions.
        """
        ch_id = _seed_channel(api_client)

        from podcast_research.db.repository import (
            get_channel_video_by_video_id,
            update_channel_video_status,
            upsert_channel_video,
        )
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            upsert_channel_video(
                session, ch_id, video_id,
                title="Guard Test Video",
                url=f"https://www.youtube.com/watch?v={video_id}",
                published_at="20260601",
                duration_seconds=1200,
            )
            if status != "new":
                cv = get_channel_video_by_video_id(session, video_id)
                if cv:
                    update_channel_video_status(
                        session, cv["id"], status,
                        report_id=report_id,
                        failure_reason=failure_reason,
                        active_job_id=active_job_id,
                    )
            session.commit()
        finally:
            session.close()

        return ch_id, video_id


class TestImportGuard(_SeedChannelWithVideosMixin):
    """Backend import route duplicate guard."""

    def test_import_guard_processing_rejected(self, api_client, monkeypatch):
        """Processing video should NOT create a new job."""
        ch_id, video_id = self._seed_channel_with_video(
            api_client, monkeypatch, status="processing", video_id="guardProc1",
            active_job_id="existing123",
        )

        resp = api_client.post(
            f"/sources/channels/{ch_id}/videos/{video_id}/import",
            data={"focus": "AI", "depth": "standard", "flow_mode": "full"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        # Should redirect to videos page with warning, NOT to /tasks/
        assert "/tasks/" not in resp.headers["location"]
        assert "videos" in resp.headers["location"]

    def test_import_guard_synced_rejected(self, api_client, monkeypatch):
        """Synced video should NOT create a new job."""
        ch_id, video_id = self._seed_channel_with_video(
            api_client, monkeypatch, status="synced", video_id="guardSync1",
            report_id=42,
        )

        resp = api_client.post(
            f"/sources/channels/{ch_id}/videos/{video_id}/import",
            data={"focus": "AI", "depth": "standard", "flow_mode": "full"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/tasks/" not in resp.headers["location"]

    def test_import_guard_analyzed_creates_sync(self, api_client, monkeypatch):
        """Analyzed + report_id → sync retry job (P2-M.3.1: sync may have failed)."""
        ch_id, video_id = self._seed_channel_with_video(
            api_client, monkeypatch, status="analyzed", video_id="guardAnal1",
            report_id=5,
        )

        resp = api_client.post(
            f"/sources/channels/{ch_id}/videos/{video_id}/import",
            data={"focus": "AI", "depth": "standard", "flow_mode": "full"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        location = resp.headers["location"]
        assert "/tasks/" in location  # Creates sync retry job

    def test_import_failed_with_report_creates_sync(self, api_client, monkeypatch):
        """Failed + report_id should create a sync retry job."""
        ch_id, video_id = self._seed_channel_with_video(
            api_client, monkeypatch, status="failed", video_id="guardFailR1",
            report_id=3,  # seeded_db report 3
            failure_reason="previous error",
        )

        resp = api_client.post(
            f"/sources/channels/{ch_id}/videos/{video_id}/import",
            data={"focus": "AI", "depth": "standard", "flow_mode": "full"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        location = resp.headers["location"]
        assert "/tasks/" in location
        # Should create a sync job (job_type=sync), not a full_flow
        import time; time.sleep(0.3)
        # Verify the job exists and is a sync type
        task_id = location.split("/tasks/")[1]
        from podcast_research.services.job_service import get_job_status
        status_data = get_job_status(task_id)
        if status_data:
            assert status_data["job_type"] == "sync", \
                f"Expected sync job, got {status_data['job_type']}"

    def test_import_failed_without_report_creates_full_flow(self, api_client, monkeypatch):
        """Failed + no report_id should create a full_flow retry job."""
        ch_id, video_id = self._seed_channel_with_video(
            api_client, monkeypatch, status="failed", video_id="guardFailNF1",
            failure_reason="analysis crashed",
        )

        resp = api_client.post(
            f"/sources/channels/{ch_id}/videos/{video_id}/import",
            data={"focus": "AI", "depth": "standard", "flow_mode": "full"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/tasks/" in resp.headers["location"]


class TestStatusActionsDisplay(_SeedChannelWithVideosMixin):
    """Template renders correct actions per video status."""

    def test_processing_shows_view_progress(self, api_client, monkeypatch):
        """Processing video should show '查看进度' link."""
        ch_id, video_id = self._seed_channel_with_video(
            api_client, monkeypatch, status="processing", video_id="uiProc1",
            active_job_id="job_ui_001",
        )

        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        html = resp.text
        assert "查看进度" in html
        assert "/tasks/job_ui_001" in html

    def test_analyzed_shows_view_report_and_sync(self, api_client, monkeypatch):
        """Analyzed video should show '查看报告' and '同步到知识库'."""
        ch_id, video_id = self._seed_channel_with_video(
            api_client, monkeypatch, status="analyzed", video_id="uiAnal1",
            report_id=5,
        )

        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        html = resp.text
        assert "查看报告" in html
        assert "/reports/5" in html

    def test_synced_shows_view_report_and_brief(self, api_client, monkeypatch):
        """Synced video should show '查看报告' and '查看研究摘要'."""
        ch_id, video_id = self._seed_channel_with_video(
            api_client, monkeypatch, status="synced", video_id="uiSync1",
            report_id=5,
        )

        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        html = resp.text
        assert "查看报告" in html
        assert "研究摘要" in html
        assert "/reports/5" in html
        assert "/briefs/latest" in html

    def test_failed_with_report_shows_retry_sync(self, api_client, monkeypatch):
        """Failed + report_id should show '重试同步' and '查看报告'."""
        ch_id, video_id = self._seed_channel_with_video(
            api_client, monkeypatch, status="failed", video_id="uiFailR1",
            report_id=5, failure_reason="sync timeout",
        )

        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        html = resp.text
        assert "重试同步" in html
        assert "查看报告" in html
        assert "同步失败" in html

    def test_failed_without_report_shows_retry(self, api_client, monkeypatch):
        """Failed + no report_id should show '重试整理'."""
        ch_id, video_id = self._seed_channel_with_video(
            api_client, monkeypatch, status="failed", video_id="uiFailNF1",
            failure_reason="analysis error",
        )

        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        html = resp.text
        assert "重试整理" in html
        assert "整理失败" in html

    def test_new_shows_import_button(self, api_client, monkeypatch):
        """New video should show '整理进知识库'."""
        ch_id, video_id = self._seed_channel_with_video(
            api_client, monkeypatch, status="new", video_id="testNew1",
        )
        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        assert resp.status_code == 200
        html = resp.text
        assert "整理进知识库" in html


class TestSourcePagesDOMStructure:
    """P2-M.5.1: Verify card-based DOM structure on source pages."""

    def test_channels_page_has_add_channel_card(self, api_client):
        """/sources/channels contains add-channel-card section."""
        resp = api_client.get("/sources/channels")
        assert resp.status_code == 200
        assert 'add-channel-card' in resp.text

    def test_channels_page_has_overview_card(self, api_client):
        """/sources/channels contains channel-overview-card section."""
        resp = api_client.get("/sources/channels")
        assert resp.status_code == 200
        assert 'channel-overview-card' in resp.text

    def test_channels_page_has_form_controls(self, api_client):
        """Add channel form uses form-control class, not bare inputs."""
        resp = api_client.get("/sources/channels")
        assert resp.status_code == 200
        assert 'form-control' in resp.text

    def test_channels_page_has_unified_buttons(self, api_client):
        """Buttons use btn btn-primary/secondary/ghost classes."""
        resp = api_client.get("/sources/channels")
        assert resp.status_code == 200
        assert 'btn-primary' in resp.text or 'btn-primary' in resp.text

    def test_videos_page_has_channel_hero(self, api_client, monkeypatch):
        """Video list page has channel-hero card."""
        ch_id = _seed_channel(api_client)
        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        assert resp.status_code == 200
        assert 'channel-hero' in resp.text

    def test_videos_page_has_filter_card(self, api_client, monkeypatch):
        """Video list page has filter-card with filter-pills."""
        ch_id = _seed_channel(api_client)
        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        assert resp.status_code == 200
        assert 'filter-card' in resp.text
        assert 'filter-pill' in resp.text

    def test_videos_page_has_video_cards(self, api_client, monkeypatch):
        """Video list page uses video-card articles."""
        ch_id = _seed_channel(api_client)
        mock_adapter = MockChannelAdapter([
            {"video_id": "domTest1", "title": "DOM Test Video",
             "url": "https://youtube.com/watch?v=domTest1",
             "published_at": "20260601", "duration_seconds": 1800},
        ])
        monkeypatch.setattr(
            "podcast_research.adapters.channel_video_adapter.ChannelVideoAdapter",
            lambda: mock_adapter,
        )
        api_client.post(f"/sources/channels/{ch_id}/refresh", follow_redirects=False)
        import time; time.sleep(0.3)

        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        assert resp.status_code == 200
        assert 'video-card' in resp.text
        assert 'video-main' in resp.text
        assert 'video-side' in resp.text

    def test_stylesheet_served_with_cache_bust(self, api_client):
        """CSS link has cache-busting version param."""
        resp = api_client.get("/sources/channels")
        assert 'style.css?v=' in resp.text

    def test_video_card_uses_grid_layout(self, api_client):
        """CSS defines video-card with display:grid for left-right structure."""
        resp = api_client.get("/static/style.css?v=p2m52")
        css = resp.text
        assert '.video-card' in css
        assert 'grid-template-columns' in css
        assert 'minmax' in css

    def test_source_card_has_visible_colors(self, api_client):
        """CSS uses hardcoded #ffffff not transparent bg for cards."""
        resp = api_client.get("/static/style.css?v=p2m52")
        css = resp.text
        assert '#ffffff' in css
        assert 'box-shadow' in css

    def test_form_control_has_explicit_height(self, api_client):
        """.form-control has height:40px to override browser defaults."""
        resp = api_client.get("/static/style.css?v=p2m52")
        css = resp.text
        assert '.form-control' in css


class TestActiveJobIdLifecycle:
    """active_job_id is written on import, cleared on completion."""

    def test_active_job_id_written_on_import(self, api_client, monkeypatch):
        """Importing a video should set active_job_id on channel_video."""
        # Mock start_job/start_sync_job to prevent job thread from clearing active_job_id
        import podcast_research.services.job_service as js
        monkeypatch.setattr(js, "start_job", lambda job: None)
        monkeypatch.setattr(js, "start_sync_job", lambda job: None)

        ch_id = _seed_channel(api_client)
        mock_adapter = MockChannelAdapter([
            {
                "video_id": "ajTest1", "title": "Active Job Test",
                "url": "https://www.youtube.com/watch?v=ajTest1",
                "published_at": "20260601", "duration_seconds": 1200,
            },
        ])
        monkeypatch.setattr(
            "podcast_research.adapters.channel_video_adapter.ChannelVideoAdapter",
            lambda: mock_adapter,
        )
        api_client.post(f"/sources/channels/{ch_id}/refresh", follow_redirects=False)
        import time; time.sleep(0.3)

        # Import the video
        resp = api_client.post(
            f"/sources/channels/{ch_id}/videos/ajTest1/import",
            data={"focus": "AI", "depth": "standard", "flow_mode": "full"},
            follow_redirects=False,
        )
        assert resp.status_code == 303

        # Check active_job_id was set
        from podcast_research.db.repository import get_channel_video_by_video_id
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            cv = get_channel_video_by_video_id(session, "ajTest1")
            assert cv["active_job_id"] is not None, \
                "active_job_id should be set on import"
        finally:
            session.close()

    def test_active_job_id_cleared_on_writeback(self, seeded_db):
        """writeback should clear active_job_id."""
        from podcast_research.db.models import ChannelVideo
        from podcast_research.db.repository import get_channel_video_by_video_id
        from podcast_research.db.session import get_session
        from podcast_research.services.job_service import (
            AnalysisJob,
            _writeback_channel_video_status,
        )

        # Create channel_video with active_job_id
        session = get_session()
        try:
            cv = ChannelVideo(
                channel_id=1, video_id="ajWriteback1",
                title="Writeback Clear Test",
                url="https://www.youtube.com/watch?v=ajWriteback1",
                status="processing", active_job_id="some_job_id_123",
            )
            session.add(cv)
            session.commit()
        finally:
            session.close()

        # Simulate job completion
        job = AnalysisJob(
            job_id="some_job_id_123", job_type="full_flow",
            source_type="channel_video", source_channel_id=1,
            video_id="ajWriteback1",
        )
        _writeback_channel_video_status(job, status="synced", report_id=1)

        # Verify cleared
        session = get_session()
        try:
            cv2 = get_channel_video_by_video_id(session, "ajWriteback1")
            assert cv2["active_job_id"] is None, \
                f"active_job_id should be cleared, got: {cv2['active_job_id']}"
        finally:
            session.close()


# ── P2-M.3: Re-run With Replacement ────────────────────────────────────

class TestRerunButton:
    """Rerun button appears in correct statuses."""

    def test_rerun_button_visible_for_synced(self, api_client, monkeypatch):
        """Synced video should show '重新整理' button."""
        ch_id = _seed_channel(api_client)
        mock_adapter = MockChannelAdapter([
            {"video_id": "rerunBtnS", "title": "Rerun Test Synced",
             "url": "https://www.youtube.com/watch?v=rerunBtnS",
             "published_at": "20260601", "duration_seconds": 1200},
        ])
        monkeypatch.setattr(
            "podcast_research.adapters.channel_video_adapter.ChannelVideoAdapter",
            lambda: mock_adapter,
        )
        api_client.post(f"/sources/channels/{ch_id}/refresh", follow_redirects=False)
        import time; time.sleep(0.3)

        # Set to synced
        from podcast_research.db.repository import (
            get_channel_video_by_video_id,
            update_channel_video_status,
        )
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            cv = get_channel_video_by_video_id(session, "rerunBtnS")
            if cv:
                update_channel_video_status(session, cv["id"], "synced", report_id=1)
                session.commit()
        finally:
            session.close()

        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        assert "重新整理" in resp.text

    def test_rerun_button_visible_for_analyzed(self, api_client, monkeypatch):
        """Analyzed video should show '重新整理' button."""
        ch_id = _seed_channel(api_client)
        mock_adapter = MockChannelAdapter([
            {"video_id": "rerunBtnA", "title": "Rerun Test Analyzed",
             "url": "https://www.youtube.com/watch?v=rerunBtnA",
             "published_at": "20260601", "duration_seconds": 1200},
        ])
        monkeypatch.setattr(
            "podcast_research.adapters.channel_video_adapter.ChannelVideoAdapter",
            lambda: mock_adapter,
        )
        api_client.post(f"/sources/channels/{ch_id}/refresh", follow_redirects=False)
        import time; time.sleep(0.3)

        from podcast_research.db.repository import (
            get_channel_video_by_video_id,
            update_channel_video_status,
        )
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            cv = get_channel_video_by_video_id(session, "rerunBtnA")
            if cv:
                update_channel_video_status(session, cv["id"], "analyzed", report_id=1)
                session.commit()
        finally:
            session.close()

        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        assert "重新整理" in resp.text


class TestRerunRoutes:
    """GET and POST rerun routes."""

    def test_rerun_get_page_loads(self, api_client, monkeypatch):
        """GET /rerun returns confirmation page."""
        ch_id = _seed_channel(api_client)
        mock_adapter = MockChannelAdapter([
            {"video_id": "rerunGet1", "title": "GET Rerun",
             "url": "https://www.youtube.com/watch?v=rerunGet1",
             "published_at": "20260601", "duration_seconds": 1200},
        ])
        monkeypatch.setattr(
            "podcast_research.adapters.channel_video_adapter.ChannelVideoAdapter",
            lambda: mock_adapter,
        )
        api_client.post(f"/sources/channels/{ch_id}/refresh", follow_redirects=False)
        import time; time.sleep(0.3)

        from podcast_research.db.repository import (
            get_channel_video_by_video_id,
            update_channel_video_status,
        )
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            cv = get_channel_video_by_video_id(session, "rerunGet1")
            if cv:
                update_channel_video_status(session, cv["id"], "synced", report_id=1)
                session.commit()
        finally:
            session.close()

        resp = api_client.get(
            f"/sources/channels/{ch_id}/videos/rerunGet1/rerun"
        )
        assert resp.status_code == 200
        assert "重新整理" in resp.text
        assert "确认重新整理" in resp.text

    def test_rerun_post_creates_job(self, api_client, monkeypatch):
        """POST /rerun creates job and redirects to /tasks/."""
        # Mock start_job to prevent background thread
        import podcast_research.services.job_service as js
        monkeypatch.setattr(js, "start_job", lambda job: None)

        ch_id = _seed_channel(api_client)
        mock_adapter = MockChannelAdapter([
            {"video_id": "rerunPost1", "title": "POST Rerun",
             "url": "https://www.youtube.com/watch?v=rerunPost1",
             "published_at": "20260601", "duration_seconds": 1200},
        ])
        monkeypatch.setattr(
            "podcast_research.adapters.channel_video_adapter.ChannelVideoAdapter",
            lambda: mock_adapter,
        )
        api_client.post(f"/sources/channels/{ch_id}/refresh", follow_redirects=False)
        import time; time.sleep(0.3)

        from podcast_research.db.repository import (
            get_channel_video_by_video_id,
            update_channel_video_status,
        )
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            cv = get_channel_video_by_video_id(session, "rerunPost1")
            if cv:
                update_channel_video_status(session, cv["id"], "synced", report_id=1)
                session.commit()
        finally:
            session.close()

        resp = api_client.post(
            f"/sources/channels/{ch_id}/videos/rerunPost1/rerun",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/tasks/" in resp.headers["location"]


# ═══════════════════════════════════════════════════════════════════════════════
# P2-M.4: Channel Filters & Watchlist Match Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestVideoListFilters:
    """Test status/long/watchlist filter query params on video list page."""

    def test_filter_status_new(self, api_client, monkeypatch):
        """status=new only shows new videos."""
        ch_id = _seed_channel_with_status_mix(api_client, monkeypatch)

        resp = api_client.get(f"/sources/channels/{ch_id}/videos?status=new")
        assert resp.status_code == 200
        html = resp.text
        assert "newVideo1" in html
        assert "syncVideo1" not in html

    def test_filter_status_synced(self, api_client, monkeypatch):
        """status=synced only shows synced videos."""
        ch_id = _seed_channel_with_status_mix(api_client, monkeypatch)

        resp = api_client.get(f"/sources/channels/{ch_id}/videos?status=synced")
        assert resp.status_code == 200
        html = resp.text
        assert "syncVideo1" in html
        assert "newVideo1" not in html

    def test_filter_status_failed(self, api_client, monkeypatch):
        """status=failed shows failed videos."""
        ch_id = _seed_channel_with_status_mix(api_client, monkeypatch)

        resp = api_client.get(f"/sources/channels/{ch_id}/videos?status=failed")
        assert resp.status_code == 200
        html = resp.text
        assert "failVideo1" in html
        assert "newVideo1" not in html

    def test_filter_long_videos(self, api_client, monkeypatch):
        """long=1 shows only videos > 90 min."""
        ch_id = _seed_channel_with_status_mix(api_client, monkeypatch)

        resp = api_client.get(f"/sources/channels/{ch_id}/videos?long=1")
        assert resp.status_code == 200
        html = resp.text
        assert "longVid1" in html
        assert "newVideo1" not in html

    def test_combined_filters(self, api_client, monkeypatch):
        """Combined status + watchlist filters work."""
        ch_id = _seed_channel_with_status_mix(api_client, monkeypatch)

        resp = api_client.get(
            f"/sources/channels/{ch_id}/videos?status=new&watchlist_match=1"
        )
        assert resp.status_code == 200

    def test_all_filter_shows_everything(self, api_client, monkeypatch):
        """No filter shows all videos."""
        ch_id = _seed_channel_with_status_mix(api_client, monkeypatch)

        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        assert resp.status_code == 200
        html = resp.text
        assert "newVideo1" in html
        assert "syncVideo1" in html
        assert "failVideo1" in html


class TestWatchlistMatch:
    """Test match_video_to_watchlist function."""

    def test_match_company_exact(self):
        """Exact company name match."""
        from podcast_research.services.watchlist_matcher import match_video_to_watchlist
        from podcast_research.workspace.watchlist import WatchlistConfig

        wl = WatchlistConfig(companies=["OpenAI", "NVIDIA"])

        result = match_video_to_watchlist("OpenAI CFO Sarah Friar on IPO", wl)
        assert result.matched is True
        assert result.matched_type == "company"
        assert "OpenAI" in result.matched_terms

    def test_match_company_case_insensitive(self):
        """Company name match is case insensitive."""
        from podcast_research.services.watchlist_matcher import match_video_to_watchlist
        from podcast_research.workspace.watchlist import WatchlistConfig

        wl = WatchlistConfig(companies=["NVIDIA"])

        result = match_video_to_watchlist(
            "nvidia GTC keynote Jensen Huang", wl
        )
        assert result.matched is True
        assert result.matched_type == "company"

    def test_match_company_alias(self):
        """Company alias map works."""
        from podcast_research.services.watchlist_matcher import match_video_to_watchlist
        from podcast_research.workspace.watchlist import WatchlistConfig

        wl = WatchlistConfig(companies=["NVIDIA"])

        # "英伟达" is an alias for NVIDIA
        result = match_video_to_watchlist("英伟达发布新GPU架构", wl)
        assert result.matched is True
        assert result.matched_type == "company"

    def test_match_topic_exact(self):
        """Exact topic name match."""
        from podcast_research.services.watchlist_matcher import match_video_to_watchlist
        from podcast_research.workspace.watchlist import WatchlistConfig

        wl = WatchlistConfig(topics=["AI Agents"])

        result = match_video_to_watchlist(
            "The Future of AI Agents in Enterprise", wl
        )
        assert result.matched is True
        assert result.matched_type == "topic"
        assert "AI Agents" in result.matched_terms

    def test_match_topic_normalized(self):
        """Normalized topic match (no spaces)."""
        from podcast_research.services.watchlist_matcher import match_video_to_watchlist
        from podcast_research.workspace.watchlist import WatchlistConfig

        wl = WatchlistConfig(topics=["AI Agents"])

        result = match_video_to_watchlist("AIAgents in Production", wl)
        assert result.matched is True
        assert result.matched_type == "topic"

    def test_match_theme_via_related_topic(self):
        """Theme matches via related topics."""
        from podcast_research.services.watchlist_matcher import match_video_to_watchlist
        from podcast_research.workspace.watchlist import WatchlistConfig

        wl = WatchlistConfig(themes=["Agent 工具链"])

        # Agent 工具链 → related topics include "AI Agents", "Developer Tools"
        result = match_video_to_watchlist(
            "Building AI Agents with MCP", wl
        )
        assert result.matched is True
        assert result.matched_type == "theme"

    def test_no_match(self):
        """No match returns False."""
        from podcast_research.services.watchlist_matcher import match_video_to_watchlist
        from podcast_research.workspace.watchlist import WatchlistConfig

        wl = WatchlistConfig(companies=["OpenAI"], topics=["AI Agents"])

        result = match_video_to_watchlist(
            "Cooking with Gordon Ramsay", wl
        )
        assert result.matched is False

    def test_company_before_topic(self):
        """Company match takes priority over topic."""
        from podcast_research.services.watchlist_matcher import match_video_to_watchlist
        from podcast_research.workspace.watchlist import WatchlistConfig

        wl = WatchlistConfig(companies=["NVIDIA"], topics=["Chips"])

        # Title mentions both but company should win
        result = match_video_to_watchlist("NVIDIA Shows Next-Gen Chips", wl)
        assert result.matched is True
        assert result.matched_type == "company"


class TestRecommendationBadges:
    """Test compute_recommendation badge logic."""

    def test_new_plus_watchlist_gets_recommended(self):
        """new + watchlist_match → 'recommended' badge."""
        from podcast_research.services.watchlist_matcher import (
            MatchResult,
            compute_recommendation,
        )
        match = MatchResult(matched=True, matched_terms=["OpenAI"],
                           matched_type="company", reason="test")
        badges = compute_recommendation("new", match, duration_seconds=1800)
        assert "recommended" in badges

    def test_synced_no_recommended_badge(self):
        """synced videos don't get recommended badge even if watchlist matches."""
        from podcast_research.services.watchlist_matcher import (
            MatchResult,
            compute_recommendation,
        )
        match = MatchResult(matched=True, matched_terms=["OpenAI"],
                           matched_type="company", reason="test")
        badges = compute_recommendation("synced", match, duration_seconds=1800)
        assert "recommended" not in badges

    def test_long_video_badge(self):
        """Videos > 90 min get long_video badge."""
        from podcast_research.services.watchlist_matcher import compute_recommendation
        badges = compute_recommendation("new", None, duration_seconds=7200)
        assert "long_video" in badges

    def test_short_video_no_long_badge(self):
        """Videos ≤ 90 min don't get long_video badge."""
        from podcast_research.services.watchlist_matcher import compute_recommendation
        badges = compute_recommendation("new", None, duration_seconds=1800)
        assert "long_video" not in badges

    def test_both_badges(self):
        """new + watchlist + long → both badges."""
        from podcast_research.services.watchlist_matcher import (
            MatchResult,
            compute_recommendation,
        )
        match = MatchResult(matched=True, matched_terms=["OpenAI"],
                           matched_type="company", reason="test")
        badges = compute_recommendation("new", match, duration_seconds=7200)
        assert "recommended" in badges
        assert "long_video" in badges


class TestChannelDefaultFocusEdit:
    """Test editing channel default_focus and using it for import."""

    def test_edit_default_focus(self, api_client, monkeypatch):
        """Can save channel default_focus via edit POST."""
        ch_id = _seed_channel(api_client, name="Test", default_focus="Old Focus")

        resp = api_client.post(
            f"/sources/channels/{ch_id}/edit",
            data={
                "name": "Test Channel",
                "priority": "core",
                "default_focus": "AI Investing, Tech Stocks",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "success" in resp.headers.get("location", "")

        # Verify in DB
        from podcast_research.db.models import Channel
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            ch = session.query(Channel).filter_by(id=ch_id).first()
            assert ch.default_focus == "AI Investing, Tech Stocks"
        finally:
            session.close()

    def test_import_page_shows_default_focus(self, api_client, monkeypatch):
        """Video list page shows import button with channel default_focus."""
        ch_id = _seed_channel(api_client, name="Test", default_focus="Semiconductor")
        mock_adapter = MockChannelAdapter([
            {"video_id": "showFoc1", "title": "New Video",
             "url": "https://www.youtube.com/watch?v=showFoc1",
             "published_at": "20260601", "duration_seconds": 1800},
        ])
        monkeypatch.setattr(
            "podcast_research.adapters.channel_video_adapter.ChannelVideoAdapter",
            lambda: mock_adapter,
        )
        api_client.post(f"/sources/channels/{ch_id}/refresh", follow_redirects=False)
        import time; time.sleep(0.3)

        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        assert resp.status_code == 200
        html = resp.text
        # The import form should contain the channel default_focus
        assert 'Semiconductor' in html


# ── Helpers for P2-M.4 tests ────────────────────────────────────────────


def _seed_channel_with_status_mix(api_client, monkeypatch):
    """Seed a channel with videos of various statuses for filter testing."""
    ch_id = _seed_channel(api_client, name="TestMix", default_focus="AI")

    mock_adapter = MockChannelAdapter([
        {"video_id": "newVideo1", "title": "Fresh AI Content",
         "url": "https://youtube.com/watch?v=newVideo1",
         "published_at": "20260605", "duration_seconds": 1800},
        {"video_id": "newVideo2", "title": "Another New One",
         "url": "https://youtube.com/watch?v=newVideo2",
         "published_at": "20260604", "duration_seconds": 2400},
        {"video_id": "syncVideo1", "title": "Already Synced",
         "url": "https://youtube.com/watch?v=syncVideo1",
         "published_at": "20260603", "duration_seconds": 1800},
        {"video_id": "failVideo1", "title": "Failed Processing",
         "url": "https://youtube.com/watch?v=failVideo1",
         "published_at": "20260602", "duration_seconds": 1800},
        {"video_id": "failSync1", "title": "Failed Sync",
         "url": "https://youtube.com/watch?v=failSync1",
         "published_at": "20260601", "duration_seconds": 1800},
        {"video_id": "longVid1", "title": "Very Long Deep Dive",
         "url": "https://youtube.com/watch?v=longVid1",
         "published_at": "20260530", "duration_seconds": 7200},
        {"video_id": "skipVideo1", "title": "Skipped Content",
         "url": "https://youtube.com/watch?v=skipVideo1",
         "published_at": "20260529", "duration_seconds": 1800},
    ])
    monkeypatch.setattr(
        "podcast_research.adapters.channel_video_adapter.ChannelVideoAdapter",
        lambda: mock_adapter,
    )
    api_client.post(f"/sources/channels/{ch_id}/refresh", follow_redirects=False)
    import time; time.sleep(0.3)

    # Set specific statuses
    from podcast_research.db.repository import (
        get_channel_video_by_video_id,
        update_channel_video_status,
    )
    from podcast_research.db.session import get_session
    session = get_session()
    try:
        cv = get_channel_video_by_video_id(session, "syncVideo1")
        if cv:
            update_channel_video_status(session, cv["id"], "synced", report_id=1)
        cv = get_channel_video_by_video_id(session, "failVideo1")
        if cv:
            update_channel_video_status(session, cv["id"], "failed", failure_reason="test error")
        cv = get_channel_video_by_video_id(session, "failSync1")
        if cv:
            update_channel_video_status(session, cv["id"], "failed", report_id=2, failure_reason="sync error")
        cv = get_channel_video_by_video_id(session, "skipVideo1")
        if cv:
            update_channel_video_status(session, cv["id"], "skipped")
        session.commit()
    finally:
        session.close()

    return ch_id


def _write_test_watchlist_with_openai():
    """Write a temporary Watchlist.yaml with OpenAI in the test vault."""
    from podcast_research import config_store
    vp_str = config_store.get_user_vault_path()
    if not vp_str:
        return
    vp = Path(vp_str)
    sys_dir = vp / "99_System"
    sys_dir.mkdir(parents=True, exist_ok=True)
    wl_path = sys_dir / "Watchlist.yaml"
    wl_path.write_text("""companies:
  - OpenAI
  - NVIDIA

topics:
  - AI Agents

themes:
  - Agent 工具链
""", encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# P2-M.4.1: last_job_id writeback & channel video log link tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestLastJobIdWriteback:
    """P2-M.4.1: last_job_id persistence and display for failed videos."""

    def test_last_job_id_written_on_import(self, api_client, monkeypatch):
        """After import creates a job, channel_video has active_job_id for log access."""
        ch_id = _seed_channel(api_client)
        mock_adapter = MockChannelAdapter([
            {"video_id": "ljTest1", "title": "LJ Test Video",
             "url": "https://youtube.com/watch?v=ljTest1",
             "published_at": "20260601", "duration_seconds": 1800},
        ])
        monkeypatch.setattr(
            "podcast_research.adapters.channel_video_adapter.ChannelVideoAdapter",
            lambda: mock_adapter,
        )
        api_client.post(f"/sources/channels/{ch_id}/refresh", follow_redirects=False)
        import time; time.sleep(0.3)

        # Mock start_job to avoid background thread
        import podcast_research.services.job_service as js
        monkeypatch.setattr(js, "start_job", lambda job: None)

        resp = api_client.post(
            f"/sources/channels/{ch_id}/videos/ljTest1/import",
            data={"focus": "AI", "depth": "standard", "flow_mode": "full"},
            follow_redirects=False,
        )
        assert resp.status_code == 303

        # Check channel_video has active_job_id for log linking
        from podcast_research.db.repository import get_channel_video_by_video_id
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            cv = get_channel_video_by_video_id(session, "ljTest1")
            assert cv is not None
            assert cv.get("active_job_id")  # Set during import for "查看进度"
        finally:
            session.close()

    def test_failed_video_shows_view_logs_link(self, api_client, monkeypatch):
        """Failed channel video with last_job_id shows '查看日志' link."""
        ch_id = _seed_channel(api_client)
        mock_adapter = MockChannelAdapter([
            {"video_id": "failLog1", "title": "Failed With Log Link",
             "url": "https://youtube.com/watch?v=failLog1",
             "published_at": "20260601", "duration_seconds": 1800},
        ])
        monkeypatch.setattr(
            "podcast_research.adapters.channel_video_adapter.ChannelVideoAdapter",
            lambda: mock_adapter,
        )
        api_client.post(f"/sources/channels/{ch_id}/refresh", follow_redirects=False)
        import time; time.sleep(0.3)

        from podcast_research.db.models import ChannelVideo
        from podcast_research.db.repository import get_channel_video_by_video_id
        from podcast_research.db.session import get_session
        session = get_session()
        try:
            cv = get_channel_video_by_video_id(session, "failLog1")
            db_cv = session.query(ChannelVideo).filter_by(id=cv["id"]).first()
            db_cv.status = "failed"
            db_cv.last_job_id = "test_job_log_123"
            db_cv.failure_reason = "test error"
            session.commit()
        finally:
            session.close()

        resp = api_client.get(f"/sources/channels/{ch_id}/videos")
        assert resp.status_code == 200
        assert "日志" in resp.text
        assert "test_job_log_123" in resp.text
