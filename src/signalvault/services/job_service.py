"""P2-K.2.1 / P2-O.2: Hybrid job service — in-memory active + DB persisted.

Active jobs tracked in memory for heartbeat/live-status.
All job creates/updates/events persisted to DB for history and log access.
On restart, historical jobs readable from DB even if in-memory is gone.

Status lifecycle:
    queued → running → long_running → success
    queued → running → long_running → failed
    queued → running → long_running → stale (no heartbeat)

Heartbeat thresholds are module-level for easy monkeypatching in tests.
"""

from __future__ import annotations

import json
import logging
import threading
import time as _time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

_log = logging.getLogger(__name__)

_MAX_JOBS = 50

# Heartbeat thresholds (seconds) — monkeypatchable for tests
LONG_JOB_THRESHOLD = 300   # 5 min: running → long_running
STALE_THRESHOLD = 600       # 10 min without heartbeat → stale

# Stage → user-visible message (shared across job types)
_ALL_STAGES: dict[str, str] = {
    # Analysis stages
    "queued": "已收到请求",
    "fetching_transcript": "正在获取视频字幕",
    "cleaning": "正在整理字幕内容",
    "analyzing": "正在进行 AI 分析",
    "analyzing_chunk": "正在分析",
    "saving": "正在生成报告",
    # Sync stages
    "exporting_report": "正在导出报告到知识库",
    "updating_cards": "正在更新主题和公司",
    "updating_relations": "正在建立知识关联",
    "refreshing_brief": "正在刷新研究摘要",
    "refreshing_watchlist": "正在刷新我的关注",
    # Full_flow stages
    "saving_report": "正在保存报告",
    "syncing_knowledge_base": "正在更新知识库",
    # Channel refresh stages
    "fetching_channel": "正在获取频道视频列表",
    "reading_video_metadata": "正在读取视频发布时间",
    "checking_import_status": "正在检查已整理状态",
    "saving_video_list": "正在更新视频列表",
    # Terminal
    "success": "任务已完成",
    "failed": "任务失败",
}

# Job-type → human-readable label
JOB_TYPE_LABELS: dict[str, str] = {
    "analysis": "生成报告",
    "sync": "同步知识库",
    "full_flow": "整理进知识库",
    "channel_refresh": "刷新频道",
}

# Job-type → page title/description
JOB_TYPE_TITLES: dict[str, str] = {
    "analysis": "正在生成研究报告",
    "sync": "正在同步到知识库",
    "full_flow": "正在整理进知识库",
    "channel_refresh": "正在刷新频道视频列表",
}

JOB_TYPE_DESCRIPTIONS: dict[str, str] = {
    "analysis": "AI 正在获取字幕、拆解观点并生成研究报告。",
    "sync": "系统正在更新 Obsidian、研究摘要和我的关注。",
    "full_flow": "系统会先生成研究报告，再更新知识库、研究摘要和我的关注。长视频可能需要较长时间，你可以离开页面，稍后从「整理任务」查看结果。",
    "channel_refresh": "系统正在获取 YouTube 频道最新视频列表并读取发布日期。通常需要数十秒。",
}


def _now_epoch() -> float:
    return _time.time()


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class JobEvent:
    """Lightweight event record for job timeline / logs."""
    timestamp: str
    level: str  # info / warning / error
    stage: str
    message: str
    detail: str | None = None


@dataclass
class AnalysisJob:
    """Unified job model for all background task types.

    Backward-compatible with P2-K.1/P2-K.2 code that references .job_id,
    .job_type, .status, .stage, .message, .youtube_url, .focus_areas, .depth,
    .mock, .report_id, .error, .created_at, .updated_at.
    """

    job_id: str
    job_type: str = "analysis"  # "analysis" | "sync" | "full_flow" | "channel_refresh"
    status: str = "queued"      # queued | running | long_running | success | failed | stale
    stage: str = "queued"
    message: str = ""
    title: str = ""
    source_url: str = ""

    # Analysis-specific
    youtube_url: str = ""
    focus_areas: list[str] = field(default_factory=list)
    depth: str = "standard"
    mock: bool = False
    auto_sync: bool = False  # P2-K.3: auto chain sync after analysis

    # Common
    report_id: int | None = None
    error: str | None = None

    # Timing & heartbeat
    created_at: str = field(default_factory=_now_iso)
    started_at: str = ""
    updated_at: str = ""
    last_heartbeat_at: float = 0.0

    # Step progress
    current_step: int | None = None
    total_steps: int | None = None

    # UX flags
    can_leave_page: bool = False

    # Result links (populated on success)
    result_links: dict[str, str] = field(default_factory=dict)

    # P2-M.1.1: Source context for status writeback
    source_type: str = ""       # "channel_video" | "manual" | ""
    source_channel_id: int | None = None
    video_id: str = ""

    # P2-M.4.1: Event log for failure UX & task logs page
    events: list[JobEvent] = field(default_factory=list)


# In-memory store
_JOBS: dict[str, AnalysisJob] = {}
_lock = threading.Lock()

# ── M2: Graceful shutdown support ─────────────────────────────────────────
_shutdown_event = threading.Event()
_active_threads: list[threading.Thread] = []


def is_shutdown_requested() -> bool:
    """Return True if the launcher has requested background task shutdown."""
    return _shutdown_event.is_set()


def shutdown_background_jobs(timeout: float = 5.0) -> None:
    """Signal all background threads to stop and wait for them to finish.

    This is called from the FastAPI lifespan shutdown and the Launcher
    exit path.  Threads should check ``is_shutdown_requested()`` at
    reasonable boundaries.
    """
    _shutdown_event.set()
    _log.info(
        "Shutdown event set; waiting up to %.1fs for %d active thread(s)",
        timeout, len(_active_threads),
    )
    deadline = _time.monotonic() + timeout
    for t in list(_active_threads):
        remaining = max(0.0, deadline - _time.monotonic())
        if t.is_alive():
            t.join(timeout=remaining)
            if t.is_alive():
                _log.warning("Thread %s did not exit within shutdown window", t.name)
    _active_threads.clear()
    _log.info("Background task shutdown complete")


def _register_thread(t: threading.Thread) -> None:
    """Register a background thread for shutdown tracking."""
    _active_threads.append(t)
    # Prune dead threads
    _active_threads[:] = [th for th in _active_threads if th.is_alive()]


def create_job(
    youtube_url: str,
    focus_areas: list[str],
    depth: str = "standard",
    mock: bool = False,
    auto_sync: bool = False,
    title: str = "",
) -> AnalysisJob:
    """Create a new analysis job.

    Args:
        auto_sync: If True, job_type="full_flow" — analysis + sync chained automatically.
        title: Optional display title (overrides JOB_TYPE_TITLES default).
    """
    job_type = "full_flow" if auto_sync else "analysis"
    job_id = uuid.uuid4().hex[:12]
    job = AnalysisJob(
        job_id=job_id,
        job_type=job_type,
        status="queued",
        stage="queued",
        message=_stage_message("queued"),
        title=title or JOB_TYPE_TITLES.get(job_type, ""),
        youtube_url=youtube_url,
        focus_areas=focus_areas,
        depth=depth,
        mock=mock,
        auto_sync=auto_sync,
        source_url=youtube_url,
    )
    with _lock:
        _JOBS[job_id] = job
        _prune_if_needed()
    _persist_job(job)  # P2-O.2: persist on create
    return job


def create_sync_job(report_id: int) -> AnalysisJob:
    """Create a new knowledge sync job.

    P2-N.4.1: Fetches report metadata to set a descriptive title
    (e.g. '同步: OpenAI CFO Interview' instead of generic '同步到知识库').
    """
    job_id = uuid.uuid4().hex[:12]
    title = JOB_TYPE_TITLES.get("sync", "")
    source_url = ""
    video_id = ""

    # Look up report context for descriptive title
    try:
        from signalvault.db.repository import get_report_detail
        from signalvault.db.session import get_session
        session = get_session()
        try:
            detail = get_report_detail(session, report_id)
            if detail:
                report_title = detail.get("episode_title", "") or detail.get("video_id", "")
                vid = detail.get("video_id", "")
                if report_title and report_title != vid:
                    short_title = report_title[:50]
                    title = f"同步: {short_title}"
                elif vid:
                    title = f"同步报告 #{report_id} ({vid})"
                else:
                    title = f"同步报告 #{report_id}"
                source_url = detail.get("source_url", "")
                video_id = vid
        finally:
            session.close()
    except Exception:
        title = f"同步报告 #{report_id}"

    job = AnalysisJob(
        job_id=job_id,
        job_type="sync",
        status="queued",
        stage="queued",
        message=_stage_message("queued"),
        title=title,
        report_id=report_id,
        source_url=source_url,
        video_id=video_id,
    )
    with _lock:
        _JOBS[job_id] = job
        _prune_if_needed()
    _persist_job(job)  # P2-O.2: persist on create
    return job


def _prune_if_needed() -> None:
    if len(_JOBS) > _MAX_JOBS:
        oldest = sorted(_JOBS.keys(), key=lambda k: _JOBS[k].created_at)[:10]
        for k in oldest:
            del _JOBS[k]


def get_job(job_id: str) -> AnalysisJob | None:
    """Get job from in-memory store, falling back to DB persistence.

    P2-O.2: If job is not in memory (e.g. after server restart), reads from DB.
    """
    job = _JOBS.get(job_id)
    if job is not None:
        return job
    return _get_job_from_db(job_id)


def list_jobs(limit: int = 20) -> list[AnalysisJob]:
    """Return recent jobs for the unified task list page.

    P2-O.2: Merges in-memory active jobs with DB-persisted terminal jobs.
    In-memory jobs take precedence (newer state for active/queued).
    """
    mem_jobs: dict[str, AnalysisJob] = {}
    with _lock:
        mem_jobs = dict(_JOBS)

    # Get DB jobs
    db_jobs: dict[str, AnalysisJob] = {}
    try:
        from signalvault.db.models import Job as JobORM
        from signalvault.db.session import get_session

        session = get_session()
        try:
            rows = session.query(JobORM).order_by(JobORM.created_at.desc()).limit(limit * 2).all()
            for row in rows:
                if row.job_id not in mem_jobs:
                    db_jobs[row.job_id] = _orm_to_dataclass(row)
        finally:
            session.close()
    except Exception:
        _log.warning("Failed to list jobs from DB", exc_info=True)

    # Merge: in-memory first (active/live), then DB (historical)
    merged = list(mem_jobs.values())
    for jid, job in db_jobs.items():
        if jid not in mem_jobs:
            merged.append(job)

    merged.sort(key=lambda j: j.created_at, reverse=True)
    return merged[:limit]


def _get_job_from_db(job_id: str) -> AnalysisJob | None:
    """Load a job from DB persistence."""
    try:
        from signalvault.db.models import Job as JobORM
        from signalvault.db.session import get_session

        session = get_session()
        try:
            row = session.query(JobORM).filter_by(job_id=job_id).first()
            if row:
                return _orm_to_dataclass(row)
        finally:
            session.close()
    except Exception:
        _log.warning("Failed to load job %s from DB", job_id, exc_info=True)
    return None


def count_active_jobs() -> int:
    """Count jobs that are still active (queued/running/long_running)."""
    with _lock:
        return sum(1 for j in _JOBS.values() if j.status in ("queued", "running", "long_running"))


def update_job(
    job_id: str,
    *,
    stage: str = "",
    status: str = "",
    message: str = "",
    report_id: int | None = None,
    error: str = "",
    current_step: int | None = None,
    total_steps: int | None = None,
    event_level: str = "",
    event_detail: str | None = None,
) -> None:
    """Thread-safe job update. Always bumps last_heartbeat_at.

    P2-M.4.1: Records a JobEvent when stage/status/error changes.
    """
    now = _now_epoch()
    with _lock:
        job = _JOBS.get(job_id)
        if not job:
            return
        stage_changed = bool(stage and stage != job.stage)
        status_changed = bool(status and status != job.status)
        has_error = bool(error)

        if stage:
            job.stage = stage
            if not message:
                job.message = _stage_message(stage)
        if status:
            job.status = status
        if message:
            job.message = message
        if report_id is not None:
            job.report_id = report_id
        if error:
            job.error = error
        if current_step is not None:
            job.current_step = current_step
        if total_steps is not None:
            job.total_steps = total_steps
        job.updated_at = _now_iso()
        job.last_heartbeat_at = now
        if not job.started_at:
            job.started_at = _now_iso()

        # Record event for stage/status/error transitions
        if has_error:
            _add_event(job, "error", job.stage, message or error, event_detail or error)
        elif status_changed and status in ("success", "failed"):
            level = "info" if status == "success" else "error"
            _add_event(job, level, job.stage, message or _stage_message(job.stage), event_detail)
        elif stage_changed:
            _add_event(job, event_level or "info", job.stage, message or _stage_message(job.stage), event_detail)

        # P2-O.2: Persist job state to DB on every update
        _persist_job(job)


def _stage_message(stage: str) -> str:
    return _ALL_STAGES.get(stage, stage)


def _add_event(
    job: AnalysisJob,
    level: str,
    stage: str,
    message: str,
    detail: str | None = None,
) -> None:
    """Record a JobEvent on the job for timeline / failure diagnosis.

    P2-O.2: Also persists event to DB.
    """
    ts = _now_iso()
    event = JobEvent(
        timestamp=ts,
        level=level,
        stage=stage,
        message=message,
        detail=detail,
    )
    job.events.append(event)
    _persist_event(job.job_id, ts, level, stage, message, detail)


# ── P2-O.2: DB Persistence Layer ──────────────────────────────────────


def _persist_job(job: AnalysisJob) -> None:
    """Insert or update a Job row in the database.

    Safe: skips silently if DB engine is not initialized (e.g. in tests
    that don't use db_session fixture and haven't monkeypatched DB_PATH).
    """
    try:
        from signalvault.db.models import Job as JobORM
        from signalvault.db.session import _engine, _SessionLocal, get_session

        if _engine is None and _SessionLocal is None:
            return  # DB not initialized, skip persistence

        session = get_session()
        try:
            existing = session.query(JobORM).filter_by(job_id=job.job_id).first()
            if existing:
                _update_job_orm(existing, job)
            else:
                session.add(_job_to_orm(job))
            session.commit()
        finally:
            session.close()
    except Exception:
        _log.warning("Failed to persist job %s to DB", job.job_id, exc_info=True)


def _persist_event(
    job_id: str,
    timestamp: str,
    level: str,
    stage: str,
    message: str,
    detail: str | None,
) -> None:
    """Insert a JobEvent row in the database.

    Safe: skips silently if DB engine is not initialized.
    """
    try:
        from signalvault.db.models import JobEvent as JobEventORM
        from signalvault.db.session import _engine, _SessionLocal, get_session

        if _engine is None and _SessionLocal is None:
            return  # DB not initialized, skip persistence

        session = get_session()
        try:
            evt = JobEventORM(
                job_id=job_id,
                timestamp=datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S"),
                level=level,
                stage=stage,
                message=message[:500],
                detail=detail,
            )
            session.add(evt)
            session.commit()
        finally:
            session.close()
    except Exception:
        _log.warning("Failed to persist event for job %s", job_id, exc_info=True)


def _job_to_orm(job: AnalysisJob):
    """Convert in-memory AnalysisJob to ORM Job instance."""
    from signalvault.db.models import Job as JobORM

    return JobORM(
        job_id=job.job_id,
        job_type=job.job_type,
        status=job.status,
        stage=job.stage,
        title=job.title,
        source_url=job.source_url,
        youtube_url=job.youtube_url,
        focus_areas=json.dumps(job.focus_areas, ensure_ascii=False),
        depth=job.depth,
        mock=job.mock,
        auto_sync=job.auto_sync,
        report_id=job.report_id,
        error=job.error,
        source_type=job.source_type,
        source_channel_id=job.source_channel_id,
        video_id=job.video_id,
        created_at=_parse_dt(job.created_at) or datetime.now(),
        started_at=_parse_dt(job.started_at),
        completed_at=datetime.now() if job.status in ("success", "failed") else None,
    )


def _update_job_orm(orm, job: AnalysisJob) -> None:
    """Update an existing ORM Job row from in-memory job."""
    orm.status = job.status
    orm.stage = job.stage
    orm.title = job.title or orm.title
    orm.report_id = job.report_id
    orm.error = job.error
    orm.failure_kind = _compute_failure_kind(job) if job.status == "failed" else None
    orm.error_summary = _error_summary_for(job)
    if job.status in ("success", "failed"):
        orm.completed_at = datetime.now()


def _orm_to_dataclass(orm) -> AnalysisJob:
    """Convert ORM Job to in-memory AnalysisJob dataclass.

    Reconstructs events from DB job_events table.
    """
    job = AnalysisJob(
        job_id=orm.job_id,
        job_type=orm.job_type,
        status=orm.status,
        stage=orm.stage,
        title=orm.title or "",
        source_url=orm.source_url or "",
        youtube_url=orm.youtube_url or "",
        focus_areas=_parse_focus_areas(orm.focus_areas),
        depth=orm.depth or "standard",
        mock=bool(orm.mock),
        auto_sync=bool(orm.auto_sync),
        report_id=orm.report_id,
        error=orm.error,
        source_type=orm.source_type or "",
        source_channel_id=orm.source_channel_id,
        video_id=orm.video_id or "",
        created_at=_fmt_dt(orm.created_at) or _now_iso(),
        started_at=_fmt_dt(orm.started_at) or "",
    )
    # Load events from DB
    try:
        from signalvault.db.models import JobEvent as JobEventORM
        from signalvault.db.session import get_session

        session = get_session()
        try:
            rows = (
                session.query(JobEventORM)
                .filter_by(job_id=orm.job_id)
                .order_by(JobEventORM.timestamp.asc())
                .all()
            )
            for row in rows:
                job.events.append(
                    JobEvent(
                        timestamp=_fmt_dt(row.timestamp) or "",
                        level=row.level or "info",
                        stage=row.stage or "",
                        message=row.message or "",
                        detail=row.detail,
                    )
                )
        finally:
            session.close()
    except Exception:
        _log.warning("Failed to load events for job %s", orm.job_id, exc_info=True)

    return job


def _parse_focus_areas(raw: str | None) -> list[str]:
    """Parse focus_areas JSON string to list."""
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_dt(s: str | None) -> datetime | None:
    """Parse ISO datetime string."""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def _fmt_dt(dt: datetime | None) -> str:
    """Format datetime to ISO string."""
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def delete_job(job_id: str) -> None:
    """P2-N.4.1: Delete a job from in-memory store and DB."""
    import logging as _logging
    _log = _logging.getLogger(__name__)
    with _lock:
        _JOBS.pop(job_id, None)
    try:
        from signalvault.db.models import Job as JobORM
        from signalvault.db.models import JobEvent as JobEventORM
        from signalvault.db.session import get_session
        session = get_session()
        try:
            session.query(JobEventORM).filter_by(job_id=job_id).delete()
            session.query(JobORM).filter_by(job_id=job_id).delete()
            session.commit()
        finally:
            session.close()
    except Exception:
        _log.warning("Failed to delete job %s from DB", job_id, exc_info=True)


def _cleanup_old_failures(video_id: str, current_job_id: str) -> None:
    """P2-N.4.1: When a job succeeds, auto-clean old failed jobs for same video_id.

    Same task = same video_id. Old failures have no value once retry succeeds.
    """
    if not video_id:
        return
    with _lock:
        for jid, job in list(_JOBS.items()):
            if jid == current_job_id:
                continue
            if job.video_id == video_id and job.status == "failed":
                job.status = "cleaned"
    # Also mark in DB
    try:
        from signalvault.db.models import Job as JobORM
        from signalvault.db.session import get_session
        session = get_session()
        try:
            rows = session.query(JobORM).filter(
                JobORM.video_id == video_id,
                JobORM.job_id != current_job_id,
                JobORM.status == "failed",
            ).all()
            for row in rows:
                row.status = "cleaned"
            session.commit()
        finally:
            session.close()
    except Exception:
        pass


def _error_summary_for(job: AnalysisJob) -> str | None:
    """Compute a user-facing error summary for persistence."""
    if job.status != "failed":
        return None
    fk = _compute_failure_kind(job)
    messages = {
        "transcript_failed": "无法获取视频字幕",
        "analysis_failed": "AI 分析未完成",
        "report_failed": "报告生成失败",
        "sync_failed_after_report": "报告已生成，但知识库同步失败",
        "sync_failed": "知识库同步失败",
        "rerun_failed": "重新整理失败",
        "channel_refresh_failed": "频道视频列表刷新失败",
    }
    return messages.get(fk, "整理失败")


def _check_heartbeat(job: AnalysisJob, now: float) -> str:
    """Determine effective status based on heartbeat health.

    Returns one of: running, long_running, stale (or unchanged for terminal states).
    """
    if job.status in ("success", "failed"):
        return job.status

    if job.last_heartbeat_at == 0:
        return "queued"

    elapsed = now - job.last_heartbeat_at
    total_elapsed = now - (job.last_heartbeat_at - _time.time() + now)  # approximate
    # More direct: compute from started
    if job.started_at:
        try:
            started_dt = datetime.strptime(job.started_at, "%Y-%m-%d %H:%M:%S")
            total_elapsed = now - started_dt.timestamp()
        except (ValueError, OSError):
            total_elapsed = 0
    else:
        total_elapsed = 0

    if elapsed >= STALE_THRESHOLD:
        return "stale"
    if total_elapsed >= LONG_JOB_THRESHOLD and elapsed < STALE_THRESHOLD:
        return "long_running"
    if job.status in ("queued",):
        return "running" if job.started_at else "queued"
    return "running"


def _compute_elapsed(job: AnalysisJob, now: float) -> int:
    """Compute elapsed seconds since job started."""
    if not job.started_at:
        return 0
    try:
        started_dt = datetime.strptime(job.started_at, "%Y-%m-%d %H:%M:%S")
        return max(0, int(now - started_dt.timestamp()))
    except (ValueError, OSError):
        return 0


def _build_can_leave(job: AnalysisJob, now: float) -> bool:
    """Determine if user can safely leave the page."""
    if job.status in ("success", "failed", "stale"):
        return True
    elapsed = _compute_elapsed(job, now)
    return elapsed >= LONG_JOB_THRESHOLD


# ── P2-M.4.1: Failure kind detection ──────────────────────────────────

def _compute_failure_kind(job: AnalysisJob) -> str:
    """Determine the failure category for UX display.

    Uses events to find the last real stage before failure (since job.stage
    gets overwritten to "failed" on error).

    Returns one of:
        transcript_failed — before transcript fetch, no report_id
        analysis_failed — transcript fetched, no report_id, failed in analysis
        report_failed — failed during report saving, no report_id
        sync_failed_after_report — report_id exists, failed during sync
        sync_failed — sync-only job failed, report_id may or may not exist
        rerun_failed — job is a rerun/full_flow with "重新整理" in title
        channel_refresh_failed — channel_refresh job failed
        unknown — fallback
    """
    is_rerun = "重新整理" in (job.title or "")

    # Channel refresh failures
    if job.job_type == "channel_refresh":
        return "channel_refresh_failed"

    # Sync-only job failures (no analysis phase)
    if job.job_type == "sync":
        return "sync_failed"

    if job.report_id:
        if is_rerun:
            return "rerun_failed"
        return "sync_failed_after_report"

    # Find the last real stage before failure from events
    stage = job.stage
    if stage == "failed":
        for evt in reversed(job.events):
            if evt.stage and evt.stage != "failed":
                stage = evt.stage
                break

    # No report_id → analysis phase failed
    if stage in ("queued", "fetching_transcript", ""):
        return "transcript_failed"

    if stage in ("cleaning", "analyzing", "analyzing_chunk"):
        return "analysis_failed"

    if stage in ("saving", "saving_report"):
        return "report_failed"

    if is_rerun:
        return "rerun_failed"

    return "analysis_failed"


def _compute_step_list(job: AnalysisJob) -> tuple[list[str], list[str]]:
    """Compute completed and pending steps based on job stage and events.

    Returns (completed_steps, pending_steps).
    """
    all_steps: list[str] = []
    if job.job_type == "full_flow":
        all_steps = [
            "获取视频字幕",
            "生成研究报告",
            "同步到 Obsidian 知识库",
            "更新主题和公司卡片",
            "生成观点和信号",
            "建立知识关联",
            "刷新研究摘要",
            "刷新我的关注",
        ]
    elif job.job_type == "analysis":
        all_steps = [
            "获取视频字幕",
            "拆解关键信息",
            "生成研究报告",
        ]
    elif job.job_type == "sync":
        all_steps = [
            "导出报告到 Obsidian",
            "更新主题和公司卡片",
            "生成观点和信号",
            "建立知识关联",
            "刷新研究摘要",
            "刷新我的关注",
        ]
    elif job.job_type == "channel_refresh":
        all_steps = [
            "获取频道视频列表",
            "读取视频发布时间",
            "检查已整理状态",
            "更新视频列表",
        ]

    # Map stage to the step index that was completed
    stage_order: dict[str, int] = {
        # full_flow / analysis
        "fetching_transcript": 0,
        "cleaning": 0,
        "analyzing": 1,
        "analyzing_chunk": 1,
        "saving": 2,
        "saving_report": 2,
        # sync
        "exporting_report": 0,
        "updating_cards": 1,
        "generating_claims_signals": 2,
        "updating_relations": 3,
        "refreshing_brief": 4,
        "refreshing_watchlist": 5,
        # channel_refresh
        "fetching_channel": 0,
        "reading_video_metadata": 1,
        "checking_import_status": 2,
        "saving_video_list": 3,
    }

    # "failed" stage means the last step before it was the one we stalled on
    last_step = stage_order.get(job.stage, -1)

    # For sync_failed_after_report, the analysis steps completed but sync failed
    failure_kind = _compute_failure_kind(job)
    if failure_kind == "sync_failed_after_report":
        # Analysis part is done (steps 0-2 in full_flow), sync started but failed
        if job.job_type == "sync":
            # Sync-only job — check how far we got
            pass  # use last_step as-is
        else:
            # Full flow — first 2 steps (到了 saving_report) then sync started
            # Map sync stages for the second half
            sync_stage_map = {
                "exporting_report": 2,
                "updating_cards": 3,
                "generating_claims_signals": 4,
                "updating_relations": 5,
                "refreshing_brief": 6,
                "refreshing_watchlist": 7,
            }
            if job.stage in sync_stage_map:
                last_step = sync_stage_map[job.stage]

    completed = all_steps[:last_step] if last_step > 0 else []
    pending = all_steps[last_step:] if last_step >= 0 else all_steps

    return completed, pending


def get_job_status(job_id: str) -> dict[str, Any] | None:
    """Return unified status dict for GET /tasks/{id}/status polling.

    Computes heartbeat health, elapsed, can_leave_page, result_links on each call.
    P2-M.4.1: Adds failure_kind, completed_steps, pending_steps, error_summary.
    """
    job = get_job(job_id)
    if not job:
        return None

    now = _now_epoch()
    effective_status = _check_heartbeat(job, now)
    elapsed = _compute_elapsed(job, now)
    can_leave = _build_can_leave(job, now)

    # Build result_links based on job_type and status
    result_links: dict[str, str] = {}
    checklist: list[str] = []
    completed_steps: list[str] = []
    pending_steps: list[str] = []
    failure_kind: str = ""
    error_summary: str = ""
    error_detail: str = ""

    if effective_status == "success":
        if job.job_type == "analysis":
            checklist = [
                "获取视频字幕",
                "拆解关键信息",
                "生成研究报告",
            ]
            if job.report_id:
                result_links["report"] = f"/reports/{job.report_id}"
                result_links["sync"] = f"/reports/{job.report_id}/sync"
        elif job.job_type == "sync":
            checklist = [
                "导出报告到 Obsidian",
                "更新主题和公司卡片",
                "建立知识关联",
                "刷新研究摘要",
                "刷新我的关注",
            ]
            result_links["brief"] = "/briefs/latest"
            result_links["watchlist"] = "/watchlist"
            result_links["dashboard"] = "/dashboard"
            if job.report_id:
                result_links["report"] = f"/reports/{job.report_id}"
        elif job.job_type == "full_flow":
            checklist = [
                "获取视频字幕",
                "生成研究报告",
                "同步到 Obsidian 知识库",
                "更新主题和公司卡片",
                "建立知识关联",
                "刷新研究摘要",
                "刷新我的关注",
            ]
            result_links["brief"] = "/briefs/latest"
            result_links["watchlist"] = "/watchlist"
            result_links["dashboard"] = "/dashboard"
            if job.report_id:
                result_links["report"] = f"/reports/{job.report_id}"
        elif job.job_type == "channel_refresh":
            checklist = [
                "获取频道视频列表",
                "读取视频发布时间",
                "检查已整理状态",
                "更新视频列表",
            ]
            if job.source_channel_id:
                result_links["videos"] = f"/sources/channels/{job.source_channel_id}/videos"
            result_links["sources"] = "/sources/channels"
    elif effective_status == "failed":
        failure_kind = _compute_failure_kind(job)
        completed_steps, pending_steps = _compute_step_list(job)

        # Error messages per failure kind
        _FAILURE_MESSAGES = {
            "transcript_failed": ("无法获取视频字幕", "请检查视频链接是否有效，或稍后重试。"),
            "analysis_failed": ("AI 分析未完成", f"分析在「{_stage_message(job.stage)}」阶段失败。"),
            "report_failed": ("报告生成失败", "报告保存阶段失败。"),
            "sync_failed_after_report": ("报告已生成，但知识库同步失败", job.error or "同步过程中遇到错误。"),
            "sync_failed": ("知识库同步失败", job.error or "同步过程中遇到错误。"),
            "rerun_failed": ("重新整理失败，旧版本已保留", job.error or "重新整理过程中遇到错误。"),
            "channel_refresh_failed": ("频道视频列表刷新失败", job.error or "获取频道视频列表时出错。"),
        }
        msg_info = _FAILURE_MESSAGES.get(failure_kind, ("整理失败", "请稍后重试。"))
        error_summary, error_detail = msg_info

        result_links["logs"] = f"/tasks/{job.job_id}/logs"

        if failure_kind == "sync_failed_after_report":
            result_links["report"] = f"/reports/{job.report_id}"
            result_links["retry_sync"] = f"/reports/{job.report_id}/sync"
        elif failure_kind == "sync_failed":
            if job.report_id:
                result_links["report"] = f"/reports/{job.report_id}"
                result_links["retry_sync"] = f"/reports/{job.report_id}/sync"
            result_links["retry"] = f"/tasks/{job.job_id}"
        elif failure_kind == "channel_refresh_failed":
            if job.source_channel_id:
                result_links["retry"] = f"/sources/channels/{job.source_channel_id}/videos"
        elif failure_kind == "rerun_failed" or failure_kind in ("transcript_failed", "analysis_failed", "report_failed"):
            result_links["retry"] = f"/tasks/{job.job_id}"

    # Build stage_progress for chunk display
    stage_progress = None
    if job.current_step is not None and job.total_steps is not None and job.total_steps > 0:
        stage_progress = {
            "current": job.current_step,
            "total": job.total_steps,
        }

    # Build success message
    success_msg: str = ""
    if effective_status == "success":
        if job.job_type == "analysis":
            success_msg = "研究报告已生成"
        elif job.job_type == "sync":
            success_msg = "知识库已更新"
        elif job.job_type == "full_flow":
            success_msg = "整理完成，知识库已更新"
        elif job.job_type == "channel_refresh":
            success_msg = "频道视频列表已更新"

    return {
        "job_id": job.job_id,
        "job_type": job.job_type,
        "job_type_label": JOB_TYPE_LABELS.get(job.job_type, job.job_type),
        "status": effective_status,
        "stage": job.stage,
        "failed_stage": job.stage if effective_status == "failed" else "",
        "failure_kind": failure_kind,
        "message": job.message,
        "title": job.title or JOB_TYPE_TITLES.get(job.job_type, ""),
        "source_url": job.source_url,
        "report_id": job.report_id,
        "report_url": f"/reports/{job.report_id}" if job.report_id else None,
        "error": job.error,
        "error_summary": error_summary,
        "error_detail": error_detail,
        "elapsed_seconds": elapsed,
        "current_step": job.current_step,
        "total_steps": job.total_steps,
        "stage_progress": stage_progress,
        "can_leave_page": can_leave,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_steps": completed_steps,
        "pending_steps": pending_steps,
        "result_links": result_links,
        "checklist": checklist,
        "success_msg": success_msg,
    }


def start_job(job: AnalysisJob, progress_callback: Callable | None = None) -> None:
    """Start analysis job in background daemon thread.

    If job.auto_sync is True (full_flow), chains sync_report_to_knowledge_base
    after analysis succeeds. Sync failure preserves the report link.
    """
    def _run():
        now = _now_epoch()
        with _lock:
            if job.job_id in _JOBS:
                _JOBS[job.job_id].status = "running"
                _JOBS[job.job_id].stage = "fetching_transcript"
                _JOBS[job.job_id].message = _stage_message("fetching_transcript")
                _JOBS[job.job_id].started_at = _now_iso()
                _JOBS[job.job_id].last_heartbeat_at = now

        try:
            from signalvault.services.analyze_service import analyze_youtube_url

            def _progress(stage: str, msg: str, **kwargs: Any) -> None:
                update_job(
                    job.job_id, stage=stage, message=msg,
                    current_step=kwargs.get("current_step"),
                    total_steps=kwargs.get("total_steps"),
                )
                if progress_callback:
                    try:
                        progress_callback(stage, msg, **kwargs)
                    except TypeError:
                        progress_callback(stage, msg)

            result = analyze_youtube_url(
                youtube_url=job.youtube_url,
                focus_areas=job.focus_areas,
                depth=job.depth,
                mock=job.mock,
                progress_callback=_progress,
            )

            if not result.success:
                update_job(job.job_id, status="failed", stage="failed",
                           error=result.message, message=result.message)
                _writeback_channel_video_status(job, status="failed",
                                                failure_reason=result.message)
                return

            # Analysis succeeded
            report_id = result.report_id
            update_job(job.job_id, report_id=report_id)

            # Write back report_id immediately — even if daemon thread dies
            # during sync (uvicorn --reload, process kill, etc.), the report
            # is findable and retry-able.
            _writeback_channel_video_status(job, status="analyzed",
                                            report_id=report_id)

            if job.auto_sync:
                # Full flow: chain sync after analysis
                update_job(job.job_id, stage="saving_report",
                           message="正在保存报告")

                from signalvault.services.sync_service import (
                    sync_report_to_knowledge_base,
                )

                def _sync_progress(stage: str, msg: str, **kwargs: Any) -> None:
                    # Map sync stages to job updates; skip "success" stage from sync
                    update_job(job.job_id, stage=stage, message=msg,
                               current_step=kwargs.get("current_step"),
                               total_steps=kwargs.get("total_steps"))

                sync_result = sync_report_to_knowledge_base(
                    report_id=report_id,
                    progress_callback=_sync_progress,
                )

                if sync_result.error:
                    # Report generated but sync failed — keep status "analyzed"
                    # so the report_id stays linked and user can retry sync
                    update_job(
                        job.job_id, status="failed", stage="failed",
                        error=sync_result.error,
                        message="报告已生成，但知识库更新失败。",
                    )
                    _set_result_links_failed_sync(job.job_id, report_id)
                    _writeback_channel_video_status(job, status="analyzed",
                                                    failure_reason=sync_result.error)
                else:
                    update_job(job.job_id, status="success", stage="success",
                               message="知识库已更新")
                    _set_result_links(job.job_id, "full_flow", report_id)
                    _writeback_channel_video_status(job, status="synced",
                                                    report_id=report_id)
            else:
                # Analysis only
                update_job(job.job_id, status="success", stage="success",
                           message="报告已生成")
                _set_result_links(job.job_id, "analysis", report_id)
                # report_id already written above with status="analyzed"

        except Exception as e:
            # P2-M.3.1: If we already have report_id, preserve it in writeback
            report_id_for_wb = job.report_id if job.report_id else None
            update_job(job.job_id, status="failed", stage="failed",
                       error=str(e), message="整理失败，请稍后重试")
            _writeback_channel_video_status(job, status="analyzed" if report_id_for_wb else "failed",
                                            failure_reason=str(e),
                                            report_id=report_id_for_wb)

    t = threading.Thread(target=_run, daemon=True)
    _register_thread(t)
    t.start()


def start_sync_job(job: AnalysisJob) -> None:
    """Start knowledge sync job in background daemon thread."""
    def _run():
        now = _now_epoch()
        with _lock:
            if job.job_id in _JOBS:
                _JOBS[job.job_id].status = "running"
                _JOBS[job.job_id].stage = "exporting_report"
                _JOBS[job.job_id].message = _stage_message("exporting_report")
                _JOBS[job.job_id].started_at = _now_iso()
                _JOBS[job.job_id].last_heartbeat_at = now

        try:
            from signalvault.services.sync_service import (
                sync_report_to_knowledge_base,
            )

            def _progress(stage: str, msg: str, **kwargs: Any) -> None:
                update_job(
                    job.job_id, stage=stage, message=msg,
                    current_step=kwargs.get("current_step"),
                    total_steps=kwargs.get("total_steps"),
                )

            result = sync_report_to_knowledge_base(
                report_id=job.report_id or 0,
                progress_callback=_progress,
            )

            if result.error:
                update_job(job.job_id, status="failed", stage="failed",
                           error=result.error, message=f"同步失败: {result.error}")
                # P2-M.1.2: Writeback sync failure to channel_videos
                if job.report_id:
                    _writeback_sync_result(job.report_id, status="failed",
                                           error=result.error)
            else:
                update_job(job.job_id, status="success", stage="success",
                           message="知识库已更新")
                _set_result_links(job.job_id, "sync", job.report_id)
                # P2-M.1.2: Writeback sync success to channel_videos
                if job.report_id:
                    _writeback_sync_result(job.report_id, status="synced")
        except Exception as e:
            update_job(job.job_id, status="failed", stage="failed",
                       error=str(e), message="同步失败，请稍后重试或查看日志。")
            # P2-M.1.2: Writeback exception failure to channel_videos
            if job.report_id:
                _writeback_sync_result(job.report_id, status="failed", error=str(e))

    t = threading.Thread(target=_run, daemon=True)
    _register_thread(t)
    t.start()


def _writeback_sync_result(
    report_id: int,
    *,
    status: str,
    error: str = "",
) -> None:
    """Write sync result back to channel_videos using report_id-based lookup.

    Works for both full_flow jobs (which have source context) and sync retry
    jobs (which lack it). Finds video_id from the report, then looks up
    ChannelVideo by video_id.

    On success (status="synced"): sets status="synced", links report_id,
        clears failure_reason.
    On failure: only updates if current status is NOT already "synced"
        (to avoid downgrading a previously successful sync).
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)
    try:
        from datetime import datetime

        from signalvault.db.models import ChannelVideo
        from signalvault.db.repository import get_report
        from signalvault.db.session import get_session

        session = get_session()
        try:
            report = get_report(session, report_id)
            if not report or not report.get("video_id"):
                return

            video_id = report["video_id"]
            cv = session.query(ChannelVideo).filter_by(video_id=video_id).first()
            if not cv:
                return

            if status == "synced":
                cv.status = "synced"
                cv.report_id = report_id
                cv.failure_reason = ""
                cv.active_job_id = None  # P2-M.2: job completed
                cv.last_checked_at = datetime.now()
            else:
                # Don't downgrade an already-synced video
                if cv.status == "synced":
                    return
                cv.status = status
                cv.active_job_id = None  # P2-M.2: job completed
                cv.last_checked_at = datetime.now()
                if error:
                    cv.failure_reason = error

            session.commit()
        finally:
            session.close()
    except Exception as e:
        _log.warning(
            "Channel video sync writeback failed for report_id=%s: %s",
            report_id, e,
        )


def _writeback_channel_video_status(
    job: AnalysisJob,
    *,
    status: str,
    report_id: int | None = None,
    failure_reason: str = "",
) -> None:
    """Write job result back to channel_videos table if job originated from a channel.

    For jobs WITH source context (full_flow from channel videos), uses direct
    video_id lookup.
    For jobs WITHOUT source context (sync retry), delegates to
    _writeback_sync_result which does report_id-based reverse lookup.
    """
    # P2-N.4.1: Auto-clean old failed jobs for same video_id on success
    if status in ("analyzed", "synced"):
        _cleanup_old_failures(job.video_id, job.job_id)

    # Path 1: Direct video_id lookup (full_flow from channel_videos page)
    if job.source_type == "channel_video" and job.video_id:
        try:
            from datetime import datetime

            from signalvault.db.models import ChannelVideo
            from signalvault.db.session import get_session
            session = get_session()
            try:
                cv = session.query(ChannelVideo).filter_by(
                    video_id=job.video_id
                ).first()
                if cv:
                    cv.status = status
                    cv.last_job_id = job.job_id  # P2-M.4.1: persist for log access
                    cv.active_job_id = None  # P2-M.2: job completed
                    cv.last_checked_at = datetime.now()
                    if report_id is not None:
                        cv.report_id = report_id
                    if failure_reason:
                        cv.failure_reason = failure_reason
                    else:
                        cv.failure_reason = ""
                    session.commit()
            finally:
                session.close()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "Channel video status writeback failed for video_id=%s: %s",
                job.video_id, e,
            )
        return

    # Path 2: Report-id based reverse lookup (sync retry jobs)
    if report_id:
        _writeback_sync_result(report_id, status=status, error=failure_reason)


def _set_result_links(job_id: str, job_type: str, report_id: int | None) -> None:
    """Populate result_links on job success."""
    with _lock:
        job = _JOBS.get(job_id)
        if not job:
            return
        links: dict[str, str] = {}
        if job_type in ("analysis",) and report_id:
            links["report"] = f"/reports/{report_id}"
            links["sync"] = f"/reports/{report_id}/sync"
        elif job_type == "sync":
            links["brief"] = "/briefs/latest"
            links["watchlist"] = "/watchlist"
            links["dashboard"] = "/dashboard"
            if report_id:
                links["report"] = f"/reports/{report_id}"
        elif job_type == "full_flow" and report_id:
            links["report"] = f"/reports/{report_id}"
            links["brief"] = "/briefs/latest"
            links["watchlist"] = "/watchlist"
            links["dashboard"] = "/dashboard"
        elif job_type == "channel_refresh":
            if job.source_channel_id:
                links["videos"] = f"/sources/channels/{job.source_channel_id}/videos"
            links["sources"] = "/sources/channels"
        job.result_links = links


def _set_result_links_failed_sync(job_id: str, report_id: int | None) -> None:
    """Populate result_links when sync fails after successful analysis (full_flow).

    The report was generated, so provide report + retry sync links.
    """
    with _lock:
        job = _JOBS.get(job_id)
        if not job:
            return
        links: dict[str, str] = {}
        if report_id:
            links["report"] = f"/reports/{report_id}"
            links["sync"] = f"/reports/{report_id}/sync"  # retry
        job.result_links = links


# ═════════════════════════════════════════════════════════════════════════════
# P2-M.1.1: Channel Refresh Job
# ═════════════════════════════════════════════════════════════════════════════


def create_channel_refresh_job(
    channel_url: str,
    channel_name: str,
    channel_id: int,
    limit: int = 20,
) -> AnalysisJob:
    """Create a channel_refresh job."""
    job_id = uuid.uuid4().hex[:12]
    job = AnalysisJob(
        job_id=job_id,
        job_type="channel_refresh",
        status="queued",
        stage="queued",
        message=_stage_message("queued"),
        title=f"刷新频道: {channel_name}",
        source_url=channel_url,
        source_type="channel_refresh",
        source_channel_id=channel_id,
    )
    with _lock:
        _JOBS[job_id] = job
        _prune_if_needed()
    _persist_job(job)  # P2-O.2: persist on create
    return job


def start_channel_refresh_job(job: AnalysisJob) -> None:
    """Start channel refresh in background daemon thread."""
    def _run():
        now = _now_epoch()
        with _lock:
            if job.job_id in _JOBS:
                _JOBS[job.job_id].status = "running"
                _JOBS[job.job_id].stage = "fetching_channel"
                _JOBS[job.job_id].message = _stage_message("fetching_channel")
                _JOBS[job.job_id].started_at = _now_iso()
                _JOBS[job.job_id].last_heartbeat_at = now

        try:
            from signalvault.adapters.channel_video_adapter import (
                ChannelVideoAdapter,
            )
            from signalvault.db.repository import (
                refresh_channel_timestamp,
                upsert_channel_video,
            )
            from signalvault.db.session import get_session

            # Stage 1: Fetch channel videos
            update_job(job.job_id, stage="fetching_channel",
                        message="正在通过 yt-dlp 获取频道视频列表")
            adapter = ChannelVideoAdapter()
            channel_url = job.source_url
            video_items = adapter.fetch_channel_videos(channel_url, limit=20)

            if not video_items:
                update_job(job.job_id, status="failed", stage="failed",
                           message="未获取到视频列表",
                           error="频道可能没有公开视频，或链接格式不正确。")
                return

            # Stage 2: Read video metadata (dates already in items)
            update_job(job.job_id, stage="reading_video_metadata",
                        message=f"已获取 {len(video_items)} 个视频，正在处理元数据")

            # Stage 3: Check import status
            update_job(job.job_id, stage="checking_import_status",
                        message="正在检查已整理状态")

            # Stage 4: Save to DB
            update_job(job.job_id, stage="saving_video_list",
                        message=f"正在将 {len(video_items)} 个视频写入数据库")

            session = get_session()
            try:
                new_count = 0
                upsert_count = 0
                for item in video_items:
                    is_new = upsert_channel_video(
                        session,
                        channel_id=job.source_channel_id or 0,
                        video_id=item.video_id,
                        title=item.title,
                        url=item.url,
                        published_at=item.published_at,
                        duration_seconds=item.duration_seconds,
                    )
                    if is_new:
                        new_count += 1
                    else:
                        upsert_count += 1
                if job.source_channel_id:
                    refresh_channel_timestamp(session, job.source_channel_id)
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

            msg = f"新增 {new_count} 个视频，更新 {upsert_count} 个"
            update_job(job.job_id, status="success", stage="success", message=msg)
            _set_result_links(job.job_id, "channel_refresh", None)

        except Exception as e:
            update_job(job.job_id, status="failed", stage="failed",
                       error=str(e),
                       message="频道视频列表获取失败，请稍后重试或检查频道链接。")

    t = threading.Thread(target=_run, daemon=True)
    _register_thread(t)
    t.start()
