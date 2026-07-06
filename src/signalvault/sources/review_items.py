"""P3-C: Review Item Manager — unified human-triage queue.

Provides CRUD, status transitions, and query operations for review_items.
Review items can originate from vault lint, patch proposals, entity merge
candidates, duplicate reports, or manual creation.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import func

from signalvault.db.models import ReviewItem
from signalvault.db.session import get_session

logger = logging.getLogger(__name__)

VALID_STATUSES = frozenset({"open", "accepted", "skipped", "resolved"})
VALID_ITEM_TYPES = frozenset({
    "lint_frontmatter_invalid",
    "lint_frontmatter_missing",
    "lint_dead_wikilink",
    "lint_duplicate_report",
    "lint_orphan_card",
    "entity_duplicate_candidate",
    "patch_review",
    "manual",
    # P4-A: PDF extraction
    "pdf_needs_ocr",
    "pdf_quality_issue",
    "pdf_extraction_failed",
    # P4-B: PDF analysis
    "pdf_analysis_skipped",
    "pdf_evidence_missing",
    # P6-A1: ZSXQ import
    "zsxq_cli_missing",
    "zsxq_auth_required",
    "zsxq_permission_denied",
    "zsxq_parse_failed",
    "zsxq_attachment_unsupported",
    # P6-A2: ZSXQ analysis
    "zsxq_analysis_skipped",
    "zsxq_content_too_short",
    "zsxq_evidence_missing",
})


class ReviewItemManager:
    """Persistent manager for review_items.

    All methods accept an optional session for testability.
    """

    # ── Create ────────────────────────────────────────────────────────────

    @staticmethod
    def create_item(
        item_type: str,
        title: str,
        severity: str = "warning",
        description: str = "",
        source_ref: str = "",
        source_path: str = "",
        suggested_action: dict | None = None,
        session=None,
    ) -> dict | None:
        """Create a review item. Returns dict or None on failure."""
        if item_type not in VALID_ITEM_TYPES:
            logger.warning("Invalid item_type: %s", item_type)
            return None
        if severity not in ("error", "warning", "info"):
            severity = "warning"

        action_json = json.dumps(suggested_action, ensure_ascii=False) if suggested_action else ""

        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            item = ReviewItem(
                item_type=item_type,
                severity=severity,
                status="open",
                title=title,
                description=description,
                source_ref=source_ref,
                source_path=source_path,
                suggested_action_json=action_json,
            )
            _session.add(item)
            _session.commit()
            return ReviewItemManager._row_to_dict(item)
        except Exception as e:
            if _session:
                with __import__("contextlib").suppress(Exception):
                    _session.rollback()
            logger.error("Failed to create review item: %s", e)
            return None
        finally:
            if _close and _session:
                _session.close()

    @staticmethod
    def create_from_lint_findings(
        findings: list[dict],
        session=None,
    ) -> int:
        """Batch-create review items from lint findings. Returns count created.

        Each finding dict should have: rule, severity, file_path, message, detail.
        Deduplicates: same source_path + same item_type = skip.
        """
        created = 0
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            for f in findings:
                rule = f.get("rule", "unknown")
                # Map rule → item_type: if rule is already a valid item_type,
                # use it directly. Otherwise prefix with "lint_" for lint rules.
                if rule in VALID_ITEM_TYPES:
                    item_type = rule
                else:
                    item_type = f"lint_{rule}"
                    if item_type not in VALID_ITEM_TYPES:
                        item_type = "manual"

                # Dedup: skip if same source_path + item_type already open
                existing = (
                    _session.query(ReviewItem)
                    .filter_by(
                        item_type=item_type,
                        source_path=f.get("file_path", ""),
                        status="open",
                    )
                    .first()
                )
                if existing:
                    continue

                item = ReviewItem(
                    item_type=item_type,
                    severity=f.get("severity", "warning"),
                    status="open",
                    title=f.get("message", "")[:500],
                    description=f.get("detail", "") or "",
                    source_ref=f"lint:{rule}",
                    source_path=f.get("file_path", ""),
                )
                _session.add(item)
                created += 1
            _session.commit()
        except Exception as e:
            if _session:
                with __import__("contextlib").suppress(Exception):
                    _session.rollback()
            logger.error("Failed to create review items from lint: %s", e)
        finally:
            if _close and _session:
                _session.close()
        return created

    # ── Query ─────────────────────────────────────────────────────────────

    @staticmethod
    def list_items(
        item_type: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        limit: int = 50,
        session=None,
    ) -> list[dict]:
        """List review items with optional filters."""
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            q = _session.query(ReviewItem)
            if item_type:
                q = q.filter_by(item_type=item_type)
            if status:
                q = q.filter_by(status=status)
            if severity:
                q = q.filter_by(severity=severity)
            q = q.order_by(
                ReviewItem.severity.desc() if False else ReviewItem.created_at.desc(),
            ).limit(limit)
            return [ReviewItemManager._row_to_dict(r) for r in q.all()]
        finally:
            if _close and _session:
                _session.close()

    @staticmethod
    def get_item(item_id: int, session=None) -> dict | None:
        """Get a single review item by ID."""
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            item = _session.get(ReviewItem, item_id)
            return ReviewItemManager._row_to_dict(item) if item else None
        finally:
            if _close and _session:
                _session.close()

    @staticmethod
    def count_by_status(session=None) -> dict[str, int]:
        """Count review items grouped by status."""
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            q = _session.query(
                ReviewItem.status,
                func.count(ReviewItem.id).label("cnt"),
            ).group_by(ReviewItem.status)
            return {row.status: row.cnt for row in q.all()}
        finally:
            if _close and _session:
                _session.close()

    # ── Status transitions ────────────────────────────────────────────────

    @staticmethod
    def accept_item(item_id: int, note: str = "", session=None) -> dict | None:
        """Accept a review item (status: open → accepted)."""
        return ReviewItemManager._transition(item_id, "accepted", note, session)

    @staticmethod
    def skip_item(item_id: int, note: str = "", session=None) -> dict | None:
        """Skip a review item (status: open → skipped)."""
        return ReviewItemManager._transition(item_id, "skipped", note, session)

    @staticmethod
    def resolve_item(item_id: int, note: str = "", session=None) -> dict | None:
        """Resolve a review item (open/accepted → resolved)."""
        return ReviewItemManager._transition(item_id, "resolved", note, session)

    @staticmethod
    def _transition(
        item_id: int, new_status: str, note: str = "", session=None,
    ) -> dict | None:
        """Internal: transition item to new_status."""
        _session = session
        _close = session is None
        try:
            if _session is None:
                _session = get_session()
            item = _session.get(ReviewItem, item_id)
            if item is None:
                return None
            # Valid source states for each target
            allowed_from = {
                "accepted": {"open"},
                "skipped": {"open"},
                "resolved": {"open", "accepted"},
            }
            if new_status in allowed_from and item.status not in allowed_from[new_status]:
                return None
            item.status = new_status
            if new_status in ("accepted", "resolved", "skipped"):
                item.resolved_at = datetime.now()
            if note:
                item.resolution_note = note
            _session.commit()
            return ReviewItemManager._row_to_dict(item)
        except Exception as e:
            if _session:
                with __import__("contextlib").suppress(Exception):
                    _session.rollback()
            logger.error("Failed to transition item %d to %s: %s", item_id, new_status, e)
            return None
        finally:
            if _close and _session:
                _session.close()

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(item: ReviewItem) -> dict:
        return {
            "id": item.id,
            "item_type": item.item_type,
            "severity": item.severity,
            "status": item.status,
            "title": item.title,
            "description": item.description,
            "source_ref": item.source_ref,
            "source_path": item.source_path,
            "suggested_action_json": item.suggested_action_json,
            "resolution_note": item.resolution_note,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
        }
