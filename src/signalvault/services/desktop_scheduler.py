"""M4-C: Desktop Scheduler — background periodic task runner.

Singleton scheduler for desktop automation:
- Daemon thread with configurable tick interval (~30s)
- Periodic task registry: {task_id: {fn, interval_seconds, last_run}}
- Quiet hours: skip tasks during configured window
- Budget tracking: enforce daily LLM call limit
- Stuck job recovery: reset "running" ProcessingJobs on startup
- Lifecycle: start() / stop() / pause() / resume()
- Status query: get_status() → {running, paused, tasks, next_runs, budget}

Design: pure threading + time.sleep — no external dependency.
Consistent with existing job_service.py patterns.
"""

from __future__ import annotations

import logging
import threading
import time as _time
from datetime import datetime, time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── Module-level singleton ────────────────────────────────────────────────────

_scheduler_instance: DesktopScheduler | None = None


def get_desktop_scheduler() -> DesktopScheduler:
    """Return the singleton DesktopScheduler, creating it if necessary."""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = DesktopScheduler()
    return _scheduler_instance


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now_epoch() -> float:
    return _time.time()


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_time(time_str: str) -> time:
    """Parse HH:MM string to time object."""
    parts = time_str.strip().split(":")
    return time(hour=int(parts[0]), minute=int(parts[1]))


def _in_quiet_hours(start_str: str, end_str: str) -> bool:
    """Check if current local time is within the quiet hours window.

    Handles overnight windows (e.g. 23:00-07:00) and same-day windows.
    """
    try:
        now = datetime.now().time()
        start = _parse_time(start_str)
        end = _parse_time(end_str)

        if start <= end:
            # Same-day: 07:00-23:00 → quiet is outside
            return now < start or now > end
        else:
            # Overnight: 23:00-07:00 → quiet is inside
            return now >= start or now <= end
    except (ValueError, IndexError):
        logger.warning("Invalid quiet hours format: %s-%s", start_str, end_str)
        return False


# ── Budget tracker ────────────────────────────────────────────────────────────


class BudgetTracker:
    """Track daily LLM call budget.

    Budget is reset at midnight local time.
    """

    def __init__(self):
        self._daily_limit: int = 10
        self._used_today: int = 0
        self._date_key: str = ""

    def configure(self, daily_limit: int) -> None:
        self._daily_limit = daily_limit

    @property
    def remaining(self) -> int:
        self._reset_if_new_day()
        if self._daily_limit == 0:
            return 999_999  # unlimited
        return max(0, self._daily_limit - self._used_today)

    @property
    def used(self) -> int:
        self._reset_if_new_day()
        return self._used_today

    def can_consume(self, count: int = 1) -> bool:
        self._reset_if_new_day()
        if self._daily_limit == 0:
            return True  # unlimited
        return (self._used_today + count) <= self._daily_limit

    def record_consumption(self, count: int = 1) -> None:
        self._reset_if_new_day()
        self._used_today += count

    def _reset_if_new_day(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._date_key:
            self._used_today = 0
            self._date_key = today

    def get_status(self) -> dict[str, Any]:
        return {
            "daily_limit": self._daily_limit,
            "used_today": self.used,
            "remaining": self.remaining,
        }


# ── Scheduler ─────────────────────────────────────────────────────────────────


class DesktopScheduler:
    """Background scheduler for periodic automation tasks.

    Usage:
        scheduler = DesktopScheduler()
        scheduler.register_task("consume_queue", job_consumer.consume_one, interval=60)
        scheduler.register_task("refresh_channels", _refresh_channels, interval=86400)
        scheduler.start()

        # Later:
        status = scheduler.get_status()
        scheduler.stop()
    """

    def __init__(self):
        self._tasks: dict[str, dict[str, Any]] = {}
        self._thread: threading.Thread | None = None
        self._running = False
        self._paused = False

        # Budget tracker (shared with JobConsumer)
        self.budget = BudgetTracker()

        # Tick interval — how often the scheduler loop wakes up (seconds)
        self._tick_seconds: float = 30.0

        # External shutdown event (from job_service / launcher)
        self._external_shutdown_event: threading.Event | None = None

    # ── Task registration ─────────────────────────────────────────────────

    def register_task(
        self,
        task_id: str,
        fn: Callable[[], Any],
        *,
        interval_seconds: int,
        enabled: bool = True,
    ) -> None:
        """Register a periodic task.

        Args:
            task_id: Unique identifier for this task.
            fn: Callable to execute (no arguments).
            interval_seconds: Minimum seconds between executions.
            enabled: Whether this task is active.
        """
        self._tasks[task_id] = {
            "fn": fn,
            "interval_seconds": interval_seconds,
            "last_run": 0.0,
            "enabled": enabled,
        }
        logger.info(
            "Registered task '%s': interval=%ds enabled=%s",
            task_id, interval_seconds, enabled,
        )

    def unregister_task(self, task_id: str) -> bool:
        """Remove a registered task. Returns False if not found."""
        if task_id in self._tasks:
            del self._tasks[task_id]
            logger.info("Unregistered task '%s'", task_id)
            return True
        return False

    def enable_task(self, task_id: str) -> bool:
        if task_id in self._tasks:
            self._tasks[task_id]["enabled"] = True
            return True
        return False

    def disable_task(self, task_id: str) -> bool:
        if task_id in self._tasks:
            self._tasks[task_id]["enabled"] = False
            return True
        return False

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the scheduler loop in a daemon thread.

        Idempotent: if already running, does nothing.
        """
        if self._running:
            logger.warning("Scheduler already running")
            return

        # Recover stuck jobs before starting
        self._recover_stuck_jobs()

        # Wire external shutdown event from job_service
        try:
            from signalvault.services.job_service import _shutdown_event
            self._external_shutdown_event = _shutdown_event
        except Exception:
            pass

        self._running = True
        # Preserve paused state if caller set it before start()
        # (useful for tests and programmatic control)
        self._thread = threading.Thread(
            target=self._loop, name="desktop-scheduler", daemon=True,
        )
        self._thread.start()
        logger.info("DesktopScheduler started (tick=%.1fs)", self._tick_seconds)

    def stop(self) -> None:
        """Stop the scheduler loop gracefully.

        Blocks until the scheduler thread exits (up to ~tick_seconds + 5s).
        """
        if not self._running:
            return
        logger.info("DesktopScheduler stopping...")
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=self._tick_seconds + 5.0)
            if self._thread.is_alive():
                logger.warning("Scheduler thread did not exit within timeout")
        logger.info("DesktopScheduler stopped")

    def pause(self) -> None:
        """Pause task execution. The loop keeps running but skips tasks."""
        self._paused = True
        logger.info("DesktopScheduler paused")

    def resume(self) -> None:
        """Resume task execution after pause."""
        self._paused = False
        logger.info("DesktopScheduler resumed")

    # ── Status query ──────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return scheduler status for API/UI consumption."""
        tasks_status = {}
        for tid, tdef in self._tasks.items():
            next_run = ""
            if tdef["last_run"] > 0:
                next_at = tdef["last_run"] + tdef["interval_seconds"]
                remaining = max(0, next_at - _now_epoch())
                if remaining > 0:
                    next_run = f"{remaining:.0f}s"
                else:
                    next_run = "即将执行"
            else:
                next_run = "启动后首次执行"

            tasks_status[tid] = {
                "enabled": tdef["enabled"],
                "interval_seconds": tdef["interval_seconds"],
                "last_run": (
                    _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(tdef["last_run"]))
                    if tdef["last_run"] > 0 else ""
                ),
                "next_run": next_run,
            }

        return {
            "running": self._running,
            "paused": self._paused,
            "tick_seconds": self._tick_seconds,
            "tasks": tasks_status,
            "budget": self.budget.get_status(),
        }

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    # ── Register default periodic tasks ───────────────────────────────────

    def register_default_tasks(self, config: dict[str, Any] | None = None) -> None:
        """Register the built-in periodic tasks based on current config.

        Called once after app startup. Reads intervals from ConfigService.
        """
        intervals = self._resolve_intervals(config)

        # Task 1: ProcessingJob queue consumer
        try:
            from signalvault.services.job_consumer import get_job_consumer
            consumer = get_job_consumer()
            self.register_task(
                "consume_queue",
                consumer.consume_one,
                interval_seconds=intervals["queue_poll"],
            )
        except Exception:
            logger.warning("Could not register consume_queue task", exc_info=True)

        # Task 2: Channel auto-refresh
        self.register_task(
            "refresh_channels",
            self._refresh_all_channels,
            interval_seconds=intervals["channel_refresh"],
        )

        # Task 3: Tracked source auto-refresh
        self.register_task(
            "scan_tracked_sources",
            self._scan_all_tracked_sources,
            interval_seconds=intervals["tracked_source_scan"],
        )

    def _resolve_intervals(self, config: dict[str, Any] | None) -> dict[str, int]:
        """Resolve task intervals from config or ConfigService."""
        if config is not None:
            return {
                "queue_poll": int(config.get("queue_poll_seconds", 60)),
                "channel_refresh": int(config.get("channel_refresh_hours", 24)) * 3600,
                "tracked_source_scan": int(config.get("tracked_source_scan_minutes", 60)) * 60,
            }

        try:
            from signalvault.settings.service import get_config_service
            svc = get_config_service()
            return {
                "queue_poll": svc.get_int("automation.queue_poll_seconds") or 60,
                "channel_refresh": (svc.get_int("automation.channel_refresh_hours") or 24) * 3600,
                "tracked_source_scan": (svc.get_int("automation.tracked_source_scan_minutes") or 60) * 60,
            }
        except Exception:
            return {"queue_poll": 60, "channel_refresh": 86400, "tracked_source_scan": 3600}

    def reload_intervals(self) -> None:
        """Reload task intervals from config (called after settings change)."""
        intervals = self._resolve_intervals(None)
        mapping = {
            "consume_queue": intervals["queue_poll"],
            "refresh_channels": intervals["channel_refresh"],
            "scan_tracked_sources": intervals["tracked_source_scan"],
        }
        for tid, interval in mapping.items():
            if tid in self._tasks:
                self._tasks[tid]["interval_seconds"] = interval
                logger.info("Updated '%s' interval to %ds", tid, interval)

    # ── Main loop ─────────────────────────────────────────────────────────

    def _loop(self) -> None:
        """Main scheduler loop. Runs in a daemon thread."""
        logger.info("Scheduler loop started")

        # Update budget from config on start
        self._refresh_budget_config()

        while self._running:
            tick_start = _now_epoch()

            if not self._paused:
                self._run_due_tasks()

            # Sleep for the tick interval, but check _running periodically
            # so stop() doesn't block for the full tick duration
            while self._running:
                elapsed = _now_epoch() - tick_start
                if elapsed >= self._tick_seconds:
                    break
                sleep_remaining = min(1.0, self._tick_seconds - elapsed)
                _time.sleep(sleep_remaining)

                # Check external shutdown event
                if self._external_shutdown_event and self._external_shutdown_event.is_set():
                    logger.info("External shutdown event received")
                    self._running = False
                    break

        logger.info("Scheduler loop exited")

    def _run_due_tasks(self) -> None:
        """Execute any registered tasks that are due."""
        now = _now_epoch()

        # Check quiet hours
        if self._in_quiet_hours():
            return

        for tid, tdef in list(self._tasks.items()):
            if not tdef["enabled"]:
                continue
            if now - tdef["last_run"] < tdef["interval_seconds"]:
                continue

            # Execute the task
            try:
                tdef["last_run"] = now
                logger.debug("Running task '%s'", tid)
                tdef["fn"]()
            except Exception:
                logger.exception("Task '%s' failed", tid)

    # ── Quiet hours ───────────────────────────────────────────────────────

    def _in_quiet_hours(self) -> bool:
        """Check if we're currently in quiet hours based on config."""
        try:
            from signalvault.settings.service import get_config_service
            svc = get_config_service()
            start = svc.get_string("automation.quiet_hours_start") or "23:00"
            end = svc.get_string("automation.quiet_hours_end") or "07:00"
            return _in_quiet_hours(start, end)
        except Exception:
            return False

    # ── Budget ────────────────────────────────────────────────────────────

    def _refresh_budget_config(self) -> None:
        """Read daily_llm_budget from config and update the budget tracker."""
        try:
            from signalvault.settings.service import get_config_service
            svc = get_config_service()
            limit = svc.get_int("automation.daily_llm_budget")
            if limit is not None:
                self.budget.configure(limit)
        except Exception:
            pass

    # ── Stuck job recovery ────────────────────────────────────────────────

    def _recover_stuck_jobs(self) -> None:
        """Reset ProcessingJobs stuck in 'running' state back to 'pending'.

        Called on startup to handle jobs left running by an unclean shutdown.
        """
        try:
            from signalvault.services.processing_job_manager import ProcessingJobManager
            running_jobs = ProcessingJobManager.get_running_jobs()
            if running_jobs:
                logger.info(
                    "Recovering %d stuck ProcessingJobs (running → pending)",
                    len(running_jobs),
                )
                for job in running_jobs:
                    ProcessingJobManager.reset_for_retry(job.id)
        except Exception:
            logger.exception("Failed to recover stuck ProcessingJobs")

    # ── Periodic task implementations ──────────────────────────────────────

    @staticmethod
    def _refresh_all_channels() -> None:
        """Refresh all active YouTube channels.

        Creates channel_refresh background jobs for each active channel.
        """
        try:
            from signalvault.db.channel_repository import list_channels
            from signalvault.db.session import get_session

            session = get_session()
            try:
                channels = list_channels(session)
            finally:
                session.close()

            active = [c for c in channels if c.get("is_active", True)]
            if not active:
                return

            from signalvault.services.job_service import (
                create_channel_refresh_job,
                start_channel_refresh_job,
            )

            for ch in active:
                try:
                    job = create_channel_refresh_job(
                        channel_url=ch["url"],
                        channel_name=ch.get("name", ch["youtube_channel_id"]),
                        channel_id=ch["id"],
                    )
                    start_channel_refresh_job(job)
                    logger.info("Auto-refreshed channel: %s", ch.get("name", ch["id"]))
                except Exception:
                    logger.exception(
                        "Failed to refresh channel id=%s", ch.get("id"),
                    )
        except Exception:
            logger.exception("Channel auto-refresh failed")

    @staticmethod
    def _scan_all_tracked_sources() -> None:
        """Scan all enabled tracked sources for new content."""
        try:
            from pathlib import Path

            from signalvault.db.repository import list_tracked_sources
            from signalvault.db.session import get_session
            from signalvault.sources.tracked_source_service import refresh_tracked_source

            session = get_session()
            try:
                sources = list_tracked_sources(session, enabled_only=True)
            finally:
                session.close()

            if not sources:
                return

            # Resolve vault path for preview store
            try:
                from signalvault.settings.service import get_config_service
                svc = get_config_service()
                vault_path_str = svc.get_string("obsidian.vault_path") or ""
                vault_path = Path(vault_path_str) if vault_path_str else Path.home() / "SignalVault"
            except Exception:
                vault_path = Path.home() / "SignalVault"

            preview_store: dict[str, Any] = {}

            for ts in sources:
                kind = ts.get("source_kind", "")
                if kind not in ("allin_notes_index",):
                    continue

                try:
                    result = refresh_tracked_source(ts["id"], vault_path, preview_store)
                    logger.info(
                        "Auto-scanned tracked source %s: %s",
                        ts.get("name", ts["id"]),
                        result.get("message", ""),
                    )
                except Exception:
                    logger.exception(
                        "Failed to scan tracked source id=%s", ts.get("id"),
                    )
        except Exception:
            logger.exception("Tracked source auto-scan failed")
