"""P2-F.2: Claim / Signal Quality Consolidation tests."""

from pathlib import Path


def _create_test_claim(vault: Path, card_id: str, status: str = "active",
                        claim_text: str = "Test claim statement",
                        source_reports: str = "report1") -> Path:
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


def test_update_claim_meta(tmp_path):
    """Test update_claim_meta adds quality/review_priority/granularity."""
    from podcast_research.claim_signal.review import get_claim, update_claim_meta

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_test_001", claim_text="AI harness claim")

    ok = update_claim_meta(vault, "claim_test_001", quality="high", review_priority="high", granularity="atomic")
    assert ok

    content = get_claim(vault, "claim_test_001")
    assert "quality: high" in content
    assert "review_priority: high" in content
    assert "granularity: atomic" in content


def test_update_signal_meta(tmp_path):
    """Test update_signal_meta adds quality/priority/signal_type."""
    from podcast_research.claim_signal.review import get_signal, update_signal_meta

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001", signal_text="CPU bottleneck signal")

    ok = update_signal_meta(vault, "signal_test_001", quality="high", review_priority="high", signal_type="infrastructure")
    assert ok

    content = get_signal(vault, "signal_test_001")
    assert "quality: high" in content
    assert "review_priority: high" in content
    assert "signal_type: infrastructure" in content


def test_invalid_quality_rejected(tmp_path):
    """Test invalid quality is rejected."""
    from podcast_research.claim_signal.review import update_claim_meta

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_test_001")
    ok = update_claim_meta(vault, "claim_test_001", quality="invalid")
    assert not ok


def test_invalid_signal_type_rejected(tmp_path):
    """Test invalid signal_type is rejected."""
    from podcast_research.claim_signal.review import update_signal_meta

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001")
    ok = update_signal_meta(vault, "signal_test_001", signal_type="bad_type")
    assert not ok


def test_index_includes_meta(tmp_path):
    """Test that index rebuild includes quality/review_priority."""
    from podcast_research.claim_signal.review import update_claim_meta

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_test_001", claim_text="AI claim")
    update_claim_meta(vault, "claim_test_001", quality="high", review_priority="high")

    index = vault / "99_System" / "Claim Index.md"
    assert index.exists()
    content = index.read_text(encoding="utf-8")
    assert "high|high|atomic" in content.replace(" ", "")


def test_find_similar_claims(tmp_path):
    """Test find_similar_claims detects similar claims."""
    from podcast_research.claim_signal.review import find_similar_claims

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_a", claim_text="NVIDIA GPU supply is the bottleneck for AI training")
    _create_test_claim(vault, "claim_b", claim_text="NVIDIA GPU supply bottleneck limits AI training scale")
    _create_test_claim(vault, "claim_c", claim_text="Shopify e-commerce platform grows rapidly")

    pairs = find_similar_claims(vault)
    assert len(pairs) >= 1
    # item_a and item_b are card_ids, not statements
    assert "claim_a" in pairs[0].item_a or "claim_b" in pairs[0].item_a


def test_find_similar_does_not_modify(tmp_path):
    """Test find_similar doesn't modify files."""
    from podcast_research.claim_signal.review import find_similar_claims

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_a", claim_text="NVIDIA GPU supply bottleneck")
    _create_test_claim(vault, "claim_b", claim_text="NVIDIA GPU supply bottleneck fix")

    before = (vault / "06_Claims" / "claim_a.md").read_text(encoding="utf-8")
    find_similar_claims(vault)
    after = (vault / "06_Claims" / "claim_a.md").read_text(encoding="utf-8")
    assert before == after


def test_backlog_generated(tmp_path):
    """Test backlog is generated."""
    from podcast_research.claim_signal.review import (
        generate_claim_backlog,
        generate_signal_backlog,
    )

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_a", claim_text="Claim A")
    _create_test_signal(vault, "signal_a", signal_text="Signal A")

    generate_claim_backlog(vault)
    generate_signal_backlog(vault)

    assert (vault / "99_System" / "Claim Review Backlog.md").exists()
    assert (vault / "99_System" / "Signal Review Backlog.md").exists()


def test_backlog_sorted(tmp_path):
    """Test backlog sorts by priority."""
    from podcast_research.claim_signal.review import (
        generate_claim_backlog,
        update_claim_meta,
    )

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_low")
    _create_test_claim(vault, "claim_high")
    update_claim_meta(vault, "claim_high", review_priority="high")

    generate_claim_backlog(vault)
    content = (vault / "99_System" / "Claim Review Backlog.md").read_text(encoding="utf-8")
    # high priority should appear before low
    high_idx = content.find("claim_high")
    low_idx = content.find("claim_low")
    assert high_idx < low_idx


def test_update_meta_writes_log(tmp_path):
    """Test update-meta writes review log."""
    from podcast_research.claim_signal.review import update_claim_meta

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_test_001")
    update_claim_meta(vault, "claim_test_001", quality="high", review_priority="high")

    log = vault / "99_System" / "Claim_Review_Log.md"
    assert log.exists()
    assert "meta_updated" in log.read_text(encoding="utf-8")


def test_cli_claims_update_meta(tmp_path):
    """Test CLI claims update-meta."""
    from typer.testing import CliRunner

    from podcast_research.cli import app

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_test_001")

    runner = CliRunner()
    result = runner.invoke(app, [
        "claims", "update-meta", "claim_test_001",
        "--vault", str(vault),
        "--quality", "high",
        "--review-priority", "high",
    ])
    assert result.exit_code == 0


def test_cli_signals_update_meta(tmp_path):
    """Test CLI signals update-meta."""
    from typer.testing import CliRunner

    from podcast_research.cli import app

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001")

    runner = CliRunner()
    result = runner.invoke(app, [
        "signals", "update-meta", "signal_test_001",
        "--vault", str(vault),
        "--quality", "medium",
        "--signal-type", "infrastructure",
    ])
    assert result.exit_code == 0


def test_cli_find_similar(tmp_path):
    """Test CLI claims find-similar."""
    from typer.testing import CliRunner

    from podcast_research.cli import app

    vault = tmp_path / "vault"
    _create_test_claim(vault, "claim_a", claim_text="NVIDIA GPU supply bottleneck for AI")
    _create_test_claim(vault, "claim_b", claim_text="NVIDIA GPU supply limits AI scaling")

    runner = CliRunner()
    result = runner.invoke(app, ["claims", "find-similar", "--vault", str(vault)])
    assert result.exit_code == 0
    assert "Similar" in result.stdout or "No similar" in result.stdout


def test_cli_backlog(tmp_path):
    """Test CLI signals backlog."""
    from typer.testing import CliRunner

    from podcast_research.cli import app

    vault = tmp_path / "vault"
    _create_test_signal(vault, "signal_test_001")

    runner = CliRunner()
    result = runner.invoke(app, ["signals", "backlog", "--vault", str(vault)])
    assert result.exit_code == 0
    assert (vault / "99_System" / "Signal Review Backlog.md").exists()
