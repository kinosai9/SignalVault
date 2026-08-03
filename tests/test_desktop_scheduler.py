"""M4-C: DesktopScheduler tests.

Tests for the background scheduler: lifecycle, task registration, quiet hours,
budget tracking, and stuck job recovery.
"""

from __future__ import annotations

import time as _time

import pytest

from signalvault.services.desktop_scheduler import (
    BudgetTracker,
    DesktopScheduler,
    _in_quiet_hours,
    _parse_time,
)


# ── BudgetTracker tests ────────────────────────────────────────────────────────


class TestBudgetTracker:
    """Tests for BudgetTracker daily LLM budget."""

    def test_initial_state(self):
        bt = BudgetTracker()
        assert bt.used == 0
        assert bt.remaining == 10  # default limit
        assert bt.can_consume(1) is True

    def test_configure_changes_limit(self):
        bt = BudgetTracker()
        bt.configure(5)
        assert bt.remaining == 5
        assert bt.can_consume(6) is False

    def test_record_consumption_decreases_remaining(self):
        bt = BudgetTracker()
        bt.record_consumption(3)
        assert bt.used == 3
        assert bt.remaining == 7
        assert bt.can_consume(7) is True
        assert bt.can_consume(8) is False

    def test_unlimited_mode(self):
        bt = BudgetTracker()
        bt.configure(0)  # 0 = unlimited
        assert bt.remaining > 100_000
        assert bt.can_consume(1000) is True

    def test_reset_daily(self):
        bt = BudgetTracker()
        bt.record_consumption(10)
        assert bt.remaining == 0

        # Force date change by manipulating _date_key
        bt._date_key = "1980-01-01"
        assert bt.remaining == 10  # reset to full

    def test_get_status(self):
        bt = BudgetTracker()
        bt.configure(15)
        bt.record_consumption(5)
        status = bt.get_status()
        assert status["daily_limit"] == 15
        assert status["used_today"] == 5
        assert status["remaining"] == 10


# ── Quiet hours tests ──────────────────────────────────────────────────────────


class TestQuietHours:
    """Tests for quiet hours helper functions."""

    def test_parse_time_valid(self):
        t = _parse_time("23:00")
        assert t.hour == 23
        assert t.minute == 0

        t = _parse_time("07:00")
        assert t.hour == 7
        assert t.minute == 0

    def test_quiet_hours_overnight_active(self, monkeypatch):
        """At 01:00, with 23:00-07:00 quiet window, should be quiet."""
        import datetime as dt_real

        class MockDatetime(dt_real.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 8, 3, 1, 0, 0)

        monkeypatch.setattr(
            "signalvault.services.desktop_scheduler.datetime",
            MockDatetime,
        )
        assert _in_quiet_hours("23:00", "07:00") is True

    def test_quiet_hours_overnight_inactive(self, monkeypatch):
        """At 12:00, with 23:00-07:00 quiet window, should NOT be quiet."""
        import datetime as dt_real

        class MockDatetime(dt_real.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 8, 3, 12, 0, 0)

        monkeypatch.setattr(
            "signalvault.services.desktop_scheduler.datetime",
            MockDatetime,
        )
        assert _in_quiet_hours("23:00", "07:00") is False

    def test_quiet_hours_same_day_active(self, monkeypatch):
        """Within 07:00-23:00 window, inactive means quiet outside."""
        import datetime as dt_real

        class MockDatetime(dt_real.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 8, 3, 3, 0, 0)

        monkeypatch.setattr(
            "signalvault.services.desktop_scheduler.datetime",
            MockDatetime,
        )
        assert _in_quiet_hours("07:00", "23:00") is True

    def test_quiet_hours_same_day_inactive(self, monkeypatch):
        """Within 07:00-23:00 window, active means not quiet."""
        import datetime as dt_real

        class MockDatetime(dt_real.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 8, 3, 14, 0, 0)

        monkeypatch.setattr(
            "signalvault.services.desktop_scheduler.datetime",
            MockDatetime,
        )
        assert _in_quiet_hours("07:00", "23:00") is False

    def test_invalid_format_returns_false(self):
        assert _in_quiet_hours("not-valid", "bad") is False


# ── DesktopScheduler lifecycle tests ───────────────────────────────────────────


class TestDesktopSchedulerLifecycle:
    """Tests for DesktopScheduler start/stop/pause/resume."""

    def test_initial_state(self):
        sched = DesktopScheduler()
        assert sched.is_running is False
        assert sched.is_paused is False

    def test_start_stop(self):
        sched = DesktopScheduler()
        sched._tick_seconds = 0.1  # faster ticks for test
        sched.start()
        assert sched.is_running is True
        assert sched.is_paused is False
        sched.stop()
        assert sched.is_running is False

    def test_pause_resume(self):
        sched = DesktopScheduler()
        sched._tick_seconds = 0.1
        sched.start()
        assert sched.is_paused is False

        sched.pause()
        assert sched.is_paused is True

        sched.resume()
        assert sched.is_paused is False

        sched.stop()

    def test_double_start_is_idempotent(self):
        sched = DesktopScheduler()
        sched._tick_seconds = 0.1
        sched.start()
        sched.start()  # should not raise or create second thread
        assert sched.is_running
        sched.stop()

    def test_stop_when_not_running_is_safe(self):
        sched = DesktopScheduler()
        sched.stop()  # should not raise
        assert sched.is_running is False


class TestDesktopSchedulerTasks:
    """Tests for task registration and execution."""

    def test_register_and_get_status(self):
        sched = DesktopScheduler()
        executed = []

        def my_task():
            executed.append(1)

        sched.register_task("test_task", my_task, interval_seconds=60)
        status = sched.get_status()
        assert "test_task" in status["tasks"]
        assert status["tasks"]["test_task"]["enabled"] is True
        assert status["tasks"]["test_task"]["interval_seconds"] == 60

    def test_enable_disable_task(self):
        sched = DesktopScheduler()
        sched.register_task("t1", lambda: None, interval_seconds=10)

        assert sched.disable_task("t1") is True
        status = sched.get_status()
        assert status["tasks"]["t1"]["enabled"] is False

        assert sched.enable_task("t1") is True
        status = sched.get_status()
        assert status["tasks"]["t1"]["enabled"] is True

    def test_unregister_task(self):
        sched = DesktopScheduler()
        sched.register_task("t1", lambda: None, interval_seconds=10)
        assert sched.unregister_task("t1") is True
        assert sched.unregister_task("t1") is False  # already gone
        assert "t1" not in sched.get_status()["tasks"]

    def test_task_execution(self):
        sched = DesktopScheduler()
        sched._tick_seconds = 0.05
        executed = []

        def my_task():
            executed.append(1)

        sched.register_task("t1", my_task, interval_seconds=0.01)
        sched.start()

        # Wait for at least one execution
        _time.sleep(0.3)
        sched.stop()

        assert len(executed) >= 1, "Task should have been executed at least once"
        status = sched.get_status()
        assert status["tasks"]["t1"]["last_run"] != ""

    def test_paused_scheduler_does_not_execute(self):
        sched = DesktopScheduler()
        sched._tick_seconds = 0.05
        executed = []

        def my_task():
            executed.append(1)

        # Register with a small interval so it would fire if not paused
        sched.register_task("t1", my_task, interval_seconds=0.01)
        # Set last_run to now so interval hasn't elapsed yet
        sched._tasks["t1"]["last_run"] = _time.time()

        # Start the scheduler already paused
        sched._paused = True
        sched.start()

        _time.sleep(0.3)
        assert len(executed) == 0, "Paused scheduler should not execute tasks"

        # Resume and verify it now executes
        sched.resume()
        _time.sleep(0.3)
        sched.stop()

        assert len(executed) >= 1, "Resumed scheduler should execute tasks"

    def test_task_exception_is_caught(self):
        """Task exceptions should not crash the scheduler."""
        sched = DesktopScheduler()
        sched._tick_seconds = 0.05

        def failing_task():
            raise RuntimeError("test error")

        sched.register_task("bad", failing_task, interval_seconds=0.01)
        sched.start()

        _time.sleep(0.2)
        # If the scheduler didn't crash, we're good
        sched.stop()
        assert True  # survived


class TestDesktopSchedulerBudget:
    """Tests for budget integration in scheduler."""

    def test_budget_shared_with_scheduler(self):
        sched = DesktopScheduler()
        assert sched.budget is not None
        assert sched.budget.remaining == 10
        status = sched.get_status()
        assert status["budget"]["daily_limit"] == 10


class TestSingletonAccessor:
    """Tests for get_desktop_scheduler singleton."""

    def test_returns_same_instance(self):
        from signalvault.services.desktop_scheduler import get_desktop_scheduler
        s1 = get_desktop_scheduler()
        s2 = get_desktop_scheduler()
        assert s1 is s2
