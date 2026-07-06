"""P2-F.3: Signal Tracking Schema & Manual Update Workflow tests."""

from pathlib import Path


def _create_test_signal(vault: Path, card_id: str, status: str = "open",
                         signal_text: str = "Test signal to watch",
                         source_reports: str = "report1") -> Path:
    signals_dir = vault / "07_Signals"
    signals_dir.mkdir(parents=True, exist_ok=True)
    card = signals_dir / f"{card_id}.md"
    card.write_text(f"""---
type: signal
status: {status}
signal: "{signal_text}"
source_reports:
  - "{source_reports}"
suggested_check_frequency: monthly
created_at: "2026-05-30T00:00:00"
updated_at: "2026-05-30T00:00:00"
---

# Signal: {signal_text}

## What to Watch

{signal_text}

## Source

- [[{source_reports}]]

## Updates
""", encoding="utf-8")
    return card


def test_update_tracking_status(tmp_path):
    """Test update_signal_tracking sets tracking_status."""
    from signalvault.claim_signal.review import get_signal, update_signal_tracking

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001")

    ok = update_signal_tracking(vault, "signal_test_001", tracking_status="active", tracking_method="manual")
    assert ok

    content = get_signal(vault, "signal_test_001")
    assert "tracking_status: active" in content


def test_update_tracking_method(tmp_path):
    """Test update_signal_tracking sets tracking_method."""
    from signalvault.claim_signal.review import get_signal, update_signal_tracking

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001")

    ok = update_signal_tracking(vault, "signal_test_001", tracking_method="news")
    assert ok
    content = get_signal(vault, "signal_test_001")
    assert "tracking_method: news" in content


def test_update_tracking_query(tmp_path):
    """Test update_signal_tracking sets tracking_query."""
    from signalvault.claim_signal.review import get_signal, update_signal_tracking

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001")

    ok = update_signal_tracking(vault, "signal_test_001", tracking_query="test query")
    assert ok
    content = get_signal(vault, "signal_test_001")
    assert 'tracking_query: "test query"' in content


def test_invalid_tracking_status_rejected(tmp_path):
    """Test invalid tracking_status is rejected."""
    from signalvault.claim_signal.review import update_signal_tracking

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001")
    ok = update_signal_tracking(vault, "signal_test_001", tracking_status="invalid")
    assert not ok


def test_invalid_tracking_method_rejected(tmp_path):
    """Test invalid tracking_method is rejected."""
    from signalvault.claim_signal.review import update_signal_tracking

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001")
    ok = update_signal_tracking(vault, "signal_test_001", tracking_method="bad_method")
    assert not ok


def test_add_update_appends(tmp_path):
    """Test add_signal_update appends to Updates section."""
    from signalvault.claim_signal.review import add_signal_update, get_signal

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001")

    ok = add_signal_update(vault, "signal_test_001", note="test update note", source="TestBlog")
    assert ok

    content = get_signal(vault, "signal_test_001")
    assert "test update note" in content
    assert "TestBlog" in content


def test_add_update_updates_last_checked(tmp_path):
    """Test add_signal_update sets last_checked_at."""
    from signalvault.claim_signal.review import add_signal_update, get_signal

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001")

    add_signal_update(vault, "signal_test_001", note="checked", checked_at="2026-06-01T00:00:00")
    content = get_signal(vault, "signal_test_001")
    assert "last_checked_at: \"2026-06-01T00:00:00\"" in content


def test_add_update_with_status_change(tmp_path):
    """Test add_signal_update optionally updates status."""
    from signalvault.claim_signal.review import add_signal_update, get_signal

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001", status="open")

    add_signal_update(vault, "signal_test_001", note="resolved via API check", new_status="resolved")
    content = get_signal(vault, "signal_test_001")
    assert "status: resolved" in content
    assert "Status: resolved" in content


def test_tracking_backlog_generated(tmp_path):
    """Test tracking-backlog generates file."""
    from signalvault.claim_signal.review import generate_signal_tracking_backlog

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001", signal_text="Test signal A")

    generate_signal_tracking_backlog(vault)
    assert (vault / "99_System" / "Signal Tracking Backlog.md").exists()


def test_tracking_backlog_sorted(tmp_path):
    """Test tracking backlog sorts by tracking status priority."""
    from signalvault.claim_signal.review import (
        generate_signal_tracking_backlog,
        update_signal_tracking,
    )

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_not_started")
    _create_test_signal(vault, "signal_active")
    update_signal_tracking(vault, "signal_active", tracking_status="active")

    generate_signal_tracking_backlog(vault)
    content = (vault / "99_System" / "Signal Tracking Backlog.md").read_text(encoding="utf-8")
    assert content.find("signal_active") < content.find("signal_not_started")


def test_signal_index_includes_tracking(tmp_path):
    """Test Signal Index includes tracking fields."""
    from signalvault.claim_signal.review import update_signal_tracking

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001")
    update_signal_tracking(vault, "signal_test_001", tracking_status="active", tracking_method="news")

    index = vault / "99_System" / "Signal Index.md"
    assert index.exists()
    content = index.read_text(encoding="utf-8")
    assert "active|news" in content.replace(" ", "")


def test_tracking_log_written(tmp_path):
    """Test update-tracking writes Signal_Tracking_Log.md."""
    from signalvault.claim_signal.review import update_signal_tracking

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001")
    update_signal_tracking(vault, "signal_test_001", tracking_status="active")

    log = vault / "99_System" / "Signal_Tracking_Log.md"
    assert log.exists()
    assert "tracking_updated" in log.read_text(encoding="utf-8")


def test_nonexistent_signal_tracking_error(tmp_path):
    """Test update-tracking on non-existent signal returns False."""
    from signalvault.claim_signal.review import update_signal_tracking

    vault = tmp_path / "vault"
    ok = update_signal_tracking(vault, "nonexistent", tracking_status="active")
    assert not ok


def test_cli_signals_update_tracking(tmp_path):
    """Test CLI signals update-tracking."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001")

    runner = CliRunner()
    result = runner.invoke(app, [
        "signals", "update-tracking", "signal_test_001",
        "--vault", str(vault),
        "--tracking-status", "active",
        "--tracking-method", "news",
        "--tracking-query", "test query",
    ])
    assert result.exit_code == 0


def test_cli_signals_add_update(tmp_path):
    """Test CLI signals add-update."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001")

    runner = CliRunner()
    result = runner.invoke(app, [
        "signals", "add-update", "signal_test_001",
        "--vault", str(vault),
        "--note", "manual check completed",
        "--source", "Wikipedia",
    ])
    assert result.exit_code == 0


def test_cli_signals_tracking_backlog(tmp_path):
    """Test CLI signals tracking-backlog."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001")

    runner = CliRunner()
    result = runner.invoke(app, [
        "signals", "tracking-backlog",
        "--vault", str(vault),
    ])
    assert result.exit_code == 0
    assert (vault / "99_System" / "Signal Tracking Backlog.md").exists()
