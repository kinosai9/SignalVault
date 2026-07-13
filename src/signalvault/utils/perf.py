"""Lightweight performance measurement for request-stage profiling.

Zero external dependencies. Provides:
- measure_stage: context manager for timing a block of code
- get_stage_report: aggregate stats (avg/max/min/p50/p95) for recent calls
- measure_page: decorator for full-page timing with Server-Timing header
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from contextlib import contextmanager
from functools import wraps

logger = logging.getLogger("signalvault.perf")

_stage_timings: dict[str, list[float]] = defaultdict(list)


@contextmanager
def measure_stage(stage_name: str):
    """Context manager that records elapsed time for a named stage.

    Usage:
        with measure_stage("vault_scan"):
            snapshot = scanner.scan()
    """
    t0 = time.perf_counter()
    yield
    elapsed = time.perf_counter() - t0
    logger.info("PERF [%s]: %.3f s", stage_name, elapsed)
    _stage_timings[stage_name].append(elapsed)


def get_stage_report() -> dict[str, dict]:
    """Return aggregate timing stats for the last 20 requests per stage.

    Keys: avg, max, min, p50, p95, samples
    """
    report: dict[str, dict] = {}
    for stage, timings in _stage_timings.items():
        if not timings:
            continue
        last_n = timings[-20:]
        sorted_n = sorted(last_n)
        n = len(sorted_n)
        report[stage] = {
            "avg": round(sum(last_n) / n, 4),
            "max": round(max(last_n), 4),
            "min": round(min(last_n), 4),
            "p50": round(sorted_n[n // 2], 4),
            "p95": round(sorted_n[int(n * 0.95)], 4),
            "samples": n,
        }
    return report


def measure_page(page_name: str):
    """Decorator that times an entire page handler and adds Server-Timing header.

    Supports both sync and async handlers.

    Usage:
        @router.get("/dashboard")
        @measure_page("dashboard")
        def page_dashboard(request: Request):
            ...
    """
    import inspect

    def decorator(fn):
        if inspect.iscoroutinefunction(fn):
            @wraps(fn)
            async def async_wrapper(*args, **kwargs):
                t0 = time.perf_counter()
                try:
                    result = await fn(*args, **kwargs)
                    elapsed = time.perf_counter() - t0
                    logger.info("PERF [%s] TOTAL: %.3f s", page_name, elapsed)
                    if hasattr(result, "headers"):
                        result.headers["Server-Timing"] = (
                            f"total;dur={elapsed * 1000:.0f}"
                        )
                    return result
                except Exception:
                    elapsed = time.perf_counter() - t0
                    logger.error(
                        "PERF [%s] FAILED after %.3f s", page_name, elapsed
                    )
                    raise
            return async_wrapper
        else:
            @wraps(fn)
            def sync_wrapper(*args, **kwargs):
                t0 = time.perf_counter()
                try:
                    result = fn(*args, **kwargs)
                    elapsed = time.perf_counter() - t0
                    logger.info("PERF [%s] TOTAL: %.3f s", page_name, elapsed)
                    if hasattr(result, "headers"):
                        result.headers["Server-Timing"] = (
                            f"total;dur={elapsed * 1000:.0f}"
                        )
                    return result
                except Exception:
                    elapsed = time.perf_counter() - t0
                    logger.error(
                        "PERF [%s] FAILED after %.3f s", page_name, elapsed
                    )
                    raise
            return sync_wrapper
    return decorator
