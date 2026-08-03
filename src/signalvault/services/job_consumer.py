"""M4-C: Job Consumer — ProcessingJob queue consumer.

Consumes pending ProcessingJobs from the database queue, executing them
via the PipelineOrchestrator with budget and quiet-hours gating.

Design:
- consume_one() processes a single job (called periodically by DesktopScheduler)
- Budget enforcement via shared BudgetTracker
- Respects automation.enabled flag
- Delegates execution to PipelineOrchestrator for analyze/sync_graph jobs
- Direct execution for simpler job types (extract_claims, etc.)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Module-level singleton ────────────────────────────────────────────────────

_consumer_instance: JobConsumer | None = None


def get_job_consumer() -> JobConsumer:
    """Return the singleton JobConsumer, creating it if necessary."""
    global _consumer_instance
    if _consumer_instance is None:
        _consumer_instance = JobConsumer()
    return _consumer_instance


# ── Job type → execution strategy ─────────────────────────────────────────────

# Job types that can be processed through the unified pipeline
_PIPELINE_JOB_TYPES = frozenset({"analyze", "extract_text"})

# Job types that use direct GraphSyncService
_GRAPH_SYNC_JOB_TYPES = frozenset({"sync_graph"})

# Job types that use direct ClaimExtractor
_CLAIM_JOB_TYPES = frozenset({"extract_claims"})


class JobConsumer:
    """Consumes ProcessingJobs from the pending queue.

    Usage:
        consumer = JobConsumer()
        consumed = consumer.consume_one()  # → bool
    """

    def __init__(self):
        self._consecutive_empty: int = 0
        self._max_empty_before_backoff: int = 10

    # ── Public API ────────────────────────────────────────────────────────

    def consume_one(self) -> bool:
        """Consume a single pending ProcessingJob.

        Returns True if a job was processed, False if queue was empty
        or consumption was blocked by budget/quiet-hours/automation toggle.
        """
        # Gate 1: Automation must be enabled
        if not self._automation_enabled():
            return False

        # Gate 2: Budget check for LLM-heavy job types
        if not self._budget_available():
            return False

        # Gate 3: Quiet hours check (non-LLM jobs can still run)
        if self._in_quiet_hours():
            return False

        # Fetch next pending job
        job = self._fetch_next_job()
        if job is None:
            self._consecutive_empty += 1
            return False

        self._consecutive_empty = 0

        # Execute the job
        try:
            self._execute_job(job)
            return True
        except Exception:
            logger.exception("JobConsumer: unhandled error for job id=%s", job.id)
            return False

    def consume_batch(self, max_jobs: int = 5) -> int:
        """Consume up to max_jobs pending jobs. Returns count processed."""
        processed = 0
        for _ in range(max_jobs):
            if not self.consume_one():
                break
            processed += 1
        return processed

    # ── Gating checks ─────────────────────────────────────────────────────

    def _automation_enabled(self) -> bool:
        """Check if automation.enabled is True in config."""
        try:
            from signalvault.settings.service import get_config_service
            svc = get_config_service()
            return svc.get_bool("automation.enabled") is not False
        except Exception:
            return True  # default: enabled

    def _budget_available(self) -> bool:
        """Check if LLM budget has remaining capacity."""
        try:
            from signalvault.services.desktop_scheduler import get_desktop_scheduler
            scheduler = get_desktop_scheduler()
            return scheduler.budget.can_consume(1)
        except Exception:
            return True

    @staticmethod
    def _in_quiet_hours() -> bool:
        """Check if we're currently in quiet hours."""
        try:
            from signalvault.services.desktop_scheduler import _in_quiet_hours
            from signalvault.settings.service import get_config_service
            svc = get_config_service()
            start = svc.get_string("automation.quiet_hours_start") or "23:00"
            end = svc.get_string("automation.quiet_hours_end") or "07:00"
            return _in_quiet_hours(start, end)
        except Exception:
            return False

    # ── Job fetching ──────────────────────────────────────────────────────

    @staticmethod
    def _fetch_next_job() -> Any | None:
        """Fetch the highest-priority pending ProcessingJob."""
        try:
            from signalvault.services.processing_job_manager import ProcessingJobManager
            return ProcessingJobManager.get_next_pending()
        except Exception:
            logger.exception("Failed to fetch next pending job")
            return None

    # ── Job execution ─────────────────────────────────────────────────────

    def _execute_job(self, job: Any) -> None:
        """Execute a ProcessingJob based on its job_type.

        Dispatches to the appropriate execution strategy.
        """
        from signalvault.services.processing_job_manager import ProcessingJobManager

        job_type = job.job_type

        # Mark as running
        ProcessingJobManager.mark_running(job.id)

        try:
            if job_type in _PIPELINE_JOB_TYPES:
                self._execute_pipeline_job(job)
            elif job_type in _GRAPH_SYNC_JOB_TYPES:
                self._execute_graph_sync_job(job)
            elif job_type in _CLAIM_JOB_TYPES:
                self._execute_claim_job(job)
            else:
                self._execute_generic_job(job)

            # Record budget consumption for LLM jobs
            if job_type in ("analyze",):
                try:
                    from signalvault.services.desktop_scheduler import get_desktop_scheduler
                    get_desktop_scheduler().budget.record_consumption(1)
                except Exception:
                    pass

        except Exception as e:
            logger.exception("Job id=%s type=%s failed", job.id, job_type)
            ProcessingJobManager.mark_failed(job.id, str(e))

            # Retry if possible
            if job.retry_count < job.max_retries:
                ProcessingJobManager.reset_for_retry(job.id)
                logger.info(
                    "Job id=%s reset for retry (%d/%d)",
                    job.id, job.retry_count + 1, job.max_retries,
                )

    def _execute_pipeline_job(self, job: Any) -> None:
        """Execute an analyze job through the unified pipeline."""
        from signalvault.services.pipeline_orchestrator import PipelineOrchestrator
        from signalvault.services.processing_job_manager import ProcessingJobManager
        from signalvault.services.source_item_manager import SourceItemManager

        # Parse params for focus/depth/mock
        import json
        params = {}
        if job.params:
            try:
                params = json.loads(job.params) if isinstance(job.params, str) else (job.params or {})
            except (json.JSONDecodeError, TypeError):
                params = {}

        focus = params.get("focus", "")
        depth = params.get("depth", "standard")
        mock = params.get("mock", True)

        orchestrator = PipelineOrchestrator()
        result = orchestrator.run(
            source_item_id=job.source_item_id,
            focus=focus,
            depth=depth,
            mock=mock,
        )

        if result.success:
            ProcessingJobManager.mark_completed(
                job.id,
                result_type="research_asset",
                result_ref=result.report_id,
            )
            # Update SourceItem status
            SourceItemManager.update_status(job.source_item_id, "processed")
            logger.info(
                "Pipeline job id=%s completed: report_id=%s claims=%d graph=%s",
                job.id, result.report_id, result.claim_count, result.graph_synced,
            )
        else:
            ProcessingJobManager.mark_failed(job.id, result.error_message)

    def _execute_graph_sync_job(self, job: Any) -> None:
        """Execute a graph sync job directly."""
        from signalvault.services.graph_sync_service import sync_report_to_graph
        from signalvault.services.processing_job_manager import ProcessingJobManager

        import json
        params = {}
        if job.params:
            try:
                params = json.loads(job.params) if isinstance(job.params, str) else (job.params or {})
            except (json.JSONDecodeError, TypeError):
                params = {}

        report_id = params.get("report_id")
        if not report_id:
            # Try to find report_id from the SourceItem
            from signalvault.services.source_item_manager import SourceItemManager
            item = SourceItemManager.get(job.source_item_id)
            if item and item.source_document_id:
                # Look up report by source_document_id
                try:
                    from signalvault.db.session import get_session
                    from signalvault.db.models import Report
                    session = get_session()
                    try:
                        rpt = session.query(Report).filter_by(
                            source_document_id=item.source_document_id
                        ).first()
                        if rpt:
                            report_id = rpt.id
                    finally:
                        session.close()
                except Exception:
                    pass

        if not report_id:
            ProcessingJobManager.mark_failed(job.id, "No report_id found for graph sync")
            return

        stats = sync_report_to_graph(report_id)
        ProcessingJobManager.mark_completed(
            job.id,
            result_type="graph_sync",
            result_ref=stats.get("edges_created", 0),
        )
        logger.info(
            "Graph sync job id=%s completed: nodes=%d edges=%d",
            job.id, stats.get("nodes_created", 0), stats.get("edges_created", 0),
        )

    def _execute_claim_job(self, job: Any) -> None:
        """Execute a claim extraction job directly."""
        from signalvault.services.claim_extractor import ClaimExtractor
        from signalvault.services.processing_job_manager import ProcessingJobManager

        import json
        params = {}
        if job.params:
            try:
                params = json.loads(job.params) if isinstance(job.params, str) else (job.params or {})
            except (json.JSONDecodeError, TypeError):
                params = {}

        report_id = params.get("report_id")
        if not report_id:
            ProcessingJobManager.mark_failed(job.id, "No report_id found for claim extraction")
            return

        extractor = ClaimExtractor()
        claims = extractor.extract_from_report(report_id)
        ProcessingJobManager.mark_completed(
            job.id,
            result_type="claims",
            result_ref=len(claims),
        )
        logger.info("Claim extraction job id=%s completed: %d claims", job.id, len(claims))

    def _execute_generic_job(self, job: Any) -> None:
        """Handle job types without a specific executor."""
        from signalvault.services.processing_job_manager import ProcessingJobManager
        ProcessingJobManager.mark_completed(
            job.id,
            result_type="skipped",
            result_ref=None,
        )
        logger.info("Generic job id=%s type=%s marked as skipped", job.id, job.job_type)
