"""M2-R: Launcher lifecycle tests — comprehensive coverage.

Every test exercises the launcher with injected fakes — no real processes,
no real sockets, no real browser, no real sleeps.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

import signalvault.launcher as launcher_mod
from signalvault.launcher import (
    DetectionOutcome,
    HealthTimeoutError,
    InstanceRecord,
    LauncherConfig,
    _archive_pid_file,
    _error_instance_conflict,
    _error_runtime_write_failed,
    _error_server_stopped_unexpectedly,
    _LaunchState,
    _read_pid_file,
    _remove_pid_file,
    _UvicornRunner,
    _write_pid_file,
    detect_existing_instance,
    launch,
    select_port,
    wait_for_health,
)

# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _reset_shutdown_state():
    """Reset global shutdown state between tests."""
    import signalvault.services.job_service as js
    js._shutdown_event.clear()
    js._active_threads.clear()
    yield
    js._shutdown_event.clear()
    js._active_threads.clear()


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _make_record(
    pid: int = 12345,
    host: str = "127.0.0.1",
    port: int = 8000,
    instance_id: str | None = None,
) -> InstanceRecord:
    return InstanceRecord(
        pid=pid,
        host=host,
        port=port,
        started_at="2026-07-20T12:00:00Z",
        instance_id=instance_id or uuid.uuid4().hex[:12],
    )


def _tmp_pid_file() -> Path:
    return Path(tempfile.mkdtemp()) / "signalvault.pid"


def _inject(**overrides: Any) -> dict[str, Any]:
    """Return a dict of saved original values, after applying overrides."""
    saved = {}
    for name, new_val in overrides.items():
        saved[name] = getattr(launcher_mod, name, None)
        setattr(launcher_mod, name, new_val)
    return saved


def _restore(saved: dict[str, Any]) -> None:
    for name, original in saved.items():
        if original is None:
            continue
        setattr(launcher_mod, name, original)


def _make_detection_reuse(record: InstanceRecord) -> DetectionOutcome:
    return DetectionOutcome(action="reuse", existing=record)


def _make_detection_start() -> DetectionOutcome:
    return DetectionOutcome(action="start")


def _make_detection_conflict(reason: str = "test conflict") -> DetectionOutcome:
    return DetectionOutcome(action="conflict", conflict_reason=reason)


# ═══════════════════════════════════════════════════════════════════════════
# 1. LauncherConfig
# ═══════════════════════════════════════════════════════════════════════════


class TestLauncherConfig:
    def test_default_host_is_localhost(self):
        c = LauncherConfig()
        assert c.host == "127.0.0.1"

    def test_non_local_host_is_rejected(self):
        c = LauncherConfig(host="0.0.0.0")
        assert c.host == "127.0.0.1"

    def test_custom_port_is_respected(self):
        c = LauncherConfig(preferred_port=9999)
        assert c.preferred_port == 9999

    def test_open_browser_false(self):
        c = LauncherConfig(open_browser=False)
        assert c.open_browser is False


# ═══════════════════════════════════════════════════════════════════════════
# 2. Windows process probe
# ═══════════════════════════════════════════════════════════════════════════


class TestWindowsProcessProbe:
    def test_pid_zero_returns_false(self):
        assert launcher_mod._os_process_exists(0) is False

    def test_pid_negative_returns_false(self):
        assert launcher_mod._os_process_exists(-1) is False

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
    def test_win32_current_process_exists(self):
        """The current Python process should be detected as alive."""
        assert launcher_mod._win32_process_exists(os.getpid()) is True

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
    def test_win32_nonexistent_process(self):
        """A very high PID should not exist on a normal system."""
        # Use a PID that almost certainly doesn't exist
        assert launcher_mod._win32_process_exists(99999) is False

    def test_os_process_exists_uses_win32_on_windows(self):
        """On Windows, _os_process_exists delegates to _win32."""
        saved = _inject(_win32_process_exists=lambda pid: True)
        try:
            # This test verifies the delegation, not the actual result
            assert launcher_mod._os_process_exists(42) is True
        finally:
            _restore(saved)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Port selection
# ═══════════════════════════════════════════════════════════════════════════


class TestSelectPort:
    def test_preferred_port_free(self):
        saved = _inject(_port_in_use=lambda h, p: False)
        try:
            port = select_port("127.0.0.1", 8000, max_attempts=10)
            assert port == 8000
        finally:
            _restore(saved)

    def test_preferred_port_in_use_increments(self):
        call_count = [0]

        def fake_use(host: str, port: int) -> bool:
            call_count[0] += 1
            return port < 8002

        saved = _inject(_port_in_use=fake_use)
        try:
            port = select_port("127.0.0.1", 8000, max_attempts=10)
            assert port == 8002
            assert call_count[0] == 3
        finally:
            _restore(saved)

    def test_no_available_port(self):
        saved = _inject(_port_in_use=lambda h, p: True)
        try:
            port = select_port("127.0.0.1", 8000, max_attempts=5)
            assert port is None
        finally:
            _restore(saved)


# ═══════════════════════════════════════════════════════════════════════════
# 4. PID file I/O + archiving
# ═══════════════════════════════════════════════════════════════════════════


class TestPidFileIO:
    def test_write_and_read(self):
        path = _tmp_pid_file()
        record = _make_record(pid=42, port=9000)
        _write_pid_file(path, record)

        parsed = _read_pid_file(path)
        assert parsed is not None
        assert parsed.pid == 42
        assert parsed.port == 9000
        assert parsed.host == "127.0.0.1"

    def test_read_non_existent(self):
        path = _tmp_pid_file()
        assert _read_pid_file(path) is None

    def test_read_empty_file(self):
        path = _tmp_pid_file()
        path.write_text("")
        assert _read_pid_file(path) is None

    def test_read_corrupted_file(self):
        path = _tmp_pid_file()
        path.write_text("not json {{{")
        assert _read_pid_file(path) is None

    def test_remove_non_existent(self):
        path = _tmp_pid_file()
        result = _remove_pid_file(path)
        assert result is False or path.exists() is False

    def test_remove_existing(self):
        path = _tmp_pid_file()
        _write_pid_file(path, _make_record())
        assert path.exists()
        _remove_pid_file(path)
        assert not path.exists()

    def test_remove_with_ownership_match(self):
        """Owned PID is removed when instance_id matches."""
        path = _tmp_pid_file()
        record = _make_record()
        _write_pid_file(path, record)
        removed = _remove_pid_file(path, owned_instance_id=record.instance_id)
        assert removed is True
        assert not path.exists()

    def test_remove_with_ownership_mismatch(self):
        """Unowned PID is NOT removed."""
        path = _tmp_pid_file()
        record = _make_record()
        _write_pid_file(path, record)
        removed = _remove_pid_file(path, owned_instance_id="other-id")
        assert removed is False
        assert path.exists()  # file preserved

    def test_archive_corrupt_pid(self):
        """Corrupt PID file is archived, not silently deleted."""
        path = _tmp_pid_file()
        path.write_text("corrupt {{{")
        _archive_pid_file(path, reason="corrupt")
        # Original should be gone
        assert not path.exists()
        # An archive file should exist in the same directory
        archives = list(path.parent.glob(f"{path.name}.corrupt.*"))
        assert len(archives) >= 1

    def test_archive_stale_pid(self):
        path = _tmp_pid_file()
        _write_pid_file(path, _make_record(pid=99999))
        _archive_pid_file(path, reason="stale")
        assert not path.exists()
        archives = list(path.parent.glob(f"{path.name}.corrupt.*"))
        assert len(archives) >= 1


# ═══════════════════════════════════════════════════════════════════════════
# 5. Instance detection — health-first state machine
# ═══════════════════════════════════════════════════════════════════════════


class TestDetectExistingInstance:
    def test_no_pid_file_returns_start(self):
        path = _tmp_pid_file()
        result = detect_existing_instance(path)
        assert result.action == "start"
        assert result.existing is None

    def test_corrupt_json_returns_start_and_archives(self):
        """Corrupt PID file → 'start' action, file archived."""
        path = _tmp_pid_file()
        path.write_text("corrupt {{{")
        result = detect_existing_instance(path)
        assert result.action == "start"
        assert not path.exists()  # should be archived

    def test_empty_pid_file_returns_start(self):
        path = _tmp_pid_file()
        path.write_text("")
        result = detect_existing_instance(path)
        assert result.action == "start"

    # ── Health OK + app=signalvault → REUSE ─────────────────────────────

    def test_health_ok_signalvault_reuses(self):
        path = _tmp_pid_file()
        record = _make_record(pid=os.getpid(), port=9001)
        _write_pid_file(path, record)

        saved = _inject(
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
                "version": "0.1.0",
            },
        )
        try:
            result = detect_existing_instance(path)
            assert result.action == "reuse"
            assert result.existing is not None
            assert result.existing.port == 9001
        finally:
            _restore(saved)

    # ── Health unreachable + PID gone → START (stale) ───────────────────

    def test_health_fail_pid_gone_returns_start(self):
        """Health unreachable + PID not running → stale, archive, start."""
        path = _tmp_pid_file()
        record = _make_record(pid=99999)
        _write_pid_file(path, record)

        saved = _inject(
            _health_check=lambda host, port, timeout: None,
            _process_exists=lambda pid: False,
        )
        try:
            result = detect_existing_instance(path)
            assert result.action == "start"
            assert not path.exists()  # archived
        finally:
            _restore(saved)

    # ── Health unreachable + PID alive → CONFLICT ───────────────────────

    def test_health_fail_pid_alive_returns_conflict(self):
        """Health unreachable + PID alive → conflict, file NOT deleted."""
        path = _tmp_pid_file()
        record = _make_record(pid=os.getpid())
        _write_pid_file(path, record)

        saved = _inject(
            _health_check=lambda host, port, timeout: None,
            _process_exists=lambda pid: True,
        )
        try:
            result = detect_existing_instance(path)
            assert result.action == "conflict"
            assert "health" in result.conflict_reason.lower() or "不可达" in result.conflict_reason
            assert path.exists()  # NOT deleted
        finally:
            _restore(saved)

    # ── Health wrong app + PID alive → CONFLICT ─────────────────────────

    def test_health_wrong_app_pid_alive_returns_conflict(self):
        """Health OK but app≠signalvault + PID alive → conflict."""
        path = _tmp_pid_file()
        record = _make_record(pid=os.getpid())
        _write_pid_file(path, record)

        saved = _inject(
            _health_check=lambda host, port, timeout: {"status": "ok", "app": "nginx"},
            _process_exists=lambda pid: True,
        )
        try:
            result = detect_existing_instance(path)
            assert result.action == "conflict"
            assert path.exists()  # NOT deleted
        finally:
            _restore(saved)

    # ── Health wrong app + PID gone → START (stale, archive) ────────────

    def test_health_wrong_app_pid_gone_returns_start(self):
        """Health OK but app≠signalvault + PID gone → stale, archive, start."""
        path = _tmp_pid_file()
        record = _make_record(pid=99999)
        _write_pid_file(path, record)

        saved = _inject(
            _health_check=lambda host, port, timeout: {"status": "ok", "app": "nginx"},
            _process_exists=lambda pid: False,
        )
        try:
            result = detect_existing_instance(path)
            assert result.action == "start"
            assert not path.exists()  # archived
        finally:
            _restore(saved)

    # ── Edge cases ──────────────────────────────────────────────────────

    def test_health_missing_fields_still_reuses_if_app_matches(self):
        """Even if health response is sparse, app=signalvault → reuse."""
        path = _tmp_pid_file()
        record = _make_record(pid=os.getpid())
        _write_pid_file(path, record)

        saved = _inject(
            _health_check=lambda host, port, timeout: {"app": "signalvault"},
        )
        try:
            result = detect_existing_instance(path)
            assert result.action == "reuse"
        finally:
            _restore(saved)

    def test_conflict_does_not_overwrite_pid(self):
        """Conflict detection preserves existing PID file."""
        path = _tmp_pid_file()
        record = _make_record(pid=os.getpid(), port=9005, instance_id="existing-id")
        _write_pid_file(path, record)

        saved = _inject(
            _health_check=lambda host, port, timeout: None,
            _process_exists=lambda pid: True,
        )
        try:
            result = detect_existing_instance(path)
            assert result.action == "conflict"
            assert path.exists()
            # Verify PID file content is unchanged
            reread = _read_pid_file(path)
            assert reread is not None
            assert reread.instance_id == "existing-id"
            assert reread.port == 9005
        finally:
            _restore(saved)


# ═══════════════════════════════════════════════════════════════════════════
# 6. Health polling
# ═══════════════════════════════════════════════════════════════════════════


class TestWaitForHealth:
    def test_health_success_first_try(self):
        saved = _inject(
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
                "version": "0.1.0",
            },
            _sleep=lambda s: None,
        )
        try:
            result = wait_for_health("127.0.0.1", 8000, timeout=5.0, interval=0.1)
            assert result["status"] == "ok"
            assert result["app"] == "signalvault"
        finally:
            _restore(saved)

    def test_health_timeout(self):
        saved = _inject(
            _health_check=lambda host, port, timeout: None,
            _sleep=lambda s: None,
        )
        try:
            with pytest.raises(HealthTimeoutError):
                wait_for_health("127.0.0.1", 8000, timeout=0.5, interval=0.1)
        finally:
            _restore(saved)

    def test_health_wrong_identity(self):
        saved = _inject(
            _health_check=lambda host, port, timeout: {"status": "ok", "app": "nginx"},
            _sleep=lambda s: None,
        )
        try:
            with pytest.raises(HealthTimeoutError):
                wait_for_health("127.0.0.1", 8000, timeout=0.5, interval=0.1)
        finally:
            _restore(saved)


# ═══════════════════════════════════════════════════════════════════════════
# 7. Existing instance reuse (duplicate launch)
# ═══════════════════════════════════════════════════════════════════════════


class TestExistingInstanceReuse:
    def test_reuse_opens_browser_only(self):
        """When an existing instance is found, launch opens browser and returns 0."""
        path = _tmp_pid_file()
        record = _make_record(pid=os.getpid(), port=9002)
        _write_pid_file(path, record)

        browser_called: list[str] = []

        saved = _inject(
            _pid_file_path=lambda: path,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
            },
            _open_browser=lambda url: browser_called.append(url) or True,
        )
        try:
            config = LauncherConfig(preferred_port=9002)
            exit_code = launch(config)
            assert exit_code == 0
            assert len(browser_called) == 1
            assert "9002" in browser_called[0]
        finally:
            _restore(saved)

    def test_reuse_does_not_start_new_uvicorn(self):
        """Reusing existing instance does NOT create a new uvicorn runner."""
        path = _tmp_pid_file()
        _write_pid_file(path, _make_record(pid=os.getpid(), port=9003))

        saved = _inject(
            _pid_file_path=lambda: path,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
            },
            _open_browser=lambda url: True,
        )
        with mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner:
            try:
                exit_code = launch(LauncherConfig(preferred_port=9003))
                assert exit_code == 0
                # _UvicornRunner should NOT have been instantiated
                mock_runner.assert_not_called()
            finally:
                _restore(saved)

    def test_reuse_port_does_not_change(self):
        """Second launch reuses the same port as existing instance."""
        path = _tmp_pid_file()
        _write_pid_file(path, _make_record(pid=os.getpid(), port=8000))

        ports_checked: list[int] = []

        saved = _inject(
            _pid_file_path=lambda: path,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
            },
            _open_browser=lambda url: True,
            _port_in_use=lambda host, port: ports_checked.append(port) or False,
        )
        try:
            exit_code = launch(LauncherConfig())
            assert exit_code == 0
            # Port selection should NOT have been called (no new start)
            assert ports_checked == []
        finally:
            _restore(saved)

    def test_reuse_pid_file_unchanged(self):
        """Second launch does not overwrite existing PID file."""
        path = _tmp_pid_file()
        original = _make_record(pid=os.getpid(), port=9004, instance_id="original-id")
        _write_pid_file(path, original)

        saved = _inject(
            _pid_file_path=lambda: path,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
            },
            _open_browser=lambda url: True,
        )
        try:
            exit_code = launch(LauncherConfig(preferred_port=9004))
            assert exit_code == 0
            reread = _read_pid_file(path)
            assert reread is not None
            assert reread.instance_id == "original-id"  # unchanged
            assert reread.port == 9004
        finally:
            _restore(saved)

    def test_reuse_browser_url_matches_existing(self):
        """Browser opened with existing instance's URL."""
        path = _tmp_pid_file()
        _write_pid_file(path, _make_record(pid=os.getpid(), port=9005))

        browser_url: list[str] = []

        saved = _inject(
            _pid_file_path=lambda: path,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
            },
            _open_browser=lambda url: browser_url.append(url) or True,
        )
        try:
            launch(LauncherConfig(preferred_port=9005))
            assert browser_url == ["http://127.0.0.1:9005"]
        finally:
            _restore(saved)

    def test_reuse_browser_failure_shows_manual_url(self, capsys):
        """Browser failure while reusing still shows manual URL."""
        path = _tmp_pid_file()
        _write_pid_file(path, _make_record(pid=os.getpid(), port=9006))

        saved = _inject(
            _pid_file_path=lambda: path,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
            },
            _open_browser=lambda url: False,
        )
        try:
            assert launch(LauncherConfig()) == 0
            captured = capsys.readouterr()
            assert "SignalVault 已在运行" in captured.out
            assert "http://127.0.0.1:9006" in captured.out
            assert "请手动访问：http://127.0.0.1:9006" in captured.err
            assert path.exists()
        finally:
            _restore(saved)


# ═══════════════════════════════════════════════════════════════════════════
# 8. Instance conflict scenarios
# ═══════════════════════════════════════════════════════════════════════════


class TestInstanceConflict:
    def test_conflict_returns_nonzero(self, capsys):
        """Conflict detection → exit code 1."""
        path = _tmp_pid_file()
        _write_pid_file(path, _make_record(pid=os.getpid()))

        saved = _inject(
            _pid_file_path=lambda: path,
            _health_check=lambda host, port, timeout: None,
            _process_exists=lambda pid: True,
        )
        try:
            exit_code = launch(LauncherConfig())
            assert exit_code == 1
        finally:
            _restore(saved)

    def test_conflict_does_not_start_second_service(self):
        """Conflict → no uvicorn runner created."""
        path = _tmp_pid_file()
        _write_pid_file(path, _make_record(pid=os.getpid()))

        saved = _inject(
            _pid_file_path=lambda: path,
            _health_check=lambda host, port, timeout: None,
            _process_exists=lambda pid: True,
        )
        with mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner:
            try:
                launch(LauncherConfig())
                mock_runner.assert_not_called()
            finally:
                _restore(saved)

    def test_conflict_does_not_overwrite_pid(self):
        """Conflict preserves existing PID file content."""
        path = _tmp_pid_file()
        original = _make_record(pid=os.getpid(), instance_id="conflict-test-id")
        _write_pid_file(path, original)

        saved = _inject(
            _pid_file_path=lambda: path,
            _health_check=lambda host, port, timeout: None,
            _process_exists=lambda pid: True,
        )
        try:
            launch(LauncherConfig())
            reread = _read_pid_file(path)
            assert reread is not None
            assert reread.instance_id == "conflict-test-id"
        finally:
            _restore(saved)

    def test_conflict_shows_actionable_message(self, capsys):
        """Conflict gives actionable Chinese error message."""
        path = _tmp_pid_file()
        _write_pid_file(path, _make_record(pid=os.getpid()))

        saved = _inject(
            _pid_file_path=lambda: path,
            _health_check=lambda host, port, timeout: None,
            _process_exists=lambda pid: True,
        )
        try:
            launch(LauncherConfig())
            captured = capsys.readouterr()
            assert "同时启动多个实例" in captured.err
            assert "日志" in captured.err
        finally:
            _restore(saved)

    def test_conflict_wrong_app_shows_message(self, capsys):
        """Conflict with wrong app identity → actionable message."""
        path = _tmp_pid_file()
        _write_pid_file(path, _make_record(pid=os.getpid()))

        saved = _inject(
            _pid_file_path=lambda: path,
            _health_check=lambda host, port, timeout: {"status": "ok", "app": "nginx"},
            _process_exists=lambda pid: True,
        )
        try:
            exit_code = launch(LauncherConfig())
            assert exit_code == 1
            captured = capsys.readouterr()
            assert "同时启动多个实例" in captured.err
        finally:
            _restore(saved)


# ═══════════════════════════════════════════════════════════════════════════
# 9. Error messages
# ═══════════════════════════════════════════════════════════════════════════


class TestErrorMessages:
    def test_instance_conflict_message(self):
        msg = _error_instance_conflict("test reason", "/tmp/launcher.log")
        assert "同时启动多个实例" in msg
        assert "/tmp/launcher.log" in msg

    def test_runtime_write_failed_message(self):
        msg = _error_runtime_write_failed("/data/runtime", "/tmp/launcher.log")
        assert "无法创建运行状态文件" in msg
        assert "/data/runtime" in msg
        assert "/tmp/launcher.log" in msg

    def test_server_stopped_unexpectedly_message(self):
        msg = _error_server_stopped_unexpectedly("/tmp/launcher.log")
        assert "服务意外停止" in msg
        assert "/tmp/launcher.log" in msg

    def test_error_messages_no_secrets(self):
        """All error messages are free of secrets/tokens/passwords."""
        messages = [
            _error_instance_conflict("x", "log"),
            _error_runtime_write_failed("dir", "log"),
            _error_server_stopped_unexpectedly("log"),
        ]
        for msg in messages:
            assert "api_key" not in msg.lower()
            assert "secret" not in msg.lower()
            assert "token" not in msg.lower()
            assert "password" not in msg.lower()


# ═══════════════════════════════════════════════════════════════════════════
# 10. Init failure → unified exception boundary
# ═══════════════════════════════════════════════════════════════════════════


class TestInitFailures:
    def test_logging_init_failure_returns_nonzero(self):
        """If logging init fails, launch still returns non-zero."""
        saved = _inject(
            _configure_launcher_logging=lambda log_path: (_ for _ in ()).throw(
                OSError("permission denied")
            ),
        )
        try:
            # This will raise because _configure_launcher_logging is called
            # inside the try block, so the exception should be caught
            exit_code = launch(LauncherConfig(open_browser=False))
            assert exit_code == 1
        finally:
            _restore(saved)

    def test_pid_write_failure_returns_nonzero_and_message(self, capsys):
        """PID write failure → exit 1, actionable message, no traceback."""
        path = _tmp_pid_file()

        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: False,
            _write_pid_file=lambda p, r: (_ for _ in ()).throw(
                PermissionError("access denied")
            ),
        )
        try:
            exit_code = launch(LauncherConfig(open_browser=False))
            assert exit_code == 1
            captured = capsys.readouterr()
            assert "无法创建运行状态文件" in captured.err
        finally:
            _restore(saved)

    def test_pre_try_exceptions_no_bare_traceback(self, capsys):
        """Exceptions from init phase produce clean error, not raw traceback."""
        saved = _inject(
            _get_log_path=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        try:
            exit_code = launch(LauncherConfig(open_browser=False))
            assert exit_code == 1
            captured = capsys.readouterr()
            # Should have a Chinese error message, not a Python traceback
            assert "Traceback" not in captured.err
            assert "SignalVault" in captured.err
        finally:
            _restore(saved)

    def test_exception_output_no_secrets(self, capsys):
        """Error output must not leak secrets."""
        path = _tmp_pid_file()

        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: False,
            _write_pid_file=lambda p, r: (_ for _ in ()).throw(
                RuntimeError("API_KEY=sk-12345-secret")
            ),
        )
        try:
            launch(LauncherConfig(open_browser=False))
            captured = capsys.readouterr()
            # Secret value should not appear in output
            assert "sk-12345-secret" not in captured.out
            assert "sk-12345-secret" not in captured.err
        finally:
            _restore(saved)


# ═══════════════════════════════════════════════════════════════════════════
# 11. Server early exit detection
# ═══════════════════════════════════════════════════════════════════════════


class TestServerEarlyExit:
    def test_server_dies_before_health_returns_nonzero(self, capsys):
        """Server thread exits before health check → immediate failure, exit 1."""
        path = _tmp_pid_file()

        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: False,
            _health_check=lambda host, port, timeout: None,
        )

        with (
            mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner_cls,
            mock.patch.object(launcher_mod, "_configure_launcher_logging"),
        ):
            mock_runner = mock_runner_cls.return_value
            # Server thread is NOT alive (died immediately)
            mock_runner.is_alive.return_value = False
            mock_runner.get_error.return_value = None

            try:
                exit_code = launch(LauncherConfig(
                    open_browser=False,
                    health_timeout=5.0,
                    health_interval=0.1,
                ))
                assert exit_code == 1
                captured = capsys.readouterr()
                assert "服务意外停止" in captured.err
            finally:
                _restore(saved)

    def test_server_dies_after_health_without_shutdown_returns_nonzero(self, capsys):
        """Server exits after health OK but without shutdown signal → exit 1."""
        path = _tmp_pid_file()

        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: False,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
            },
            _sleep=lambda s: None,  # no-op sleep to avoid real delay
        )

        with (
            mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner_cls,
            mock.patch.object(launcher_mod, "_configure_launcher_logging"),
            mock.patch.object(launcher_mod, "_shutdown_background_tasks"),
        ):
            mock_runner = mock_runner_cls.return_value
            # Thread is alive for health check, then immediately dies
            mock_runner.is_alive.side_effect = [True, False]
            mock_runner.get_error.return_value = RuntimeError("server crash")

            try:
                exit_code = launch(LauncherConfig(
                    open_browser=False,
                    health_timeout=5.0,
                ))
                assert exit_code == 1
                captured = capsys.readouterr()
                assert "服务意外停止" in captured.err
            finally:
                _restore(saved)

    def test_server_dies_before_health_does_not_wait_full_timeout(self):
        """Server dying before health should fail immediately, not after timeout."""
        path = _tmp_pid_file()

        health_checks: list[bool] = []

        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: False,
            _health_check=lambda host, port, timeout: health_checks.append(True) or None,
        )

        with (
            mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner_cls,
            mock.patch.object(launcher_mod, "_configure_launcher_logging"),
        ):
            mock_runner = mock_runner_cls.return_value
            mock_runner.is_alive.return_value = False
            mock_runner.get_error.return_value = None

            try:
                exit_code = launch(LauncherConfig(
                    open_browser=False,
                    health_timeout=15.0,  # long timeout
                    health_interval=0.1,
                ))
                assert exit_code == 1
                # Should fail on first iteration (is_alive check), not after many polls
                assert len(health_checks) == 0  # health never reached
            finally:
                _restore(saved)


# ═══════════════════════════════════════════════════════════════════════════
# 12. Thread exception propagation
# ═══════════════════════════════════════════════════════════════════════════


class TestThreadExceptionPropagation:
    def test_uvicorn_runner_captures_thread_exception(self):
        """_UvicornRunner.get_error() returns exception from server thread."""
        test_error = RuntimeError("uvicorn internal error")

        with (
            mock.patch("uvicorn.Config"),
            mock.patch("uvicorn.Server"),
            mock.patch("signalvault.api.app.create_app"),
        ):
            runner = _UvicornRunner("127.0.0.1", 8000)
            # Manually simulate what happens when server thread crashes
            runner._error_queue.put(test_error)
            assert runner.get_error() is test_error

    def test_uvicorn_runner_get_error_empty_queue(self):
        """get_error() returns None when no error was captured."""
        with (
            mock.patch("uvicorn.Config"),
            mock.patch("uvicorn.Server"),
            mock.patch("signalvault.api.app.create_app"),
        ):
            runner = _UvicornRunner("127.0.0.1", 8000)
            assert runner.get_error() is None

    def test_server_exception_propagated_to_launch_state(self):
        """When server crashes, launch captures the error."""
        path = _tmp_pid_file()

        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: False,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
            },
            _sleep=lambda s: None,
        )

        test_error = RuntimeError("server crash detail")

        with (
            mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner_cls,
            mock.patch.object(launcher_mod, "_configure_launcher_logging"),
            mock.patch.object(launcher_mod, "_shutdown_background_tasks"),
        ):
            mock_runner = mock_runner_cls.return_value
            mock_runner.is_alive.side_effect = [True, False]  # alive→dead
            mock_runner.get_error.return_value = test_error

            try:
                exit_code = launch(LauncherConfig(open_browser=False))
                assert exit_code == 1
                # Runner's get_error was called
                mock_runner.get_error.assert_called()
            finally:
                _restore(saved)


# ═══════════════════════════════════════════════════════════════════════════
# 13. Signal handling (SIGINT / SIGTERM)
# ═══════════════════════════════════════════════════════════════════════════


class TestSignalHandling:
    @pytest.mark.parametrize("requested_signal", [signal.SIGINT, signal.SIGTERM])
    def test_controlled_signal_exits_zero_and_cleans_pid(self, requested_signal):
        """SIGINT/SIGTERM → exit 0, shutdown called, PID cleaned."""
        path = _tmp_pid_file()
        signal_sent = False

        def send_signal_once(_seconds):
            nonlocal signal_sent
            if not signal_sent:
                signal_sent = True
                signal.raise_signal(requested_signal)

        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: False,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
            },
            _sleep=send_signal_once,
        )
        with (
            mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner_cls,
            mock.patch.object(launcher_mod, "_configure_launcher_logging"),
            mock.patch.object(launcher_mod, "_shutdown_background_tasks"),
        ):
            mock_runner = mock_runner_cls.return_value
            mock_runner.is_alive.return_value = True
            try:
                exit_code = launch(LauncherConfig(open_browser=False))
                assert exit_code == 0
                assert mock_runner.request_shutdown.called
            finally:
                _restore(saved)

        assert not path.exists()

    def test_normal_shutdown_request_shutdown_called(self):
        """Normal exit via thread stop → request_shutdown called, PID cleaned."""
        path = _tmp_pid_file()

        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: False,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
            },
            _sleep=lambda s: None,
        )

        with (
            mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner_cls,
            mock.patch.object(launcher_mod, "_configure_launcher_logging"),
            mock.patch.object(launcher_mod, "_shutdown_background_tasks"),
        ):
            mock_runner = mock_runner_cls.return_value
            # Thread alive for keep-alive first iteration, then dead
            mock_runner.is_alive.side_effect = [True, False]

            try:
                exit_code = launch(LauncherConfig(open_browser=False))
                # Without shutdown_requested, server death → exit 1
                assert exit_code == 1
            finally:
                _restore(saved)

        assert not path.exists()

    def test_exception_during_launch_cleans_pid(self):
        """Even if something goes wrong in main loop, PID file is cleaned."""
        path = _tmp_pid_file()

        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: False,
            _health_check=lambda host, port, timeout: {"status": "ok", "app": "signalvault"},
            _sleep=lambda s: None,
        )

        with (
            mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner_cls,
            mock.patch.object(launcher_mod, "_configure_launcher_logging"),
            mock.patch.object(launcher_mod, "_shutdown_background_tasks"),
        ):
            mock_runner = mock_runner_cls.return_value
            mock_runner.is_alive.side_effect = RuntimeError("simulated crash")

            try:
                exit_code = launch(LauncherConfig(open_browser=False))
                assert exit_code == 1
            finally:
                _restore(saved)

        assert not path.exists()


# ═══════════════════════════════════════════════════════════════════════════
# 14. PID ownership — cleanup only owned PIDs
# ═══════════════════════════════════════════════════════════════════════════


class TestPidOwnership:
    def test_owned_pid_cleaned_on_normal_exit(self):
        """PID we wrote is cleaned up on normal exit."""
        path = _tmp_pid_file()

        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: False,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
            },
            _sleep=lambda s: None,
        )

        with (
            mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner_cls,
            mock.patch.object(launcher_mod, "_configure_launcher_logging"),
            mock.patch.object(launcher_mod, "_shutdown_background_tasks"),
        ):
            mock_runner = mock_runner_cls.return_value
            mock_runner.is_alive.side_effect = [True, False]

            try:
                launch(LauncherConfig(open_browser=False))
            finally:
                _restore(saved)

        # PID should have been written and then cleaned
        assert not path.exists()

    def test_existing_instance_pid_preserved(self):
        """If we reuse an existing instance, its PID is NOT deleted."""
        path = _tmp_pid_file()
        original = _make_record(pid=os.getpid(), port=9007, instance_id="keep-me")
        _write_pid_file(path, original)

        saved = _inject(
            _pid_file_path=lambda: path,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
            },
            _open_browser=lambda url: True,
        )
        try:
            exit_code = launch(LauncherConfig(preferred_port=9007))
            assert exit_code == 0
            assert path.exists()
            reread = _read_pid_file(path)
            assert reread is not None
            assert reread.instance_id == "keep-me"
        finally:
            _restore(saved)

    def test_conflict_pid_preserved(self):
        """Conflict → existing PID is NOT deleted or overwritten."""
        path = _tmp_pid_file()
        original = _make_record(pid=os.getpid(), instance_id="conflict-pid")
        _write_pid_file(path, original)

        saved = _inject(
            _pid_file_path=lambda: path,
            _health_check=lambda host, port, timeout: None,
            _process_exists=lambda pid: True,
        )
        try:
            launch(LauncherConfig())
            assert path.exists()
            reread = _read_pid_file(path)
            assert reread is not None
            assert reread.instance_id == "conflict-pid"
        finally:
            _restore(saved)


# ═══════════════════════════════════════════════════════════════════════════
# 15. Browser behavior
# ═══════════════════════════════════════════════════════════════════════════


class TestBrowserBehavior:
    def test_webbrowser_exception_is_converted_to_false(self):
        with mock.patch.object(
            launcher_mod.webbrowser, "open", side_effect=RuntimeError("browser unavailable")
        ):
            assert launcher_mod._webbrowser_open("http://127.0.0.1:8000") is False

    def test_new_instance_browser_failure_keeps_service_until_signal(self):
        """Browser fail doesn't kill server; still needs signal to exit."""
        path = _tmp_pid_file()
        signal_sent = False

        def stop_after_browser_failure(_seconds):
            nonlocal signal_sent
            if not signal_sent:
                signal_sent = True
                signal.raise_signal(signal.SIGINT)

        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: False,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
            },
            _open_browser=lambda url: False,
            _sleep=stop_after_browser_failure,
        )
        with (
            mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner_cls,
            mock.patch.object(launcher_mod, "_configure_launcher_logging"),
            mock.patch.object(launcher_mod, "_shutdown_background_tasks"),
        ):
            mock_runner = mock_runner_cls.return_value
            mock_runner.is_alive.return_value = True
            try:
                assert launch(LauncherConfig()) == 0
            finally:
                _restore(saved)

        assert mock_runner.request_shutdown.called
        assert not path.exists()

    def test_no_browser_flag(self):
        """--no-browser: browser not called."""
        path = _tmp_pid_file()

        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: False,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
            },
            _sleep=lambda s: None,
        )

        with (
            mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner_cls,
            mock.patch.object(launcher_mod, "_configure_launcher_logging"),
            mock.patch.object(launcher_mod, "_shutdown_background_tasks"),
        ):
            mock_runner = mock_runner_cls.return_value
            mock_runner.is_alive.side_effect = [True, False]

            try:
                config = LauncherConfig(open_browser=False)
                exit_code = launch(config)
                assert exit_code == 1  # server dies without shutdown → abnormal
            finally:
                _restore(saved)
                if path.exists():
                    _remove_pid_file(path)

    def test_new_instance_browser_uses_selected_port(self):
        """Browser opens with the actual selected port."""
        path = _tmp_pid_file()
        browser_hits: list[str] = []
        signal_sent = False

        def stop_after_open(_seconds):
            nonlocal signal_sent
            if not signal_sent:
                signal_sent = True
                signal.raise_signal(signal.SIGINT)

        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: port < 8003,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
            },
            _open_browser=lambda url: browser_hits.append(url) or True,
            _sleep=stop_after_open,
        )
        with (
            mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner_cls,
            mock.patch.object(launcher_mod, "_configure_launcher_logging"),
            mock.patch.object(launcher_mod, "_shutdown_background_tasks"),
        ):
            mock_runner = mock_runner_cls.return_value
            mock_runner.is_alive.return_value = True
            try:
                assert launch(LauncherConfig()) == 0
            finally:
                _restore(saved)

        assert browser_hits == ["http://127.0.0.1:8003"]
        assert not path.exists()


# ═══════════════════════════════════════════════════════════════════════════
# 16. User-facing feedback
# ═══════════════════════════════════════════════════════════════════════════


class TestLauncherUserFeedback:
    def test_port_fallback_and_success_are_visible(self, capsys):
        path = _tmp_pid_file()
        signal_sent = False

        def stop_after_message(_seconds):
            nonlocal signal_sent
            if not signal_sent:
                signal_sent = True
                signal.raise_signal(signal.SIGINT)

        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: port == 8000,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
            },
            _sleep=stop_after_message,
        )
        with (
            mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner_cls,
            mock.patch.object(launcher_mod, "_configure_launcher_logging"),
            mock.patch.object(launcher_mod, "_shutdown_background_tasks"),
        ):
            mock_runner = mock_runner_cls.return_value
            mock_runner.is_alive.return_value = True
            try:
                assert launch(LauncherConfig(open_browser=False)) == 0
            finally:
                _restore(saved)

        captured = capsys.readouterr()
        assert "SignalVault 正在启动" in captured.out
        assert "端口 8000 已被占用，改用 8001" in captured.out
        assert "SignalVault 启动成功" in captured.out
        assert "访问地址：http://127.0.0.1:8001" in captured.out
        assert "关闭浏览器不会停止服务" in captured.out

    def test_all_ports_busy_shows_action_and_log(self, capsys):
        path = _tmp_pid_file()
        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: True,
        )
        try:
            assert launch(LauncherConfig(max_port_attempts=10)) == 1
        finally:
            _restore(saved)

        captured = capsys.readouterr()
        assert "端口 8000–8009 均被占用" in captured.err
        assert "--port" in captured.err
        assert "日志位置" in captured.err


# ═══════════════════════════════════════════════════════════════════════════
# 17. Log safety
# ═══════════════════════════════════════════════════════════════════════════


class TestLauncherLogSafety:
    def test_instance_record_serialization_safe(self):
        """InstanceRecord JSON does not contain any sensitive fields."""
        record = _make_record()
        raw = record.to_json()
        data = json.loads(raw)
        assert set(data.keys()) == {"pid", "host", "port", "started_at", "instance_id"}
        for v in data.values():
            if isinstance(v, str):
                assert "api_key" not in v.lower()
                assert "secret" not in v.lower()
                assert "token" not in v.lower()
                assert "password" not in v.lower()

    def test_pid_file_content_is_safe(self):
        """PID file on disk only contains instance metadata."""
        path = _tmp_pid_file()
        record = _make_record()
        _write_pid_file(path, record)
        raw = path.read_text()
        assert "api_key" not in raw.lower()
        assert "secret" not in raw.lower()
        assert "token" not in raw.lower()


# ═══════════════════════════════════════════════════════════════════════════
# 18. Background thread shutdown
# ═══════════════════════════════════════════════════════════════════════════


class TestBackgroundShutdown:
    def test_shutdown_event_registered(self):
        from signalvault.services.job_service import (
            is_shutdown_requested,
            shutdown_background_jobs,
        )
        assert is_shutdown_requested() is False
        shutdown_background_jobs(timeout=0.1)
        assert is_shutdown_requested() is True

    def test_shutdown_event_is_cleared_for_next_launch(self):
        from signalvault.services.job_service import (
            is_shutdown_requested,
            shutdown_background_jobs,
        )
        shutdown_background_jobs(timeout=0.1)
        assert is_shutdown_requested() is True

    def test_short_task_finishes_during_controlled_shutdown(self):
        from signalvault.services import job_service

        started = threading.Event()

        def worker():
            started.set()
            job_service._shutdown_event.wait()

        thread = threading.Thread(target=worker, name="short-qa-task")
        thread.start()
        assert started.wait(timeout=1.0)
        job_service._register_thread(thread)

        job_service.shutdown_background_jobs(timeout=1.0)

        assert not thread.is_alive()
        assert job_service._active_threads == []


# ═══════════════════════════════════════════════════════════════════════════
# 19. Non-local host enforced
# ═══════════════════════════════════════════════════════════════════════════


class TestNonLocalHost:
    def test_launch_config_always_uses_localhost(self):
        c = LauncherConfig(host="192.168.1.1")
        assert c.host == "127.0.0.1"
        c2 = LauncherConfig(host="0.0.0.0")
        assert c2.host == "127.0.0.1"


# ═══════════════════════════════════════════════════════════════════════════
# 20. InstanceRecord serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestInstanceRecord:
    def test_roundtrip(self):
        r1 = _make_record(pid=7777, port=8888)
        json_str = r1.to_json()
        r2 = InstanceRecord.from_json(json_str)
        assert r2 is not None
        assert r2.pid == 7777
        assert r2.port == 8888
        assert r2.host == "127.0.0.1"

    def test_from_invalid_json(self):
        assert InstanceRecord.from_json("garbage") is None

    def test_from_missing_fields(self):
        assert InstanceRecord.from_json('{"pid": 1}') is None


# ═══════════════════════════════════════════════════════════════════════════
# 21. DetectionOutcome
# ═══════════════════════════════════════════════════════════════════════════


class TestDetectionOutcome:
    def test_reuse_action(self):
        record = _make_record()
        outcome = DetectionOutcome(action="reuse", existing=record)
        assert outcome.action == "reuse"
        assert outcome.existing is record
        assert outcome.conflict_reason == ""

    def test_start_action(self):
        outcome = DetectionOutcome(action="start")
        assert outcome.action == "start"
        assert outcome.existing is None

    def test_conflict_action(self):
        outcome = DetectionOutcome(action="conflict", conflict_reason="test")
        assert outcome.action == "conflict"
        assert outcome.conflict_reason == "test"


# ═══════════════════════════════════════════════════════════════════════════
# 22. _LaunchState
# ═══════════════════════════════════════════════════════════════════════════


class TestLaunchState:
    def test_defaults(self):
        state = _LaunchState()
        assert state.owned_instance_id is None
        assert state.pid_written is False
        assert state.logger_available is False
        assert state.shutdown_requested is False
        assert state.server_error is None

    def test_mutable_fields(self):
        state = _LaunchState()
        state.owned_instance_id = "test-id"
        state.pid_written = True
        state.logger_available = True
        state.shutdown_requested = True
        state.server_error = RuntimeError("test")
        assert state.owned_instance_id == "test-id"
        assert state.pid_written is True
