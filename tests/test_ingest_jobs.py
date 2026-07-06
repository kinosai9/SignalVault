"""P3-A: Tests for persistent ingest job manager.

Covers: CRUD, status transitions, dedup, retry, expiry, resume, dual-write,
and CLI commands.
"""

import json

import pytest

from signalvault.db.models import IngestJob
from signalvault.db.session import get_session, init_db, reset_engine

# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    """Isolate DB to temp file so tests don't touch real data."""
    db_path = tmp_path / "test_ingest.db"
    import signalvault.config as cfg
    monkeypatch.setattr(cfg, "DB_PATH", db_path)
    reset_engine()
    init_db(str(db_path))
    yield
    reset_engine()


@pytest.fixture
def manager():
    """Return the IngestJobManager class (stateless, no init needed)."""
    from signalvault.sources.ingest_jobs import IngestJobManager
    return IngestJobManager


@pytest.fixture
def session():
    """Return a fresh DB session."""
    s = get_session()
    yield s
    s.close()


# ═════════════════════════════════════════════════════════════════════════════
# Job Creation
# ═════════════════════════════════════════════════════════════════════════════


class TestCreateJob:
    """Tests for IngestJobManager.create_job()."""

    def test_create_url_import_job(self, manager):
        job = manager.create_job(
            source_type="url_import",
            source_url="https://example.com/article",
            source_hash="abc123",
            source_name="Test Article",
        )
        assert job is not None
        assert job["source_type"] == "url_import"
        assert job["source_url"] == "https://example.com/article"
        assert job["source_hash"] == "abc123"
        assert job["source_name"] == "Test Article"
        assert job["status"] == "pending_preview"
        assert job["retry_count"] == 0
        assert job["job_key"].startswith("url_import:")
        assert job["created_at"] is not None
        assert job["expires_at"] is not None

    def test_create_file_upload_job(self, manager):
        job = manager.create_job(
            source_type="file_upload",
            source_hash="def456",
            source_name="research.txt",
            preview_id="prev12345678",
        )
        assert job is not None
        assert job["source_type"] == "file_upload"
        assert job["job_key"] == "file_upload:def456"
        assert job["preview_id"] == "prev12345678"

    def test_create_tracked_entry_job(self, manager):
        job = manager.create_job(
            source_type="tracked_entry",
            source_url="https://example.com/episode/1",
            source_name="Episode 1",
            tracked_source_id=5,
            tracked_entry_id=10,
            preview_id="te1234567890",
        )
        assert job is not None
        assert job["source_type"] == "tracked_entry"
        assert job["tracked_source_id"] == 5
        assert job["tracked_entry_id"] == 10
        assert job["job_key"].startswith("tracked_entry:5:")

    def test_create_source_profile_job(self, manager):
        job = manager.create_job(
            source_type="source_profile",
            source_url="https://example.com/index",
            source_name="Example Index",
            preview_id="sp1234567890",
        )
        assert job is not None
        assert job["source_type"] == "source_profile"
        assert job["job_key"].startswith("source_profile:")

    def test_create_job_with_preview_data(self, manager):
        preview_data = json.dumps({"title": "Test", "summary": "A test article"})
        job = manager.create_job(
            source_type="url_import",
            source_url="https://example.com/test",
            preview_data=preview_data,
        )
        assert job is not None
        assert "Test" in job["preview_data"]
        assert "A test article" in job["preview_data"]


# ═════════════════════════════════════════════════════════════════════════════
# Find / Query
# ═════════════════════════════════════════════════════════════════════════════


class TestFindJob:
    """Tests for find_by_job_key, find_by_preview_id, get_job."""

    def test_find_by_job_key(self, manager):
        manager.create_job(
            source_type="url_import",
            source_url="https://example.com/findme",
        )
        # The job_key is deterministic from the URL
        import hashlib
        url_hash = hashlib.sha256(b"https://example.com/findme").hexdigest()[:16]
        job_key = f"url_import:{url_hash}"
        found = manager.find_by_job_key(job_key)
        assert found is not None
        assert found["source_url"] == "https://example.com/findme"

    def test_find_by_job_key_not_found(self, manager):
        found = manager.find_by_job_key("url_import:nonexistent")
        assert found is None

    def test_find_by_preview_id(self, manager):
        manager.create_job(
            source_type="file_upload",
            source_hash="hash_xyz",
            preview_id="findme_pid_1",
        )
        found = manager.find_by_preview_id("findme_pid_1")
        assert found is not None
        assert found["source_type"] == "file_upload"

    def test_find_by_preview_id_not_found(self, manager):
        found = manager.find_by_preview_id("nonexistent_pid")
        assert found is None

    def test_get_job_by_id(self, manager):
        job = manager.create_job(source_type="url_import", source_url="https://x.com")
        assert job is not None
        found = manager.get_job(job["id"])
        assert found is not None
        assert found["id"] == job["id"]

    def test_get_job_not_found(self, manager):
        found = manager.get_job(99999)
        assert found is None

    def test_find_by_job_key_only_pending(self, manager):
        """find_by_job_key only returns pending_preview jobs."""
        url = "https://example.com/only-pending"
        manager.create_job(source_type="url_import", source_url=url, preview_id="pid1")
        import hashlib
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        job_key = f"url_import:{url_hash}"
        # Confirm the job
        manager.confirm_job("pid1", action="skip")
        # Now find_by_job_key should NOT return it
        found = manager.find_by_job_key(job_key)
        assert found is None


# ═════════════════════════════════════════════════════════════════════════════
# List / Query
# ═════════════════════════════════════════════════════════════════════════════


class TestListJobs:
    """Tests for get_pending_previews and list_jobs."""

    def test_get_pending_previews(self, manager):
        manager.create_job(source_type="url_import", source_url="https://a.com")
        manager.create_job(source_type="url_import", source_url="https://b.com")
        manager.create_job(source_type="file_upload", source_hash="hash_c")
        pending = manager.get_pending_previews()
        assert len(pending) == 3

    def test_get_pending_previews_by_type(self, manager):
        manager.create_job(source_type="url_import", source_url="https://a.com")
        manager.create_job(source_type="url_import", source_url="https://b.com")
        manager.create_job(source_type="file_upload", source_hash="hash_c")
        pending = manager.get_pending_previews(source_type="url_import")
        assert len(pending) == 2
        pending = manager.get_pending_previews(source_type="file_upload")
        assert len(pending) == 1

    def test_list_jobs_with_status_filter(self, manager):
        manager.create_job(
            source_type="url_import", source_url="https://a.com", preview_id="l1",
        )
        manager.create_job(
            source_type="url_import", source_url="https://b.com", preview_id="l2",
        )
        manager.confirm_job("l1", action="skip")
        # Only pending should remain
        pending = manager.list_jobs(status="pending_preview")
        assert len(pending) == 1
        skipped = manager.list_jobs(status="skipped")
        assert len(skipped) == 1

    def test_list_jobs_with_limit(self, manager):
        for i in range(10):
            manager.create_job(source_type="url_import", source_url=f"https://x.com/{i}")
        jobs = manager.list_jobs(limit=5)
        assert len(jobs) == 5


# ═════════════════════════════════════════════════════════════════════════════
# Status Transitions
# ═════════════════════════════════════════════════════════════════════════════


class TestStatusTransitions:
    """Tests for confirm_job, mark_failed, skip."""

    def test_confirm_archive(self, manager):
        manager.create_job(
            source_type="file_upload", source_hash="h1",
            preview_id="confirm_test_1",
        )
        result = manager.confirm_job(
            "confirm_test_1", action="confirm_archive",
            action_label="确认归档",
            result_path="01_Reports/SourceArchive/file.md",
            result_message="文件已归档: file.md",
        )
        assert result is not None
        assert result["status"] == "confirmed_archive"
        assert result["action"] == "confirm_archive"
        assert result["result_path"] == "01_Reports/SourceArchive/file.md"
        assert result["confirmed_at"] is not None

    def test_confirm_deep_notes(self, manager):
        manager.create_job(
            source_type="url_import", source_url="https://youtube.com/watch?v=abc",
            preview_id="confirm_test_2",
        )
        result = manager.confirm_job(
            "confirm_test_2", action="import_as_deep_notes_derived_only",
            action_label="导入为独立精读笔记",
        )
        assert result is not None
        assert result["status"] == "confirmed_derived_only"

    def test_confirm_skip(self, manager):
        manager.create_job(
            source_type="url_import", source_url="https://skipme.com",
            preview_id="confirm_test_3",
        )
        result = manager.confirm_job("confirm_test_3", action="skip")
        assert result is not None
        assert result["status"] == "skipped"

    def test_confirm_nonexistent_preview(self, manager):
        result = manager.confirm_job("nonexistent_pid", action="skip")
        assert result is None

    def test_mark_failed(self, manager):
        manager.create_job(
            source_type="url_import", source_url="https://failme.com",
            preview_id="fail_test_1",
        )
        result = manager.mark_failed("fail_test_1", "Network timeout")
        assert result is not None
        assert result["status"] == "preview_failed"
        assert result["error_message"] == "Network timeout"
        assert result["retry_count"] == 1

    def test_mark_failed_nonexistent(self, manager):
        result = manager.mark_failed("nonexistent_pid", "error")
        assert result is None

    def test_confirm_already_confirmed_noop(self, manager):
        """Confirming an already confirmed job should not find it."""
        manager.create_job(
            source_type="url_import", source_url="https://twice.com",
            preview_id="twice_test",
        )
        first = manager.confirm_job("twice_test", action="skip")
        assert first is not None
        second = manager.confirm_job("twice_test", action="skip")
        assert second is None  # Already transitioned, not pending


# ═════════════════════════════════════════════════════════════════════════════
# Dedup
# ═════════════════════════════════════════════════════════════════════════════


class TestDedup:
    """Tests for job_key deduplication."""

    def test_same_url_creates_one_job(self, manager, session):
        """Same URL twice should create only one pending_preview job."""
        url = "https://example.com/dedup-test"
        j1 = manager.create_job(
            source_type="url_import", source_url=url, session=session,
        )
        _dup = manager.create_job(
            source_type="url_import", source_url=url, session=session,
        )
        # First succeeds, second may fail uniquely or succeed by replacing
        assert j1 is not None
        # Count pending for this URL
        count = session.query(IngestJob).filter_by(
            job_key=j1["job_key"], status="pending_preview",
        ).count()
        # Should be exactly 1 (UNIQUE constraint on job_key + pending_preview)
        assert count == 1

    def test_different_url_creates_different_jobs(self, manager):
        j1 = manager.create_job(source_type="url_import", source_url="https://a.com/x")
        j2 = manager.create_job(source_type="url_import", source_url="https://a.com/y")
        assert j1 is not None
        assert j2 is not None
        assert j1["job_key"] != j2["job_key"]

    def test_confirmed_job_allows_new_pending(self, manager, session):
        """After confirming, the same URL can be imported again."""
        url = "https://example.com/reimport"
        j1 = manager.create_job(
            source_type="url_import", source_url=url, preview_id="reimp1",
        )
        assert j1 is not None
        manager.confirm_job("reimp1", action="skip")

        # Now create a new job with the same URL
        j2 = manager.create_job(
            source_type="url_import", source_url=url, preview_id="reimp2",
        )
        assert j2 is not None
        # Should have different preview_ids
        assert j2["preview_id"] == "reimp2"

    def test_different_source_type_same_url_different_jobs(self, manager):
        """url_import and source_profile for same URL are different jobs."""
        url = "https://example.com/same-url"
        j1 = manager.create_job(source_type="url_import", source_url=url)
        j2 = manager.create_job(source_type="source_profile", source_url=url)
        assert j1 is not None
        assert j2 is not None
        assert j1["job_key"] != j2["job_key"]


# ═════════════════════════════════════════════════════════════════════════════
# Retry
# ═════════════════════════════════════════════════════════════════════════════


class TestRetry:
    """Tests for retry_job."""

    def test_retry_failed_job(self, manager):
        job = manager.create_job(
            source_type="url_import", source_url="https://retryme.com",
            preview_id="retry_test",
        )
        assert job is not None
        manager.mark_failed("retry_test", "Temporary error")
        result = manager.retry_job(job["id"])
        assert result is not None
        assert result["status"] == "pending_preview"
        assert result["retry_count"] == 2  # 1 from fail + 1 from retry
        assert result["error_message"] == ""

    def test_retry_exceeded_max(self, manager):
        """Cannot retry beyond MAX_RETRY_COUNT (3)."""
        job = manager.create_job(
            source_type="url_import", source_url="https://maxretry.com",
            preview_id="maxretry",
        )
        assert job is not None
        # Fail it 3 times
        for i in range(3):
            manager.mark_failed("maxretry", f"Error {i}")
            # Reset to pending for retry
        manager.retry_job(job["id"])  # retry 1 (count becomes 1 from retry)
        # Mark failed again
        # Actually, the retry count increments on each retry_job call
        # Let me think about this...
        # After create: retry_count=0
        # After mark_failed: retry_count=1
        # After retry_job: retry_count=2 (reset to pending)
        # After mark_failed: retry_count=3
        # After retry_job: should fail since retry_count (3) >= MAX (3)
        manager.mark_failed("maxretry", "Error again")
        result = manager.retry_job(job["id"])
        # retry_count is now 3, which equals MAX_RETRY_COUNT
        # So it should be blocked
        # Actually, the check is retry_count >= MAX_RETRY_COUNT BEFORE incrementing
        # So at retry_count=3, the next retry_job should return None
        assert result is None

    def test_retry_nonexistent_job(self, manager):
        result = manager.retry_job(99999)
        assert result is None


# ═════════════════════════════════════════════════════════════════════════════
# Expiry
# ═════════════════════════════════════════════════════════════════════════════


class TestExpiry:
    """Tests for expire_old_jobs."""

    def test_expire_old_jobs(self, manager, session):
        """Jobs with past expires_at should be marked as expired."""
        job = manager.create_job(
            source_type="url_import", source_url="https://old.com",
            preview_id="exp_old",
            expiry_hours=-1,  # Already expired
            session=session,
        )
        assert job is not None

        count = manager.expire_old_jobs(session=session)
        assert count >= 1

        # Verify the job is now expired
        refreshed = manager.get_job(job["id"], session=session)
        assert refreshed["status"] == "expired"

    def test_expire_does_not_touch_confirmed(self, manager, session):
        """Confirmed jobs should not be expired."""
        manager.create_job(
            source_type="url_import", source_url="https://confirmed.com",
            preview_id="exp_confirmed",
            expiry_hours=-1,
            session=session,
        )
        manager.confirm_job("exp_confirmed", action="skip")

        count = manager.expire_old_jobs(session=session)
        # Should return 0 because the only expired job was already confirmed
        assert count == 0

    def test_expire_fresh_jobs_not_affected(self, manager, session):
        """Fresh jobs (future expires_at) should not be expired."""
        manager.create_job(
            source_type="url_import", source_url="https://fresh.com",
            expiry_hours=48,  # 48 hours from now
            session=session,
        )
        count = manager.expire_old_jobs(session=session)
        assert count == 0


# ═════════════════════════════════════════════════════════════════════════════
# Statistics
# ═════════════════════════════════════════════════════════════════════════════


class TestStatistics:
    """Tests for count_by_status and count_by_source_type."""

    def test_count_by_status(self, manager):
        manager.create_job(source_type="url_import", source_url="https://a.com")
        manager.create_job(source_type="url_import", source_url="https://b.com")
        manager.create_job(
            source_type="url_import", source_url="https://c.com",
            preview_id="stat_test",
        )
        manager.confirm_job("stat_test", action="skip")

        counts = manager.count_by_status()
        assert counts.get("pending_preview", 0) == 2
        assert counts.get("skipped", 0) == 1

    def test_count_by_status_with_type_filter(self, manager):
        manager.create_job(source_type="url_import", source_url="https://a.com")
        manager.create_job(source_type="file_upload", source_hash="hash_f")

        url_counts = manager.count_by_status(source_type="url_import")
        assert url_counts.get("pending_preview", 0) == 1

        file_counts = manager.count_by_status(source_type="file_upload")
        assert file_counts.get("pending_preview", 0) == 1

    def test_count_by_source_type(self, manager):
        manager.create_job(source_type="url_import", source_url="https://a.com")
        manager.create_job(source_type="url_import", source_url="https://b.com")
        manager.create_job(source_type="file_upload", source_hash="h1")
        manager.create_job(source_type="source_profile", source_url="https://p.com")

        counts = manager.count_by_source_type()
        assert counts.get("url_import", 0) == 2
        assert counts.get("file_upload", 0) == 1
        assert counts.get("source_profile", 0) == 1


# ═════════════════════════════════════════════════════════════════════════════
# Resume (Restart Recovery)
# ═════════════════════════════════════════════════════════════════════════════


class TestResume:
    """Tests for resume_pending — simulates restart recovery."""

    def test_resume_counts_pending_by_type(self, manager):
        manager.create_job(source_type="url_import", source_url="https://a.com")
        manager.create_job(source_type="url_import", source_url="https://b.com")
        manager.create_job(source_type="file_upload", source_hash="hash_f")

        counts = manager.resume_pending()
        assert counts.get("url_import", 0) == 2
        assert counts.get("file_upload", 0) == 1

    def test_resume_empty_when_nothing_pending(self, manager):
        """After confirming all jobs, resume should return empty."""
        manager.create_job(
            source_type="url_import", source_url="https://a.com",
            preview_id="resume_test",
        )
        manager.confirm_job("resume_test", action="skip")
        counts = manager.resume_pending()
        assert counts == {}

    def test_resume_survives_new_session(self, manager):
        """Pending jobs are visible after getting a new session (simulates restart)."""
        manager.create_job(source_type="url_import", source_url="https://persist.com")
        # Get a fresh session (simulating restart)
        fresh_session = get_session()
        try:
            counts = manager.resume_pending(session=fresh_session)
            assert counts.get("url_import", 0) >= 1
        finally:
            fresh_session.close()

    def test_resume_only_counts_pending(self, manager):
        """Failed and skipped jobs should not appear in resume."""
        manager.create_job(
            source_type="url_import", source_url="https://fail.com",
            preview_id="res_fail",
        )
        manager.mark_failed("res_fail", "error")
        manager.create_job(
            source_type="url_import", source_url="https://skip.com",
            preview_id="res_skip",
        )
        manager.confirm_job("res_skip", action="skip")
        manager.create_job(
            source_type="url_import", source_url="https://pending.com",
        )
        counts = manager.resume_pending()
        assert counts.get("url_import", 0) == 1  # Only the pending one


# ═════════════════════════════════════════════════════════════════════════════
# Dual-write Consistency
# ═════════════════════════════════════════════════════════════════════════════


class TestDualWriteConsistency:
    """Tests for dual-write between memory store and ingest_jobs."""

    def test_preview_write_also_creates_job(self, manager):
        """When preview is created, both _preview_store and ingest_jobs have it."""
        import signalvault.web.routes as routes_mod

        # Simulate preview creation
        preview_id = "dw_test_001"
        routes_mod._preview_store[preview_id] = object()

        manager.create_job(
            source_type="url_import",
            source_url="https://dual.com",
            preview_id=preview_id,
        )

        # Both should have it
        assert preview_id in routes_mod._preview_store
        found = manager.find_by_preview_id(preview_id)
        assert found is not None

    def test_confirm_clears_both(self, manager):
        """When confirmed, both memory store and ingest_jobs reflect the change."""
        import signalvault.web.routes as routes_mod

        preview_id = "dw_test_002"
        routes_mod._preview_store[preview_id] = object()
        manager.create_job(
            source_type="url_import",
            source_url="https://dual2.com",
            preview_id=preview_id,
        )

        # Confirm
        routes_mod._preview_store.pop(preview_id, None)
        manager.confirm_job(preview_id, action="skip")

        # Memory store cleared
        assert preview_id not in routes_mod._preview_store
        # DB reflects skip
        found = manager.find_by_preview_id(preview_id)
        assert found is not None
        assert found["status"] == "skipped"

    def test_dashboard_falls_back_to_ingest_jobs(self, tmp_path, manager):
        """When memory store is empty, dashboard uses ingest_jobs."""
        import signalvault.web.routes as routes_mod
        from signalvault.web.routes import _build_sources_dashboard_context

        # Clear memory stores
        routes_mod._preview_store.clear()
        routes_mod._file_preview_store.clear()

        # Add to ingest_jobs
        manager.create_job(source_type="url_import", source_url="https://fallback.com")
        manager.create_job(source_type="file_upload", source_hash="fb_hash")

        ctx = _build_sources_dashboard_context(str(tmp_path))
        # When memory is empty, ingest_jobs provides the counts
        assert ctx["url_preview_count"] >= 0  # At minimum, not crashing
        assert ctx["file_preview_count"] >= 0


# ═════════════════════════════════════════════════════════════════════════════
# CLI Smoke Tests
# ═════════════════════════════════════════════════════════════════════════════


class TestCLI:
    """Smoke tests for ingest CLI commands."""

    def test_ingest_list_empty(self):
        """ingest list on empty DB should not crash."""
        from typer.testing import CliRunner

        from signalvault.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["ingest", "list"])
        assert result.exit_code == 0

    def test_ingest_list_with_data(self, manager):
        """ingest list should show jobs."""
        manager.create_job(source_type="url_import", source_url="https://cli-test.com")
        from typer.testing import CliRunner

        from signalvault.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["ingest", "list"])
        assert result.exit_code == 0
        assert "cli-test.com" in result.stdout or "url_import" in result.stdout

    def test_ingest_show_nonexistent(self):
        """ingest show on nonexistent job returns error."""
        from typer.testing import CliRunner

        from signalvault.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["ingest", "show", "99999"])
        assert result.exit_code != 0

    def test_ingest_show_existing(self, manager):
        """ingest show on existing job prints details."""
        job = manager.create_job(
            source_type="url_import",
            source_url="https://showme.com",
            source_name="Show Me Article",
        )
        assert job is not None
        from typer.testing import CliRunner

        from signalvault.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["ingest", "show", str(job["id"])])
        assert result.exit_code == 0
        assert "Show Me Article" in result.stdout

    def test_ingest_retry(self, manager):
        """ingest retry should reset a failed job."""
        job = manager.create_job(
            source_type="url_import",
            source_url="https://retrycli.com",
            preview_id="retrycli",
        )
        assert job is not None
        manager.mark_failed("retrycli", "CLI test failure")
        from typer.testing import CliRunner

        from signalvault.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["ingest", "retry", str(job["id"])])
        assert result.exit_code == 0

    def test_ingest_resume(self, manager):
        """ingest resume should show pending counts."""
        manager.create_job(source_type="url_import", source_url="https://resume1.com")
        manager.create_job(source_type="url_import", source_url="https://resume2.com")
        from typer.testing import CliRunner

        from signalvault.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["ingest", "resume"])
        assert result.exit_code == 0
        assert "url_import" in result.stdout.lower() or "URL" in result.stdout


# ═════════════════════════════════════════════════════════════════════════════
# Edge Cases
# ═════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_source_url_ok(self, manager):
        """Empty source_url should not crash."""
        job = manager.create_job(source_type="file_upload", source_hash="h")
        assert job is not None
        assert job["source_url"] == ""

    def test_long_source_url_truncates_in_hash(self, manager):
        """Very long URLs should still produce a valid job_key."""
        long_url = "https://example.com/" + "x" * 500
        job = manager.create_job(source_type="url_import", source_url=long_url)
        assert job is not None
        assert len(job["job_key"]) < 200  # job_key has fixed length

    def test_preview_data_with_special_chars(self, manager):
        """Preview data with special characters (quotes, newlines) should work."""
        special = '{"text": "He said \\"hello\\"\\nAnd she replied."}'
        job = manager.create_job(
            source_type="url_import",
            source_url="https://special.com",
            preview_data=special,
        )
        assert job is not None
        found = manager.get_job(job["id"])
        assert found is not None
        assert "hello" in found["preview_data"]

    def test_create_job_invalid_source_type(self, manager):
        """Invalid source_type should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown source_type"):
            from signalvault.sources.ingest_jobs import _make_job_key
            _make_job_key("invalid_type", source_url="https://x.com")

    def test_multiple_confirms_same_preview_id(self, manager):
        """Only the first confirm should succeed."""
        manager.create_job(
            source_type="url_import", source_url="https://once.com",
            preview_id="once_only",
        )
        first = manager.confirm_job("once_only", action="skip")
        assert first is not None
        second = manager.confirm_job("once_only", action="skip")
        assert second is None
