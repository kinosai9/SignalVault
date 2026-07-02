"""P3-A: Persistent ingest job manager — replaces in-memory preview stores.

Provides IngestJobManager with CRUD, dedup, expiry, and statistics operations.
All state lives in the SQLite ingest_jobs table; survives server restart.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func

from podcast_research.db.models import IngestJob
from podcast_research.db.session import get_session

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_EXPIRY_HOURS = 24
MAX_RETRY_COUNT = 3

VALID_STATUSES = frozenset({
    "pending_preview",
    "preview_failed",
    "confirmed_archive",
    "confirmed_deep_notes",
    "confirmed_derived_only",
    "confirmed_linked",
    "skipped",
    "expired",
    "overwritten",
})

TERMINAL_STATUSES = frozenset({
    "confirmed_archive",
    "confirmed_deep_notes",
    "confirmed_derived_only",
    "confirmed_linked",
    "skipped",
    "expired",
    "overwritten",
})


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_job_key(source_type: str, source_url: str = "", source_hash: str = "",
                  tracked_source_id: int | None = None) -> str:
    """Build a deterministic dedup key from job identity fields."""
    if source_type == "url_import":
        url_hash = hashlib.sha256(source_url.encode()).hexdigest()[:16]
        return f"url_import:{url_hash}"
    elif source_type == "file_upload":
        return f"file_upload:{source_hash}"
    elif source_type == "pdf_upload":
        return f"pdf_upload:{source_hash}"
    elif source_type == "tracked_entry":
        url_hash = hashlib.sha256(source_url.encode()).hexdigest()[:16]
        return f"tracked_entry:{tracked_source_id}:{url_hash}"
    elif source_type == "source_profile":
        url_hash = hashlib.sha256(source_url.encode()).hexdigest()[:16]
        return f"source_profile:{url_hash}"
    else:
        raise ValueError(f"Unknown source_type: {source_type}")


def _serialize_preview(preview: Any) -> str:
    """Serialize an ImportPreview / FileImportPreview / SourceProfile to JSON."""
    if preview is None:
        return ""
    try:
        return json.dumps(preview, default=lambda o: o.__dict__, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        logger.warning("Failed to serialize preview: %s", e)
        return ""


def _now() -> datetime:
    return datetime.now()


# ── IngestJobManager ─────────────────────────────────────────────────────────


class IngestJobManager:
    """Persistent manager for ingest_jobs (URL import, file upload, tracked entries, profiles).

    All methods that touch the DB accept an optional session argument for testability.
    When session is None, a new session is created and closed automatically.
    """

    # ── Create ────────────────────────────────────────────────────────────

    @staticmethod
    def create_job(
        source_type: str,
        source_url: str = "",
        source_hash: str = "",
        source_name: str = "",
        preview_data: str = "",
        preview_id: str = "",
        tracked_source_id: int | None = None,
        tracked_entry_id: int | None = None,
        expiry_hours: int = DEFAULT_EXPIRY_HOURS,
        session=None,
    ) -> dict | None:
        """Create a new ingest job. Returns the job as a dict, or None on failure."""
        job_key = _make_job_key(
            source_type, source_url, source_hash, tracked_source_id,
        )
        expires_at = _now() + timedelta(hours=expiry_hours)

        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            job = IngestJob(
                job_key=job_key,
                source_type=source_type,
                source_url=source_url,
                source_hash=source_hash,
                source_name=source_name,
                status="pending_preview",
                retry_count=0,
                preview_data=preview_data,
                preview_id=preview_id,
                tracked_source_id=tracked_source_id,
                tracked_entry_id=tracked_entry_id,
                expires_at=expires_at,
            )
            _session.add(job)
            _session.commit()
            result = IngestJobManager._row_to_dict(job)
            return result
        except Exception as e:
            if _session:
                with contextlib.suppress(Exception):
                    _session.rollback()
            logger.error("Failed to create ingest job: %s", e)
            return None
        finally:
            if _close and _session:
                _session.close()

    # ── Find ──────────────────────────────────────────────────────────────

    @staticmethod
    def find_by_job_key(job_key: str, session=None) -> dict | None:
        """Find a pending_preview job by its job_key."""
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            job = (
                _session.query(IngestJob)
                .filter_by(job_key=job_key, status="pending_preview")
                .order_by(IngestJob.created_at.desc())
                .first()
            )
            return IngestJobManager._row_to_dict(job) if job else None
        finally:
            if _close and _session:
                _session.close()

    @staticmethod
    def find_by_preview_id(preview_id: str, session=None) -> dict | None:
        """Find a job by its preview_id."""
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            job = (
                _session.query(IngestJob)
                .filter_by(preview_id=preview_id)
                .first()
            )
            return IngestJobManager._row_to_dict(job) if job else None
        finally:
            if _close and _session:
                _session.close()

    @staticmethod
    def get_job(job_id: int, session=None) -> dict | None:
        """Get a job by its primary key."""
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            job = _session.get(IngestJob, job_id)
            return IngestJobManager._row_to_dict(job) if job else None
        finally:
            if _close and _session:
                _session.close()

    # ── Query ─────────────────────────────────────────────────────────────

    @staticmethod
    def get_pending_previews(source_type: str | None = None,
                             session=None) -> list[dict]:
        """List all pending_preview jobs, optionally filtered by source_type."""
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            q = _session.query(IngestJob).filter_by(status="pending_preview")
            if source_type:
                q = q.filter_by(source_type=source_type)
            q = q.order_by(IngestJob.created_at.desc())
            return [IngestJobManager._row_to_dict(j) for j in q.all()]
        finally:
            if _close and _session:
                _session.close()

    @staticmethod
    def list_jobs(source_type: str | None = None,
                  status: str | None = None,
                  limit: int = 50,
                  session=None) -> list[dict]:
        """List jobs with optional source_type and status filters."""
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            q = _session.query(IngestJob)
            if source_type:
                q = q.filter_by(source_type=source_type)
            if status:
                q = q.filter_by(status=status)
            q = q.order_by(IngestJob.created_at.desc()).limit(limit)
            return [IngestJobManager._row_to_dict(j) for j in q.all()]
        finally:
            if _close and _session:
                _session.close()

    # ── Confirm / Transition ──────────────────────────────────────────────

    @staticmethod
    def confirm_job(preview_id: str, action: str = "",
                    action_label: str = "",
                    result_path: str = "",
                    result_message: str = "",
                    session=None) -> dict | None:
        """Confirm a pending_preview job by preview_id, transitioning to the target status.

        Returns the updated job dict, or None if job not found.
        """
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            job = (
                _session.query(IngestJob)
                .filter_by(preview_id=preview_id, status="pending_preview")
                .first()
            )
            if job is None:
                logger.warning("No pending job found for preview_id=%s", preview_id)
                return None

            # Map action string to status
            status_map = {
                "confirm_archive": "confirmed_archive",
                "import_as_source_archive": "confirmed_archive",
                "archive_only": "confirmed_archive",
                "import_as_deep_notes_linked": "confirmed_linked",
                "import_as_deep_notes_derived_only": "confirmed_derived_only",
                "import_as_deep_notes": "confirmed_deep_notes",
                "overwrite_deep_notes": "overwritten",
                "skip": "skipped",
            }
            new_status = status_map.get(action, "skipped")

            job.status = new_status
            job.action = action
            job.action_label = action_label
            job.result_path = result_path
            job.result_message = result_message
            job.confirmed_at = _now()

            _session.commit()
            return IngestJobManager._row_to_dict(job)
        except Exception as e:
            if _session:
                with contextlib.suppress(Exception):
                    _session.rollback()
            logger.error("Failed to confirm job preview_id=%s: %s", preview_id, e)
            return None
        finally:
            if _close and _session:
                _session.close()

    @staticmethod
    def mark_failed(preview_id: str, error_message: str,
                    session=None) -> dict | None:
        """Mark a pending_preview job as failed."""
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            job = (
                _session.query(IngestJob)
                .filter_by(preview_id=preview_id, status="pending_preview")
                .first()
            )
            if job is None:
                return None
            job.status = "preview_failed"
            job.error_message = error_message
            job.retry_count = (job.retry_count or 0) + 1
            _session.commit()
            return IngestJobManager._row_to_dict(job)
        except Exception as e:
            if _session:
                with contextlib.suppress(Exception):
                    _session.rollback()
            logger.error("Failed to mark job failed preview_id=%s: %s", preview_id, e)
            return None
        finally:
            if _close and _session:
                _session.close()

    # ── Retry ─────────────────────────────────────────────────────────────

    @staticmethod
    def retry_job(job_id: int, session=None) -> dict | None:
        """Reset a failed/expired/skipped job back to pending_preview for retry.

        Increments retry_count. Returns None if max retries exceeded or job not found.
        """
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            job = _session.get(IngestJob, job_id)
            if job is None:
                return None
            if job.retry_count >= MAX_RETRY_COUNT:
                logger.warning(
                    "Job %d has reached max retry count %d", job_id, MAX_RETRY_COUNT,
                )
                return None
            job.status = "pending_preview"
            job.retry_count = (job.retry_count or 0) + 1
            job.error_message = ""
            job.expires_at = _now() + timedelta(hours=DEFAULT_EXPIRY_HOURS)
            _session.commit()
            return IngestJobManager._row_to_dict(job)
        except Exception as e:
            if _session:
                with contextlib.suppress(Exception):
                    _session.rollback()
            logger.error("Failed to retry job %d: %s", job_id, e)
            return None
        finally:
            if _close and _session:
                _session.close()

    @staticmethod
    def resume_pending(session=None) -> dict[str, int]:
        """Find all pending_preview jobs and return counts. Used on server restart."""
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            q = _session.query(
                IngestJob.source_type,
                func.count(IngestJob.id).label("cnt"),
            ).filter_by(status="pending_preview").group_by(IngestJob.source_type).all()
            return {row.source_type: row.cnt for row in q}
        finally:
            if _close and _session:
                _session.close()

    # ── Expiry ────────────────────────────────────────────────────────────

    @staticmethod
    def expire_old_jobs(session=None) -> int:
        """Mark expired pending_preview jobs as 'expired'. Returns count expired."""
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            expired = (
                _session.query(IngestJob)
                .filter(
                    IngestJob.status == "pending_preview",
                    IngestJob.expires_at.isnot(None),
                    IngestJob.expires_at < _now(),
                )
                .all()
            )
            count = len(expired)
            for job in expired:
                job.status = "expired"
            _session.commit()
            if count:
                logger.info("Expired %d ingest jobs", count)
            return count
        except Exception as e:
            if _session:
                with contextlib.suppress(Exception):
                    _session.rollback()
            logger.error("Failed to expire jobs: %s", e)
            return 0
        finally:
            if _close and _session:
                _session.close()

    # ── Statistics ────────────────────────────────────────────────────────

    @staticmethod
    def count_by_status(source_type: str | None = None,
                        session=None) -> dict[str, int]:
        """Count jobs by status, optionally filtered by source_type."""
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            q = _session.query(
                IngestJob.status,
                func.count(IngestJob.id).label("cnt"),
            )
            if source_type:
                q = q.filter_by(source_type=source_type)
            q = q.group_by(IngestJob.status)
            return {row.status: row.cnt for row in q.all()}
        finally:
            if _close and _session:
                _session.close()

    @staticmethod
    def count_by_source_type(session=None) -> dict[str, int]:
        """Count total jobs by source_type."""
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            q = _session.query(
                IngestJob.source_type,
                func.count(IngestJob.id).label("cnt"),
            ).group_by(IngestJob.source_type)
            return {row.source_type: row.cnt for row in q.all()}
        finally:
            if _close and _session:
                _session.close()

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(job: IngestJob) -> dict:
        """Convert an IngestJob ORM object to a plain dict."""
        return {
            "id": job.id,
            "job_key": job.job_key,
            "source_type": job.source_type,
            "source_url": job.source_url,
            "source_hash": job.source_hash,
            "source_name": job.source_name,
            "status": job.status,
            "retry_count": job.retry_count,
            "preview_data": job.preview_data,
            "preview_id": job.preview_id,
            "action": job.action,
            "action_label": job.action_label,
            "result_path": job.result_path,
            "result_message": job.result_message,
            "error_message": job.error_message,
            "tracked_source_id": job.tracked_source_id,
            "tracked_entry_id": job.tracked_entry_id,
            "created_at": (
                job.created_at.isoformat() if job.created_at else None
            ),
            "confirmed_at": (
                job.confirmed_at.isoformat() if job.confirmed_at else None
            ),
            "expires_at": (
                job.expires_at.isoformat() if job.expires_at else None
            ),
        }
