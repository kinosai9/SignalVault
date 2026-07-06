"""P7-B: Operation Log — structured audit trail for user/system actions.

Writes to SQLite operation_logs table. Independent of the existing JobEvent
table. Complements stdlib logging (which stays in log files for developers).
"""

from __future__ import annotations

import json as _json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from signalvault.db.session import get_session

logger = logging.getLogger(__name__)

# ── Operation types ──────────────────────────────────────────────────────────

VALID_OPERATION_TYPES = frozenset({
    # ZSXQ
    "zsxq.groups.refresh",
    "zsxq.topic.import",
    "zsxq.topic.analyze",
    "zsxq.sync",
    "zsxq.doctor",
    # PDF
    "pdf.preview",
    "pdf.extract",
    "pdf.analyze",
    # Ingest
    "ingest.confirm",
    "ingest.retry",
    "ingest.resume",
    "ingest.expire",
    # Vault
    "vault.lint",
    "vault.export",
    # Review
    "review.accept",
    "review.skip",
    "review.resolve",
    # Search
    "search.unified",
    # Graph
    "graph.rebuild",
    "graph.export",
    # MCP
    "mcp.serve.start",
    "mcp.serve.stop",
    # System
    "system.doctor",
    "system.diagnostics",
    "system.unknown",
})

VALID_STATUSES = frozenset({"started", "succeeded", "failed", "cancelled"})


# ── Dataclass ────────────────────────────────────────────────────────────────


@dataclass
class OperationLog:
    operation_id: str = ""
    operation_type: str = ""
    status: str = "started"
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    source_type: str = ""
    target_ref: str = ""
    summary: str = ""
    error_code: str = ""
    error_detail: str = ""
    initiated_by: str = "user"
    metadata_json: str = "{}"

    def to_dict(self) -> dict:
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "source_type": self.source_type,
            "target_ref": self.target_ref,
            "summary": self.summary,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "initiated_by": self.initiated_by,
            "metadata_json": self.metadata_json,
        }


# ── Manager ──────────────────────────────────────────────────────────────────


class OperationLogManager:
    """CRUD for operation_logs table. All methods accept optional session
    for testability. When session is None, a new session is created."""

    @staticmethod
    def _row_to_dict(row) -> dict:
        return {
            "id": row.id,
            "operation_id": row.operation_id,
            "operation_type": row.operation_type,
            "status": row.status,
            "started_at": row.started_at.isoformat() if row.started_at else "",
            "finished_at": row.finished_at.isoformat() if row.finished_at else "",
            "duration_ms": row.duration_ms or 0,
            "source_type": row.source_type or "",
            "target_ref": row.target_ref or "",
            "summary": row.summary or "",
            "error_code": row.error_code or "",
            "error_detail": row.error_detail or "",
            "initiated_by": row.initiated_by or "user",
            "metadata_json": row.metadata_json or "{}",
            "created_at": row.created_at.isoformat() if row.created_at else "",
        }

    @staticmethod
    def _sanitize_metadata(metadata: dict | None) -> str:
        """Ensure metadata is JSON-safe and contains no secrets."""
        if metadata is None:
            return "{}"

        # Keys that must NEVER appear in metadata
        forbidden = {"api_key", "token", "password", "secret", "llm_api_key",
                      "auth_token", "access_token", "refresh_token", "cookie"}

        clean: dict[str, Any] = {}
        for k, v in metadata.items():
            if k.lower() in forbidden:
                clean[k] = "[REDACTED]"
            elif isinstance(v, str) and len(v) > 500:
                clean[k] = v[:500] + "..."
            else:
                clean[k] = v

        # Don't include full content_text or source_quote
        for long_key in ("content_text", "source_quote", "report_markdown",
                          "full_text", "page_text"):
            if long_key in clean:
                clean[long_key] = f"[{len(str(clean[long_key]))} chars redacted]"

        try:
            return _json.dumps(clean, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return "{}"

    # ── Create / Lifecycle ────────────────────────────────────────────

    @staticmethod
    def start(
        operation_type: str,
        source_type: str = "",
        target_ref: str = "",
        initiated_by: str = "user",
        summary: str = "",
        metadata: dict | None = None,
        session=None,
    ) -> OperationLog:
        """Begin a new operation. Returns an OperationLog with a UUID."""
        if operation_type not in VALID_OPERATION_TYPES:
            logger.debug("Unknown operation_type '%s', using system.unknown", operation_type)

        op = OperationLog(
            operation_id=str(uuid.uuid4()),
            operation_type=operation_type,
            status="started",
            started_at=datetime.now(timezone.utc).isoformat(),
            source_type=source_type,
            target_ref=target_ref,
            summary=summary,
            initiated_by=initiated_by,
            metadata_json=OperationLogManager._sanitize_metadata(metadata),
        )

        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            from signalvault.db.models import OperationLog as OperationLogORM
            orm = OperationLogORM(
                operation_id=op.operation_id,
                operation_type=op.operation_type,
                status=op.status,
                started_at=datetime.now(timezone.utc),
                source_type=op.source_type,
                target_ref=op.target_ref,
                summary=op.summary,
                initiated_by=op.initiated_by,
                metadata_json=op.metadata_json,
            )
            _session.add(orm)
            _session.commit()
        except Exception as e:
            logger.warning("Failed to write operation_log start: %s", e)
            if _session:
                with __import__("contextlib").suppress(Exception):
                    _session.rollback()
        finally:
            if _close and _session:
                _session.close()

        return op

    @staticmethod
    def succeed(
        op: OperationLog,
        summary: str = "",
        metadata: dict | None = None,
        session=None,
    ) -> OperationLog:
        """Mark an operation as succeeded. Computes duration_ms automatically."""
        started = datetime.fromisoformat(op.started_at) if op.started_at else datetime.now(timezone.utc)
        now = datetime.now(timezone.utc)
        duration_ms = int((now - started).total_seconds() * 1000)

        op.status = "succeeded"
        op.finished_at = now.isoformat()
        op.duration_ms = duration_ms
        if summary:
            op.summary = summary[:500]
        if metadata:
            op.metadata_json = OperationLogManager._sanitize_metadata(metadata)

        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            from signalvault.db.models import OperationLog as OperationLogORM
            orm = _session.query(OperationLogORM).filter_by(
                operation_id=op.operation_id,
            ).first()
            if orm:
                orm.status = "succeeded"
                orm.finished_at = now
                orm.duration_ms = duration_ms
                orm.summary = op.summary
                orm.metadata_json = op.metadata_json
                _session.commit()
        except Exception as e:
            logger.warning("Failed to update operation_log succeed: %s", e)
            if _session:
                with __import__("contextlib").suppress(Exception):
                    _session.rollback()
        finally:
            if _close and _session:
                _session.close()

        return op

    @staticmethod
    def fail(
        op: OperationLog,
        error_code: str = "",
        error_detail: str = "",
        summary: str = "",
        session=None,
    ) -> OperationLog:
        """Mark an operation as failed. Computes duration_ms automatically."""
        started = datetime.fromisoformat(op.started_at) if op.started_at else datetime.now(timezone.utc)
        now = datetime.now(timezone.utc)
        duration_ms = int((now - started).total_seconds() * 1000)

        op.status = "failed"
        op.finished_at = now.isoformat()
        op.duration_ms = duration_ms
        op.error_code = error_code
        op.error_detail = (error_detail or "")[:500]
        if summary:
            op.summary = summary[:500]

        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            from signalvault.db.models import OperationLog as OperationLogORM
            orm = _session.query(OperationLogORM).filter_by(
                operation_id=op.operation_id,
            ).first()
            if orm:
                orm.status = "failed"
                orm.finished_at = now
                orm.duration_ms = duration_ms
                orm.error_code = op.error_code
                orm.error_detail = op.error_detail
                orm.summary = op.summary
                _session.commit()
        except Exception as e:
            logger.warning("Failed to update operation_log fail: %s", e)
            if _session:
                with __import__("contextlib").suppress(Exception):
                    _session.rollback()
        finally:
            if _close and _session:
                _session.close()

        return op

    # ── Query ────────────────────────────────────────────────────────

    @staticmethod
    def get(operation_id: str, session=None) -> dict | None:
        """Get a single operation log by operation_id."""
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            from signalvault.db.models import OperationLog as OperationLogORM
            row = _session.query(OperationLogORM).filter_by(
                operation_id=operation_id,
            ).first()
            if row is None:
                return None
            return OperationLogManager._row_to_dict(row)
        finally:
            if _close and _session:
                _session.close()

    @staticmethod
    def list_operations(
        operation_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        session=None,
    ) -> list[dict]:
        """List recent operation logs with optional filters."""
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            from signalvault.db.models import OperationLog as OperationLogORM
            q = _session.query(OperationLogORM)
            if operation_type:
                q = q.filter_by(operation_type=operation_type)
            if status:
                q = q.filter_by(status=status)
            q = q.order_by(OperationLogORM.created_at.desc()).limit(limit)
            return [OperationLogManager._row_to_dict(row) for row in q.all()]
        finally:
            if _close and _session:
                _session.close()

    @staticmethod
    def count_by_status(session=None) -> dict[str, int]:
        """Count operations grouped by status."""
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            from sqlalchemy import func

            from signalvault.db.models import OperationLog as OperationLogORM
            rows = _session.query(
                OperationLogORM.status,
                func.count(OperationLogORM.id).label("cnt"),
            ).group_by(OperationLogORM.status).all()
            return {row.status: row.cnt for row in rows}
        finally:
            if _close and _session:
                _session.close()

    @staticmethod
    def recent_failures(limit: int = 20, session=None) -> list[dict]:
        """Get recent failed operations."""
        return OperationLogManager.list_operations(
            status="failed", limit=limit, session=session,
        )
