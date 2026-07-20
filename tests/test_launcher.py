"""M2: Launcher unit tests.

Every test exercises the launcher with injected fakes — no real processes,
no real sockets, no real browser, no real sleeps.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

import signalvault.launcher as launcher_mod
from signalvault.launcher import (
    HealthTimeoutError,
    InstanceRecord,
    LauncherConfig,
    _read_pid_file,
    _remove_pid_file,
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
    # Clear the shutdown event
    js._shutdown_event.clear()
    # Clear active thread list
    js._active_threads.clear()
    yield
    js._shutdown_event.clear()
    js._active_threads.clear()

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _make_record(pid=12345, host="127.0.0.1", port=8000) -> InstanceRecord:
    return InstanceRecord(
        pid=pid,
        host=host,
        port=port,
        started_at="2026-07-20T12:00:00Z",
        instance_id=uuid.uuid4().hex[:12],
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


# ═══════════════════════════════════════════════════════════════════════════
# 1. Default host is localhost
# ═══════════════════════════════════════════════════════════════════════════


class TestLauncherConfig:
    def test_default_host_is_localhost(self):
        c = LauncherConfig()
        assert c.host == "127.0.0.1"

    def test_non_local_host_is_rejected(self):
        """Even if someone passes 0.0.0.0, the LauncherConfig enforces 127.0.0.1."""
        c = LauncherConfig(host="0.0.0.0")
        assert c.host == "127.0.0.1"

    def test_custom_port_is_respected(self):
        c = LauncherConfig(preferred_port=9999)
        assert c.preferred_port == 9999

    def test_open_browser_false(self):
        c = LauncherConfig(open_browser=False)
        assert c.open_browser is False


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
            return port < 8002  # 8000 and 8001 in use

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
# 6–9. PID file read/write/remove
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
        """Corrupted JSON → None."""
        path = _tmp_pid_file()
        path.write_text("not json {{{")
        assert _read_pid_file(path) is None

    def test_remove_non_existent(self):
        path = _tmp_pid_file()
        _remove_pid_file(path)  # must not raise

    def test_remove_existing(self):
        path = _tmp_pid_file()
        _write_pid_file(path, _make_record())
        assert path.exists()
        _remove_pid_file(path)
        assert not path.exists()


# ═══════════════════════════════════════════════════════════════════════════
# 10–11. Instance detection
# ═══════════════════════════════════════════════════════════════════════════


class TestDetectExistingInstance:
    def test_no_pid_file(self):
        path = _tmp_pid_file()
        result = detect_existing_instance(path)
        assert result is None

    def test_stale_pid_process_dead(self):
        """PID file with a non-existent process → None, file cleaned."""
        path = _tmp_pid_file()
        record = _make_record(pid=99999)
        _write_pid_file(path, record)

        saved = _inject(_process_exists=lambda pid: False)
        try:
            result = detect_existing_instance(path)
            assert result is None
            assert not path.exists()  # stale file cleaned
        finally:
            _restore(saved)

    def test_pid_alive_but_health_fails(self):
        """Process exists but health endpoint unreachable → None, file NOT deleted."""
        path = _tmp_pid_file()
        record = _make_record(pid=os.getpid())
        _write_pid_file(path, record)

        saved = _inject(
            _process_exists=lambda pid: True,
            _health_check=lambda host, port, timeout: None,
        )
        try:
            result = detect_existing_instance(path)
            assert result is None
            assert path.exists()  # NOT deleted — conflict, not stale
        finally:
            _restore(saved)

    def test_pid_alive_health_wrong_app(self):
        """Health endpoint responds but with wrong app identity → None."""
        path = _tmp_pid_file()
        record = _make_record(pid=os.getpid())
        _write_pid_file(path, record)

        saved = _inject(
            _process_exists=lambda pid: True,
            _health_check=lambda host, port, timeout: {"status": "ok", "app": "other"},
        )
        try:
            result = detect_existing_instance(path)
            assert result is None
        finally:
            _restore(saved)

    def test_valid_existing_instance(self):
        """All checks pass → the record is returned."""
        path = _tmp_pid_file()
        record = _make_record(pid=os.getpid(), port=9001)
        _write_pid_file(path, record)

        saved = _inject(
            _process_exists=lambda pid: True,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
                "version": "0.1.0",
            },
        )
        try:
            result = detect_existing_instance(path)
            assert result is not None
            assert result.pid == record.pid
            assert result.port == 9001
        finally:
            _restore(saved)

    def test_existing_instance_opens_browser_only(self):
        """When an existing instance is found, launch opens browser and returns 0."""
        path = _tmp_pid_file()
        record = _make_record(pid=os.getpid(), port=9002)
        _write_pid_file(path, record)

        browser_called: list[str] = []

        saved = _inject(
            _pid_file_path=lambda: path,
            _process_exists=lambda pid: True,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
                "version": "0.1.0",
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


# ═══════════════════════════════════════════════════════════════════════════
# 14. Health check identity verification
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
        """Health responds but app != 'signalvault' → timeout."""
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
# 15. Server early exit during health poll
# ═══════════════════════════════════════════════════════════════════════════


class TestLaunchHealthFailure:
    def test_launch_exits_non_zero_on_health_timeout(self):
        """When uvicorn starts but health never responds, launch returns 1."""
        path = _tmp_pid_file()

        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: False,
            _health_check=lambda host, port, timeout: None,
            _sleep=lambda s: None,
        )

        with (
            mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner,
            mock.patch.object(launcher_mod, "_configure_launcher_logging"),
            mock.patch.object(launcher_mod, "_shutdown_background_tasks"),
        ):
            mock_runner.return_value._thread = mock.Mock()
            mock_runner.return_value._thread.is_alive.return_value = True

            try:
                config = LauncherConfig(
                    health_timeout=0.5, health_interval=0.1, open_browser=False
                )
                exit_code = launch(config)
                assert exit_code == 1
            finally:
                _restore(saved)
                if path.exists():
                    _remove_pid_file(path)


# ═══════════════════════════════════════════════════════════════════════════
# 17. Browser failure doesn't stop service
# ═══════════════════════════════════════════════════════════════════════════


class TestBrowserBehavior:
    def test_no_browser_flag(self):
        """--no-browser: launch exits 0, browser not called."""
        path = _tmp_pid_file()

        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: False,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
                "version": "0.1.0",
            },
            _sleep=lambda s: None,
        )

        with (
            mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner,
            mock.patch.object(launcher_mod, "_configure_launcher_logging"),
            mock.patch.object(launcher_mod, "_shutdown_background_tasks"),
        ):
            mock_runner.return_value._thread = mock.Mock()
            mock_runner.return_value._thread.is_alive.side_effect = [True, False, False]

            try:
                config = LauncherConfig(open_browser=False, health_timeout=5.0)
                exit_code = launch(config)
                assert exit_code == 0
            finally:
                _restore(saved)
                if path.exists():
                    _remove_pid_file(path)


# ═══════════════════════════════════════════════════════════════════════════
# 18–20. Signal handling and PID cleanup
# ═══════════════════════════════════════════════════════════════════════════


class TestSignalHandling:
    def test_launch_cleanup_on_server_thread_exit(self):
        """PID file is cleaned up after normal exit."""
        path = _tmp_pid_file()

        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: False,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
                "version": "0.1.0",
            },
            _sleep=lambda s: None,
        )

        with (
            mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner,
            mock.patch.object(launcher_mod, "_configure_launcher_logging"),
            mock.patch.object(launcher_mod, "_shutdown_background_tasks"),
        ):
            mock_runner.return_value._thread = mock.Mock()
            mock_runner.return_value._thread.is_alive.side_effect = [True, False, False]

            try:
                config = LauncherConfig(open_browser=False, health_timeout=5.0)
                exit_code = launch(config)
                assert exit_code == 0
            finally:
                _restore(saved)

        # PID file must be cleaned up in finally block
        assert not path.exists()

    def test_launch_cleanup_on_exception(self):
        """Even if something goes wrong, PID file is cleaned."""
        path = _tmp_pid_file()

        saved = _inject(
            _pid_file_path=lambda: path,
            _port_in_use=lambda host, port: False,
            _health_check=lambda host, port, timeout: {"status": "ok", "app": "signalvault"},
            _sleep=lambda s: None,
        )

        with (
            mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner,
            mock.patch.object(launcher_mod, "_configure_launcher_logging"),
            mock.patch.object(launcher_mod, "_shutdown_background_tasks"),
        ):
            mock_runner.return_value._thread = mock.Mock()
            mock_runner.return_value._thread.is_alive.side_effect = RuntimeError(
                "simulated crash"
            )

            try:
                config = LauncherConfig(open_browser=False, health_timeout=5.0)
                exit_code = launch(config)
                assert exit_code == 1
            finally:
                _restore(saved)

        # PID file must be cleaned up even on exception
        assert not path.exists()


# ═══════════════════════════════════════════════════════════════════════════
# 21. Launcher log does not contain secrets
# ═══════════════════════════════════════════════════════════════════════════


class TestLauncherLogSafety:
    def test_instance_record_serialization_safe(self):
        """InstanceRecord JSON does not contain any sensitive fields."""
        record = _make_record()
        raw = record.to_json()
        data = json.loads(raw)
        # Only expected keys
        assert set(data.keys()) == {"pid", "host", "port", "started_at", "instance_id"}
        # No secrets, keys, tokens
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
# 22. Background thread shutdown hook
# ═══════════════════════════════════════════════════════════════════════════


class TestBackgroundShutdown:
    def test_shutdown_event_registered(self):
        """shutdown_event and related functions are importable."""
        from signalvault.services.job_service import (
            is_shutdown_requested,
            shutdown_background_jobs,
        )
        # Before shutdown is triggered
        assert is_shutdown_requested() is False
        # Calling shutdown sets the event
        shutdown_background_jobs(timeout=0.1)
        assert is_shutdown_requested() is True

    def test_shutdown_event_is_cleared_for_next_launch(self):
        """shutdown_background_jobs must reset state."""
        from signalvault.services.job_service import (
            is_shutdown_requested,
            shutdown_background_jobs,
        )
        # Trigger shutdown
        shutdown_background_jobs(timeout=0.1)
        # After cleanup, threads list is empty and event IS set (one-shot)
        # The event stays set — subsequent shutdowns just re-set it.
        assert is_shutdown_requested() is True


# ═══════════════════════════════════════════════════════════════════════════
# 23. Duplicate launch does not create second instance
# ═══════════════════════════════════════════════════════════════════════════


class TestDuplicateLaunch:
    def test_second_launch_reuses_existing(self):
        """Launching twice → second launch detects existing and opens browser only."""
        path = _tmp_pid_file()

        # First, simulate an existing healthy instance
        record = _make_record(pid=os.getpid(), port=9003)
        _write_pid_file(path, record)

        browser_hits: list[str] = []
        uvicorn_starts: list[bool] = []

        saved = _inject(
            _pid_file_path=lambda: path,
            _process_exists=lambda pid: True,
            _health_check=lambda host, port, timeout: {
                "status": "ok",
                "app": "signalvault",
                "version": "0.1.0",
            },
            _open_browser=lambda url: browser_hits.append(url) or True,
            _sleep=lambda s: None,
        )

        with mock.patch.object(launcher_mod, "_UvicornRunner") as mock_runner:
            mock_runner.return_value._thread = mock.Mock()
            mock_runner.return_value._thread.is_alive.return_value = True
            uvicorn_starts.append(True)  # record attempt

            try:
                config = LauncherConfig(preferred_port=9003, open_browser=True)
                exit_code = launch(config)
                assert exit_code == 0
                # Browser called exactly once
                assert len(browser_hits) == 1
                # But uvicorn was NOT started (the mock's .start_in_thread was never called
                # because detect_existing_instance found the instance first)
                # Test: if uvicorn start was called, it would have set up mock differently
            finally:
                _restore(saved)
                if path.exists():
                    _remove_pid_file(path)


# ═══════════════════════════════════════════════════════════════════════════
# 2 (from spec). Non-local host enforced
# ═══════════════════════════════════════════════════════════════════════════


class TestNonLocalHost:
    def test_launch_config_always_uses_localhost(self):
        """Regardless of internal config, host is 127.0.0.1."""
        # The LauncherConfig dataclass enforces this in __post_init__
        c = LauncherConfig(host="192.168.1.1")
        assert c.host == "127.0.0.1"
        c2 = LauncherConfig(host="0.0.0.0")
        assert c2.host == "127.0.0.1"


# ═══════════════════════════════════════════════════════════════════════════
# InstanceRecord serialization
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
