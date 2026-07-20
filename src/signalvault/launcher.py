"""M2: SignalVault Launcher — lifecycle orchestration for desktop launch.

Responsibilities (and nothing else):
    - Detect existing instances via PID file + health check
    - Select a free local port
    - Start uvicorn in-process with controlled lifecycle
    - Poll /api/health until ready
    - Open default browser
    - Handle SIGINT/SIGTERM for graceful shutdown
    - Clean up PID file on exit

This module does NOT implement business logic, UI, settings, or .app bundling.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import sys
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uvicorn

from signalvault.settings.app_paths import AppPaths

logger = logging.getLogger("signalvault.launcher")


# ═══════════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class LauncherConfig:
    """Immutable configuration for a launcher run."""

    host: str = "127.0.0.1"
    preferred_port: int = 8000
    max_port_attempts: int = 10
    health_timeout: float = 15.0
    health_interval: float = 0.2
    open_browser: bool = True

    def __post_init__(self) -> None:
        # Enforce local-only binding
        if self.host != "127.0.0.1":
            object.__setattr__(self, "host", "127.0.0.1")


@dataclass(frozen=True)
class InstanceRecord:
    """Serialisable record stored in the PID file."""

    pid: int
    host: str
    port: int
    started_at: str
    instance_id: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "pid": self.pid,
                "host": self.host,
                "port": self.port,
                "started_at": self.started_at,
                "instance_id": self.instance_id,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> InstanceRecord | None:
        try:
            data = json.loads(raw)
            return cls(
                pid=int(data["pid"]),
                host=str(data["host"]),
                port=int(data["port"]),
                started_at=str(data["started_at"]),
                instance_id=str(data["instance_id"]),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None


# ═══════════════════════════════════════════════════════════════════════════
# Injection points (overridable for tests)
# ═══════════════════════════════════════════════════════════════════════════

# These module-level callables allow tests to inject fakes without
# monkey-patching.  In production they are wired to real OS / stdlib functions.


def _pid_file_path() -> Path:
    return AppPaths.resolve().runtime_dir / "signalvault.pid"


def _process_exists(pid: int) -> bool:
    return _os_process_exists(pid)


def _port_in_use(host: str, port: int) -> bool:
    return _socket_port_in_use(host, port)


def _health_check(host: str, port: int, timeout: float) -> dict[str, Any] | None:
    return _http_health_check(host, port, timeout)


def _open_browser(url: str) -> bool:
    return _webbrowser_open(url)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


# ═══════════════════════════════════════════════════════════════════════════
# Real implementations (used in production)
# ═══════════════════════════════════════════════════════════════════════════


def _os_process_exists(pid: int) -> bool:
    """Return True if a process with *pid* exists on this system."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, PermissionError):
        return False


def _socket_port_in_use(host: str, port: int) -> bool:
    """Return True if *host:port* is already bound by another process."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.1)
        try:
            s.connect((host, port))
            s.shutdown(socket.SHUT_RDWR)
            return True
        except (ConnectionRefusedError, OSError, TimeoutError):
            return False


def _http_health_check(
    host: str, port: int, timeout: float
) -> dict[str, Any] | None:
    """Perform a single HTTP GET /api/health and return the parsed JSON body,
    or None on any failure (connection, HTTP error, non-200, JSON parse).
    """
    import urllib.request

    url = f"http://{host}:{port}/api/health"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except Exception:
        return None


def _webbrowser_open(url: str) -> bool:
    """Open *url* in the default browser.  Return True on success."""
    try:
        return webbrowser.open(url)
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# PID file helpers
# ═══════════════════════════════════════════════════════════════════════════


def _read_pid_file(path: Path) -> InstanceRecord | None:
    """Read and parse a PID file.  Returns None on any error."""
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        return InstanceRecord.from_json(raw)
    except (OSError, UnicodeDecodeError):
        return None


def _write_pid_file(path: Path, record: InstanceRecord) -> None:
    """Atomically write the PID file (write-then-rename)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(record.to_json(), encoding="utf-8")
    tmp.replace(path)


def _remove_pid_file(path: Path) -> None:
    """Best-effort removal of the PID file."""
    import contextlib
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════
# Instance detection
# ═══════════════════════════════════════════════════════════════════════════


def detect_existing_instance(pid_path: Path) -> InstanceRecord | None:
    """Check for a running SignalVault instance.

    Returns an ``InstanceRecord`` if a healthy instance is found, or
    ``None`` if no valid instance exists.  Stale PID files are cleaned up.

    Detection requires ALL of:
        1. PID file is parseable
        2. The PID refers to a running process
        3. The health endpoint is reachable
        4. The health response contains ``"app": "signalvault"``
    """
    record = _read_pid_file(pid_path)
    if record is None:
        return None

    # Check process exists
    if not _process_exists(record.pid):
        logger.info(
            "Stale PID file detected (pid=%d not running), cleaning up", record.pid
        )
        _remove_pid_file(pid_path)
        return None

    # Check health endpoint
    health = _health_check(record.host, record.port, 1.0)
    if health is None:
        logger.warning(
            "PID %d is alive but health check failed on %s:%d — "
            "not killing, treating as conflict",
            record.pid,
            record.host,
            record.port,
        )
        return None

    if health.get("app") != "signalvault":
        logger.warning(
            "Health endpoint on %s:%d returned app=%r (expected 'signalvault')",
            record.host,
            record.port,
            health.get("app"),
        )
        return None

    logger.info(
        "Existing healthy instance found: pid=%d, port=%d, id=%s",
        record.pid,
        record.port,
        record.instance_id,
    )
    return record


# ═══════════════════════════════════════════════════════════════════════════
# Port selection
# ═══════════════════════════════════════════════════════════════════════════


def select_port(
    host: str,
    preferred: int,
    max_attempts: int = 10,
) -> int | None:
    """Find a free port starting from *preferred*.

    Returns the first free port, or ``None`` if all *max_attempts* ports
    are in use.
    """
    for offset in range(max_attempts):
        port = preferred + offset
        if not _port_in_use(host, port):
            return port
        logger.debug("Port %d in use, trying %d", port, port + 1)
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Health polling
# ═══════════════════════════════════════════════════════════════════════════


class HealthTimeoutError(RuntimeError):
    """Raised when the server does not become healthy within the timeout."""


def wait_for_health(
    host: str,
    port: int,
    timeout: float = 15.0,
    interval: float = 0.2,
) -> dict[str, Any]:
    """Poll /api/health until the server responds with identity.

    Returns the health JSON dict on success.

    Raises:
        HealthTimeoutError: if the server does not respond within *timeout*.
    """
    deadline = time.monotonic() + timeout
    last_error: str | None = None

    while time.monotonic() < deadline:
        health = _health_check(host, port, 2.0)
        if health is not None:
            if (
                health.get("status") == "ok"
                and health.get("app") == "signalvault"
            ):
                logger.info("Health OK: version=%s", health.get("version", "?"))
                return health
            else:
                last_error = (
                    f"Unexpected health response: status={health.get('status')}, "
                    f"app={health.get('app')}"
                )
                logger.warning(last_error)
        else:
            last_error = "Health endpoint not reachable"

        _sleep(interval)

    raise HealthTimeoutError(
        f"Server did not become healthy within {timeout:.0f}s. "
        f"Last error: {last_error or 'unknown'}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Uvicorn lifecycle (in-process, controlled)
# ═══════════════════════════════════════════════════════════════════════════


class _UvicornRunner:
    """Thin wrapper around uvicorn.Server for controlled lifecycle.

    Runs uvicorn in a daemon thread so the launcher main thread can
    poll health, open the browser, and wait for signals.
    """

    def __init__(self, host: str, port: int) -> None:
        import uvicorn

        from signalvault.api.app import create_app

        app = create_app()
        config = uvicorn.Config(
            app=app,
            host=host,
            port=port,
            log_level="info",
            # No reload in production launcher
        )
        self._server = uvicorn.Server(config)
        self._thread: threading.Thread | None = None

    @property
    def server(self) -> "uvicorn.Server":
        return self._server

    def start_in_thread(self) -> None:
        """Start the uvicorn server in a daemon thread."""

        def _run() -> None:
            self._server.run()

        self._thread = threading.Thread(target=_run, name="uvicorn-server", daemon=True)
        self._thread.start()

    def request_shutdown(self) -> None:
        """Signal uvicorn to shut down gracefully."""
        self._server.should_exit = True

    def wait(self, timeout: float | None = None) -> None:
        """Wait for the server thread to finish."""
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)


# ═══════════════════════════════════════════════════════════════════════════
# Main launcher entry point
# ═══════════════════════════════════════════════════════════════════════════


def launch(config: LauncherConfig | None = None) -> int:
    """Run the launcher lifecycle.

    Returns an exit code (0 = success, non-zero = failure).
    """
    if config is None:
        config = LauncherConfig()

    host = config.host  # always 127.0.0.1
    pid_path = _pid_file_path()
    log_path = _get_log_path()

    _configure_launcher_logging()

    print("SignalVault 正在启动…")
    print(f"日志位置：{log_path}")

    logger.info("SignalVault Launcher starting (version=%s)", _get_version())
    logger.info("PID file: %s", pid_path)

    # ── 1. Detect existing instance ───────────────────────────────────────
    existing = detect_existing_instance(pid_path)
    if existing is not None:
        url = f"http://{existing.host}:{existing.port}"
        logger.info("Reusing existing instance at %s", url)
        print("SignalVault 已在运行，正在打开现有页面。")
        print(f"访问地址：{url}")
        if config.open_browser and not _open_browser(url):
            logger.warning(
                "Failed to reopen browser for existing instance; open manually: %s",
                url,
            )
            print(f"无法自动打开浏览器，请手动访问：{url}", file=sys.stderr)
        # If user wants to open the existing instance, we are done
        return 0

    # ── 2. Select port ────────────────────────────────────────────────────
    port = select_port(host, config.preferred_port, config.max_port_attempts)
    if port is None:
        msg = (
            f"No free port found after {config.max_port_attempts} attempts "
            f"(starting from {config.preferred_port})"
        )
        logger.error(msg)
        print(
            "SignalVault 无法启动：端口 "
            f"{config.preferred_port}–{config.preferred_port + config.max_port_attempts - 1} "
            "均被占用。\n请关闭占用端口的程序，或使用 --port 指定其他端口。\n"
            f"日志位置：{log_path}",
            file=sys.stderr,
        )
        return 1

    logger.info("Selected port: %d", port)
    if port != config.preferred_port:
        print(f"端口 {config.preferred_port} 已被占用，改用 {port}。")

    # ── 3. Write PID file (preliminary) ───────────────────────────────────
    instance_id = uuid.uuid4().hex[:12]
    record = InstanceRecord(
        pid=os.getpid(),
        host=host,
        port=port,
        started_at=_now_iso(),
        instance_id=instance_id,
    )
    _write_pid_file(pid_path, record)
    logger.info("Instance ID: %s", instance_id)

    # ── 4. Start uvicorn in thread ────────────────────────────────────────
    runner = _UvicornRunner(host, port)
    shutdown_requested = False

    def _on_signal(signum: int, _frame: Any) -> None:
        nonlocal shutdown_requested
        sig_name = signal.Signals(signum).name
        logger.info("Received signal %s (%d), initiating shutdown", sig_name, signum)
        shutdown_requested = True
        runner.request_shutdown()

    # Register signal handlers
    original_sigint = signal.signal(signal.SIGINT, _on_signal)
    original_sigterm = signal.signal(signal.SIGTERM, _on_signal)

    try:
        runner.start_in_thread()
        logger.info("Uvicorn started on %s:%d", host, port)

        # ── 5. Wait for health ────────────────────────────────────────────
        url = f"http://{host}:{port}"
        try:
            health = wait_for_health(
                host, port,
                timeout=config.health_timeout,
                interval=config.health_interval,
            )
            logger.info(
                "Server healthy: version=%s, db=%s",
                health.get("version", "?"),
                health.get("database", "?"),
            )
        except HealthTimeoutError as e:
            logger.error("Health check failed: %s", e)
            print(
                "SignalVault 无法启动：本地服务未能就绪。\n"
                "请稍后重试；如果仍然失败，请查看日志：\n"
                f"{log_path}",
                file=sys.stderr,
            )
            runner.request_shutdown()
            runner.wait(timeout=5.0)
            _remove_pid_file(pid_path)
            return 1

        print("SignalVault 启动成功。")
        print(f"访问地址：{url}")
        print("按 Ctrl+C 停止服务；关闭浏览器不会停止服务。")

        # ── 6. Open browser ───────────────────────────────────────────────
        if config.open_browser:
            opened = _open_browser(url)
            if opened:
                logger.info("Browser opened at %s", url)
            else:
                logger.warning("Failed to open browser; open manually: %s", url)
                print(f"无法自动打开浏览器，请手动访问：{url}", file=sys.stderr)

        # ── 7. Keep-alive until signal ────────────────────────────────────
        # Poll periodically (cheap) while waiting for a shutdown signal.
        while not shutdown_requested and runner._thread is not None and runner._thread.is_alive():
            _sleep(0.5)

        # ── 8. Graceful shutdown ──────────────────────────────────────────
        logger.info("Shutting down...")
        runner.request_shutdown()

        # Trigger FastAPI lifespan shutdown + background thread shutdown
        _shutdown_background_tasks()

        runner.wait(timeout=10.0)
        if runner._thread is not None and runner._thread.is_alive():
            logger.warning("Uvicorn thread did not exit within 10s")

        logger.info("Launcher exit (code=0)")
        return 0

    except Exception:
        logger.exception("Unhandled exception in launcher")
        print(
            "SignalVault 无法启动。请确认数据目录可写后重试；"
            f"详细信息见日志：{log_path}",
            file=sys.stderr,
        )
        runner.request_shutdown()
        runner.wait(timeout=5.0)
        return 1

    finally:
        # Restore original signal handlers
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)
        # Always clean up PID file
        _remove_pid_file(pid_path)
        logger.info("PID file cleaned up")


# ═══════════════════════════════════════════════════════════════════════════
# Background task shutdown
# ═══════════════════════════════════════════════════════════════════════════


def _shutdown_background_tasks() -> None:
    """Request shutdown of registered background threads and wait.

    This is the integration point between the launcher and job_service.
    """
    try:
        from signalvault.services.job_service import shutdown_background_jobs
        shutdown_background_jobs(timeout=5.0)
    except Exception:
        logger.exception("Error during background task shutdown")


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _get_version() -> str:
    try:
        from signalvault import __version__
        return __version__
    except Exception:
        return "unknown"


def _get_log_path() -> str:
    try:
        return str(AppPaths.resolve().log_dir / "launcher.log")
    except Exception:
        return "launcher.log"


def _configure_launcher_logging() -> None:
    """Set up file-based logging for the launcher."""
    try:
        app_paths = AppPaths.resolve()
        log_dir = app_paths.log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "launcher.log"

        handler = logging.FileHandler(str(log_file), encoding="utf-8")
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        handler.setLevel(logging.DEBUG)

        launcher_logger = logging.getLogger("signalvault.launcher")
        launcher_logger.addHandler(handler)
        launcher_logger.setLevel(logging.DEBUG)
        # Don't propagate to root — launcher log is standalone
        launcher_logger.propagate = False
    except Exception:
        pass  # best-effort logging setup
