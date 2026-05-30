"""P2-F.1: Claim / Signal Review Workflow tests."""

import pytest
from pathlib import Path


def _create_test_claim(vault: Path, card_id: str, status: str = "active",
                        claim_text: str = "Test claim statement",
                        source_reports: str = "report1") -> Path:
    """Helper: create a claim card."""
    claims_dir = vault / "06_Claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    card = claims_dir / f"{card_id}.md"
    card.write_text(f"""---
type: claim
status: {status}
claim: "{claim_text}"
source_reports:
  - "{source_reports}"
evidence_strength: extracted
created_at: "2026-05-30T00:00:00"
updated_at: "2026-05-30T00:00:00"
---

# Claim: {claim_text}

## Statement

{claim_text}

## Evidence

- Source: [[{source_reports}]]

## Related Topics

## Related Companies

## Notes
""", encoding="utf-8")
    return card


def _create_test_signal(vault: Path, card_id: str, status: str = "open",
                         signal_text: str = "Test signal to watch",
                         source_reports: str = "report1") -> Path:
    """Helper: create a signal card."""
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


def test_list_claims(tmp_path):
    """Test listing claims."""
    from podcast_research.claim_signal.review import list_claims

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_test_001", status="active")
    _create_test_claim(vault, "claim_test_002", status="verified")
    _create_test_claim(vault, "claim_test_003", status="challenged")

    results = list_claims(vault)
    assert len(results) == 3


def test_list_claims_status_filter(tmp_path):
    """Test listing claims with status filter."""
    from podcast_research.claim_signal.review import list_claims

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_test_001", status="active")
    _create_test_claim(vault, "claim_test_002", status="verified")

    active = list_claims(vault, status="active")
    assert len(active) == 1
    assert active[0].status == "active"


def test_list_signals(tmp_path):
    """Test listing signals."""
    from podcast_research.claim_signal.review import list_signals

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001", status="open")
    _create_test_signal(vault, "signal_test_002", status="watching")

    results = list_signals(vault)
    assert len(results) == 2


def test_list_signals_status_filter(tmp_path):
    """Test listing signals with status filter."""
    from podcast_research.claim_signal.review import list_signals

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001", status="open")
    _create_test_signal(vault, "signal_test_002", status="watching")

    open_signals = list_signals(vault, status="open")
    assert len(open_signals) == 1


def test_show_claim(tmp_path):
    """Test showing a claim card."""
    from podcast_research.claim_signal.review import get_claim

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_test_001", claim_text="AI Agents bottleneck is harness")
    content = get_claim(vault, "claim_test_001")
    assert content is not None
    assert "harness" in content


def test_show_signal(tmp_path):
    """Test showing a signal card."""
    from podcast_research.claim_signal.review import get_signal

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001", signal_text="Monitor CPU bottleneck")
    content = get_signal(vault, "signal_test_001")
    assert content is not None
    assert "CPU" in content


def test_update_claim_status(tmp_path):
    """Test updating claim status."""
    from podcast_research.claim_signal.review import update_claim_status

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_test_001", status="active")
    ok = update_claim_status(vault, "claim_test_001", "verified", note="source confirmed")
    assert ok

    from podcast_research.claim_signal.review import get_claim
    content = get_claim(vault, "claim_test_001")
    assert "status: verified" in content
    assert "## Review History" in content
    assert "source confirmed" in content


def test_update_signal_status(tmp_path):
    """Test updating signal status."""
    from podcast_research.claim_signal.review import update_signal_status

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001", status="open")
    ok = update_signal_status(vault, "signal_test_001", "watching", note="needs tracking")
    assert ok

    from podcast_research.claim_signal.review import get_signal
    content = get_signal(vault, "signal_test_001")
    assert "status: watching" in content
    assert "needs tracking" in content


def test_invalid_claim_status_rejected(tmp_path):
    """Test that invalid claim status is rejected."""
    from podcast_research.claim_signal.review import update_claim_status

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_test_001")
    ok = update_claim_status(vault, "claim_test_001", "invalid_status")
    assert not ok


def test_invalid_signal_status_rejected(tmp_path):
    """Test that invalid signal status is rejected."""
    from podcast_research.claim_signal.review import update_signal_status

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001")
    ok = update_signal_status(vault, "signal_test_001", "bad_status")
    assert not ok


def test_nonexistent_claim_error(tmp_path):
    """Test that non-existent claim returns error."""
    from podcast_research.claim_signal.review import update_claim_status

    vault = tmp_path / "vault"
    ok = update_claim_status(vault, "nonexistent", "verified")
    assert not ok


def test_nonexistent_signal_error(tmp_path):
    """Test that non-existent signal returns error."""
    from podcast_research.claim_signal.review import update_signal_status

    vault = tmp_path / "vault"
    ok = update_signal_status(vault, "nonexistent", "watching")
    assert not ok


def test_update_writes_review_log(tmp_path):
    """Test that status update writes Claim_Review_Log.md."""
    from podcast_research.claim_signal.review import update_claim_status

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_test_001")
    update_claim_status(vault, "claim_test_001", "verified", note="test note")

    log_path = vault / "99_System" / "Claim_Review_Log.md"
    assert log_path.exists()
    assert "claim_test_001" in log_path.read_text(encoding="utf-8")


def test_update_writes_signal_review_log(tmp_path):
    """Test that status update writes Signal_Review_Log.md."""
    from podcast_research.claim_signal.review import update_signal_status

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001")
    update_signal_status(vault, "signal_test_001", "watching", note="track")

    log_path = vault / "99_System" / "Signal_Review_Log.md"
    assert log_path.exists()
    assert "signal_test_001" in log_path.read_text(encoding="utf-8")


def test_update_updates_index(tmp_path):
    """Test that status update rebuilds index."""
    from podcast_research.claim_signal.review import update_claim_status

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_test_001", status="active")
    update_claim_status(vault, "claim_test_001", "verified", note="done")

    index_path = vault / "99_System" / "Claim Index.md"
    assert index_path.exists()
    content = index_path.read_text(encoding="utf-8")
    assert "verified" in content
    assert "## Summary" in content


def test_cli_claims_list(tmp_path):
    """Test CLI claims list."""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_test_001", status="active")

    runner = CliRunner()
    result = runner.invoke(app, ["claims", "list", "--vault", str(vault)])
    assert result.exit_code == 0
    assert "claim_test_001" in result.stdout


def test_cli_signals_list(tmp_path):
    """Test CLI signals list."""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001", status="open")

    runner = CliRunner()
    result = runner.invoke(app, ["signals", "list", "--vault", str(vault)])
    assert result.exit_code == 0
    assert "signal_test_001" in result.stdout


def test_cli_claims_update(tmp_path):
    """Test CLI claims update-status."""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_test_001", status="active")

    runner = CliRunner()
    result = runner.invoke(app, [
        "claims", "update-status", "claim_test_001",
        "--vault", str(vault),
        "--status", "verified",
        "--note", "looks good",
    ])
    assert result.exit_code == 0


def test_cli_signals_update(tmp_path):
    """Test CLI signals update-status."""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001", status="open")

    runner = CliRunner()
    result = runner.invoke(app, [
        "signals", "update-status", "signal_test_001",
        "--vault", str(vault),
        "--status", "watching",
        "--note", "needs monitoring",
    ])
    assert result.exit_code == 0
