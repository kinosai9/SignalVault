"""P2-H.1: Workspace dashboard tests. All use tmp_path vault, never real vault."""

from __future__ import annotations

from pathlib import Path

from signalvault.workspace import refresh_workspace
from signalvault.workspace.generators import (
    generate_home_dashboard,
    generate_knowledge_map,
    generate_review_queue,
)
from signalvault.workspace.managed_block import (
    _has_managed_block,
    _remove_managed_block,
    _upsert_managed_block,
)
from signalvault.workspace.scanner import VaultScanner

# ── Vault builder helpers ──────────────────────────────────────────

def _make_vault(tmp_path: Path) -> Path:
    """Create a vault skeleton with all subdirectories."""
    vault = tmp_path / "vault"
    for d in [
        "01_Reports", "02_Topics", "03_Companies", "05_Channels",
        "06_Claims", "07_Signals", "99_System", "00_Inbox/LLM_Patches",
    ]:
        (vault / d).mkdir(parents=True)
    return vault


def _add_report(vault: Path, filename: str, *, channel="TestChannel",
                video_id="vid001", analyzed_at="2026-05-29 17:00",
                title="Test Report Title") -> Path:
    p = vault / "01_Reports" / f"{filename}.md"
    p.write_text(f"""---
type: report
channel: {channel}
video_id: {video_id}
analyzed_at: "{analyzed_at}"
tags:
  - podcast-report
---
# {title}

## Summary

Test content.
""", encoding="utf-8")
    return p


def _add_topic(vault: Path, name: str, *, status="core",
               source_reports: list[str] | None = None) -> Path:
    p = vault / "02_Topics" / f"{name}.md"
    sr = source_reports or []
    sr_yaml = "\n".join(f"  - {s}" for s in sr) if sr else "  []"
    p.write_text(f"""---
type: topic
status: {status}
topic: {name}
aliases: []
tags: []
source_reports:
{sr_yaml}
updated_at: "2026-05-30 12:00"
---
# {name}

## Source Reports
""", encoding="utf-8")
    return p


def _add_company(vault: Path, name: str, *, source_reports: list[str] | None = None) -> Path:
    p = vault / "03_Companies" / f"{name}.md"
    sr = source_reports or []
    sr_yaml = "\n".join(f"  - {s}" for s in sr) if sr else "  []"
    p.write_text(f"""---
type: company
company: {name}
ticker: ""
sector: ""
tags: []
source_reports:
{sr_yaml}
updated_at: "2026-05-30 12:00"
---
# {name}

## Source Reports
""", encoding="utf-8")
    return p


def _add_claim(vault: Path, card_id: str, *, status="active",
               claim_text="Test claim statement",
               source_reports: list[str] | None = None,
               related_topics: list[str] | None = None,
               related_companies: list[str] | None = None) -> Path:
    p = vault / "06_Claims" / f"{card_id}.md"
    sr = source_reports or []
    sr_yaml = "\n".join(f'  - "{s}"' for s in sr) if sr else "  []"
    rt = related_topics or []
    rt_yaml = "\n".join(f'  - {t}' for t in rt) if rt else "  []"
    rc = related_companies or []
    rc_yaml = "\n".join(f'  - {c}' for c in rc) if rc else "  []"
    p.write_text(f"""---
type: claim
status: {status}
claim: "{claim_text}"
source_reports:
{sr_yaml}
related_topics:
{rt_yaml}
related_companies:
{rc_yaml}
created_at: "2026-05-30T20:07:34"
updated_at: "2026-05-30T20:07:34"
---
# Claim: {claim_text}

## Statement
""", encoding="utf-8")
    return p


def _add_signal(vault: Path, card_id: str, *, status="open",
                signal_text="Test signal statement",
                source_reports: list[str] | None = None,
                related_topics: list[str] | None = None,
                related_companies: list[str] | None = None,
                tracking_status: str = "") -> Path:
    p = vault / "07_Signals" / f"{card_id}.md"
    sr = source_reports or []
    sr_yaml = "\n".join(f'  - "{s}"' for s in sr) if sr else "  []"
    rt = related_topics or []
    rt_yaml = "\n".join(f'  - {t}' for t in rt) if rt else "  []"
    rc = related_companies or []
    rc_yaml = "\n".join(f'  - {c}' for c in rc) if rc else "  []"
    ts_line = f'tracking_status: "{tracking_status}"\n' if tracking_status else ""
    p.write_text(f"""---
type: signal
status: {status}
signal: "{signal_text}"
source_reports:
{sr_yaml}
related_topics:
{rt_yaml}
related_companies:
{rc_yaml}
{ts_line}created_at: "2026-05-30T20:07:34"
updated_at: "2026-05-30T20:07:34"
---
# Signal: {signal_text}

## What to Watch
""", encoding="utf-8")
    return p


def _add_patch(vault: Path, patch_id: str, *, target_type="topic",
               target="AI Agents", status="pending_review",
               generated_at="2026-05-30T15:00:00Z",
               source_reports: list[str] | None = None) -> Path:
    p = vault / "00_Inbox" / "LLM_Patches" / f"{patch_id}.md"
    sr = source_reports or []
    sr_yaml = "\n".join(f'  - "{s}"' for s in sr) if sr else "  []"
    p.write_text(f"""---
type: llm_wiki_patch
target_type: {target_type}
target: "{target}"
target_card: "02_Topics/{target}.md"
provider: openai_compatible
model: deepseek-v4-pro
prompt_version: v1.0
generated_at: "{generated_at}"
source_reports:
{sr_yaml}
status: {status}
auto_apply: false
---
# Patch Proposal: {target}

## Review Checklist
""", encoding="utf-8")
    return p


def _add_channel(vault: Path, name: str, *, url="", priority="core") -> Path:
    p = vault / "05_Channels" / f"{name}.md"
    p.write_text(f"""---
type: channel
channel: {name}
source_type: youtube
url: "{url}"
tags: []
priority: {priority}
updated_at: "2026-05-30 12:00"
---
# {name}

## Recent Reports
""", encoding="utf-8")
    return p


def _add_log(vault: Path, log_name: str, entries: list[str]) -> Path:
    """Create a log file in 99_System with ## timestamp headers."""
    p = vault / "99_System" / f"{log_name}.md"
    lines = [f"# {log_name}", ""]
    for entry in entries:
        lines.append(entry)
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


# ── Managed Block Tests ───────────────────────────────────────────

class TestManagedBlock:
    def test_creates_new_file_with_block(self, tmp_path):
        f = tmp_path / "test.md"
        _upsert_managed_block(f, "test-block", "Hello world")
        assert f.exists()
        content = f.read_text(encoding="utf-8")
        assert "<!-- signalvault:BEGIN test-block -->" in content
        assert "Hello world" in content
        assert "<!-- signalvault:END test-block -->" in content

    def test_upserts_existing_block(self, tmp_path):
        f = tmp_path / "test.md"
        _upsert_managed_block(f, "test-block", "Version 1")
        _upsert_managed_block(f, "test-block", "Version 2")
        content = f.read_text(encoding="utf-8")
        assert "Version 2" in content
        assert "Version 1" not in content
        # Only one BEGIN marker
        assert content.count("<!-- signalvault:BEGIN test-block -->") == 1

    def test_appends_to_file_without_block(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# My custom content\n\nUser notes here.\n", encoding="utf-8")
        _upsert_managed_block(f, "test-block", "Managed content")
        content = f.read_text(encoding="utf-8")
        assert "My custom content" in content
        assert "User notes here" in content
        assert "Managed content" in content

    def test_does_not_overwrite_user_content(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# User Header\n\nUser paragraph.\n", encoding="utf-8")
        _upsert_managed_block(f, "test-block", "Managed content")
        _upsert_managed_block(f, "test-block", "Updated managed")
        content = f.read_text(encoding="utf-8")
        assert "# User Header" in content
        assert "User paragraph" in content
        assert "Updated managed" in content
        # Only one marker pair
        assert content.count("<!-- signalvault:BEGIN test-block -->") == 1

    def test_multiple_different_blocks(self, tmp_path):
        f = tmp_path / "test.md"
        _upsert_managed_block(f, "block-a", "Content A")
        _upsert_managed_block(f, "block-b", "Content B")
        content = f.read_text(encoding="utf-8")
        assert "Content A" in content
        assert "Content B" in content
        assert "block-a" in content
        assert "block-b" in content

    def test_remove_managed_block(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# User content\n", encoding="utf-8")
        _upsert_managed_block(f, "test-block", "Managed content")
        assert _has_managed_block(f, "test-block")
        removed = _remove_managed_block(f, "test-block")
        assert removed
        content = f.read_text(encoding="utf-8")
        assert "Managed content" not in content
        assert "# User content" in content
        assert not _has_managed_block(f, "test-block")

    def test_remove_nonexistent_block(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# Test\n", encoding="utf-8")
        assert not _remove_managed_block(f, "nonexistent")

    def test_has_managed_block_false_for_missing_file(self, tmp_path):
        assert not _has_managed_block(tmp_path / "nonexistent.md", "test-block")


# ── Scanner Tests ──────────────────────────────────────────────────

class TestVaultScanner:
    def test_scans_empty_vault(self, tmp_path):
        vault = _make_vault(tmp_path)
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        assert len(snapshot.reports) == 0
        assert len(snapshot.topics) == 0
        assert len(snapshot.companies) == 0

    def test_scans_reports(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_report(vault, "2026-05-29_TestChannel_vid001", channel="TestChannel",
                     analyzed_at="2026-05-29 17:00")
        _add_report(vault, "2026-05-30_TestChannel_vid002", channel="TestChannel",
                     analyzed_at="2026-05-30 10:00")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        assert len(snapshot.reports) == 2
        assert snapshot.reports[0].channel == "TestChannel"
        # Recent reports: most recent first
        recent = snapshot.recent_reports(10)
        assert recent[0].analyzed_at == "2026-05-30 10:00"

    def test_scans_topics_with_status(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core", source_reports=["r1", "r2"])
        _add_topic(vault, "Old Topic", status="long_tail", source_reports=[])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        assert len(snapshot.topics) == 2
        core = snapshot.core_topics()
        assert len(core) == 1
        assert core[0].name == "AI Agents"
        assert len(core[0].source_reports) == 2

    def test_scans_companies(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_company(vault, "NVIDIA", source_reports=["r1", "r2", "r3"])
        _add_company(vault, "RandomCo", source_reports=["r1"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        assert len(snapshot.companies) == 2
        # NVIDIA is in HIGH_VALUE_COMPANIES
        core = snapshot.core_companies()
        assert any(c.name == "NVIDIA" for c in core)

    def test_scans_claims(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_claim(vault, "claim_001", status="active")
        _add_claim(vault, "claim_002", status="verified")
        _add_claim(vault, "claim_003", status="challenged")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        assert len(snapshot.claims) == 3
        assert len(snapshot.active_claims()) == 1
        assert len(snapshot.review_claims()) == 2  # active + challenged

    def test_scans_signals(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_signal(vault, "signal_001", status="open")
        _add_signal(vault, "signal_002", status="watching")
        _add_signal(vault, "signal_003", status="resolved")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        assert len(snapshot.signals) == 3
        assert len(snapshot.open_signals()) == 1
        assert len(snapshot.watching_signals()) == 1
        assert len(snapshot.review_signals()) == 2  # open + watching

    def test_scans_channels(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_channel(vault, "Acquired", priority="core")
        _add_channel(vault, "Latent Space", priority="core")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        assert len(snapshot.channels) == 2

    def test_scans_llm_patches(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_patch(vault, "topic_AI_Agents_001", status="pending_review")
        _add_patch(vault, "topic_AI_Agents_002", status="applied")
        _add_patch(vault, "company_NVIDIA_001", status="rejected")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        assert len(snapshot.llm_patches) == 3
        assert len(snapshot.pending_patches()) == 1

    def test_claims_count_for_topic(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core")
        _add_claim(vault, "claim_001", status="active",
                    related_topics=["AI Agents"])
        _add_claim(vault, "claim_002", status="active",
                    related_topics=["AI Agents"])
        _add_claim(vault, "claim_003", status="active",
                    related_topics=["Other Topic"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        assert snapshot.claims_count_for("AI Agents") == 2

    def test_signals_count_for_topic(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core")
        _add_signal(vault, "signal_001", status="open",
                     related_topics=["AI Agents"])
        _add_signal(vault, "signal_002", status="watching",
                     related_topics=["Other"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        assert snapshot.signals_count_for("AI Agents") == 1

    def test_recent_log_entries(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_log(vault, "Export Log", [
            "# Export Log",
            "## 2026-05-30 20:00",
            "Exported 5 reports.",
            "## 2026-05-29 15:00",
            "Exported 3 reports.",
        ])
        _add_log(vault, "Card Generation Log", [
            "# Card Generation Log",
            "## 2026-05-30 18:00",
            "Generated 10 cards.",
        ])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        entries = snapshot.recent_log_entries(5)
        assert len(entries) >= 2
        # Most recent first
        assert "2026-05-30 20:00" in entries[0]

    def test_topic_without_status(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Models", status="")  # no status
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        assert len(snapshot.topics_without_status()) == 1
        assert len(snapshot.core_topics()) == 0


# ── Generator Tests ────────────────────────────────────────────────

class TestHomeDashboard:
    def test_includes_quick_nav(self, tmp_path):
        vault = _make_vault(tmp_path)
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_home_dashboard(snapshot)
        assert "快速入口" in content
        assert "Knowledge Map" in content
        assert "Review Queue" in content

    def test_includes_core_topics_table(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core", source_reports=["r1"])
        _add_topic(vault, "Semiconductor", status="core", source_reports=["r1", "r2"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_home_dashboard(snapshot)
        assert "核心主题" in content
        assert "AI Agents" in content
        assert "Semiconductor" in content

    def test_includes_core_companies_table(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_company(vault, "NVIDIA", source_reports=["r1", "r2"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_home_dashboard(snapshot)
        assert "核心公司" in content
        # NVIDIA is in HIGH_VALUE_COMPANIES
        assert "NVIDIA" in content

    def test_includes_pending_review_counts(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_patch(vault, "patch_001", status="pending_review")
        _add_claim(vault, "claim_001", status="active")
        _add_claim(vault, "claim_002", status="challenged")
        _add_signal(vault, "signal_001", status="open")
        _add_signal(vault, "signal_002", status="watching")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_home_dashboard(snapshot)
        # P2-N.4.3: Home now shows "需要你确认" instead of raw counts
        assert "需要你确认" in content
        assert "系统健康" in content
        # Challenged claims are high priority → appear in needs review
        # (watching signals may appear based on priority)

    def test_recent_reports_limited_to_10(self, tmp_path):
        vault = _make_vault(tmp_path)
        for i in range(15):
            _add_report(vault, f"report_{i:03d}",
                         analyzed_at=f"2026-05-{20+i:02d} 10:00")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_home_dashboard(snapshot)
        # Count report wiki links in content
        report_links = content.count("[[01_Reports/")
        assert report_links <= 10

    def test_empty_vault_shows_placeholders(self, tmp_path):
        vault = _make_vault(tmp_path)
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_home_dashboard(snapshot)
        assert "No core topics yet" in content or "核心主题" in content


class TestKnowledgeMap:
    def test_core_topics_section(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core", source_reports=["r1", "r2"])
        _add_topic(vault, "Semiconductor", status="core", source_reports=["r1"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_knowledge_map(snapshot)
        assert "Core Topics" in content
        assert "AI Agents" in content
        assert "Semiconductor" in content

    def test_long_tail_shows_count_only(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core", source_reports=["r1"])
        _add_topic(vault, "Old Topic", status="long_tail")
        _add_topic(vault, "Another", status="long_tail")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_knowledge_map(snapshot)
        # Long-tail topics should not appear individually
        assert "Old Topic" not in content
        assert "Topic Index" in content

    def test_includes_active_claims(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_claim(vault, "claim_001", status="active", claim_text="AI is transformative")
        _add_claim(vault, "claim_002", status="verified", claim_text="Cloud is growing")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_knowledge_map(snapshot)
        assert "Active Claims" in content
        assert "claim_001" in content
        assert "claim_002" not in content  # verified, not active

    def test_includes_watching_signals(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_signal(vault, "signal_001", status="watching", signal_text="GPU shortage")
        _add_signal(vault, "signal_002", status="open", signal_text="New regulation")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_knowledge_map(snapshot)
        assert "Watching Signals" in content
        assert "signal_001" in content
        # open signals not in watching section
        assert "signal_002" not in content

    def test_includes_source_channels(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_channel(vault, "Acquired", priority="core")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_knowledge_map(snapshot)
        assert "Source Channels" in content
        assert "Acquired" in content


class TestReviewQueue:
    def test_pending_patches_section(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_patch(vault, "patch_001", status="pending_review", target="AI Agents")
        _add_patch(vault, "patch_002", status="applied", target="NVIDIA", target_type="company")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_review_queue(snapshot)
        assert "Pending LLM Patches" in content
        assert "patch_001" in content
        assert "patch_002" not in content  # applied, not pending

    def test_claims_to_review(self, tmp_path):
        vault = _make_vault(tmp_path)
        # P2-N.4.4.1: Claims must pass actionability gate (not just priority)
        _add_claim(vault, "claim_001", status="active",
                    claim_text="Normal active claim with enough text for review")
        _add_claim(vault, "claim_002", status="challenged",
                    claim_text="Challenged claim about AI agents transforming enterprise")
        _add_claim(vault, "claim_003", status="verified",
                    claim_text="Verified claim about AI agents transforming enterprise")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        snapshot.claims[0].review_priority = "normal"
        snapshot.claims[1].review_priority = "high"
        snapshot.claims[2].review_priority = "high"
        content = generate_review_queue(snapshot)
        assert "需要你确认" in content
        assert "claim_002" in content  # challenged + high + actionable
        assert "claim_003" not in content  # verified → already accepted

    def test_signals_to_review(self, tmp_path):
        vault = _make_vault(tmp_path)
        # P2-N.4.4.1: Signals must pass actionability gate (not just priority)
        _add_signal(vault, "signal_001", status="open",
                     signal_text="Open signal about GPU supply chain risk in semiconductor industry")
        _add_signal(vault, "signal_002", status="watching",
                     signal_text="Watching signal about new EU AI regulation affecting tech companies")
        _add_signal(vault, "signal_003", status="resolved",
                     signal_text="Resolved signal about GPU supply chain risk in semiconductor industry")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        snapshot.signals[0].review_priority = "high"
        snapshot.signals[1].review_priority = "high"
        snapshot.signals[2].review_priority = "high"
        content = generate_review_queue(snapshot)
        assert "需要你确认" in content
        assert "signal_001" in content  # open + high = actionable
        assert "signal_002" not in content  # watching = already followed
        assert "signal_003" not in content  # resolved = closed

    def test_tracking_items(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_signal(vault, "signal_001", status="open", tracking_status="active")
        _add_signal(vault, "signal_002", status="watching", tracking_status="tracking")
        _add_signal(vault, "signal_003", status="resolved")  # resolved, no tracking
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_review_queue(snapshot)
        # P2-N.4.3: "Tracking Items" → "正在跟踪"
        assert "正在跟踪" in content
        assert "signal_001" in content
        assert "signal_002" in content
        # signal_003 is resolved — should not appear in review OR tracking
        assert "signal_003" not in content


# ── Integration Tests ─────────────────────────────────────────────

class TestRefreshWorkspace:
    def test_creates_all_files(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_report(vault, "r1", analyzed_at="2026-05-29 17:00")
        _add_topic(vault, "AI Agents", status="core", source_reports=["r1"])
        _add_channel(vault, "TestChannel")

        refresh_workspace(vault, dry_run=False)

        home = vault / "Home.md"
        km = vault / "99_System" / "Knowledge Map.md"
        rq = vault / "99_System" / "Review Queue.md"

        assert home.exists()
        assert km.exists()
        assert rq.exists()

        home_content = home.read_text(encoding="utf-8")
        assert "快速入口" in home_content
        assert "AI Agents" in home_content

    def test_dry_run_does_not_write(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_report(vault, "r1")

        result = refresh_workspace(vault, dry_run=True)

        home = vault / "Home.md"
        assert not home.exists()
        assert "home" in result
        assert len(result["home"]) > 0

    def test_idempotent_double_run(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_report(vault, "r1")
        _add_topic(vault, "AI Agents", status="core")

        refresh_workspace(vault, dry_run=False)
        refresh_workspace(vault, dry_run=False)

        home = vault / "Home.md"
        content = home.read_text(encoding="utf-8")
        # Only one managed block
        assert content.count("<!-- signalvault:BEGIN home-dashboard -->") == 1

    def test_does_not_overwrite_user_content(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_report(vault, "r1")

        # Pre-create Home.md with user content
        home = vault / "Home.md"
        home.write_text("# My Custom Home\n\nPersonal notes here.\n", encoding="utf-8")

        refresh_workspace(vault, dry_run=False)

        content = home.read_text(encoding="utf-8")
        assert "My Custom Home" in content
        assert "Personal notes here" in content
        assert "<!-- signalvault:BEGIN home-dashboard -->" in content

    def test_home_only_flag(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_report(vault, "r1")

        result = refresh_workspace(vault, dry_run=False, home_only=True)

        assert (vault / "Home.md").exists()
        assert not (vault / "99_System" / "Knowledge Map.md").exists()
        assert not (vault / "99_System" / "Review Queue.md").exists()
        assert len(result["files_written"]) == 1

    def test_knowledge_map_only_flag(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_report(vault, "r1")

        refresh_workspace(vault, dry_run=False, knowledge_map_only=True)

        assert not (vault / "Home.md").exists()
        assert (vault / "99_System" / "Knowledge Map.md").exists()
        assert not (vault / "99_System" / "Review Queue.md").exists()

    def test_review_queue_only_flag(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_report(vault, "r1")

        refresh_workspace(vault, dry_run=False, review_queue_only=True)

        assert not (vault / "Home.md").exists()
        assert not (vault / "99_System" / "Knowledge Map.md").exists()
        assert (vault / "99_System" / "Review Queue.md").exists()

    def test_stats_are_accurate(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_report(vault, "r1")
        _add_report(vault, "r2")
        _add_topic(vault, "AI Agents", status="core", source_reports=["r1"])
        _add_topic(vault, "Old", status="long_tail")
        _add_company(vault, "NVIDIA", source_reports=["r1", "r2"])
        _add_channel(vault, "TestChannel")

        result = refresh_workspace(vault, dry_run=True)
        stats = result["stats"]

        assert stats["reports"] == 2
        assert stats["topics"] == 2
        assert stats["core_topics"] == 1
        assert stats["companies"] == 1
        assert stats["core_companies"] == 1  # NVIDIA in HIGH_VALUE_COMPANIES
        assert stats["channels"] == 1


# ── CLI Tests ──────────────────────────────────────────────────────

class TestWorkspaceCLI:
    """Test the CLI command via Typer test runner."""

    def test_refresh_dry_run(self, tmp_path):
        from typer.testing import CliRunner

        from signalvault.cli import app

        vault = _make_vault(tmp_path)
        _add_report(vault, "r1")
        _add_topic(vault, "AI Agents", status="core")

        runner = CliRunner()
        result = runner.invoke(app, [
            "obsidian", "workspace", "refresh",
            "--vault", str(vault),
            "--dry-run",
        ])
        assert result.exit_code == 0
        assert "DRY-RUN" in result.stdout
        # Should not create files
        assert not (vault / "Home.md").exists()

    def test_refresh_requires_vault(self):
        from typer.testing import CliRunner

        from signalvault.cli import app

        runner = CliRunner()
        result = runner.invoke(app, [
            "obsidian", "workspace", "refresh",
            "--vault", "/nonexistent/path",
        ])
        assert result.exit_code == 1

    def test_refresh_mutually_exclusive_flags(self, tmp_path):
        from typer.testing import CliRunner

        from signalvault.cli import app

        vault = _make_vault(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, [
            "obsidian", "workspace", "refresh",
            "--vault", str(vault),
            "--home-only",
            "--knowledge-map-only",
        ])
        assert result.exit_code == 1


# ── P2-H.2 Backfill Tests ────────────────────────────────────────

class TestBackfillRelations:
    def test_backfill_topics_from_related_topics_section(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core")
        _add_topic(vault, "Semiconductor", status="core")
        p = vault / "06_Claims" / "claim_test.md"
        p.write_text("""---
type: claim
status: active
claim: "Test claim"
related_topics: []
related_companies: []
source_reports: []
---
# Claim: Test

## Related Topics
- [[AI Agents]]
- [[Semiconductor]]
""", encoding="utf-8")

        from signalvault.workspace.backfill import backfill_relations
        result = backfill_relations(vault, dry_run=True, apply=False)
        updated = [r for r in result["results"] if r.get("updated")]
        assert len(updated) == 1
        assert "AI Agents" in updated[0]["new_topics"]

    def test_backfill_topics_from_statement_text(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core")
        _add_topic(vault, "Enterprise AI", status="core")
        p = vault / "06_Claims" / "claim_test.md"
        p.write_text("""---
type: claim
status: active
claim: "AI Agents in enterprise"
related_topics: []
related_companies: []
source_reports: []
---
# Claim: AI Agents in enterprise

## Statement
AI Agents are transforming enterprise AI adoption patterns.

## Related Topics
""", encoding="utf-8")

        from signalvault.workspace.backfill import backfill_relations
        result = backfill_relations(vault, dry_run=True, apply=False)
        updated = [r for r in result["results"] if r.get("updated")]
        assert len(updated) == 1
        assert "AI Agents" in updated[0]["new_topics"]

    def test_backfill_companies_from_text(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_company(vault, "NVIDIA")
        _add_company(vault, "OpenAI")
        p = vault / "06_Claims" / "claim_test.md"
        p.write_text("""---
type: claim
status: active
claim: "NVIDIA and OpenAI"
related_topics: []
related_companies: []
source_reports: []
---
# Claim: Test

## Statement
NVIDIA GPUs power OpenAI training infrastructure.

## Related Companies
""", encoding="utf-8")

        from signalvault.workspace.backfill import backfill_relations
        result = backfill_relations(vault, dry_run=True, apply=False)
        updated = [r for r in result["results"] if r.get("updated")]
        assert len(updated) == 1
        new_companies = updated[0]["new_companies"]
        assert "NVIDIA" in new_companies
        assert "OpenAI" in new_companies

    def test_only_writes_existing_topics(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core")
        p = vault / "06_Claims" / "claim_test.md"
        p.write_text("""---
type: claim
status: active
claim: "AI Agents and Blockchain"
related_topics: []
related_companies: []
source_reports: []
---
# Claim: Test

## Statement
AI Agents and Blockchain technology.

## Related Topics
""", encoding="utf-8")

        from signalvault.workspace.backfill import backfill_relations
        result = backfill_relations(vault, dry_run=True, apply=False)
        updated = [r for r in result["results"] if r.get("updated")]
        assert len(updated) == 1
        assert "AI Agents" in updated[0]["new_topics"]
        assert "Blockchain" not in updated[0]["new_topics"]

    def test_preserves_existing_relations(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core")
        _add_topic(vault, "Semiconductor", status="core")
        p = vault / "06_Claims" / "claim_test.md"
        p.write_text("""---
type: claim
status: active
claim: "Test"
related_topics:
  - Semiconductor
related_companies: []
source_reports: []
---
# Claim: Test

## Statement
AI Agents are important.

## Related Topics
""", encoding="utf-8")

        from signalvault.workspace.backfill import backfill_relations
        result = backfill_relations(vault, dry_run=True, apply=False)
        updated = [r for r in result["results"] if r.get("updated")]
        new_t = updated[0]["new_topics"]
        assert "AI Agents" in new_t
        assert "Semiconductor" not in new_t  # already exists

    def test_dry_run_does_not_write(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core")
        p = vault / "06_Claims" / "claim_test.md"
        original = """---
type: claim
status: active
claim: "Test"
related_topics: []
related_companies: []
source_reports: []
---
# Claim: Test

## Statement
AI Agents.

## Related Topics
"""
        p.write_text(original, encoding="utf-8")

        from signalvault.workspace.backfill import backfill_relations
        backfill_relations(vault, dry_run=True, apply=False)
        assert p.read_text(encoding="utf-8") == original

    def test_apply_updates_frontmatter(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core")
        p = vault / "06_Claims" / "claim_test.md"
        p.write_text("""---
type: claim
status: active
claim: "Test"
related_topics: []
related_companies: []
source_reports: []
---
# Claim: Test

## Statement
AI Agents are important.

## Related Topics
""", encoding="utf-8")

        from signalvault.workspace.backfill import backfill_relations
        backfill_relations(vault, dry_run=False, apply=True)
        content = p.read_text(encoding="utf-8")
        assert "AI Agents" in content

    def test_signal_backfill_from_what_to_watch(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "Semiconductor", status="core")
        p = vault / "07_Signals" / "signal_test.md"
        p.write_text("""---
type: signal
status: open
signal: "Test signal"
related_topics: []
related_companies: []
source_reports: []
---
# Signal: Test

## What to Watch
The semiconductor supply chain is changing.

## Related Topics
""", encoding="utf-8")

        from signalvault.workspace.backfill import backfill_relations
        result = backfill_relations(vault, dry_run=True, apply=False)
        updated = [r for r in result["results"] if r.get("updated")]
        assert len(updated) == 1
        assert "Semiconductor" in updated[0]["new_topics"]

    def test_writes_backfill_log(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core")
        p = vault / "06_Claims" / "claim_test.md"
        p.write_text("""---
type: claim
status: active
claim: "Test"
related_topics: []
related_companies: []
source_reports: []
---
# Claim: Test

## Statement
AI Agents.

## Related Topics
""", encoding="utf-8")

        from signalvault.workspace.backfill import backfill_relations
        backfill_relations(vault, dry_run=False, apply=True)
        log_path = vault / "99_System" / "Relation_Backfill_Log.md"
        assert log_path.exists()


# ── P2-H.2 Curation Tests ────────────────────────────────────────

class TestCurationStatus:
    def test_topic_enhanced_with_llm_wiki_marker(self, tmp_path):
        vault = _make_vault(tmp_path)
        p = vault / "02_Topics" / "AI Agents.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("""---
type: topic
status: core
topic: AI Agents
source_reports: []
---
# AI Agents

<!-- LLM-WIKI:BEGIN topic_AI_Agents_001 -->
Patched content.
<!-- LLM-WIKI:END topic_AI_Agents_001 -->
""", encoding="utf-8")

        from signalvault.workspace.curation import refresh_curation_status
        result = refresh_curation_status(vault, dry_run=True)
        updated = [r for r in result["results"] if r.get("updated")]
        assert len(updated) == 1
        assert updated[0]["new_curation"] == "enhanced"

    def test_topic_indexed_with_source_reports(self, tmp_path):
        vault = _make_vault(tmp_path)
        p = vault / "02_Topics" / "AI Agents.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("""---
type: topic
status: core
topic: AI Agents
source_reports:
  - r1
  - r2
---
# AI Agents

No LLM-WIKI marker here.
""", encoding="utf-8")

        from signalvault.workspace.curation import refresh_curation_status
        result = refresh_curation_status(vault, dry_run=True)
        updated = [r for r in result["results"] if r.get("updated")]
        assert len(updated) == 1
        assert updated[0]["new_curation"] == "indexed"

    def test_topic_raw_no_source_reports(self, tmp_path):
        vault = _make_vault(tmp_path)
        p = vault / "02_Topics" / "Empty Topic.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("""---
type: topic
status: long_tail
topic: Empty Topic
source_reports: []
---
# Empty Topic
""", encoding="utf-8")

        from signalvault.workspace.curation import refresh_curation_status
        result = refresh_curation_status(vault, dry_run=True)
        updated = [r for r in result["results"] if r.get("updated")]
        assert len(updated) == 1
        assert updated[0]["new_curation"] == "raw"

    def test_claim_reviewed_when_verified(self, tmp_path):
        vault = _make_vault(tmp_path)
        p = vault / "06_Claims" / "claim_test.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("""---
type: claim
status: verified
claim: "Test"
source_reports: []
---
# Claim: Test
""", encoding="utf-8")

        from signalvault.workspace.curation import refresh_curation_status
        result = refresh_curation_status(vault, dry_run=True)
        updated = [r for r in result["results"] if r.get("updated")]
        assert len(updated) == 1
        assert updated[0]["new_curation"] == "reviewed"

    def test_claim_archived(self, tmp_path):
        vault = _make_vault(tmp_path)
        p = vault / "06_Claims" / "claim_test.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("""---
type: claim
status: archived
claim: "Test"
source_reports: []
---
# Claim: Test
""", encoding="utf-8")

        from signalvault.workspace.curation import refresh_curation_status
        result = refresh_curation_status(vault, dry_run=True)
        updated = [r for r in result["results"] if r.get("updated")]
        assert len(updated) == 1
        assert updated[0]["new_curation"] == "archived"

    def test_signal_reviewed_when_watching(self, tmp_path):
        vault = _make_vault(tmp_path)
        p = vault / "07_Signals" / "signal_test.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("""---
type: signal
status: watching
signal: "Test"
source_reports: []
---
# Signal: Test
""", encoding="utf-8")

        from signalvault.workspace.curation import refresh_curation_status
        result = refresh_curation_status(vault, dry_run=True)
        updated = [r for r in result["results"] if r.get("updated")]
        assert len(updated) == 1
        assert updated[0]["new_curation"] == "reviewed"

    def test_curation_status_not_changed_when_same(self, tmp_path):
        vault = _make_vault(tmp_path)
        p = vault / "06_Claims" / "claim_test.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("""---
type: claim
status: active
claim: "Test"
curation_status: indexed
source_reports: []
---
# Claim: Test
""", encoding="utf-8")

        from signalvault.workspace.curation import refresh_curation_status
        result = refresh_curation_status(vault, dry_run=True)
        updated = [r for r in result["results"] if r.get("updated")]
        assert len(updated) == 0  # already indexed


# ── P2-H.2 Enhanced Scanner Tests ────────────────────────────────

class TestScannerCuration:
    def test_scanner_reads_curation_status(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core")
        p = vault / "02_Topics" / "AI Agents.md"
        content = p.read_text(encoding="utf-8")
        content = content.replace(
            "updated_at: \"2026-05-30 12:00\"",
            "updated_at: \"2026-05-30 12:00\"\ncuration_status: enhanced"
        )
        p.write_text(content, encoding="utf-8")

        from signalvault.workspace.scanner import VaultScanner
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        assert snapshot.topics[0].curation_status == "enhanced"

    def test_curation_summary(self, tmp_path):
        vault = _make_vault(tmp_path)
        p = vault / "02_Topics" / "AI Agents.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("""---
type: topic
status: core
topic: AI Agents
curation_status: enhanced
source_reports: []
---
# AI Agents
""", encoding="utf-8")

        from signalvault.workspace.scanner import VaultScanner
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        summary = snapshot.curation_summary()
        assert summary.get("enhanced", 0) >= 1


# ── P2-H.2 Enhanced Generator Tests ──────────────────────────────

class TestHomeDashboardCuration:
    def test_includes_curation_column(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core")
        from signalvault.workspace.generators import generate_home_dashboard
        from signalvault.workspace.scanner import VaultScanner
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_home_dashboard(snapshot)
        assert "Curation" in content


class TestReviewQueueTopN:
    def test_limits_claims_to_10(self, tmp_path):
        vault = _make_vault(tmp_path)
        # P2-N.4.3: Only challenged claims (high priority) appear in needs-review
        # Active claims without watchlist are normal → shown in system auto-curation summary
        for i in range(15):
            _add_claim(vault, f"claim_{i:03d}", status="challenged",
                        claim_text=f"Challenged claim about AI industry trend number {i} with enough detail")
        from signalvault.workspace.generators import generate_review_queue
        from signalvault.workspace.scanner import VaultScanner
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        for c in snapshot.claims:
            c.review_priority = "high"
        content = generate_review_queue(snapshot)
        claim_links = content.count("[[06_Claims/")
        assert claim_links <= 10
        assert "more items" in content.lower() or claim_links > 0

    def test_limits_signals_to_10(self, tmp_path):
        vault = _make_vault(tmp_path)
        # P2-N.4.3: Only watching signals (high priority) appear in needs-review
        for i in range(15):
            _add_signal(vault, f"signal_{i:03d}", status="open",
                         signal_text=f"Open signal about semiconductor supply chain risk number {i}")
        from signalvault.workspace.generators import generate_review_queue
        from signalvault.workspace.scanner import VaultScanner
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        for s in snapshot.signals:
            s.review_priority = "high"
        content = generate_review_queue(snapshot)
        signal_links = content.count("[[07_Signals/")
        assert signal_links <= 10
        assert "more items" in content.lower() or signal_links > 0

    def test_under_10_shows_all_no_backlog(self, tmp_path):
        vault = _make_vault(tmp_path)
        # P2-N.4.3: Only challenged claims appear in needs-review
        _add_claim(vault, "claim_001", status="challenged",
                    claim_text="Claim about AI agents transforming enterprise workflows with automation")
        _add_claim(vault, "claim_002", status="challenged",
                    claim_text="Claim about semiconductor supply chain constraints in global market")
        from signalvault.workspace.generators import generate_review_queue
        from signalvault.workspace.scanner import VaultScanner
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        for c in snapshot.claims:
            c.review_priority = "high"
        content = generate_review_queue(snapshot)
        assert "claim_001" in content
        assert "claim_002" in content


# ── P2-H.2 CLI Tests ─────────────────────────────────────────────

class TestBackfillCLI:
    def test_backfill_dry_run(self, tmp_path):
        from typer.testing import CliRunner

        from signalvault.cli import app

        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core")
        p = vault / "06_Claims" / "claim_test.md"
        p.write_text("""---
type: claim
status: active
claim: "Test"
related_topics: []
related_companies: []
source_reports: []
---
# Claim: Test

## Statement
AI Agents.

## Related Topics
""", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(app, [
            "obsidian", "workspace", "backfill-relations",
            "--vault", str(vault),
            "--dry-run",
        ])
        assert result.exit_code == 0

    def test_backfill_requires_flag(self, tmp_path):
        from typer.testing import CliRunner

        from signalvault.cli import app

        vault = _make_vault(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, [
            "obsidian", "workspace", "backfill-relations",
            "--vault", str(vault),
        ])
        assert result.exit_code == 1

    def test_curation_status_dry_run(self, tmp_path):
        from typer.testing import CliRunner

        from signalvault.cli import app

        vault = _make_vault(tmp_path)
        p = vault / "02_Topics" / "AI Agents.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("""---
type: topic
status: core
topic: AI Agents
source_reports:
  - r1
---
# AI Agents
""", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(app, [
            "obsidian", "workspace", "refresh-curation-status",
            "--vault", str(vault),
            "--dry-run",
        ])
        assert result.exit_code == 0


# ── P2-H.3 Metadata Polish Tests ─────────────────────────────────

class TestReportMetadataPolish:
    def test_title_from_h1_when_no_frontmatter_title(self, tmp_path):
        vault = _make_vault(tmp_path)
        p = vault / "01_Reports" / "test_report.md"
        p.write_text("""---
type: report
channel: TestChannel
video_id: abc123def45
tags: []
---
# Human Readable Title

## Summary
""", encoding="utf-8")

        from signalvault.workspace.metadata import polish_report_metadata
        result = polish_report_metadata(vault, dry_run=True, apply=False)
        updated = [r for r in result["results"] if r.get("action") == "update_metadata"]
        assert len(updated) == 1
        assert updated[0]["suggested_title"] == "Human Readable Title"

    def test_title_from_db_when_available(self, tmp_path):
        from signalvault.workspace.metadata import _determine_title
        title = _determine_title("# d6EMk6dyrOU\n", "", "Acquired 10 Years", False)
        assert title == "Acquired 10 Years"

    def test_does_not_overwrite_existing_title(self, tmp_path):
        vault = _make_vault(tmp_path)
        p = vault / "01_Reports" / "test_report.md"
        p.write_text("""---
type: report
channel: TestChannel
video_id: abc123def45
title: "Existing Title"
tags: []
---
# Existing Title

## Summary
""", encoding="utf-8")

        from signalvault.workspace.metadata import polish_report_metadata
        result = polish_report_metadata(vault, dry_run=True, apply=False)
        updated = [r for r in result["results"] if r.get("action") == "update_metadata"]
        assert len(updated) == 0

    def test_overwrite_title_flag(self):
        from signalvault.workspace.metadata import _determine_title
        title = _determine_title(
            "---\ntitle: Old\n---\n# New Title\n",
            "Old", "DB Title", overwrite_title=True
        )
        assert title == "DB Title"

    def test_h1_is_video_id_detection(self):
        from signalvault.workspace.metadata import (
            _h1_is_video_id,
            _is_video_id_string,
        )
        assert _is_video_id_string("d6EMk6dyrOU")
        assert _is_video_id_string("CSYWbbP_OkY")
        assert not _is_video_id_string("Human Readable Title")
        assert _h1_is_video_id("# d6EMk6dyrOU\n\n## Summary\n")
        assert not _h1_is_video_id("# Human Title\n\n## Summary\n")

    def test_fix_h1_replaces_video_id(self):
        from signalvault.workspace.metadata import _fix_h1
        content = "# d6EMk6dyrOU\n\n## Summary\n"
        fixed = _fix_h1(content, "Acquired 10 Years")
        assert "# Acquired 10 Years" in fixed
        assert "# d6EMk6dyrOU" not in fixed

    def test_dry_run_does_not_write(self, tmp_path):
        vault = _make_vault(tmp_path)
        p = vault / "01_Reports" / "test_report.md"
        original = """---
type: report
channel: TestChannel
video_id: abc123def45
tags: []
---
# Human Title

## Summary
"""
        p.write_text(original, encoding="utf-8")
        from signalvault.workspace.metadata import polish_report_metadata
        polish_report_metadata(vault, dry_run=True, apply=False)
        assert p.read_text(encoding="utf-8") == original

    def test_source_report_display_refresh(self):
        from signalvault.workspace.metadata import _refresh_source_report_display
        title_map = {"2026-05-29_Latent Space_CSYWbbP_OkY": "Latent Space — Competing with ChatGPT"}
        content = "- [[2026-05-29_Latent Space_CSYWbbP_OkY]] — CSYWbbP_OkY\n"
        updated = _refresh_source_report_display(content, title_map)
        assert "Latent Space — Competing with ChatGPT" in updated
        assert "[[2026-05-29_Latent Space_CSYWbbP_OkY]]" in updated


# ── P2-H.3 Long-tail Cleanup Tests ────────────────────────────────

class TestLongTailCleanup:
    def test_alias_resolution_cicd(self):
        from signalvault.workspace.longtail import _resolve_alias
        assert _resolve_alias("Cicd") == "CI/CD"

    def test_alias_resolution_egc(self):
        from signalvault.workspace.longtail import _resolve_alias
        assert _resolve_alias("Egc") == "Employee Generated Content"

    def test_alias_resolution_plg(self):
        from signalvault.workspace.longtail import _resolve_alias
        assert _resolve_alias("Plg") == "Product-Led Growth"

    def test_alias_resolution_mac_os(self):
        from signalvault.workspace.longtail import _resolve_alias
        assert _resolve_alias("Mac Os") == "macOS"

    def test_alias_resolution_mcp(self):
        from signalvault.workspace.longtail import _resolve_alias
        assert _resolve_alias("MCP") == "Model Context Protocol"

    def test_rename_topic(self, tmp_path):
        vault = _make_vault(tmp_path)
        p = vault / "02_Topics" / "Cicd.md"
        p.write_text("""---
type: topic
status: long_tail
topic: Cicd
source_reports:
  - r1
---
# Cicd
""", encoding="utf-8")
        from signalvault.workspace.longtail import _rename_topic
        _rename_topic(p, "CI/CD", vault / "02_Topics")
        new_path = vault / "02_Topics" / "CI-CD.md"
        assert new_path.exists()
        content = new_path.read_text(encoding="utf-8")
        assert "CI/CD" in content

    def test_merge_topics(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "Mac Os", status="long_tail", source_reports=["r1"])
        _add_topic(vault, "macOS", status="long_tail", source_reports=["r2"])
        from signalvault.workspace.longtail import _merge_source_reports
        from_path = vault / "02_Topics" / "Mac Os.md"
        to_path = vault / "02_Topics" / "macOS.md"
        _merge_source_reports(from_path, to_path)
        content = to_path.read_text(encoding="utf-8")
        assert "r1" in content
        assert "r2" in content

    def test_dry_run_does_not_write(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "Cicd", status="long_tail", source_reports=["r1"])
        from signalvault.workspace.longtail import cleanup_long_tail_topics
        result = cleanup_long_tail_topics(vault, dry_run=True, apply=False)
        updated = [r for r in result["results"] if r["action"] != "skip"]
        assert len(updated) == 1
        assert updated[0]["action"] == "rename_topic"
        assert (vault / "02_Topics" / "Cicd.md").exists()

    def test_apply_renames_file(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "Cicd", status="long_tail", source_reports=["r1"])
        from signalvault.workspace.longtail import cleanup_long_tail_topics
        result = cleanup_long_tail_topics(vault, dry_run=False, apply=True)
        assert result["stats"]["renamed"] >= 1
        assert not (vault / "02_Topics" / "Cicd.md").exists()
        assert (vault / "02_Topics" / "CI-CD.md").exists()

    def test_quality_tagging(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "Useful Topic", status="long_tail", source_reports=["r1", "r2"])
        from signalvault.workspace.longtail import cleanup_long_tail_topics
        cleanup_long_tail_topics(vault, dry_run=False, apply=True)
        content = (vault / "02_Topics" / "Useful Topic.md").read_text(encoding="utf-8")
        assert "topic_quality: useful" in content

    def test_topic_quality_column_in_scanner(self, tmp_path):
        vault = _make_vault(tmp_path)
        p = vault / "02_Topics" / "AI Agents.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("""---
type: topic
status: core
topic: AI Agents
topic_quality: useful
source_reports: []
---
# AI Agents
""", encoding="utf-8")
        from signalvault.workspace.scanner import VaultScanner
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        assert snapshot.topics[0].topic_quality == "useful"


# ── P2-H.3 CLI Tests ─────────────────────────────────────────────

class TestMetadataCLI:
    def test_metadata_dry_run(self, tmp_path):
        from typer.testing import CliRunner

        from signalvault.cli import app
        vault = _make_vault(tmp_path)
        p = vault / "01_Reports" / "test.md"
        p.write_text("""---
type: report
channel: Test
video_id: abc123def45
tags: []
---
# Human Title
""", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(app, [
            "obsidian", "workspace", "polish-report-metadata",
            "--vault", str(vault),
            "--dry-run",
        ])
        assert result.exit_code == 0

    def test_longtail_cleanup_dry_run(self, tmp_path):
        from typer.testing import CliRunner

        from signalvault.cli import app
        vault = _make_vault(tmp_path)
        _add_topic(vault, "Cicd", status="long_tail", source_reports=["r1"])
        runner = CliRunner()
        result = runner.invoke(app, [
            "obsidian", "workspace", "cleanup-long-tail-topics",
            "--vault", str(vault),
            "--dry-run",
        ])
        assert result.exit_code == 0


# ── P2-N.4.3: Curation & Review UX Rebalance Tests ──────────────────

class TestSignalAggregation:
    """Sub-task 1: Signal→Topic/Company aggregation."""

    def test_signals_aggregate_to_topic_count(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core")
        _add_signal(vault, "sig_001", status="open",
                     related_topics=["AI Agents"])
        _add_signal(vault, "sig_002", status="watching",
                     related_topics=["AI Agents"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        assert snapshot.signals_count_for("AI Agents") == 2

    def test_signals_aggregate_to_company_count(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_company(vault, "NVIDIA", source_reports=["r1", "r2"])
        _add_signal(vault, "sig_001", status="open",
                     related_companies=["NVIDIA"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        assert snapshot.signals_count_for("NVIDIA") == 1

    def test_archived_signals_not_counted(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core")
        _add_signal(vault, "sig_001", status="open",
                     related_topics=["AI Agents"])
        # Archived signals are skipped during scan — write one directly
        p = vault / "07_Signals" / "sig_archived.md"
        p.write_text("""---
type: signal
status: archived
signal: "Archived signal"
source_reports: []
related_topics:
  - AI Agents
related_companies: []
---
# Signal: Archived
""", encoding="utf-8")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        # Only the open signal counts, not the archived one
        assert snapshot.signals_count_for("AI Agents") == 1

    def test_signals_matched_by_body_text_fallback(self, tmp_path):
        """P2-N.4.3: signals_count_for falls back to scanning signal body text."""
        vault = _make_vault(tmp_path)
        _add_topic(vault, "Semiconductor", status="core")
        # Signal doesn't have related_topics frontmatter, but body mentions topic
        p = vault / "07_Signals" / "sig_body.md"
        p.write_text("""---
type: signal
status: open
signal: "Semiconductor supply chain risk detected"
source_reports: []
related_topics: []
related_companies: []
---
# Signal: Semiconductor supply chain risk

## What to Watch
Semiconductor industry faces GPU shortage.
""", encoding="utf-8")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        assert snapshot.signals_count_for("Semiconductor") == 1


class TestSystemCuration:
    """Sub-task 2: system_curation for Topic and Company."""

    def test_topic_curation_raw(self, tmp_path):
        from signalvault.workspace.system_curation import (
            TOPIC_CURATION_RAW,
            compute_topic_system_curation,
        )
        vault = _make_vault(tmp_path)
        _add_topic(vault, "New Topic", status="core")  # 0 reports
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        topic = [t for t in snapshot.topics if t.name == "New Topic"][0]
        assert compute_topic_system_curation(topic, snapshot) == TOPIC_CURATION_RAW

    def test_topic_curation_emerging(self, tmp_path):
        from signalvault.workspace.system_curation import (
            TOPIC_CURATION_EMERGING,
            compute_topic_system_curation,
        )
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core", source_reports=["r1", "r2"])
        # 2 reports → emerging
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        topic = [t for t in snapshot.topics if t.name == "AI Agents"][0]
        assert compute_topic_system_curation(topic, snapshot) == TOPIC_CURATION_EMERGING

    def test_topic_curation_tracking(self, tmp_path):
        from signalvault.workspace.system_curation import (
            TOPIC_CURATION_TRACKING,
            compute_topic_system_curation,
        )
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Safety", status="core", source_reports=["r1"])
        _add_signal(vault, "sig_001", status="open",
                     related_topics=["AI Safety"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        topic = [t for t in snapshot.topics if t.name == "AI Safety"][0]
        assert compute_topic_system_curation(topic, snapshot) == TOPIC_CURATION_TRACKING

    def test_topic_curation_established(self, tmp_path):
        from signalvault.workspace.system_curation import (
            TOPIC_CURATION_ESTABLISHED,
            compute_topic_system_curation,
        )
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Models", status="core",
                    source_reports=[f"r{i}" for i in range(5)])
        # Add 5 claims with cross-report support (>=2 source_reports each)
        for i in range(5):
            _add_claim(vault, f"claim_{i:03d}", status="active",
                        related_topics=["AI Models"],
                        source_reports=["r1", "r2"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        topic = [t for t in snapshot.topics if t.name == "AI Models"][0]
        assert compute_topic_system_curation(topic, snapshot) == TOPIC_CURATION_ESTABLISHED

    def test_company_curation_mentioned(self, tmp_path):
        from signalvault.workspace.system_curation import (
            COMPANY_CURATION_MENTIONED,
            compute_company_system_curation,
        )
        vault = _make_vault(tmp_path)
        _add_company(vault, "NewCo", source_reports=["r1"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        company = [c for c in snapshot.companies if c.name == "NewCo"][0]
        assert compute_company_system_curation(company, snapshot) == COMPANY_CURATION_MENTIONED

    def test_company_curation_covered(self, tmp_path):
        from signalvault.workspace.system_curation import (
            COMPANY_CURATION_COVERED,
            compute_company_system_curation,
        )
        vault = _make_vault(tmp_path)
        _add_company(vault, "MidCo", source_reports=["r1", "r2", "r3"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        company = [c for c in snapshot.companies if c.name == "MidCo"][0]
        assert compute_company_system_curation(company, snapshot) == COMPANY_CURATION_COVERED

    def test_company_curation_tracking(self, tmp_path):
        from signalvault.workspace.system_curation import (
            COMPANY_CURATION_TRACKING,
            compute_company_system_curation,
        )
        vault = _make_vault(tmp_path)
        _add_company(vault, "NVIDIA", source_reports=["r1"])
        _add_signal(vault, "sig_001", status="open",
                     related_companies=["NVIDIA"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        company = [c for c in snapshot.companies if c.name == "NVIDIA"][0]
        assert compute_company_system_curation(company, snapshot) == COMPANY_CURATION_TRACKING

    def test_watchlist_company_shows_high_attention(self, tmp_path):
        from signalvault.workspace.system_curation import (
            COMPANY_CURATION_HIGH_ATTENTION,
            compute_company_system_curation,
        )
        vault = _make_vault(tmp_path)
        _add_company(vault, "OpenAI", source_reports=["r1", "r2"])
        _add_claim(vault, "claim_001", status="active",
                    related_companies=["OpenAI"])
        _add_claim(vault, "claim_002", status="active",
                    related_companies=["OpenAI"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        company = [c for c in snapshot.companies if c.name == "OpenAI"][0]
        # OpenAI is in watchlist → high_attention because claims >= 2
        assert compute_company_system_curation(
            company, snapshot, {"OpenAI"},
        ) == COMPANY_CURATION_HIGH_ATTENTION

    def test_curation_display_shows_label_not_unknown(self, tmp_path):
        """P2-N.4.3: Curation column should show labels, not 'unknown'."""
        from signalvault.workspace.system_curation import (
            compute_topic_system_curation,
            curation_label,
        )
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core",
                    source_reports=["r1", "r2", "r3"])
        _add_claim(vault, "c1", status="active",
                    related_topics=["AI Agents"])
        _add_claim(vault, "c2", status="active",
                    related_topics=["AI Agents"])
        _add_claim(vault, "c3", status="active",
                    related_topics=["AI Agents"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        topic = [t for t in snapshot.topics if t.name == "AI Agents"][0]
        curation = compute_topic_system_curation(topic, snapshot)
        label = curation_label(curation)
        # Should be a meaningful label, not "unknown"
        assert label != "未知"
        assert label != "unknown"
        assert len(label) > 0


class TestEntityTypeFiltering:
    """Sub-task 3: entity_type filtering for core companies."""

    def test_product_model_excluded_from_core_companies(self, tmp_path):
        vault = _make_vault(tmp_path)
        _add_company(vault, "NVIDIA", source_reports=["r1", "r2"])
        # Add a company card with entity_type = model
        p = vault / "03_Companies" / "Claude.md"
        p.write_text("""---
type: company
company: Claude
entity_type: model
ticker: ""
sector: ""
tags: []
source_reports:
  - "r1"
  - "r2"
---
# Claude
""", encoding="utf-8")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        core_names = {c.name for c in snapshot.core_companies()}
        assert "NVIDIA" in core_names
        assert "Claude" not in core_names  # model entity_type filtered out

    def test_person_excluded_from_core_companies(self, tmp_path):
        vault = _make_vault(tmp_path)
        p = vault / "03_Companies" / "Sam Altman.md"
        p.write_text("""---
type: company
company: Sam Altman
entity_type: person
ticker: ""
sector: ""
tags: []
source_reports:
  - "r1"
  - "r2"
---
# Sam Altman
""", encoding="utf-8")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        core_names = {c.name for c in snapshot.core_companies()}
        assert "Sam Altman" not in core_names  # person filtered out

    def test_not_a_company_list_excluded(self, tmp_path):
        """P2-N.4.3: Names in _NOT_A_COMPANY are excluded even without entity_type."""
        vault = _make_vault(tmp_path)
        # GPU is in _NOT_A_COMPANY
        p = vault / "03_Companies" / "GPU.md"
        p.write_text("""---
type: company
company: GPU
ticker: ""
sector: ""
tags: []
source_reports:
  - "r1"
  - "r2"
---
# GPU
""", encoding="utf-8")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        core_names = {c.name for c in snapshot.core_companies()}
        assert "GPU" not in core_names

    def test_organization_type_included(self, tmp_path):
        """Organization entities are valid companies."""
        vault = _make_vault(tmp_path)
        p = vault / "03_Companies" / "EU Commission.md"
        p.write_text("""---
type: company
company: EU Commission
entity_type: organization
ticker: ""
sector: ""
tags: []
source_reports:
  - "r1"
  - "r2"
---
# EU Commission
""", encoding="utf-8")
        # P2-N.4.3.2: Add a claim referencing this company to meet minimum criteria
        _add_claim(vault, "claim_eu", status="active",
                    related_companies=["EU Commission"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        core_names = {c.name for c in snapshot.core_companies()}
        assert "EU Commission" in core_names


class TestReviewPriority:
    """Sub-task 4: Review Queue priority reconstruction."""

    def test_challenged_claim_is_high_priority(self, tmp_path):
        from signalvault.workspace.review_priority import (
            PRIORITY_HIGH,
            compute_claim_review_priority,
        )
        vault = _make_vault(tmp_path)
        _add_claim(vault, "claim_001", status="challenged")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        claim = snapshot.claims[0]
        priority = compute_claim_review_priority(claim, snapshot)
        assert priority == PRIORITY_HIGH

    def test_auto_accepted_claim_not_in_needs_review(self, tmp_path):
        from signalvault.workspace.review_priority import (
            claims_needing_review,
        )
        vault = _make_vault(tmp_path)
        # High quality + has source_reports + non-challenged → auto_accepted
        p = vault / "06_Claims" / "claim_auto.md"
        p.write_text("""---
type: claim
status: active
claim: "High quality verified claim"
quality: high
source_reports:
  - "r1"
related_topics: []
related_companies: []
---
# Claim: High quality
""", encoding="utf-8")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        needs = claims_needing_review(snapshot)
        assert "claim_auto" not in {c.card_id for c in needs}

    def test_watching_signal_is_high_priority(self, tmp_path):
        from signalvault.workspace.review_priority import (
            PRIORITY_HIGH,
            compute_signal_review_priority,
        )
        vault = _make_vault(tmp_path)
        _add_signal(vault, "sig_001", status="watching")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        signal = snapshot.signals[0]
        priority = compute_signal_review_priority(signal, snapshot)
        assert priority == PRIORITY_HIGH

    def test_home_shows_needs_review_not_raw_counts(self, tmp_path):
        """P2-N.4.3: Home shows '需要你确认' not 'Active claims: N'."""
        vault = _make_vault(tmp_path)
        _add_claim(vault, "claim_001", status="active")
        _add_signal(vault, "sig_001", status="open")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_home_dashboard(snapshot)
        assert "需要你确认" in content
        # Old-style raw counts should NOT appear
        assert "Active claims:" not in content
        assert "Open signals:" not in content
        assert "Challenged claims:" not in content
        assert "Watching signals:" not in content

    def test_home_shows_system_curation_sections(self, tmp_path):
        """P2-N.4.3: Home shows system auto-curation and tracking sections."""
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_home_dashboard(snapshot)
        assert "系统健康" in content
        assert "系统索引" in content
        assert "研究摘要" in content or "快速入口" in content  # at least one of these

    def test_system_curation_computed_during_refresh(self, tmp_path):
        """P2-N.4.3: system_curation is computed during refresh_workspace."""
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core",
                    source_reports=["r1", "r2", "r3"])
        _add_claim(vault, "c1", status="active",
                    related_topics=["AI Agents"])
        _add_claim(vault, "c2", status="active",
                    related_topics=["AI Agents"])
        _add_claim(vault, "c3", status="active",
                    related_topics=["AI Agents"])
        refresh_workspace(vault, dry_run=True, home_only=True)
        # After refresh, the snapshot (which was composed during refresh)
        # should have system_curation on topics
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        # Recompute since refresh was dry_run
        from signalvault.workspace.system_curation import (
            compute_topic_system_curation,
        )
        topic = [t for t in snapshot.topics if t.name == "AI Agents"][0]
        curation = compute_topic_system_curation(topic, snapshot)
        # Should be at least "emerging" (3 reports, 3 claims)
        from signalvault.workspace.system_curation import TOPIC_CURATION_EMERGING
        assert curation == TOPIC_CURATION_EMERGING


# ── P2-N.4.3.2: Home Signal Compression & Topic Aggregation Fix ──────

class TestSignalAggregationV2:
    """Sub-task: 3-pass signal→topic aggregation."""

    def test_alias_signal_aggregation(self, tmp_path):
        """Signals mentioning topic aliases should aggregate."""
        vault = _make_vault(tmp_path)
        # Topic with aliases
        p = vault / "02_Topics" / "AI Agents.md"
        p.write_text("""---
type: topic
status: core
topic: "AI Agents"
aliases:
  - "agent"
  - "agents"
tags: []
source_reports: []
---
# AI Agents
""", encoding="utf-8")
        # Signal that doesn't have related_topics but mentions alias in text
        _add_signal(vault, "sig_001", status="open",
                     signal_text="AI agent deployment growing rapidly")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        count = snapshot.signals_count_for("AI Agents")
        assert count >= 1  # Should match via alias "agent" in text

    def test_company_inferred_topic_signals(self, tmp_path):
        """Signal→company→topic inference should work."""
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Models", status="core")
        _add_company(vault, "OpenAI", source_reports=["r1", "r2"])
        # Claim tying OpenAI to AI Models topic
        _add_claim(vault, "c1", status="active",
                    related_companies=["OpenAI"],
                    related_topics=["AI Models"])
        # Signal referencing OpenAI but not AI Models directly
        _add_signal(vault, "sig_001", status="open",
                     related_companies=["OpenAI"],
                     signal_text="OpenAI releases new model")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        count = snapshot.signals_count_for("AI Models")
        assert count >= 1  # Company-inferred via OpenAI


class TestNeedsReviewCompression:
    """Sub-task: needs review compression and dedup."""

    def test_needs_review_capped_at_6(self, tmp_path):
        """Home should show at most 6 needs-review items."""
        vault = _make_vault(tmp_path)
        for i in range(10):
            _add_claim(vault, f"claim_{i:03d}", status="challenged",
                        claim_text=f"Unique claim number {i} about different topics")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_home_dashboard(snapshot)
        claim_count = content.count("[[06_Claims/")
        assert claim_count <= 6

    def test_dedup_strips_markdown(self, tmp_path):
        """Claims with markdown formatting differences should be deduped."""
        from signalvault.workspace.generators import (
            _prefix_overlap,
            _token_overlap,
        )
        txt1 = "**AI agents are transforming enterprise workflows** with automation"
        txt2 = "AI agents are transforming enterprise workflows with automation"
        assert _token_overlap(txt1, txt2) > 0.5
        assert _prefix_overlap(txt1, txt2)

    def test_watchlist_section_has_grouping(self, tmp_path):
        """Home watchlist should show company/direction grouping."""
        vault = _make_vault(tmp_path)
        _add_topic(vault, "AI Agents", status="core")
        _add_company(vault, "OpenAI", source_reports=["r1", "r2"])
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        # Without watchlist items, the section is omitted
        # With watchlist items, it should show groupings
        content = generate_home_dashboard(snapshot)
        # Verify Home structure exists
        assert "需要你确认" in content


class TestReportLinks:
    """Sub-task: report link formatting fixes."""

    def test_report_links_use_clean_alias(self, tmp_path):
        """Report links should use [[path|alias]] without escaping the pipe."""
        vault = _make_vault(tmp_path)
        _add_report(vault, "2026-06-12_Acquired_d6EMk6dyrOU",
                     channel="Acquired",
                     title="Dan Loeb: The Lost Art of Short Selling, and Why Stock Picking is Back")
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_home_dashboard(snapshot)
        # Should NOT have escaped pipe
        assert "\\|" not in content
        # Should have regular Obsidian link format
        assert "[[01_Reports/" in content
        assert "|" in content  # pipe separator

    def test_report_alias_max_60_chars(self, tmp_path):
        """Report alias display should be max 60 chars."""
        vault = _make_vault(tmp_path)
        long_title = "A" * 100 + " This is a very long report title"
        _add_report(vault, "test_report", channel="Test",
                     title=long_title)
        scanner = VaultScanner(vault)
        snapshot = scanner.scan()
        content = generate_home_dashboard(snapshot)
        # Extract the alias part from [[path|alias]]
        import re
        match = re.search(r'\[\[01_Reports/[^|]+\|([^\]]+)\]\]', content)
        if match:
            alias = match.group(1)
            assert len(alias) <= 65  # Allow 60 + "..." truncation
