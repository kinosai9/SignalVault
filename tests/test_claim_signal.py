"""P2-F: Claim / Signal Card Generation tests."""

import pytest
from pathlib import Path


def _create_report(reports_dir: Path, filename: str, content: str = "") -> Path:
    """Helper: create a report file with claim/signal sections."""
    report_path = reports_dir / f"{filename}.md"
    if not content:
        content = f"""---
type: report
channel: TestChannel
video_id: vid001
---

# {filename}

## Core Investment Views

- NVIDIA is well-positioned in AI infrastructure due to data center growth.
  - Source: [[{filename}]]
  - Evidence: strong growth in data center revenue

## Tech / Industry Insights

- AI Agents are becoming more capable with tool use and multi-step reasoning.

## Tracking Signals

- Monitor NVIDIA quarterly earnings for AI revenue growth trends.
- Watch for enterprise AI adoption rate changes.

## Risks

- Regulatory uncertainty around AI safety could impact deployment speed.

## Open Questions

- Will Zendesk and Salesforce build their own AI agents to compete with startups?

## Source Quotes

> "AI agents will transform enterprise software" - Speaker 1

## Entities

- [[NVIDIA]]
- [[OpenAI]]
- [[Anthropic]]
"""
    report_path.write_text(content, encoding="utf-8")
    return report_path


def _create_applied_patch(patches_dir: Path, filename: str,
                           target_type: str = "topic",
                           target_name: str = "AI Agents",
                           target_card_rel: str = "02_Topics/AI Agents.md") -> Path:
    """Helper: create an applied patch with Key Claims and Open Questions."""
    patch_path = patches_dir / f"{filename}.md"
    patch_path.write_text(f"""---
type: llm_wiki_patch
target_type: {target_type}
target: "{target_name}"
target_card: "{target_card_rel}"
provider: mock
model: mock-v1
prompt_version: v1.0
generated_at: "2026-05-30T00:00:00Z"
source_reports:
  - "report1"
status: applied
auto_apply: false
applied_at: "2026-05-30T08:00:00Z"
applied_to: "{target_card_rel}"
---

# Patch Proposal: {target_name}

## Proposed Key Claims

- Current AI Agent bottleneck is engineering harness, not model capability.
  - Source: [[report1]]
  - Evidence: expert judgment, medium-strong

## Proposed Open Questions

- What is the long-term impact of AI Agents on enterprise SaaS pricing models?

## Proposed Risks

- Multi-model competition may weaken OpenAI's API call share over time.

## Patch Safety

- Safe

## Review Checklist

- [ ] Item
""", encoding="utf-8")
    return patch_path


def _create_vault(tmp_path):
    """Create a vault with reports, topic, and patches."""
    vault = tmp_path / "vault"
    reports_dir = vault / "01_Reports"
    topics_dir = vault / "02_Topics"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    reports_dir.mkdir(parents=True)
    topics_dir.mkdir(parents=True)
    patches_dir.mkdir(parents=True)

    _create_report(reports_dir, "report1")
    _create_applied_patch(patches_dir, "topic_AI_Agents_20260530_000000")

    # Create topic card
    (topics_dir / "AI Agents.md").write_text("""---
type: topic
status: core
topic: AI Agents
---

# AI Agents

## Source Reports

- [[report1]]
""", encoding="utf-8")

    return vault


def test_extract_claims_from_reports(tmp_path):
    """Test claim extraction from reports."""
    from podcast_research.claim_signal.extractor import extract_claims

    vault = _create_vault(tmp_path)
    claims = extract_claims(vault, source="reports", limit=50)
    assert len(claims) >= 2
    # First claim should be about NVIDIA
    nvidia_claims = [c for c in claims if "NVIDIA" in c.statement]
    assert len(nvidia_claims) >= 1


def test_extract_claims_from_patches(tmp_path):
    """Test claim extraction from applied patches."""
    from podcast_research.claim_signal.extractor import extract_claims

    vault = tmp_path / "vault"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    patches_dir.mkdir(parents=True)
    _create_applied_patch(patches_dir, "topic_AI_Agents_20260530_000000")

    claims = extract_claims(vault, source="patches", limit=50)
    assert len(claims) >= 1
    assert any("harness" in c.statement for c in claims)


def test_extract_signals_from_reports(tmp_path):
    """Test signal extraction from reports."""
    from podcast_research.claim_signal.extractor import extract_signals

    vault = _create_vault(tmp_path)
    signals = extract_signals(vault, source="reports", limit=50)
    assert len(signals) >= 3  # Tracking Signals(2) + Open Questions(1) + Risks(1)
    assert any("Zendesk" in s.statement for s in signals)


def test_extract_signals_from_patches(tmp_path):
    """Test signal extraction from applied patches."""
    from podcast_research.claim_signal.extractor import extract_signals

    vault = tmp_path / "vault"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    patches_dir.mkdir(parents=True)
    _create_applied_patch(patches_dir, "topic_AI_Agents_20260530_000000")

    signals = extract_signals(vault, source="patches", limit=50)
    assert len(signals) >= 2  # Open Questions + Risks
    assert any("pricing" in s.statement.lower() for s in signals)


def test_pending_patch_not_processed(tmp_path):
    """Test that pending patches are NOT processed."""
    from podcast_research.claim_signal.extractor import extract_claims

    vault = tmp_path / "vault"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    patches_dir.mkdir(parents=True)
    # Create a pending patch
    patch = patches_dir / "topic_Pending_20260530_000000.md"
    patch.write_text("""---
type: llm_wiki_patch
target_type: topic
target: "Test"
status: pending_review
auto_apply: false
---

## Proposed Key Claims

- Pending claim that should not be extracted.
  - Source: [[report1]]
""", encoding="utf-8")

    claims = extract_claims(vault, source="patches")
    assert len(claims) == 0


def test_investment_advice_filtered(tmp_path):
    """Test that investment advice keywords are filtered."""
    from podcast_research.claim_signal.extractor import _is_investment_advice

    assert _is_investment_advice("建议买入 NVIDIA 股票")
    assert _is_investment_advice("target price 500")
    assert not _is_investment_advice("NVIDIA is well-positioned in AI infrastructure")


def test_short_claims_filtered(tmp_path):
    """Test that claims shorter than 20 chars are filtered."""
    from podcast_research.claim_signal.extractor import extract_claims

    vault = tmp_path / "vault"
    reports_dir = vault / "01_Reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "short.md").write_text("""---
type: report
---

## Core Investment Views

- Short claim
- This is a long enough claim to pass the length filter test here.
  - Source: [[short]]
""", encoding="utf-8")

    claims = extract_claims(vault, source="reports")
    assert len(claims) == 1
    assert "long enough" in claims[0].statement


def test_dry_run_does_not_write(tmp_path):
    """Test dry-run doesn't write files."""
    from podcast_research.claim_signal.generator import generate_all

    vault = _create_vault(tmp_path)
    claims_dir = vault / "06_Claims"
    signals_dir = vault / "07_Signals"

    result = generate_all(vault, dry_run=True)
    assert not claims_dir.exists() or len(list(claims_dir.glob("*.md"))) == 0
    assert not signals_dir.exists() or len(list(signals_dir.glob("*.md"))) == 0


def test_claims_only_generation(tmp_path):
    """Test --claims-only generates only claims."""
    from podcast_research.claim_signal.generator import generate_all

    vault = _create_vault(tmp_path)
    result = generate_all(vault, dry_run=False, claims_only=True)
    assert result.claims_created > 0
    assert result.signals_created == 0


def test_signals_only_generation(tmp_path):
    """Test --signals-only generates only signals."""
    from podcast_research.claim_signal.generator import generate_all

    vault = _create_vault(tmp_path)
    result = generate_all(vault, dry_run=False, signals_only=True)
    assert result.signals_created > 0
    assert result.claims_created == 0


def test_claim_card_format(tmp_path):
    """Test Claim Card has correct frontmatter and structure."""
    from podcast_research.claim_signal.extractor import extract_claims
    from podcast_research.claim_signal.generator import generate_claim_card

    vault = _create_vault(tmp_path)
    claims = extract_claims(vault, source="reports", limit=5)
    assert len(claims) > 0

    claims_dir = vault / "06_Claims"
    r = generate_claim_card(claims[0], claims_dir, overwrite=False)

    assert r.action == "create"
    content = r.path.read_text(encoding="utf-8")
    assert "type: claim" in content
    assert "status: active" in content
    assert "claim:" in content
    assert "source_reports:" in content
    assert "# Claim:" in content
    assert "## Statement" in content
    assert "## Evidence" in content


def test_signal_card_format(tmp_path):
    """Test Signal Card has correct frontmatter and structure."""
    from podcast_research.claim_signal.extractor import extract_signals
    from podcast_research.claim_signal.generator import generate_signal_card

    vault = _create_vault(tmp_path)
    signals = extract_signals(vault, source="reports", limit=5)
    assert len(signals) > 0

    signals_dir = vault / "07_Signals"
    r = generate_signal_card(signals[0], signals_dir, overwrite=False)

    assert r.action == "create"
    content = r.path.read_text(encoding="utf-8")
    assert "type: signal" in content
    assert "status: open" in content
    assert "signal:" in content
    assert "source_reports:" in content
    assert "suggested_check_frequency:" in content
    assert "# Signal:" in content
    assert "## What to Watch" in content


def test_existing_card_skipped(tmp_path):
    """Test that existing cards are skipped by default."""
    from podcast_research.claim_signal.extractor import extract_claims
    from podcast_research.claim_signal.generator import generate_claim_card

    vault = _create_vault(tmp_path)
    claims = extract_claims(vault, source="reports", limit=5)
    claims_dir = vault / "06_Claims"

    # First create
    r1 = generate_claim_card(claims[0], claims_dir, overwrite=False)
    assert r1.action == "create"
    # Second create should skip
    r2 = generate_claim_card(claims[0], claims_dir, overwrite=False)
    assert r2.action == "skip"
    assert r2.reason == "exists"


def test_overwrite_flag(tmp_path):
    """Test --overwrite flag overwrites existing cards."""
    from podcast_research.claim_signal.extractor import extract_claims
    from podcast_research.claim_signal.generator import generate_claim_card

    vault = _create_vault(tmp_path)
    claims = extract_claims(vault, source="reports", limit=5)
    claims_dir = vault / "06_Claims"

    r1 = generate_claim_card(claims[0], claims_dir, overwrite=False)
    assert r1.action == "create"
    r2 = generate_claim_card(claims[0], claims_dir, overwrite=True)
    assert r2.action == "overwrite"


def test_indexes_generated(tmp_path):
    """Test that indexes are generated."""
    from podcast_research.claim_signal.generator import generate_all

    vault = _create_vault(tmp_path)
    generate_all(vault, dry_run=False)

    system_dir = vault / "99_System"
    assert (system_dir / "Claim Index.md").exists()
    assert (system_dir / "Signal Index.md").exists()
    assert (system_dir / "Claim_Signal_Generation_Log.md").exists()


def test_source_reports_only(tmp_path):
    """Test --source reports only extracts from reports."""
    from podcast_research.claim_signal.generator import generate_all

    vault = _create_vault(tmp_path)
    result = generate_all(vault, dry_run=False, source="reports")
    assert result.claims_created > 0 or result.signals_created > 0


def test_source_patches_only(tmp_path):
    """Test --source patches only extracts from patches."""
    from podcast_research.claim_signal.generator import generate_all

    vault = tmp_path / "vault"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    patches_dir.mkdir(parents=True)
    _create_applied_patch(patches_dir, "topic_AI_Agents_20260530_000000")

    result = generate_all(vault, dry_run=False, source="patches")
    assert result.claims_created > 0 or result.signals_created > 0


def test_cli_generate_claims_signals_dry_run(tmp_path):
    """Test CLI obsidian generate-claims-signals --dry-run."""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    vault = _create_vault(tmp_path)

    runner = CliRunner()
    result = runner.invoke(app, [
        "obsidian", "generate-claims-signals",
        "--vault", str(vault),
        "--dry-run",
    ])
    assert result.exit_code == 0
    assert "Preview" in result.stdout


def test_cli_claims_only(tmp_path):
    """Test CLI --claims-only."""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    vault = _create_vault(tmp_path)

    runner = CliRunner()
    result = runner.invoke(app, [
        "obsidian", "generate-claims-signals",
        "--vault", str(vault),
        "--claims-only",
    ])
    assert result.exit_code == 0
    assert "Claims created: " in result.stdout
    assert "Signals created: 0" in result.stdout


def test_cli_mutual_exclusion(tmp_path):
    """Test --claims-only and --signals-only mutual exclusion."""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    runner = CliRunner()
    result = runner.invoke(app, [
        "obsidian", "generate-claims-signals",
        "--vault", str(tmp_path),
        "--claims-only",
        "--signals-only",
    ])
    assert result.exit_code == 1
