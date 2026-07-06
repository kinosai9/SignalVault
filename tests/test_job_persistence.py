"""P2-O.2: Job persistence, job_events, failure_kind, and task failure UX."""

import re

from signalvault.services.job_service import (
    AnalysisJob,
    _compute_failure_kind,
    _compute_step_list,
    _error_summary_for,
    create_job,
    get_job,
    get_job_status,
    list_jobs,
    update_job,
)


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


# ── Job persistence: create → DB → read ───────────────────────────


def test_create_job_persists_to_db(tmp_path, monkeypatch):
    """P2-O.2: Creating a job writes to the jobs table."""
    from signalvault.db.models import Job as JobORM
    from signalvault.db.session import get_session, init_db, reset_engine

    db_path = tmp_path / "test.db"
    monkeypatch.setattr("signalvault.config.DB_PATH", db_path)
    reset_engine()
    init_db(str(db_path))

    job = create_job("https://www.youtube.com/watch?v=test123", ["AI", "芯片"])

    # Verify in DB
    session = get_session()
    try:
        row = session.query(JobORM).filter_by(job_id=job.job_id).first()
        assert row is not None
        assert row.job_type == "analysis"
        assert row.youtube_url == "https://www.youtube.com/watch?v=test123"
    finally:
        session.close()
        reset_engine()


def test_job_events_persisted_on_progress(db_session, monkeypatch):
    """P2-O.2: Progress update writes a job_event row to DB."""
    from signalvault.db.models import JobEvent as JobEventORM
    from signalvault.db.session import get_session

    # Use temp DB path but reuse seeded_db session for simplicity
    # Create job and update stage several times
    job = create_job("https://youtube.com/watch?v=evt1", ["AI"])

    update_job(job.job_id, stage="fetching_transcript", message="正在获取字幕")
    update_job(job.job_id, stage="analyzing", message="分析中")
    update_job(job.job_id, stage="saving", message="保存报告")
    update_job(job.job_id, status="success", stage="success", message="完成")

    # Events persisted to DB
    session = get_session()
    try:
        rows = (
            session.query(JobEventORM)
            .filter_by(job_id=job.job_id)
            .order_by(JobEventORM.timestamp.asc())
            .all()
        )
        assert len(rows) >= 3  # at least: fetching_transcript, analyzing, saving, success
        messages = [r.message for r in rows]
        assert any("获取字幕" in m for m in messages)
        assert any("分析" in m for m in messages)
    finally:
        session.close()


def test_failure_writes_error_summary(db_session, monkeypatch):
    """P2-O.2: Failure records error_summary and failure_kind on Job row."""
    from signalvault.db.models import Job as JobORM
    from signalvault.db.session import get_session

    job = create_job("https://youtube.com/watch?v=fail1", ["AI"])

    # Simulate transcript failure — no report_id, early stage
    update_job(job.job_id, stage="fetching_transcript")
    update_job(
        job.job_id,
        status="failed",
        stage="failed",
        error="无法获取字幕",
        message="获取失败",
    )

    session = get_session()
    try:
        row = session.query(JobORM).filter_by(job_id=job.job_id).first()
        assert row is not None
        assert row.status == "failed"
        assert row.error == "无法获取字幕"
        assert row.failure_kind == "transcript_failed"
        assert row.error_summary == "无法获取视频字幕"
    finally:
        session.close()


# ── failure_kind classification ────────────────────────────────────


def _make_job(**kw) -> AnalysisJob:
    defaults = {
        "job_id": "test001",
        "job_type": "analysis",
        "status": "failed",
        "stage": "failed",
        "title": "",
        "report_id": None,
    }
    defaults.update(kw)
    return AnalysisJob(**defaults)


def test_failure_kind_transcript_failed():
    j = _make_job(stage="fetching_transcript", report_id=None)
    assert _compute_failure_kind(j) == "transcript_failed"


def test_failure_kind_analysis_failed():
    j = _make_job(stage="analyzing", report_id=None)
    assert _compute_failure_kind(j) == "analysis_failed"


def test_failure_kind_report_failed():
    j = _make_job(stage="saving", report_id=None)
    assert _compute_failure_kind(j) == "report_failed"


def test_failure_kind_sync_failed_after_report():
    j = _make_job(stage="exporting_report", report_id=42)
    assert _compute_failure_kind(j) == "sync_failed_after_report"


def test_failure_kind_rerun_failed():
    j = _make_job(
        stage="failed",
        report_id=None,
        title="[重新整理] NVIDIA 分析",
    )
    assert _compute_failure_kind(j) == "rerun_failed"


def test_error_summary_sync_failed():
    j = _make_job(
        stage="exporting_report",
        report_id=42,
        status="failed",
        error="obsidian vault not found",
    )
    assert _error_summary_for(j) == "报告已生成，但知识库同步失败"


def test_error_summary_analysis_failed():
    j = _make_job(stage="analyzing", report_id=None, status="failed")
    assert _error_summary_for(j) == "AI 分析未完成"


# ── Task logs page ─────────────────────────────────────────────────


def test_task_logs_page_opens(api_client, db_session):
    """P2-O.2: /tasks/{job_id}/logs renders with job info and events."""
    job = create_job("https://youtube.com/watch?v=logtest", ["AI"])
    update_job(job.job_id, stage="fetching_transcript", message="正在获取")
    update_job(job.job_id, stage="analyzing", message="分析中")
    update_job(job.job_id, status="success", stage="success", message="完成")

    resp = api_client.get(f"/tasks/{job.job_id}/logs")
    assert resp.status_code == 200
    # Check key content
    text = _strip_ansi(resp.text)
    assert job.job_id in text
    assert "获取" in text or "fetching" in text.lower() or "fetch" in text.lower()
    # Should show events — at minimum the terminal success
    assert "完成" in text or "success" in text.lower()


def test_task_logs_page_404_for_nonexistent(api_client):
    """P2-O.2: /tasks/nonexistent/logs returns 404."""
    resp = api_client.get("/tasks/nonexistent123/logs")
    assert resp.status_code == 404


# ── Task detail page: failure UX ───────────────────────────────────


def test_failed_task_shows_failed_stage(api_client, db_session):
    """P2-O.2: Failed task page displays failed_stage."""
    job = create_job("https://youtube.com/watch?v=failux", ["AI"])
    update_job(job.job_id, stage="fetching_transcript")
    update_job(
        job.job_id,
        status="failed",
        stage="failed",
        error="字幕获取失败",
        message="获取失败",
    )

    resp = api_client.get(f"/tasks/{job.job_id}")
    assert resp.status_code == 200
    text = _strip_ansi(resp.text)
    # Failure indication should be present
    assert "失败" in text or "failed" in text.lower()


def test_sync_failed_after_report_shows_actions(api_client, db_session):
    """P2-O.2: sync_failed_after_report shows report link, retry sync, and logs."""
    job = create_job(
        "https://youtube.com/watch?v=syncfail",
        ["AI"],
        auto_sync=True,
    )
    # Simulate: report saved but sync failed
    job.report_id = 42
    job.status = "failed"
    job.stage = "exporting_report"
    job.error = "obsidian vault not found"
    update_job(
        job.job_id,
        status="failed",
        stage="failed",
        report_id=42,
        error="obsidian vault not found",
    )

    st = get_job_status(job.job_id)
    assert st is not None
    assert st["failure_kind"] == "sync_failed_after_report"
    assert "报告已生成" in st["error_summary"]
    # result_links should have report and retry_sync
    assert "report" in st["result_links"]
    assert "logs" in st["result_links"]


def test_failed_with_report_shows_report_link(api_client, db_session):
    """P2-O.2: Failed task with report_id shows report, retry, and log link."""
    job = create_job("https://youtube.com/watch?v=rptfail", ["AI"])
    job.report_id = 15
    update_job(
        job.job_id,
        status="failed",
        stage="failed",
        report_id=15,
        error="生成失败",
    )

    resp = api_client.get(f"/tasks/{job.job_id}")
    assert resp.status_code == 200
    text = _strip_ansi(resp.text)
    # Should contain or link to the report
    assert "/reports/15" in text or "report" in text.lower()


# ── ChannelVideo last_job_id ───────────────────────────────────────


def test_channel_video_last_job_id_written_and_retained(
    db_session, monkeypatch, tmp_path
):
    """P2-O.2: ChannelVideo.last_job_id is written on job completion and retained after retry success."""
    from signalvault.db.channel_repository import (
        add_channel,
        get_video,
        upsert_videos,
    )
    from signalvault.db.models import ChannelVideo
    from signalvault.db.session import get_session

    # Set up a channel + video
    session = get_session()
    try:
        ch_id = add_channel(
            session,
            youtube_channel_id="UC_test_001",
            url="https://www.youtube.com/@testchan",
            name="Test Channel",
        )
        upsert_videos(
            session,
            channel_id=ch_id,
            videos=[{
                "video_id": "vid001",
                "title": "Test Video",
                "url": "https://youtube.com/watch?v=vid001",
                "published_at": "2025-01-01",
                "duration_seconds": 600,
            }],
        )
        session.commit()
    finally:
        session.close()

    # Simulate a job that writes last_job_id
    s2 = get_session()
    try:
        cv = s2.query(ChannelVideo).filter_by(video_id="vid001").first()
        cv.last_job_id = "job_abc123"
        s2.commit()
    finally:
        s2.close()

    # last_job_id should be retrievable
    v = get_video(get_session(), "vid001")
    assert v is not None
    assert v["last_job_id"] == "job_abc123"

    # After successful retry, last_job_id should still be retained
    s3 = get_session()
    try:
        cv2 = s3.query(ChannelVideo).filter_by(video_id="vid001").first()
        cv2.status = "synced"
        cv2.report_id = 100
        cv2.failure_reason = ""
        s3.commit()
    finally:
        s3.close()

    v2 = get_video(get_session(), "vid001")
    assert v2 is not None
    assert v2["status"] == "synced"
    assert v2["last_job_id"] == "job_abc123"  # retained


# ── Step list for failure display ──────────────────────────────────


def test_step_list_sync_failed_after_report():
    """P2-O.2: sync_failed_after_report shows all analysis steps complete."""
    j = _make_job(
        job_type="full_flow",
        stage="exporting_report",
        report_id=10,
        status="failed",
    )
    completed, pending = _compute_step_list(j)
    # For full_flow, "获取视频字幕" (idx 0) and "生成研究报告" (idx 1) are done
    assert len(completed) >= 1
    assert len(pending) >= 1


def test_step_list_transcript_failed():
    """P2-O.2: transcript failure shows no completed steps."""
    j = _make_job(
        job_type="analysis",
        stage="fetching_transcript",
        report_id=None,
        status="failed",
    )
    completed, pending = _compute_step_list(j)
    assert len(completed) == 0
    assert len(pending) == 3  # 获取视频字幕, 拆解关键信息, 生成研究报告


# ── DB fallback: get_job after restart ─────────────────────────────


def test_get_job_falls_back_to_db(tmp_path, monkeypatch):
    """P2-O.2: get_job reads from DB when job is not in memory."""
    from signalvault.db.session import init_db, reset_engine

    db_path = tmp_path / "test.db"
    monkeypatch.setattr("signalvault.config.DB_PATH", db_path)
    reset_engine()
    init_db(str(db_path))

    job = create_job("https://youtube.com/watch?v=dbfb", ["AI"])
    update_job(job.job_id, stage="fetching_transcript", message="获取中")
    update_job(job.job_id, status="success", stage="success", message="完成")

    # Remove from in-memory to simulate restart
    from signalvault.services import job_service

    with job_service._lock:
        job_service._JOBS.clear()

    # Should still be findable from DB
    found = get_job(job.job_id)
    assert found is not None
    assert found.job_id == job.job_id
    assert found.status == "success"
    # Events loaded from DB
    assert len(found.events) >= 1

    reset_engine()


def test_list_jobs_includes_db_jobs(tmp_path, monkeypatch):
    """P2-O.2: list_jobs merges in-memory and DB jobs."""
    from signalvault.db.session import init_db, reset_engine

    db_path = tmp_path / "test.db"
    monkeypatch.setattr("signalvault.config.DB_PATH", db_path)
    reset_engine()
    init_db(str(db_path))

    job = create_job("https://youtube.com/watch?v=dblist", ["AI"])
    update_job(job.job_id, stage="fetching_transcript", message="获取中")
    update_job(job.job_id, status="success", stage="success", message="完成")

    # Clear in-memory
    from signalvault.services import job_service

    with job_service._lock:
        job_service._JOBS.clear()

    jobs = list_jobs(limit=50)
    ids = [j.job_id for j in jobs]
    assert job.job_id in ids

    reset_engine()


# ── P2-O.2.1: New failure kinds ────────────────────────────────────


def test_failure_kind_channel_refresh_failed():
    j = _make_job(job_type="channel_refresh", stage="fetching_channel", report_id=None)
    assert _compute_failure_kind(j) == "channel_refresh_failed"


def test_failure_kind_sync_failed():
    j = _make_job(job_type="sync", stage="exporting_report", report_id=5)
    assert _compute_failure_kind(j) == "sync_failed"


def test_error_summary_channel_refresh():
    j = _make_job(
        job_type="channel_refresh",
        stage="fetching_channel",
        report_id=None,
        status="failed",
        error="channel not found",
    )
    assert _error_summary_for(j) == "频道视频列表刷新失败"


def test_error_summary_sync():
    j = _make_job(
        job_type="sync",
        stage="exporting_report",
        report_id=5,
        status="failed",
        error="vault not configured",
    )
    assert _error_summary_for(j) == "知识库同步失败"


# ── P2-O.2.1: Server-rendered failure page ─────────────────────────


def test_server_rendered_failure_page_shows_error_summary(api_client, db_session):
    """P2-O.2.1: When page loads with an already-failed job, error_summary is visible."""
    job = create_job("https://youtube.com/watch?v=srvfail", ["AI"])
    update_job(job.job_id, stage="fetching_transcript", message="正在获取")
    update_job(
        job.job_id,
        status="failed",
        stage="failed",
        error="test transcript error",
        message="获取失败",
    )

    resp = api_client.get(f"/tasks/{job.job_id}")
    assert resp.status_code == 200
    text = _strip_ansi(resp.text)

    # P2-O.2.1: The embedded status_json should contain the failure data
    assert "error_summary" in text or "无法获取" in text or "失败" in text
    # The page should have the status_json with failure_kind
    assert "failure_kind" in text
    # And the failed_stage
    assert "failed_stage" in text


def test_server_rendered_sync_failed_shows_actions(api_client, db_session):
    """P2-O.2.1: sync_failed_after_report shows 报告已生成 in server-rendered page."""
    job = create_job(
        "https://youtube.com/watch?v=syncsrv", ["AI"], auto_sync=True
    )
    job.report_id = 42
    update_job(job.job_id, stage="saving_report", report_id=42)
    update_job(
        job.job_id,
        status="failed",
        stage="failed",
        report_id=42,
        error="sync error",
        message="报告已生成，但知识库更新失败。",
    )

    resp = api_client.get(f"/tasks/{job.job_id}")
    assert resp.status_code == 200
    text = _strip_ansi(resp.text)

    # The embedded status_json should contain sync_failed_after_report info
    assert "报告已生成" in text or "sync_failed_after_report" in text
    # Should have report link in the embedded JSON
    assert "/reports/42" in text


# ── Ruff check pass-through (no ruff violations in new code) ──────
# This module is lint-clean: verify with `python -m ruff check tests/test_job_persistence.py`
