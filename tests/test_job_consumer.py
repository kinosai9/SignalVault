"""M4-C: JobConsumer tests.

Tests for the ProcessingJob queue consumer: gating, execution dispatch,
budget enforcement, and empty queue handling.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from signalvault.services.job_consumer import JobConsumer, get_job_consumer


# ── Helpers ────────────────────────────────────────────────────────────────────


class _FakeJob:
    """Minimal ProcessingJob stub for testing."""

    def __init__(self, id=1, job_type="analyze", source_item_id=1,
                 status="pending", retry_count=0, max_retries=3, params=None):
        self.id = id
        self.job_type = job_type
        self.source_item_id = source_item_id
        self.status = status
        self.retry_count = retry_count
        self.max_retries = max_retries
        self.params = params or {}


# ── Gating tests ──────────────────────────────────────────────────────────────


class TestJobConsumerGating:
    """Tests for automation, budget, and quiet-hours gating."""

    def test_consume_when_automation_disabled_returns_false(self):
        """When automation.enabled is False, consume_one should return False."""
        consumer = JobConsumer()

        with patch.object(consumer, "_automation_enabled", return_value=False):
            assert consumer.consume_one() is False

    def test_consume_when_budget_exhausted_returns_false(self):
        """When budget is exhausted, consume_one should return False."""
        consumer = JobConsumer()

        with patch.object(consumer, "_automation_enabled", return_value=True), \
             patch.object(consumer, "_budget_available", return_value=False):
            assert consumer.consume_one() is False

    def test_consume_when_in_quiet_hours_returns_false(self):
        """When in quiet hours, consume_one should return False."""
        consumer = JobConsumer()

        with patch.object(consumer, "_automation_enabled", return_value=True), \
             patch.object(consumer, "_budget_available", return_value=True), \
             patch.object(consumer, "_in_quiet_hours", return_value=True):
            assert consumer.consume_one() is False

    def test_empty_queue_returns_false(self):
        """When no pending jobs exist, consume_one returns False."""
        consumer = JobConsumer()

        with patch.object(consumer, "_automation_enabled", return_value=True), \
             patch.object(consumer, "_budget_available", return_value=True), \
             patch.object(consumer, "_in_quiet_hours", return_value=False), \
             patch.object(consumer, "_fetch_next_job", return_value=None):
            assert consumer.consume_one() is False


class TestJobConsumerExecution:
    """Tests for job execution dispatch."""

    def test_consume_analyze_job(self):
        """Analyze jobs should be dispatched via PipelineOrchestrator."""
        consumer = JobConsumer()
        job = _FakeJob(id=42, job_type="analyze", source_item_id=1)

        with patch.object(consumer, "_automation_enabled", return_value=True), \
             patch.object(consumer, "_budget_available", return_value=True), \
             patch.object(consumer, "_in_quiet_hours", return_value=False), \
             patch.object(consumer, "_fetch_next_job", return_value=job), \
             patch.object(consumer, "_execute_job") as mock_exec:
            result = consumer.consume_one()
            assert result is True
            mock_exec.assert_called_once_with(job)

    def test_consume_batch_processes_multiple(self):
        """consume_batch should process up to max_jobs."""
        consumer = JobConsumer()
        call_count = [0]

        def fake_consume():
            call_count[0] += 1
            return call_count[0] <= 3  # succeed 3 times, then stop

        with patch.object(consumer, "consume_one", side_effect=fake_consume):
            processed = consumer.consume_batch(max_jobs=10)
            assert processed == 3

    def test_consume_batch_stops_on_empty(self):
        """consume_batch stops when consume_one returns False."""
        consumer = JobConsumer()
        call_count = [0]

        def fake_consume():
            call_count[0] += 1
            if call_count[0] == 1:
                return True
            return False  # queue empty after first

        with patch.object(consumer, "consume_one", side_effect=fake_consume):
            processed = consumer.consume_batch(max_jobs=10)
            assert processed == 1


class TestJobConsumerFetch:
    """Tests for _fetch_next_job."""

    def test_fetch_returns_none_when_queue_empty(self):
        """When ProcessingJobManager returns None, _fetch_next_job returns None."""
        with patch(
            "signalvault.services.processing_job_manager.ProcessingJobManager.get_next_pending",
            return_value=None,
        ):
            result = JobConsumer._fetch_next_job()
            assert result is None

    def test_fetch_returns_job_when_available(self):
        """When a job is pending, _fetch_next_job returns it."""
        job = _FakeJob(id=1, job_type="sync_graph", source_item_id=2)
        with patch(
            "signalvault.services.processing_job_manager.ProcessingJobManager.get_next_pending",
            return_value=job,
        ):
            result = JobConsumer._fetch_next_job()
            assert result is job
            assert result.job_type == "sync_graph"


class TestJobConsumerGenericJob:
    """Tests for handling unsupported/generic job types."""

    def test_generic_job_type_skipped(self):
        """Jobs without a specific executor should be marked completed."""
        consumer = JobConsumer()
        job = _FakeJob(id=99, job_type="unknown_type", source_item_id=1)

        with patch(
            "signalvault.services.processing_job_manager.ProcessingJobManager.mark_running"
        ) as mock_running, patch(
            "signalvault.services.processing_job_manager.ProcessingJobManager.mark_completed"
        ) as mock_completed:
            consumer._execute_job(job)

            mock_running.assert_called_once_with(99)
            mock_completed.assert_called_once()
            _, kwargs = mock_completed.call_args
            assert kwargs.get("result_type") == "skipped"


class TestJobConsumerErrorHandling:
    """Tests for error handling and retries."""

    def test_job_execution_failure_marks_failed(self):
        """When execute_job raises, job is marked failed and retried if possible."""
        consumer = JobConsumer()
        job = _FakeJob(id=7, job_type="analyze", source_item_id=1,
                       retry_count=0, max_retries=3)

        with patch(
            "signalvault.services.processing_job_manager.ProcessingJobManager.mark_running"
        ), patch(
            "signalvault.services.processing_job_manager.ProcessingJobManager.mark_failed"
        ) as mock_failed, patch(
            "signalvault.services.processing_job_manager.ProcessingJobManager.reset_for_retry"
        ) as mock_reset:
            # Force execution to fail by passing to a failing _execute_pipeline_job
            with patch.object(consumer, "_execute_pipeline_job",
                              side_effect=RuntimeError("test failure")):
                consumer._execute_job(job)

            mock_failed.assert_called()
            # Should try to reset for retry
            mock_reset.assert_called()

    def test_job_retry_exhausted_does_not_reset(self):
        """When retry_count >= max_retries, reset_for_retry is NOT called.

        The _execute_job method checks `job.retry_count < job.max_retries`
        before calling reset_for_retry. When exhausted, it skips the reset.
        """
        job = _FakeJob(id=8, job_type="analyze", source_item_id=1,
                       retry_count=3, max_retries=3)

        with patch(
            "signalvault.services.processing_job_manager.ProcessingJobManager.reset_for_retry"
        ) as mock_reset:
            consumer = JobConsumer()
            with patch(
                "signalvault.services.processing_job_manager.ProcessingJobManager.mark_running"
            ), patch(
                "signalvault.services.processing_job_manager.ProcessingJobManager.mark_failed"
            ):
                with patch.object(consumer, "_execute_pipeline_job",
                                  side_effect=RuntimeError("test")):
                    consumer._execute_job(job)

            # retry_count (3) < max_retries (3) is False → no reset
            mock_reset.assert_not_called()


class TestSingletonConsumer:
    """Tests for get_job_consumer singleton."""

    def test_returns_same_instance(self):
        c1 = get_job_consumer()
        c2 = get_job_consumer()
        assert c1 is c2
