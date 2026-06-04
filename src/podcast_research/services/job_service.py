"""P2-K.2.1: Unified in-memory job service — analysis, sync, and future task types.

Local single-user tool. Jobs lost on restart. Max 50 jobs.

Status lifecycle:
    queued → running → long_running → success
    queued → running → long_running → failed
    queued → running → long_running → stale (no heartbeat)

Heartbeat thresholds are module-level for easy monkeypatching in tests.
"""

from __future__ import annotations

import threading
import time as _time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

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


# In-memory store
_JOBS: dict[str, AnalysisJob] = {}
_lock = threading.Lock()


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
    return job


def create_sync_job(report_id: int) -> AnalysisJob:
    """Create a new knowledge sync job."""
    job_id = uuid.uuid4().hex[:12]
    job = AnalysisJob(
        job_id=job_id,
        job_type="sync",
        status="queued",
        stage="queued",
        message=_stage_message("queued"),
        title=JOB_TYPE_TITLES.get("sync", ""),
        report_id=report_id,
    )
    with _lock:
        _JOBS[job_id] = job
        _prune_if_needed()
    return job


def _prune_if_needed() -> None:
    if len(_JOBS) > _MAX_JOBS:
        oldest = sorted(_JOBS.keys(), key=lambda k: _JOBS[k].created_at)[:10]
        for k in oldest:
            del _JOBS[k]


def get_job(job_id: str) -> AnalysisJob | None:
    return _JOBS.get(job_id)


def list_jobs(limit: int = 20) -> list[AnalysisJob]:
    """Return recent jobs for the unified task list page."""
    with _lock:
        jobs = sorted(_JOBS.values(), key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]


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
) -> None:
    """Thread-safe job update. Always bumps last_heartbeat_at."""
    now = _now_epoch()
    with _lock:
        job = _JOBS.get(job_id)
        if not job:
            return
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


def _stage_message(stage: str) -> str:
    return _ALL_STAGES.get(stage, stage)


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


def get_job_status(job_id: str) -> dict[str, Any] | None:
    """Return unified status dict for GET /tasks/{id}/status polling.

    Computes heartbeat health, elapsed, can_leave_page, result_links on each call.
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
    elif effective_status == "failed" and job.job_type == "full_flow" and job.report_id:
        # Sync failed after analysis succeeded — preserve report + retry links
        result_links["report"] = f"/reports/{job.report_id}"
        result_links["sync"] = f"/reports/{job.report_id}/sync"

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
        "message": job.message,
        "title": job.title or JOB_TYPE_TITLES.get(job.job_type, ""),
        "source_url": job.source_url,
        "report_id": job.report_id,
        "report_url": f"/reports/{job.report_id}" if job.report_id else None,
        "error": job.error,
        "elapsed_seconds": elapsed,
        "current_step": job.current_step,
        "total_steps": job.total_steps,
        "stage_progress": stage_progress,
        "can_leave_page": can_leave,
        "created_at": job.created_at,
        "started_at": job.started_at,
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
            from podcast_research.services.analyze_service import analyze_youtube_url

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

            if job.auto_sync:
                # Full flow: chain sync after analysis
                update_job(job.job_id, stage="saving_report",
                           message="正在保存报告")

                from podcast_research.services.sync_service import sync_report_to_knowledge_base

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
                    # Report generated but sync failed — user can retry
                    update_job(
                        job.job_id, status="failed", stage="failed",
                        error=sync_result.error,
                        message="报告已生成，但知识库更新失败。",
                    )
                    _set_result_links_failed_sync(job.job_id, report_id)
                    _writeback_channel_video_status(job, status="failed",
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
                _writeback_channel_video_status(job, status="analyzed",
                                                report_id=report_id)

        except Exception as e:
            update_job(job.job_id, status="failed", stage="failed",
                       error=str(e), message="整理失败，请稍后重试")
            _writeback_channel_video_status(job, status="failed",
                                            failure_reason=str(e))

    t = threading.Thread(target=_run, daemon=True)
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
            from podcast_research.services.sync_service import sync_report_to_knowledge_base

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
        from podcast_research.db.session import get_session
        from podcast_research.db.repository import get_report
        from podcast_research.db.models import ChannelVideo
        from datetime import datetime

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
    # Path 1: Direct video_id lookup (full_flow from channel_videos page)
    if job.source_type == "channel_video" and job.video_id:
        try:
            from podcast_research.db.session import get_session
            from podcast_research.db.models import ChannelVideo
            from datetime import datetime
            session = get_session()
            try:
                cv = session.query(ChannelVideo).filter_by(
                    video_id=job.video_id
                ).first()
                if cv:
                    cv.status = status
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
            from podcast_research.adapters.channel_video_adapter import (
                ChannelVideoAdapter, ChannelVideoItem,
            )
            from podcast_research.db.repository import (
                upsert_channel_video, refresh_channel_timestamp,
                detect_video_import_status,
            )
            from podcast_research.db.session import get_session

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
            except Exception as e:
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
    t.start()
