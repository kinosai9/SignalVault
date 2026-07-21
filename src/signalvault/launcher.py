"""M2-R: SignalVault Launcher — lifecycle orchestration for desktop launch.

Responsibilities (and nothing else):
    - Detect existing instances via PID file + health-first state machine
    - Select a free local port
    - Start uvicorn in-process with controlled lifecycle
    - Poll /api/health until ready
    - Open default browser
    - Handle SIGINT/SIGTERM for graceful shutdown
    - Clean up PID file on exit (only owned PIDs)

This module does NOT implement business logic, UI, settings, or .app bundling.
"""

from __future__ import annotations

import json
import logging
import os
import queue
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


@dataclass(frozen=True)
class DetectionOutcome:
    """Result of instance detection state machine.

    Actions:
        "reuse"   — healthy existing instance found, reuse it
        "start"   — no instance, safe to start fresh
        "conflict" — ambiguous state, do NOT start, return non-zero
    """

    action: str  # "reuse" | "start" | "conflict"
    existing: InstanceRecord | None = None
    conflict_reason: str = ""


@dataclass
class _LaunchState:
    """Mutable state tracked across the launch lifecycle for cleanup decisions."""

    owned_instance_id: str | None = None
    pid_written: bool = False
    logger_available: bool = False
    shutdown_requested: bool = False
    server_error: BaseException | None = None


# ═══════════════════════════════════════════════════════════════════════════
# Injection points (overridable for tests)
# ═══════════════════════════════════════════════════════════════════════════

# These module-level callables allow tests to inject fakes without
# monkey-patching.  In production they are wired to real OS / stdlib functions.


def _pid_file_path() -> Path:
    from signalvault.settings.app_paths import AppPaths
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
    """Return True if a process with *pid* exists on this system.

    On Windows, uses the Win32 API (OpenProcess + GetExitCodeProcess)
    because os.kill(pid, 0) is unreliable for cross-process checks.
    On POSIX, uses os.kill(pid, 0).
    """
    if pid <= 0:
        return False

    if sys.platform == "win32":
        return _win32_process_exists(pid)

    try:
        os.kill(pid, 0)
        return True
    except (OSError, PermissionError):
        return False


def _win32_process_exists(pid: int) -> bool:
    """Check process existence on Windows using Win32 API.

    Uses OpenProcess with PROCESS_QUERY_LIMITED_INFORMATION
    (least privilege required) + GetExitCodeProcess to check
    if the process is still running (STILL_ACTIVE == 259).

    No external dependency — uses stdlib ctypes only.
    """
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    kernel32 = ctypes.windll.kernel32

    # OpenProcess
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [
        wintypes.DWORD,   # dwDesiredAccess
        wintypes.BOOL,    # bInheritHandle
        wintypes.DWORD,   # dwProcessId
    ]

    # GetExitCodeProcess
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE,                      # hProcess
        ctypes.POINTER(wintypes.DWORD),       # lpExitCode
    ]

    # CloseHandle
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )

    if not handle:
        # OpenProcess failed
        # ERROR_ACCESS_DENIED (5) = process exists but access denied (e.g. elevated)
        err = kernel32.GetLastError()
        # ACCESS_DENIED (5) → process exists but we can't open it
        return err == 5

    exit_code = wintypes.DWORD()
    success = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
    kernel32.CloseHandle(handle)

    if not success:
        return False

    return exit_code.value == STILL_ACTIVE


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


def _remove_pid_file(path: Path, *, owned_instance_id: str | None = None) -> bool:
    """Remove the PID file.

    If *owned_instance_id* is provided, only removes the file if the
    on-disk record's instance_id matches.  Returns True if removed.
    """
    import contextlib

    if owned_instance_id is not None:
        record = _read_pid_file(path)
        if record is not None and record.instance_id != owned_instance_id:
            logger.warning(
                "PID file ownership mismatch: expected %s, found %s — not removing",
                owned_instance_id,
                record.instance_id,
            )
            return False

    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)
        return True
    return False


def _archive_pid_file(path: Path, reason: str) -> None:
    """Archive a corrupt or stale PID file with timestamp suffix.

    Atomic rename: signalvault.pid → signalvault.pid.corrupt.<YYYYMMDDTHHMMSS>
    """
    timestamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    archive_path = path.with_name(f"{path.name}.corrupt.{timestamp}")
    try:
        path.rename(archive_path)
        logger.info("Archived %s PID file: %s → %s", reason, path.name, archive_path.name)
    except OSError:
        logger.warning(
            "Failed to archive %s PID file at %s; will overwrite on next write",
            reason, path,
        )


# ═══════════════════════════════════════════════════════════════════════════
# Instance detection — health-first state machine
# ═══════════════════════════════════════════════════════════════════════════


def detect_existing_instance(pid_path: Path) -> DetectionOutcome:
    """Check for a running SignalVault instance using health-first detection.

    State machine:
        1. Read PID file → if absent or unparseable, archive if corrupt, start
        2. Health-check the recorded host:port
        3. health OK + app="signalvault" → REUSE
        4. health unreachable → check PID
           - PID gone → stale, archive, start
           - PID alive → CONFLICT (ambiguous, do not touch)
        5. health OK but app ≠ "signalvault" →
           - PID alive → CONFLICT
           - PID gone → stale, archive, start

    Returns:
        DetectionOutcome with action in {"reuse", "start", "conflict"}.
    """
    record = _read_pid_file(pid_path)
    if record is None:
        # File exists but couldn't be parsed (corrupt JSON, missing fields, empty)
        if pid_path.exists():
            _archive_pid_file(pid_path, reason="corrupt")
        return DetectionOutcome(action="start")

    # ── Step 1: Health-check first ──────────────────────────────────────
    health = _health_check(record.host, record.port, 1.0)

    # ── health OK + correct identity → healthy existing instance ─────────
    if health is not None and health.get("app") == "signalvault":
        logger.info(
            "Existing healthy instance found: pid=%d, port=%d, id=%s",
            record.pid,
            record.port,
            record.instance_id,
        )
        return DetectionOutcome(action="reuse", existing=record)

    # ── health returned something else on that port ──────────────────────
    if health is not None:
        # app != "signalvault" — something else is on that port
        logger.warning(
            "Health endpoint on %s:%d returned app=%r (expected 'signalvault')",
            record.host,
            record.port,
            health.get("app"),
        )
        if _process_exists(record.pid):
            # PID is alive but it's not SignalVault → conflict
            return DetectionOutcome(
                action="conflict",
                conflict_reason=(
                    f"端口 {record.host}:{record.port} 上运行的不是 SignalVault "
                    f"(app={health.get('app')!r})，但 PID {record.pid} 仍存活"
                ),
            )
        # PID gone — stale record, something else on port
        _archive_pid_file(pid_path, reason="wrong_app")
        return DetectionOutcome(action="start")

    # ── health unreachable → check PID ──────────────────────────────────
    # health is None (connection refused, timeout, etc.)

    if _process_exists(record.pid):
        # PID exists but health is unreachable → ambiguous conflict
        logger.warning(
            "PID %d is alive but health check failed on %s:%d — "
            "ambiguous state, treating as conflict (not killing, not overwriting)",
            record.pid,
            record.host,
            record.port,
        )
        return DetectionOutcome(
            action="conflict",
            conflict_reason=(
                f"PID {record.pid} 存活但 {record.host}:{record.port} "
                f"health 检查不可达"
            ),
        )

    # PID is gone → stale
    logger.info(
        "Stale PID file detected (pid=%d not running), archiving", record.pid
    )
    _archive_pid_file(pid_path, reason="stale")
    return DetectionOutcome(action="start")


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

    Thread exceptions are captured via queue.Queue so the launcher
    can detect abnormal server termination.
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
        self._error_queue: queue.Queue = queue.Queue()

    @property
    def server(self) -> "uvicorn.Server":
        return self._server

    def start_in_thread(self) -> None:
        """Start the uvicorn server in a daemon thread."""

        def _run() -> None:
            try:
                self._server.run()
            except BaseException as e:
                self._error_queue.put(e)
                raise

        self._thread = threading.Thread(target=_run, name="uvicorn-server", daemon=True)
        self._thread.start()

    def request_shutdown(self) -> None:
        """Signal uvicorn to shut down gracefully."""
        self._server.should_exit = True

    def is_alive(self) -> bool:
        """Return True if the server thread is still running."""
        return self._thread is not None and self._thread.is_alive()

    def get_error(self) -> BaseException | None:
        """Return any exception captured from the server thread, or None."""
        try:
            return self._error_queue.get_nowait()
        except queue.Empty:
            return None

    def wait(self, timeout: float | None = None) -> None:
        """Wait for the server thread to finish."""
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)


# ═══════════════════════════════════════════════════════════════════════════
# Error messages (actionable, no bare tracebacks)
# ═══════════════════════════════════════════════════════════════════════════


def _error_instance_conflict(reason: str, log_path: str) -> str:
    return (
        "检测到 SignalVault 进程仍在运行，但暂时无法连接。\n"
        "为避免同时启动多个实例，本次启动已停止。\n"
        "请稍后重试，或结束现有进程后重新启动。\n"
        f"日志：{log_path}"
    )


def _error_runtime_write_failed(dir_path: str, log_path: str) -> str:
    return (
        "SignalVault 无法创建运行状态文件。\n"
        "请检查数据目录是否可写。\n"
        f"目录：{dir_path}\n"
        f"日志：{log_path}"
    )


def _error_server_stopped_unexpectedly(log_path: str) -> str:
    return (
        "SignalVault 服务意外停止。\n"
        "请查看日志后重新启动。\n"
        f"日志：{log_path}"
    )


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
        from signalvault.settings.app_paths import AppPaths
        return str(AppPaths.resolve().log_dir / "launcher.log")
    except Exception:
        return "launcher.log"


def _configure_launcher_logging(log_path: str) -> None:
    """Set up file-based logging for the launcher."""
    log_file = Path(log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)

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


# ═══════════════════════════════════════════════════════════════════════════
# Main launcher entry point
# ═══════════════════════════════════════════════════════════════════════════


def launch(config: LauncherConfig | None = None) -> int:
    """Run the launcher lifecycle.

    Returns an exit code (0 = success, non-zero = failure).

    All operations from the earliest fallible point are wrapped in
    a unified try/except/finally boundary.  PID files are only
    cleaned up when owned by this launch instance.
    """
    if config is None:
        config = LauncherConfig()

    host = config.host  # always 127.0.0.1
    state = _LaunchState()
    runner: _UvicornRunner | None = None
    pid_path: Path | None = None
    log_path: str = "launcher.log"
    original_sigint: Any = None
    original_sigterm: Any = None

    # ── Unified exception boundary ───────────────────────────────────────
    try:
        # ── Phase 0: Early init ──────────────────────────────────────────
        log_path = _get_log_path()
        _configure_launcher_logging(log_path)
        state.logger_available = True

        pid_path = _pid_file_path()

        print("SignalVault 正在启动…")
        print(f"日志位置：{log_path}")

        logger.info("SignalVault Launcher starting (version=%s)", _get_version())
        logger.info("PID file: %s", pid_path)

        # ── Phase 1: Detect existing instance ────────────────────────────
        detection = detect_existing_instance(pid_path)

        if detection.action == "reuse":
            existing = detection.existing
            assert existing is not None
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
            return 0

        if detection.action == "conflict":
            logger.error("Instance conflict: %s", detection.conflict_reason)
            print(
                _error_instance_conflict(detection.conflict_reason, log_path),
                file=sys.stderr,
            )
            return 1

        # detection.action == "start" — proceed

        # ── Phase 2: Select port ─────────────────────────────────────────
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

        # ── Phase 3: Write PID file ──────────────────────────────────────
        state.owned_instance_id = uuid.uuid4().hex[:12]
        record = InstanceRecord(
            pid=os.getpid(),
            host=host,
            port=port,
            started_at=_now_iso(),
            instance_id=state.owned_instance_id,
        )
        try:
            _write_pid_file(pid_path, record)
            state.pid_written = True
        except OSError as e:
            logger.error("Failed to write PID file: %s", e)
            runtime_dir = str(pid_path.parent)
            print(
                _error_runtime_write_failed(runtime_dir, log_path),
                file=sys.stderr,
            )
            return 1

        logger.info("Instance ID: %s", state.owned_instance_id)

        # ── Phase 4: Start uvicorn in thread ─────────────────────────────
        runner = _UvicornRunner(host, port)

        def _on_signal(signum: int, _frame: Any) -> None:
            sig_name = signal.Signals(signum).name
            logger.info(
                "Received signal %s (%d), initiating shutdown", sig_name, signum
            )
            state.shutdown_requested = True
            if runner is not None:
                runner.request_shutdown()

        # Register signal handlers
        original_sigint = signal.signal(signal.SIGINT, _on_signal)
        original_sigterm = signal.signal(signal.SIGTERM, _on_signal)

        runner.start_in_thread()
        logger.info("Uvicorn started on %s:%d", host, port)

        # ── Phase 5: Wait for health (checking server liveness) ──────────
        url = f"http://{host}:{port}"
        health_ok = False
        deadline = time.monotonic() + config.health_timeout

        while time.monotonic() < deadline:
            # If server thread died before health, fail immediately
            if not runner.is_alive():
                state.server_error = runner.get_error()
                logger.error(
                    "Server thread exited before health check succeeded%s",
                    f": {state.server_error}" if state.server_error else "",
                )
                print(
                    _error_server_stopped_unexpectedly(log_path),
                    file=sys.stderr,
                )
                runner.request_shutdown()
                runner.wait(timeout=5.0)
                return 1

            health = _health_check(host, port, 2.0)
            if (
                health is not None
                and health.get("status") == "ok"
                and health.get("app") == "signalvault"
            ):
                health_ok = True
                logger.info(
                    "Server healthy: version=%s, db=%s",
                    health.get("version", "?"),
                    health.get("database", "?"),
                )
                break

            _sleep(config.health_interval)

        if not health_ok:
            logger.error("Health check timed out after %.0fs", config.health_timeout)
            print(
                "SignalVault 无法启动：本地服务未能就绪。\n"
                "请稍后重试；如果仍然失败，请查看日志：\n"
                f"{log_path}",
                file=sys.stderr,
            )
            runner.request_shutdown()
            runner.wait(timeout=5.0)
            return 1

        # ── Phase 6: Success — open browser ──────────────────────────────
        print("SignalVault 启动成功。")
        print(f"访问地址：{url}")
        print("按 Ctrl+C 停止服务；关闭浏览器不会停止服务。")

        if config.open_browser:
            opened = _open_browser(url)
            if opened:
                logger.info("Browser opened at %s", url)
            else:
                logger.warning("Failed to open browser; open manually: %s", url)
                print(f"无法自动打开浏览器，请手动访问：{url}", file=sys.stderr)

        # ── Phase 7: Keep-alive until signal or server exit ──────────────
        while not state.shutdown_requested and runner.is_alive():
            _sleep(0.5)

        # ── Phase 8: Determine exit reason ───────────────────────────────
        if not state.shutdown_requested:
            # Server thread exited without us requesting shutdown → abnormal
            state.server_error = runner.get_error()
            logger.error(
                "SignalVault server stopped unexpectedly%s",
                f": {state.server_error}" if state.server_error else "",
            )
            print(
                _error_server_stopped_unexpectedly(log_path),
                file=sys.stderr,
            )
            runner.request_shutdown()
            runner.wait(timeout=5.0)
            return 1

        # ── Phase 9: Graceful shutdown ───────────────────────────────────
        logger.info("Shutting down...")
        runner.request_shutdown()

        # Trigger FastAPI lifespan shutdown + background thread shutdown
        _shutdown_background_tasks()

        runner.wait(timeout=10.0)
        if runner.is_alive():
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
        if runner is not None:
            try:
                runner.request_shutdown()
                runner.wait(timeout=5.0)
            except Exception:
                pass
        return 1

    finally:
        # ── Restore original signal handlers ─────────────────────────────
        if original_sigint is not None:
            signal.signal(signal.SIGINT, original_sigint)
        if original_sigterm is not None:
            signal.signal(signal.SIGTERM, original_sigterm)

        # ── Clean up PID file (only if we own it) ────────────────────────
        if state.pid_written and pid_path is not None:
            _remove_pid_file(pid_path, owned_instance_id=state.owned_instance_id)
            logger.info("PID file cleaned up")
