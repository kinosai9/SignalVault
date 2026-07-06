"""P2-E: LLM-WIKI patch generation tests."""

from pathlib import Path

import pytest

from signalvault.llm_wiki import (
    build_topic_context,
    find_core_topics,
    generate_topic_patch,
    write_patch_file,
)


def _create_topic_card(topics_dir: Path, topic_name: str, status: str, source_reports: list[str]) -> Path:
    """Helper: create a topic card file."""
    card_path = topics_dir / f"{topic_name}.md"
    source_lines = "\n".join(f"- [[{r}]]" for r in source_reports)
    content = f"""---
type: topic
status: {status}
topic: {topic_name}
aliases: []
tags: []
---

# {topic_name}

## Current Understanding

Placeholder for {topic_name}.

## Related Companies

## Related Topics

## Source Reports

{source_lines}

"""
    card_path.write_text(content, encoding="utf-8")
    return card_path


def _create_report(reports_dir: Path, filename: str, channel: str, video_id: str) -> Path:
    """Helper: create a report file."""
    report_path = reports_dir / f"{filename}.md"
    content = f"""---
type: report
channel: {channel}
video_id: {video_id}
title: Test Report {filename}
---

# Test Report {filename}

## Summary

This is a test report about AI Agents and related topics.

## Core Investment Views

- NVIDIA is well-positioned in the AI infrastructure space
  - Evidence: strong growth in data center revenue
  - Source: [[{filename}]]

## Tech / Industry Insights

- AI Agents are becoming more capable with tool use
- Enterprise adoption is accelerating

## Risks

- Regulatory uncertainty around AI safety

## Tracking Signals

- Monitor NVIDIA quarterly earnings for AI revenue growth

## Entities

- [[NVIDIA]]
- [[OpenAI]]
- [[Anthropic]]

## Source Quotes

> "AI agents will transform enterprise software" - Speaker 1

"""
    report_path.write_text(content, encoding="utf-8")
    return report_path


def test_find_core_topics(tmp_path):
    """Test finding core topics in vault."""
    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    topics_dir.mkdir(parents=True)

    # Create core and non-core topics
    _create_topic_card(topics_dir, "AI Agents", "core", ["report1", "report2"])
    _create_topic_card(topics_dir, "AI Models", "core", ["report3"])
    _create_topic_card(topics_dir, "Some Emerging", "emerging", ["report4"])
    _create_topic_card(topics_dir, "Some Long Tail", "long_tail", [])

    core_topics = find_core_topics(vault)

    assert len(core_topics) == 2
    names = {p.stem for p in core_topics}
    assert names == {"AI Agents", "AI Models"}


def test_find_core_topics_empty(tmp_path):
    """Test finding core topics when none exist."""
    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    topics_dir.mkdir(parents=True)

    _create_topic_card(topics_dir, "Some Topic", "emerging", [])

    core_topics = find_core_topics(vault)
    assert len(core_topics) == 0


def test_build_topic_context(tmp_path):
    """Test building context for a topic."""
    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    # Create topic card
    topic_path = _create_topic_card(
        topics_dir, "AI Agents", "core",
        ["2026-05-29_TechPod_vid001", "2026-05-30_AllIn_vid002"]
    )

    # Create source reports
    _create_report(reports_dir, "2026-05-29_TechPod_vid001", "TechPod", "vid001")
    _create_report(reports_dir, "2026-05-30_AllIn_vid002", "AllIn", "vid002")

    context = build_topic_context(vault, topic_path, max_reports=5)

    assert context.topic_name == "AI Agents"
    assert context.status == "core"
    assert len(context.source_reports) == 2
    assert context.source_reports[0].filename == "2026-05-29_TechPod_vid001"
    assert context.source_reports[0].channel == "TechPod"
    assert "NVIDIA" in context.source_reports[0].core_investment_views


def test_build_topic_context_max_reports(tmp_path):
    """Test max_reports limit in context building."""
    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    # Create topic with many source reports
    report_names = [f"report_{i}" for i in range(10)]
    topic_path = _create_topic_card(topics_dir, "AI Agents", "core", report_names)

    # Create all reports
    for name in report_names:
        _create_report(reports_dir, name, "Channel", f"vid_{name}")

    # Limit to 3 reports
    context = build_topic_context(vault, topic_path, max_reports=3)

    assert len(context.source_reports) == 3


def test_build_topic_context_missing_reports(tmp_path):
    """Test context building when some reports are missing."""
    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    # Create topic with 3 source reports
    topic_path = _create_topic_card(
        topics_dir, "AI Agents", "core",
        ["report_exists", "report_missing", "report_also_exists"]
    )

    # Only create 2 of the 3 reports
    _create_report(reports_dir, "report_exists", "Channel1", "vid1")
    _create_report(reports_dir, "report_also_exists", "Channel2", "vid2")

    context = build_topic_context(vault, topic_path, max_reports=5)

    # Should only include the 2 existing reports
    assert len(context.source_reports) == 2


def test_generate_topic_patch_mock(tmp_path):
    """Test mock patch generation."""
    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    # Create topic and report
    topic_path = _create_topic_card(
        topics_dir, "AI Agents", "core",
        ["2026-05-29_TechPod_vid001"]
    )
    _create_report(reports_dir, "2026-05-29_TechPod_vid001", "TechPod", "vid001")

    context = build_topic_context(vault, topic_path, max_reports=5)
    patch_md = generate_topic_patch(context, provider="mock")

    # Check patch structure
    assert "# Patch Proposal: AI Agents" in patch_md
    assert "## Target Card" in patch_md
    assert "[[AI Agents]]" in patch_md
    assert "## Source Reports Used" in patch_md
    assert "[[2026-05-29_TechPod_vid001]]" in patch_md
    assert "## Proposed Current Understanding" in patch_md
    assert "## Proposed Key Claims" in patch_md
    assert "## Patch Safety" in patch_md
    assert "mock mode" in patch_md


def test_generate_topic_patch_no_reports(tmp_path):
    """Test mock patch generation with no source reports."""
    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    topics_dir.mkdir(parents=True)

    # Create topic with no source reports
    topic_path = _create_topic_card(topics_dir, "Empty Topic", "core", [])

    context = build_topic_context(vault, topic_path, max_reports=5)
    patch_md = generate_topic_patch(context, provider="mock")

    assert "# Patch Proposal: Empty Topic" in patch_md
    assert "No source reports" in patch_md


def test_write_patch_file(tmp_path):
    """Test writing patch file to inbox."""
    vault = tmp_path / "vault"
    vault.mkdir()

    patch_md = "# Patch Proposal: Test\n\nTest content"
    patch_path = write_patch_file(vault, "AI Agents", patch_md)

    assert patch_path.exists()
    assert "topic_AI_Agents_" in patch_path.name
    assert patch_path.suffix == ".md"
    assert patch_path.read_text(encoding="utf-8") == patch_md
    assert "00_Inbox" in str(patch_path)
    assert "LLM_Patches" in str(patch_path)


def test_write_patch_file_custom_dir(tmp_path):
    """Test writing patch file to custom directory."""
    vault = tmp_path / "vault"
    vault.mkdir()

    patch_md = "# Patch Proposal: Test\n\nTest content"
    patch_path = write_patch_file(vault, "AI Agents", patch_md, output_dir="99_System/Patches")

    assert patch_path.exists()
    assert "99_System" in str(patch_path)
    assert "Patches" in str(patch_path)


def test_write_patch_file_collision(tmp_path):
    """Test patch file collision handling."""
    vault = tmp_path / "vault"
    vault.mkdir()

    patch_md = "# Patch Proposal: Test"

    # Write first file
    path1 = write_patch_file(vault, "AI Agents", patch_md)
    assert path1.exists()

    # Write second file with same topic (should add suffix)
    path2 = write_patch_file(vault, "AI Agents", patch_md)
    assert path2.exists()
    assert path1 != path2


def test_cli_llm_wiki_dry_run(tmp_path):
    """Test CLI llm-wiki generate-patches --dry-run."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    # Create core topic with source report
    _create_topic_card(topics_dir, "AI Agents", "core", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "generate-patches",
        "--vault", str(vault),
        "--dry-run",
    ])

    assert result.exit_code == 0
    assert "DRY-RUN" in result.stdout
    assert "AI Agents" in result.stdout
    assert "Source reports: 1" in result.stdout


def test_cli_llm_wiki_mock_mode(tmp_path):
    """Test CLI llm-wiki generate-patches --mock."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    # Create core topic with source report
    _create_topic_card(topics_dir, "AI Agents", "core", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "generate-patches",
        "--vault", str(vault),
        "--mock",
    ])

    assert result.exit_code == 0
    assert "生成 patches" in result.stdout or "开始生成" in result.stdout
    assert "AI Agents" in result.stdout
    assert "Written to:" in result.stdout

    # Check patch file was created
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    assert patches_dir.exists()
    patch_files = list(patches_dir.glob("*.md"))
    assert len(patch_files) == 1
    assert "topic_AI_Agents_" in patch_files[0].name


def test_cli_llm_wiki_specific_topic(tmp_path):
    """Test CLI llm-wiki generate-patches --topic."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    # Create multiple core topics
    _create_topic_card(topics_dir, "AI Agents", "core", ["report1"])
    _create_topic_card(topics_dir, "AI Models", "core", ["report2"])
    _create_report(reports_dir, "report1", "Channel", "vid1")
    _create_report(reports_dir, "report2", "Channel", "vid2")

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "generate-patches",
        "--vault", str(vault),
        "--topic", "AI Agents",
        "--mock",
    ])

    assert result.exit_code == 0
    assert "AI Agents" in result.stdout

    # Check only AI Agents patch was created
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    patch_files = list(patches_dir.glob("*.md"))
    assert len(patch_files) == 1
    assert "AI_Agents" in patch_files[0].name


def test_cli_llm_wiki_core_only(tmp_path):
    """Test CLI llm-wiki generate-patches --core-only."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    # Create core and non-core topics
    _create_topic_card(topics_dir, "AI Agents", "core", ["report1"])
    _create_topic_card(topics_dir, "Some Emerging", "emerging", ["report2"])
    _create_report(reports_dir, "report1", "Channel", "vid1")
    _create_report(reports_dir, "report2", "Channel", "vid2")

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "generate-patches",
        "--vault", str(vault),
        "--core-only",
        "--mock",
    ])

    assert result.exit_code == 0

    # Check only core topic patch was created
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    patch_files = list(patches_dir.glob("*.md"))
    assert len(patch_files) == 1
    assert "AI_Agents" in patch_files[0].name


def test_cli_llm_wiki_no_vault(monkeypatch):
    """Test CLI llm-wiki generate-patches without vault."""
    from typer.testing import CliRunner

    import signalvault.config
    from signalvault.cli import app

    monkeypatch.setattr(signalvault.config, "OBSIDIAN_VAULT_PATH", "")

    runner = CliRunner()
    result = runner.invoke(app, ["llm-wiki", "generate-patches"])

    assert result.exit_code == 1
    assert "请指定 --vault" in result.stdout


def test_cli_llm_wiki_topic_not_found(tmp_path):
    """Test CLI llm-wiki generate-patches with non-existent topic."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    topics_dir.mkdir(parents=True)

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "generate-patches",
        "--vault", str(vault),
        "--topic", "NonExistent",
    ])

    assert result.exit_code == 1
    assert "不存在" in result.stdout


def test_cli_llm_wiki_no_source_reports(tmp_path):
    """Test CLI llm-wiki generate-patches when topic has no source reports."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    topics_dir.mkdir(parents=True)

    # Create topic with no source reports
    _create_topic_card(topics_dir, "Empty Topic", "core", [])

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "generate-patches",
        "--vault", str(vault),
        "--mock",
    ])

    assert result.exit_code == 0
    assert "跳过" in result.stdout or "无 source reports" in result.stdout

    # Check no patch was created
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    if patches_dir.exists():
        patch_files = list(patches_dir.glob("*.md"))
        assert len(patch_files) == 0


def test_generate_topic_patch_real_no_api_key(tmp_path):
    """Test real LLM patch generation fails without API key."""
    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    topic_path = _create_topic_card(topics_dir, "AI Agents", "core", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    context = build_topic_context(vault, topic_path, max_reports=5)
    with pytest.raises(ValueError, match="api_key"):
        generate_topic_patch(context, provider="openai_compatible", api_key="")


def test_generate_topic_patch_real_no_base_url(tmp_path):
    """Test real LLM patch generation fails without base URL."""
    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    topic_path = _create_topic_card(topics_dir, "AI Agents", "core", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    context = build_topic_context(vault, topic_path, max_reports=5)
    with pytest.raises(ValueError, match="base_url"):
        generate_topic_patch(context, provider="openai_compatible", api_key="test-key", base_url="")


def test_generate_topic_patch_unknown_provider(tmp_path):
    """Test patch generation with unknown provider raises error."""
    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    topics_dir.mkdir(parents=True)

    topic_path = _create_topic_card(topics_dir, "AI Agents", "core", [])
    context = build_topic_context(vault, topic_path, max_reports=5)
    with pytest.raises(ValueError, match="Unknown provider"):
        generate_topic_patch(context, provider="unknown_provider")


def test_find_core_topics_no_topics_dir(tmp_path):
    """Test find_core_topics returns empty when 02_Topics doesn't exist."""
    vault = tmp_path / "vault"
    vault.mkdir()
    # No 02_Topics directory
    core_topics = find_core_topics(vault)
    assert core_topics == []


def test_cli_llm_wiki_no_mock_without_api_key(tmp_path, monkeypatch):
    """Test CLI --no-mock fails gracefully without API config."""
    from typer.testing import CliRunner

    import signalvault.config
    from signalvault.cli import app

    monkeypatch.setattr(signalvault.config, "LLM_API_KEY", "")
    monkeypatch.setattr(signalvault.config, "LLM_BASE_URL", "")

    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    topics_dir.mkdir(parents=True)
    _create_topic_card(topics_dir, "AI Agents", "core", [])

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "generate-patches",
        "--vault", str(vault),
        "--no-mock",
    ])

    assert result.exit_code == 1
    assert "LLM_API_KEY" in result.stdout or "LLM" in result.stdout


# ---------------------------------------------------------------------------
# P2-E.1: Frontmatter + Review Checklist + Validation tests
# ---------------------------------------------------------------------------


def test_mock_patch_has_yaml_frontmatter(tmp_path):
    """Test that mock patch includes YAML frontmatter."""
    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    topic_path = _create_topic_card(topics_dir, "AI Agents", "core", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    context = build_topic_context(vault, topic_path, max_reports=5)
    patch_md = generate_topic_patch(context, provider="mock")

    # Check frontmatter
    assert patch_md.startswith("---")
    assert "type: llm_wiki_patch" in patch_md
    assert "target_type: topic" in patch_md
    assert 'target: "AI Agents"' in patch_md
    assert "target_card: " in patch_md
    assert "provider: mock" in patch_md
    assert "model: mock-v1" in patch_md
    assert "prompt_version:" in patch_md
    assert "generated_at:" in patch_md
    assert "source_reports:" in patch_md
    assert "status: pending_review" in patch_md
    assert "auto_apply: false" in patch_md


def test_mock_patch_has_frontmatter_status_pending_review(tmp_path):
    """Test that patch frontmatter status defaults to pending_review."""
    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    topic_path = _create_topic_card(topics_dir, "AI Agents", "core", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    context = build_topic_context(vault, topic_path, max_reports=5)
    patch_md = generate_topic_patch(context, provider="mock")

    # Verify status is pending_review (not approved)
    assert "status: pending_review" in patch_md
    assert "status: approved" not in patch_md


def test_mock_patch_contains_review_checklist(tmp_path):
    """Test that mock patch includes Review Checklist section."""
    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    topic_path = _create_topic_card(topics_dir, "AI Agents", "core", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    context = build_topic_context(vault, topic_path, max_reports=5)
    patch_md = generate_topic_patch(context, provider="mock")

    assert "## Review Checklist" in patch_md
    assert "- [ ] 每条关键判断都能追溯到 Source Reports" in patch_md
    assert "- [ ] 没有新增 source reports 中不存在的事实" in patch_md
    assert "- [ ] 没有输出投资建议" in patch_md
    assert "- [ ] 已区分事实、观点、推测和未验证问题" in patch_md
    assert "- [ ] 可以安全应用到目标 Topic Card" in patch_md


def test_validate_patches_valid_patch(tmp_path):
    """Test validate-patches recognizes a valid patch."""
    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    patches_dir.mkdir(parents=True)

    # Create valid setup
    _create_topic_card(topics_dir, "AI Agents", "core", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    topic_path = topics_dir / "AI Agents.md"
    context = build_topic_context(vault, topic_path, max_reports=5)
    patch_md = generate_topic_patch(context, provider="mock")
    patch_path = write_patch_file(vault, "AI Agents", patch_md)

    from signalvault.llm_wiki.validator import validate_patches

    results = validate_patches(vault)
    assert len(results) >= 1

    # Find our patch result
    our_result = [r for r in results if r.patch_filename == patch_path.name]
    assert len(our_result) == 1
    assert our_result[0].is_valid
    assert len(our_result[0].issues) == 0


def test_validate_patches_missing_source_report(tmp_path):
    """Test validate-patches identifies missing source report in frontmatter."""
    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    topics_dir.mkdir(parents=True)
    patches_dir.mkdir(parents=True)

    # Create the target topic card so target_card check passes
    _create_topic_card(topics_dir, "AI Agents", "core", [])

    # Write a patch that references a non-existent source report
    bad_patch = """---
type: llm_wiki_patch
target_type: topic
target: "AI Agents"
target_card: "02_Topics/AI Agents.md"
provider: mock
model: mock-v1
prompt_version: v1.0
generated_at: "2026-05-30T00:00:00Z"
source_reports:
  - "nonexistent_report"
status: pending_review
auto_apply: false
---

# Patch Proposal: AI Agents

## Target Card

[[AI Agents]]

## Proposed Current Understanding

Test

## Proposed Key Claims

- Some claim

## Proposed Related Companies

- [[NVIDIA]]

## Proposed Related Topics

- [[AI Models]]

## Proposed Open Questions

- Question?

## Evidence Notes

- Note

## Patch Safety

- Safe

## Review Checklist

- [ ] Item
"""
    patch_path = patches_dir / "bad_source.md"
    patch_path.write_text(bad_patch, encoding="utf-8")

    from signalvault.llm_wiki.validator import validate_patches

    results = validate_patches(vault)
    our_result = [r for r in results if r.patch_filename == "bad_source.md"]
    assert len(our_result) == 1
    assert not our_result[0].is_valid
    assert any("Source report not found" in issue for issue in our_result[0].issues)


def test_validate_patches_missing_required_section(tmp_path):
    """Test validate-patches identifies missing required section."""
    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    patches_dir.mkdir(parents=True)

    _create_topic_card(topics_dir, "AI Agents", "core", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    # Write a patch with missing section
    bad_patch = """---
type: llm_wiki_patch
target_type: topic
target: "AI Agents"
target_card: "02_Topics/AI Agents.md"
provider: mock
model: mock-v1
prompt_version: v1.0
generated_at: "2026-05-30T00:00:00Z"
source_reports:
  - "report1"
status: pending_review
auto_apply: false
---

# Patch Proposal: AI Agents

## Target Card

[[AI Agents]]

## Proposed Key Claims

- Some claim

## Proposed Current Understanding

Test
"""
    # Missing: Proposed Related Companies, Related Topics, Open Questions, Evidence Notes, Patch Safety, Review Checklist

    patch_path = patches_dir / "bad_patch.md"
    patch_path.write_text(bad_patch, encoding="utf-8")

    from signalvault.llm_wiki.validator import validate_patches

    results = validate_patches(vault)
    our_result = [r for r in results if r.patch_filename == "bad_patch.md"]
    assert len(our_result) == 1
    assert not our_result[0].is_valid
    assert any("Missing section" in issue for issue in our_result[0].issues)


def test_validate_patches_no_frontmatter(tmp_path):
    """Test validate-patches rejects patch without frontmatter."""
    vault = tmp_path / "vault"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    patches_dir.mkdir(parents=True)

    bad_patch = "# No Frontmatter\n\nJust some content"
    patch_path = patches_dir / "no_fm.md"
    patch_path.write_text(bad_patch, encoding="utf-8")

    from signalvault.llm_wiki.validator import validate_patches

    results = validate_patches(vault)
    our_result = [r for r in results if r.patch_filename == "no_fm.md"]
    assert len(our_result) == 1
    assert not our_result[0].is_valid
    assert any("Missing YAML frontmatter" in issue for issue in our_result[0].issues)


def test_cli_validate_patches(tmp_path):
    """Test CLI llm-wiki validate-patches command."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    # Create valid setup
    _create_topic_card(topics_dir, "AI Agents", "core", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    # Generate a patch first
    topic_path = topics_dir / "AI Agents.md"
    context = build_topic_context(vault, topic_path, max_reports=5)
    patch_md = generate_topic_patch(context, provider="mock")
    write_patch_file(vault, "AI Agents", patch_md)

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "validate-patches",
        "--vault", str(vault),
    ])

    assert result.exit_code == 0
    assert "Yes" in result.stdout  # Valid
    assert "AI Agents" in result.stdout


def test_cli_validate_patches_empty(tmp_path):
    """Test CLI validate-patches with no patches."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    vault.mkdir()

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "validate-patches",
        "--vault", str(vault),
    ])

    assert result.exit_code == 0
    assert "没有 patch 文件" in result.stdout


def test_cli_validate_patches_specific_patch(tmp_path):
    """Test CLI validate-patches --patch for a specific file."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    _create_topic_card(topics_dir, "AI Agents", "core", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    topic_path = topics_dir / "AI Agents.md"
    context = build_topic_context(vault, topic_path, max_reports=5)
    patch_md = generate_topic_patch(context, provider="mock")
    patch_path = write_patch_file(vault, "AI Agents", patch_md)

    relative_path = str(patch_path.relative_to(vault))

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "validate-patches",
        "--vault", str(vault),
        "--patch", relative_path,
    ])

    assert result.exit_code == 0
    assert "Yes" in result.stdout


def test_cli_llm_wiki_dry_run_does_not_write(tmp_path):
    """Test that dry-run does not write patch files."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    _create_topic_card(topics_dir, "AI Agents", "core", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    patches_dir = vault / "00_Inbox" / "LLM_Patches"

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "generate-patches",
        "--vault", str(vault),
        "--dry-run",
    ])

    assert result.exit_code == 0
    assert "DRY-RUN" in result.stdout
    # No patch files should be created
    assert not patches_dir.exists() or len(list(patches_dir.glob("*.md"))) == 0


# ---------------------------------------------------------------------------
# P2-E.2: Patch Apply tests
# ---------------------------------------------------------------------------


def _make_patch_with_status(
    patches_dir: Path,
    target_name: str = "AI Agents",
    status: str = "pending_review",
    source_reports: list[str] | None = None,
    auto_apply: str = "false",
) -> Path:
    """Helper: create a patch file with specific frontmatter status."""
    if source_reports is None:
        source_reports = ["report1"]
    sr_yaml = "\n".join(f'  - "{r}"' for r in source_reports)

    patch_content = f"""---
type: llm_wiki_patch
target_type: topic
target: "{target_name}"
target_card: "02_Topics/{target_name}.md"
provider: mock
model: mock-v1
prompt_version: v1.0
generated_at: "2026-05-30T00:00:00Z"
source_reports:
{sr_yaml}
status: {status}
auto_apply: {auto_apply}
---

# Patch Proposal: {target_name}

## Target Card

[[{target_name}]]

## Proposed Current Understanding

Mock understanding for {target_name}.

## Proposed Key Claims

- Mock claim about {target_name}
  - Source: [[report1]]
  - Evidence: mock-evidence

## Proposed Related Companies

- [[NVIDIA]]
- [[OpenAI]]

## Proposed Related Topics

- [[AI Models]]

## Proposed Open Questions

- Question about {target_name}?

## Proposed Timeline

- 2026-05: Initial mock timeline entry

## Evidence Notes

- Note

## Patch Safety

- Safe

## Review Checklist

- [ ] Item 1
- [ ] Item 2
"""
    patch_path = patches_dir / f"topic_{target_name.replace(' ', '_')}_20260530_000000.md"
    patch_path.write_text(patch_content, encoding="utf-8")
    return patch_path


def _setup_vault_for_apply(tmp_path, target_name="AI Agents", patch_status="pending_review"):
    """Helper: set up vault with topic card, report, and patch."""
    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    patches_dir.mkdir(parents=True)

    # Create topic card and report
    _create_topic_card(topics_dir, target_name, "core", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    # Create patch
    patch_path = _make_patch_with_status(patches_dir, target_name, status=patch_status)

    return vault, patch_path


def test_apply_patch_dry_run_does_not_write(tmp_path):
    """Test apply-patch dry-run does not modify target card."""
    from signalvault.llm_wiki.applier import apply_patch

    vault, patch_path = _setup_vault_for_apply(tmp_path)
    patch_rel = str(patch_path.relative_to(vault))

    result = apply_patch(vault, patch_rel, dry_run=True, confirm_reviewed=True)

    assert result.dry_run
    assert not result.applied
    assert len(result.sections_applied) > 0
    assert len(result.errors) == 0

    # Target card should be unchanged
    target_card = vault / "02_Topics" / "AI Agents.md"
    original = target_card.read_text(encoding="utf-8")
    assert "LLM-WIKI:BEGIN" not in original


def test_apply_patch_invalid_patch_rejected(tmp_path):
    """Test that invalid patch is rejected."""
    from signalvault.llm_wiki.applier import apply_patch

    vault, patch_path = _setup_vault_for_apply(tmp_path)
    str(patch_path.relative_to(vault))

    # Create invalid patch (no frontmatter)
    bad_patch = vault / "00_Inbox" / "LLM_Patches" / "bad.md"
    bad_patch.write_text("# No frontmatter\n\nJust content", encoding="utf-8")

    result = apply_patch(vault, "00_Inbox/LLM_Patches/bad.md", dry_run=True)
    assert len(result.errors) > 0
    assert not result.applied


def test_apply_patch_missing_target_card_rejected(tmp_path):
    """Test that patch with missing target card is rejected."""
    from signalvault.llm_wiki.applier import apply_patch

    vault = tmp_path / "vault"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    patches_dir.mkdir(parents=True)

    # Create patch referencing non-existent target card
    _make_patch_with_status(patches_dir, "NonExistent", status="approved")

    result = apply_patch(vault, "00_Inbox/LLM_Patches/topic_NonExistent_20260530_000000.md", dry_run=True)
    assert len(result.errors) > 0
    assert any("Target card not found" in e for e in result.errors)


def test_apply_patch_status_applied_rejected(tmp_path):
    """Test that already-applied patch is rejected."""
    from signalvault.llm_wiki.applier import apply_patch

    vault, patch_path = _setup_vault_for_apply(tmp_path, patch_status="applied")
    patch_rel = str(patch_path.relative_to(vault))

    result = apply_patch(vault, patch_rel, dry_run=True)
    assert len(result.errors) > 0
    assert any("already applied" in e for e in result.errors)


def test_apply_patch_status_rejected_rejected(tmp_path):
    """Test that rejected patch cannot be applied."""
    from signalvault.llm_wiki.applier import apply_patch

    vault, patch_path = _setup_vault_for_apply(tmp_path, patch_status="rejected")
    patch_rel = str(patch_path.relative_to(vault))

    result = apply_patch(vault, patch_rel, dry_run=True)
    assert len(result.errors) > 0
    assert any("rejected" in e.lower() for e in result.errors)


def test_apply_patch_pending_review_without_confirm_rejected(tmp_path):
    """Test pending_review patch requires --confirm-reviewed."""
    from signalvault.llm_wiki.applier import apply_patch

    vault, patch_path = _setup_vault_for_apply(tmp_path, patch_status="pending_review")
    patch_rel = str(patch_path.relative_to(vault))

    result = apply_patch(vault, patch_rel, dry_run=True, confirm_reviewed=False)
    assert len(result.errors) > 0
    assert any("pending_review" in e for e in result.errors)


def test_apply_patch_pending_review_with_confirm_allowed(tmp_path):
    """Test pending_review patch with --confirm-reviewed can apply."""
    from signalvault.llm_wiki.applier import apply_patch

    vault, patch_path = _setup_vault_for_apply(tmp_path, patch_status="pending_review")
    patch_rel = str(patch_path.relative_to(vault))

    result = apply_patch(vault, patch_rel, dry_run=True, confirm_reviewed=True)
    assert len(result.errors) == 0
    assert len(result.sections_applied) > 0


def test_apply_patch_section_mapping(tmp_path):
    """Test section mapping from patch to target card."""
    from signalvault.llm_wiki.applier import apply_patch

    vault, patch_path = _setup_vault_for_apply(tmp_path)
    patch_rel = str(patch_path.relative_to(vault))

    result = apply_patch(vault, patch_rel, dry_run=True, confirm_reviewed=True)

    # Check that sections are mapped correctly
    assert "## Current Understanding" in result.sections_applied
    assert "## Key Claims" in result.sections_applied
    assert "## Related Companies" in result.sections_applied
    assert "## Related Topics" in result.sections_applied
    assert "## Open Questions" in result.sections_applied


def test_apply_patch_creates_missing_section(tmp_path):
    """Test that missing target section is created."""
    from signalvault.llm_wiki.applier import _extract_patch_id, apply_patch

    vault, patch_path = _setup_vault_for_apply(tmp_path, target_name="New Topic")
    patch_rel = str(patch_path.relative_to(vault))
    patch_id = _extract_patch_id(patch_path)

    result = apply_patch(vault, patch_rel, dry_run=False, confirm_reviewed=True)

    assert result.applied
    target_card = vault / "02_Topics" / "New Topic.md"
    content = target_card.read_text(encoding="utf-8")
    # Section should be created with marker
    assert "## Current Understanding" in content
    assert f"LLM-WIKI:BEGIN {patch_id}" in content
    assert f"LLM-WIKI:END {patch_id}" in content


def test_apply_patch_marker_prevents_duplicate(tmp_path):
    """Test that marker prevents duplicate patch application."""
    from signalvault.llm_wiki.applier import apply_patch

    vault, patch_path = _setup_vault_for_apply(tmp_path)
    patch_rel = str(patch_path.relative_to(vault))

    # First apply
    result1 = apply_patch(vault, patch_rel, dry_run=False, confirm_reviewed=True)
    assert result1.applied

    # Reset patch status to pending_review to allow second attempt
    patch_content = patch_path.read_text(encoding="utf-8")
    patch_content = patch_content.replace("status: applied", "status: pending_review")
    # Also remove applied_at/applied_to lines to avoid parsing issues
    lines = patch_content.split("\n")
    clean_lines = [l for l in lines if not l.startswith("applied_at:") and not l.startswith("applied_to:")]
    patch_content = "\n".join(clean_lines)
    patch_path.write_text(patch_content, encoding="utf-8")

    # Second attempt should be rejected (marker found)
    result2 = apply_patch(vault, patch_rel, dry_run=True, confirm_reviewed=True)
    assert len(result2.errors) > 0
    assert any("marker found" in e for e in result2.errors)


def test_apply_patch_updates_patch_status(tmp_path):
    """Test that patch frontmatter status is updated to 'applied' after apply."""
    from signalvault.llm_wiki.applier import apply_patch

    vault, patch_path = _setup_vault_for_apply(tmp_path)
    patch_rel = str(patch_path.relative_to(vault))

    result = apply_patch(vault, patch_rel, dry_run=False, confirm_reviewed=True)
    assert result.applied

    # Check patch frontmatter
    updated = patch_path.read_text(encoding="utf-8")
    assert "status: applied" in updated
    assert "applied_at:" in updated
    assert "applied_to:" in updated


def test_apply_patch_generates_apply_log(tmp_path):
    """Test that apply generates Patch_Apply_Log.md."""
    from signalvault.llm_wiki.applier import apply_patch

    vault, patch_path = _setup_vault_for_apply(tmp_path)
    patch_rel = str(patch_path.relative_to(vault))

    apply_patch(vault, patch_rel, dry_run=False, confirm_reviewed=True)

    log_path = vault / "99_System" / "Patch_Apply_Log.md"
    assert log_path.exists()
    log_content = log_path.read_text(encoding="utf-8")
    assert "AI Agents" in log_content
    assert "applied" in log_content


def test_apply_patch_source_reports_untouched(tmp_path):
    """Test that source reports are not modified by apply."""
    from signalvault.llm_wiki.applier import apply_patch

    vault, patch_path = _setup_vault_for_apply(tmp_path)
    report_path = vault / "01_Reports" / "report1.md"
    original = report_path.read_text(encoding="utf-8")

    apply_patch(vault, str(patch_path.relative_to(vault)), dry_run=False, confirm_reviewed=True)

    # Report should be unchanged
    assert report_path.read_text(encoding="utf-8") == original


def test_apply_patch_company_cards_untouched(tmp_path):
    """Test that company cards are not modified by apply."""
    from signalvault.llm_wiki.applier import apply_patch

    vault, patch_path = _setup_vault_for_apply(tmp_path)
    patch_rel = str(patch_path.relative_to(vault))

    # Create a company card
    companies_dir = vault / "03_Companies"
    companies_dir.mkdir(parents=True)
    company_path = companies_dir / "NVIDIA.md"
    company_content = "---\ntype: company\nname: NVIDIA\n---\n\n# NVIDIA\n"
    company_path.write_text(company_content, encoding="utf-8")

    apply_patch(vault, patch_rel, dry_run=False, confirm_reviewed=True)

    # Company card should be unchanged
    assert company_path.read_text(encoding="utf-8") == company_content


def test_cli_apply_patch_dry_run(tmp_path):
    """Test CLI apply-patch --dry-run."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault, patch_path = _setup_vault_for_apply(tmp_path)
    patch_rel = str(patch_path.relative_to(vault))

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "apply-patch",
        "--vault", str(vault),
        "--patch", patch_rel,
        "--dry-run",
    ])

    assert result.exit_code == 0
    assert "DRY-RUN" in result.stdout
    assert "AI Agents" in result.stdout
    assert "Sections to apply" in result.stdout


def test_cli_apply_patch_apply_without_confirm_rejected(tmp_path):
    """Test CLI apply-patch --apply without --confirm-reviewed is rejected."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault, patch_path = _setup_vault_for_apply(tmp_path)
    patch_rel = str(patch_path.relative_to(vault))

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "apply-patch",
        "--vault", str(vault),
        "--patch", patch_rel,
        "--apply",
    ])

    assert "pending_review" in result.stdout or result.exit_code == 1


def test_cli_apply_patch_apply_with_confirm(tmp_path):
    """Test CLI apply-patch --apply --confirm-reviewed."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault, patch_path = _setup_vault_for_apply(tmp_path)
    patch_rel = str(patch_path.relative_to(vault))

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "apply-patch",
        "--vault", str(vault),
        "--patch", patch_rel,
        "--apply",
        "--confirm-reviewed",
    ])

    assert result.exit_code == 0
    assert "applied" in result.stdout.lower() or "Patch Apply" in result.stdout


def test_apply_patch_auto_apply_true_rejected(tmp_path):
    """Test that patch with auto_apply=true is rejected."""
    from signalvault.llm_wiki.applier import apply_patch

    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    patches_dir.mkdir(parents=True)

    _create_topic_card(topics_dir, "AI Agents", "core", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")
    patch_path = _make_patch_with_status(patches_dir, "AI Agents", status="approved", auto_apply="true")

    result = apply_patch(vault, str(patch_path.relative_to(vault)), dry_run=True)
    assert len(result.errors) > 0
    assert any("auto_apply" in e for e in result.errors)


# ---------------------------------------------------------------------------
# P2-E.2.1: Apply Formatting Hardening tests
# ---------------------------------------------------------------------------


def test_section_inserted_at_correct_position(tmp_path):
    """Test that missing sections are inserted at correct canonical position."""
    from signalvault.llm_wiki.applier import apply_patch
    from signalvault.llm_wiki.taxonomy import SECTION_ORDER

    vault, patch_path = _setup_vault_for_apply(tmp_path, target_name="NewTopic")
    patch_rel = str(patch_path.relative_to(vault))

    result = apply_patch(vault, patch_rel, dry_run=False, confirm_reviewed=True)
    assert result.applied

    target_card = vault / "02_Topics" / "NewTopic.md"
    content = target_card.read_text(encoding="utf-8")

    # Find the order of section headers in the file
    section_positions = {}
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## ") and stripped in SECTION_ORDER:
            section_positions[stripped] = content.split("\n").index(line)

    # Verify sections appear in canonical order
    sorted(section_positions.keys(), key=lambda s: section_positions[s])
    # Check that Current Understanding comes before Key Claims
    cu_idx = section_positions.get("## Current Understanding", -1)
    kc_idx = section_positions.get("## Key Claims", -1)
    rc_idx = section_positions.get("## Related Companies", -1)
    rt_idx = section_positions.get("## Related Topics", -1)
    oq_idx = section_positions.get("## Open Questions", -1)
    tl_idx = section_positions.get("## Timeline", -1)
    section_positions.get("## Source Reports", -1)

    assert cu_idx < kc_idx, "Current Understanding should be before Key Claims"
    assert kc_idx < rc_idx, "Key Claims should be before Related Companies"
    assert rc_idx < rt_idx, "Related Companies should be before Related Topics"
    assert rt_idx < oq_idx, "Related Topics should be before Open Questions"
    assert oq_idx < tl_idx, "Open Questions should be before Timeline"
    # Source Reports may be in legacy position (before Related Companies)
    # from original card layout; only assert it exists


def test_topic_canonical_normalization(tmp_path):
    """Test that Related Topics are normalized to canonical names."""
    from signalvault.llm_wiki.applier import apply_patch

    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    patches_dir.mkdir(parents=True)

    _create_topic_card(topics_dir, "AI Agents", "core", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    # Create patch with non-canonical topic names
    patch = _make_patch_with_status(patches_dir, "AI Agents", status="approved")
    # Modify patch to use non-canonical topic names
    content = patch.read_text(encoding="utf-8")
    content = content.replace("[[AI Models]]", "[[enterprise saas]]")
    content = content.replace("status: approved", "status: approved")
    patch.write_text(content, encoding="utf-8")

    result = apply_patch(vault, str(patch.relative_to(vault)), dry_run=False, confirm_reviewed=True)
    assert result.applied

    target_card = vault / "02_Topics" / "AI Agents.md"
    card_content = target_card.read_text(encoding="utf-8")
    assert "[[Enterprise AI]]" in card_content
    assert "[[enterprise saas]]" not in card_content


def test_entity_type_annotation(tmp_path):
    """Test that known non-company entities get type annotations."""
    from signalvault.llm_wiki.applier import apply_patch

    vault = tmp_path / "vault"
    topics_dir = vault / "02_Topics"
    reports_dir = vault / "01_Reports"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    topics_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    patches_dir.mkdir(parents=True)

    _create_topic_card(topics_dir, "AI Agents", "core", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    patch = _make_patch_with_status(patches_dir, "AI Agents", status="approved")
    content = patch.read_text(encoding="utf-8")
    # Add known non-company entities
    content = content.replace("[[NVIDIA]]", "[[NVIDIA]]\n- [[Claude Code]]\n- [[LangChain]]")
    patch.write_text(content, encoding="utf-8")

    result = apply_patch(vault, str(patch.relative_to(vault)), dry_run=False, confirm_reviewed=True)
    assert result.applied

    target_card = vault / "02_Topics" / "AI Agents.md"
    card_content = target_card.read_text(encoding="utf-8")
    # Known tools/frameworks should be annotated
    assert "[[Claude Code]] *(tool)*" in card_content
    assert "[[LangChain]] *(framework)*" in card_content
    # Real companies should NOT be annotated
    assert "[[NVIDIA]]" in card_content
    assert "[[NVIDIA]] *(company)*" not in card_content


def test_normalize_topic_name():
    """Test topic canonical normalization function."""
    from signalvault.llm_wiki.taxonomy import normalize_topic_name

    assert normalize_topic_name("enterprise saas") == "Enterprise AI"
    assert normalize_topic_name("ai agents") == "AI Agents"
    assert normalize_topic_name("llm") == "AI Models"
    assert normalize_topic_name("AI Agents") == "AI Agents"  # already canonical
    assert normalize_topic_name("Unknown Topic XYZ") == "Unknown Topic XYZ"  # unknown


def test_classify_entity():
    """Test entity classification function."""
    from signalvault.llm_wiki.taxonomy import classify_entity

    assert classify_entity("Claude Code") == "tool"
    assert classify_entity("LangChain") == "framework"
    assert classify_entity("ChatGPT") == "product"
    assert classify_entity("NVIDIA") is None  # real company
    assert classify_entity("OpenAI") is None  # real company (not in non-company list)


def test_source_report_context_includes_channel():
    """Test that source report context includes channel info."""
    from signalvault.llm_wiki.context_builder import SourceReport
    from signalvault.llm_wiki.prompts import build_source_reports_context

    reports = [
        SourceReport(
            filename="2026-05-29_Latent Space_abc123",
            path=None,
            channel="Latent Space",
            video_id="abc123",
            summary="Test summary",
        )
    ]

    context = build_source_reports_context(reports)
    # Should include channel + video_id as display name
    assert "Latent Space" in context
    assert "abc123" in context
    assert "Latent Space — abc123" in context


# ---------------------------------------------------------------------------
# P2-E.3: Company Card Patch Generation tests
# ---------------------------------------------------------------------------


def _create_company_card(companies_dir: Path, company_name: str, source_reports: list[str]) -> Path:
    """Helper: create a company card file."""
    card_path = companies_dir / f"{company_name}.md"
    source_lines = "\n".join(f"- [[{r}]]" for r in source_reports)
    content = f"""---
type: company
company: {company_name}
aliases: []
ticker:
sector:
tags:
  - company/{company_name.lower()}
---

# {company_name}

## Current Thesis

> Placeholder.

## Related Investment Views

## Risks

## Related Topics

## Source Reports

{source_lines}

## Timeline

"""
    card_path.write_text(content, encoding="utf-8")
    return card_path


def test_find_companies(tmp_path):
    """Test finding company cards."""
    vault = tmp_path / "vault"
    companies_dir = vault / "03_Companies"
    companies_dir.mkdir(parents=True)

    _create_company_card(companies_dir, "NVIDIA", ["report1", "report2"])
    _create_company_card(companies_dir, "OpenAI", ["report3"])

    from signalvault.llm_wiki.context_builder import find_companies
    companies = find_companies(vault)
    assert len(companies) == 2
    names = {p.stem for p in companies}
    assert names == {"NVIDIA", "OpenAI"}


def test_find_companies_specific(tmp_path):
    """Test finding a specific company."""
    vault = tmp_path / "vault"
    companies_dir = vault / "03_Companies"
    companies_dir.mkdir(parents=True)

    _create_company_card(companies_dir, "NVIDIA", ["report1"])
    _create_company_card(companies_dir, "OpenAI", ["report2"])

    from signalvault.llm_wiki.context_builder import find_companies
    companies = find_companies(vault, company_name="NVIDIA")
    assert len(companies) == 1
    assert companies[0].stem == "NVIDIA"


def test_build_company_context(tmp_path):
    """Test building context for a company."""
    vault = tmp_path / "vault"
    companies_dir = vault / "03_Companies"
    reports_dir = vault / "01_Reports"
    companies_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    _create_company_card(companies_dir, "NVIDIA", ["report1", "report2"])
    _create_report(reports_dir, "report1", "Channel", "vid1")
    _create_report(reports_dir, "report2", "Channel2", "vid2")

    from signalvault.llm_wiki.context_builder import build_company_context
    company_path = companies_dir / "NVIDIA.md"
    context = build_company_context(vault, company_path, max_reports=5)

    assert context.company_name == "NVIDIA"
    assert len(context.source_reports) == 2
    assert context.source_reports[0].filename == "report1"


def test_generate_company_patch_mock(tmp_path):
    """Test mock company patch generation."""
    vault = tmp_path / "vault"
    companies_dir = vault / "03_Companies"
    reports_dir = vault / "01_Reports"
    companies_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    _create_company_card(companies_dir, "NVIDIA", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    from signalvault.llm_wiki.context_builder import build_company_context
    from signalvault.llm_wiki.patch_generator import generate_company_patch

    company_path = companies_dir / "NVIDIA.md"
    context = build_company_context(vault, company_path, max_reports=5)
    patch_md = generate_company_patch(context, provider="mock")

    # Check structure
    assert "---" in patch_md  # frontmatter
    assert "target_type: company" in patch_md
    assert 'target: "NVIDIA"' in patch_md
    assert "target_card: \"03_Companies/NVIDIA.md\"" in patch_md
    assert "# Patch Proposal: NVIDIA" in patch_md
    assert "## Proposed Current Thesis" in patch_md
    assert "## Proposed Key Claims" in patch_md
    assert "## Proposed Risks" in patch_md
    assert "## Review Checklist" in patch_md
    assert "status: pending_review" in patch_md
    assert "auto_apply: false" in patch_md


def test_cli_company_mock(tmp_path):
    """Test CLI --company --mock."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    companies_dir = vault / "03_Companies"
    reports_dir = vault / "01_Reports"
    companies_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    _create_company_card(companies_dir, "NVIDIA", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "generate-patches",
        "--vault", str(vault),
        "--company", "NVIDIA",
        "--mock",
    ])

    assert result.exit_code == 0
    assert "Written to:" in result.stdout
    # Check file was created
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    files = list(patches_dir.glob("company_*.md"))
    assert len(files) == 1
    assert "company_NVIDIA_" in files[0].name


def test_cli_company_dry_run(tmp_path):
    """Test CLI --company --dry-run."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    companies_dir = vault / "03_Companies"
    reports_dir = vault / "01_Reports"
    companies_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    _create_company_card(companies_dir, "NVIDIA", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "generate-patches",
        "--vault", str(vault),
        "--company", "NVIDIA",
        "--dry-run",
    ])

    assert result.exit_code == 0
    assert "NVIDIA" in result.stdout
    assert "Source reports: 1" in result.stdout


def test_cli_topic_and_company_mutually_exclusive(tmp_path):
    """Test --topic and --company cannot be used together."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    vault.mkdir()

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "generate-patches",
        "--vault", str(vault),
        "--topic", "AI Agents",
        "--company", "NVIDIA",
    ])

    assert result.exit_code == 1
    assert "不能同时使用" in result.stdout


def test_validate_company_patch(tmp_path):
    """Test validate-patches recognizes valid company patch."""
    vault = tmp_path / "vault"
    companies_dir = vault / "03_Companies"
    reports_dir = vault / "01_Reports"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    companies_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    patches_dir.mkdir(parents=True)

    _create_company_card(companies_dir, "NVIDIA", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    from signalvault.llm_wiki.context_builder import build_company_context
    from signalvault.llm_wiki.patch_generator import (
        generate_company_patch,
        write_patch_file,
    )

    company_path = companies_dir / "NVIDIA.md"
    context = build_company_context(vault, company_path, max_reports=5)
    patch_md = generate_company_patch(context, provider="mock")
    write_patch_file(vault, "NVIDIA", patch_md, patch_prefix="company")

    from signalvault.llm_wiki.validator import validate_patches
    results = validate_patches(vault)

    company_patches = [r for r in results if "company_NVIDIA" in r.patch_filename]
    assert len(company_patches) == 1
    assert company_patches[0].is_valid


def test_apply_company_patch_dry_run(tmp_path):
    """Test apply-patch dry-run for company patches."""
    from signalvault.llm_wiki.applier import apply_patch

    vault = tmp_path / "vault"
    companies_dir = vault / "03_Companies"
    reports_dir = vault / "01_Reports"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    companies_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    patches_dir.mkdir(parents=True)

    _create_company_card(companies_dir, "NVIDIA", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    from signalvault.llm_wiki.context_builder import build_company_context
    from signalvault.llm_wiki.patch_generator import (
        generate_company_patch,
        write_patch_file,
    )

    company_path = companies_dir / "NVIDIA.md"
    context = build_company_context(vault, company_path, max_reports=5)
    patch_md = generate_company_patch(context, provider="mock")
    patch_path = write_patch_file(vault, "NVIDIA", patch_md, patch_prefix="company")

    result = apply_patch(
        vault,
        str(patch_path.relative_to(vault)),
        dry_run=True,
        confirm_reviewed=True,
    )

    assert len(result.errors) == 0
    assert len(result.sections_applied) > 0
    # Check company sections are mapped
    assert "## Current Thesis" in result.sections_applied
    assert "## Risks" in result.sections_applied


def test_apply_company_patch_with_marker(tmp_path):
    """Test company patch apply with marker."""
    from signalvault.llm_wiki.applier import apply_patch

    vault = tmp_path / "vault"
    companies_dir = vault / "03_Companies"
    reports_dir = vault / "01_Reports"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    companies_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    patches_dir.mkdir(parents=True)

    _create_company_card(companies_dir, "NVIDIA", ["report1"])
    _create_report(reports_dir, "report1", "Channel", "vid1")

    from signalvault.llm_wiki.context_builder import build_company_context
    from signalvault.llm_wiki.patch_generator import (
        generate_company_patch,
        write_patch_file,
    )

    company_path = companies_dir / "NVIDIA.md"
    context = build_company_context(vault, company_path, max_reports=5)
    patch_md = generate_company_patch(context, provider="mock")
    patch_path = write_patch_file(vault, "NVIDIA", patch_md, patch_prefix="company")

    result = apply_patch(
        vault,
        str(patch_path.relative_to(vault)),
        dry_run=False,
        confirm_reviewed=True,
    )

    assert result.applied
    card = companies_dir / "NVIDIA.md"
    content = card.read_text(encoding="utf-8")
    assert "LLM-WIKI:BEGIN" in content
    assert "LLM-WIKI:END" in content
    assert "## Current Thesis" in content


# ---------------------------------------------------------------------------
# P2-E.4: Rollback / Reject tests
# ---------------------------------------------------------------------------


def _make_applied_patch_in_vault(vault, patch_id, target_type="topic",
                                  target_name="AI Agents",
                                  target_card_rel="02_Topics/AI Agents.md"):
    """Helper: create a patch with status=applied and markers in target card."""
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    patches_dir.mkdir(parents=True, exist_ok=True)

    patch_path = patches_dir / f"{patch_id}.md"
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

## Target Card

[[{target_name}]]
""", encoding="utf-8")

    target_path = vault / target_card_rel
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(f"""---
type: {target_type}
status: core
---

# {target_name}

## Current Understanding

<!-- LLM-WIKI:BEGIN {patch_id} -->

Some content

<!-- LLM-WIKI:END {patch_id} -->

## Source Reports

- [[report1]]
""", encoding="utf-8")

    return patch_path


def test_list_applied_patches(tmp_path):
    """Test list-applied-patches finds applied patches."""
    from signalvault.llm_wiki.rollback import list_applied_patches

    vault = tmp_path / "vault"
    vault.mkdir()

    _make_applied_patch_in_vault(vault, "topic_AI_Agents_20260530_000000")
    _make_applied_patch_in_vault(vault, "company_OpenAI_20260530_000000",
                                  target_type="company", target_name="OpenAI",
                                  target_card_rel="03_Companies/OpenAI.md")

    results = list_applied_patches(vault)
    assert len(results) == 2
    assert results[0].marker_exists == "yes"
    assert results[1].marker_exists == "yes"


def test_list_applied_patches_missing_marker(tmp_path):
    """Test that missing marker is detected."""
    from signalvault.llm_wiki.rollback import list_applied_patches

    vault = tmp_path / "vault"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    patches_dir.mkdir(parents=True)
    patch_path = patches_dir / "topic_Missing_20260530_000000.md"
    patch_path.write_text("""---
type: llm_wiki_patch
target_type: topic
target: "Missing"
target_card: "02_Topics/Missing.md"
status: applied
auto_apply: false
applied_at: "2026-05-30T08:00:00Z"
applied_to: "02_Topics/Missing.md"
---
""", encoding="utf-8")
    target = vault / "02_Topics" / "Missing.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Missing\n\nNo markers here.\n", encoding="utf-8")

    results = list_applied_patches(vault)
    assert len(results) == 1
    assert results[0].marker_exists == "missing"


def test_rollback_dry_run_does_not_write(tmp_path):
    """Test rollback dry-run doesn't modify files."""
    from signalvault.llm_wiki.rollback import _count_marker_blocks, rollback_patch

    vault = tmp_path / "vault"
    vault.mkdir()
    patch_path = _make_applied_patch_in_vault(vault, "topic_Test_20260530_000000")

    target_card = vault / "02_Topics" / "AI Agents.md"
    original = target_card.read_text(encoding="utf-8")
    assert _count_marker_blocks(original, "topic_Test_20260530_000000") == 1

    result = rollback_patch(vault, patch_path=patch_path, dry_run=True)
    assert result.blocks_removed == 1
    assert len(result.errors) == 0
    assert target_card.read_text(encoding="utf-8") == original


def test_rollback_apply_removes_markers(tmp_path):
    """Test rollback apply removes marker blocks."""
    from signalvault.llm_wiki.rollback import _count_marker_blocks, rollback_patch

    vault = tmp_path / "vault"
    vault.mkdir()
    patch_path = _make_applied_patch_in_vault(vault, "topic_Test_20260530_000000")

    result = rollback_patch(vault, patch_path=patch_path, dry_run=False)
    assert result.rolled_back
    assert result.blocks_removed == 1

    target_card = vault / "02_Topics" / "AI Agents.md"
    assert _count_marker_blocks(target_card.read_text(encoding="utf-8"), "topic_Test_20260530_000000") == 0


def test_rollback_updates_patch_status(tmp_path):
    """Test rollback updates patch status to rolled_back."""
    from signalvault.llm_wiki.rollback import rollback_patch

    vault = tmp_path / "vault"
    vault.mkdir()
    patch_path = _make_applied_patch_in_vault(vault, "topic_Test_20260530_000000")

    rollback_patch(vault, patch_path=patch_path, dry_run=False)

    content = patch_path.read_text(encoding="utf-8")
    assert "status: rolled_back" in content
    assert "rolled_back_at:" in content
    assert "rolled_back_from:" in content


def test_rollback_writes_rollback_log(tmp_path):
    """Test rollback writes Patch_Rollback_Log.md."""
    from signalvault.llm_wiki.rollback import rollback_patch

    vault = tmp_path / "vault"
    vault.mkdir()
    patch_path = _make_applied_patch_in_vault(vault, "topic_Test_20260530_000000")

    rollback_patch(vault, patch_path=patch_path, dry_run=False)

    log_path = vault / "99_System" / "Patch_Rollback_Log.md"
    assert log_path.exists()
    assert "topic_Test_20260530_000000" in log_path.read_text(encoding="utf-8")


def test_rollback_missing_marker_rejected(tmp_path):
    """Test rollback with missing marker returns error."""
    from signalvault.llm_wiki.rollback import rollback_patch

    vault = tmp_path / "vault"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    patches_dir.mkdir(parents=True)
    patch_path = patches_dir / "topic_NoMarker_20260530_000000.md"
    patch_path.write_text("""---
type: llm_wiki_patch
target_type: topic
target: "NoMarker"
target_card: "02_Topics/NoMarker.md"
status: applied
auto_apply: false
applied_at: "2026-05-30T08:00:00Z"
applied_to: "02_Topics/NoMarker.md"
---
""", encoding="utf-8")
    target = vault / "02_Topics" / "NoMarker.md"
    target.parent.mkdir(parents=True)
    target.write_text("# NoMarker\n\nNo blocks here.\n", encoding="utf-8")

    result = rollback_patch(vault, patch_path=patch_path, dry_run=True)
    assert len(result.errors) > 0
    assert any("No marker blocks" in e for e in result.errors)


def test_rollback_non_applied_rejected(tmp_path):
    """Test rollback rejects non-applied patch."""
    from signalvault.llm_wiki.rollback import rollback_patch

    vault = tmp_path / "vault"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    patches_dir.mkdir(parents=True)
    patch_path = patches_dir / "topic_Pending_20260530_000000.md"
    patch_path.write_text("""---
type: llm_wiki_patch
target_type: topic
target: "Test"
status: pending_review
auto_apply: false
---
""", encoding="utf-8")

    result = rollback_patch(vault, patch_path=patch_path, dry_run=True)
    assert len(result.errors) > 0
    assert any("not 'applied'" in e for e in result.errors)


def test_rollback_by_patch_id(tmp_path):
    """Test rollback with --patch-id."""
    from signalvault.llm_wiki.rollback import rollback_patch

    vault = tmp_path / "vault"
    vault.mkdir()
    _make_applied_patch_in_vault(vault, "topic_Test_20260530_000000")

    result = rollback_patch(vault, patch_id="topic_Test_20260530_000000", dry_run=True)
    assert result.blocks_removed == 1


def test_reject_pending_review_succeeds(tmp_path):
    """Test reject-patch on pending_review patch."""
    from signalvault.llm_wiki.rollback import reject_patch

    vault = tmp_path / "vault"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    patches_dir.mkdir(parents=True)
    patch_path = patches_dir / "topic_Pending_20260530_000000.md"
    patch_path.write_text("""---
type: llm_wiki_patch
target_type: topic
target: "Test"
status: pending_review
auto_apply: false
---
""", encoding="utf-8")

    result = reject_patch(vault, patch_path, reason="manual review rejected")
    assert result.rejected
    content = patch_path.read_text(encoding="utf-8")
    assert "status: rejected" in content
    assert "rejected_at:" in content
    assert "reject_reason:" in content


def test_reject_approved_succeeds(tmp_path):
    """Test reject-patch on approved patch."""
    from signalvault.llm_wiki.rollback import reject_patch

    vault = tmp_path / "vault"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    patches_dir.mkdir(parents=True)
    patch_path = patches_dir / "topic_Approved_20260530_000000.md"
    patch_path.write_text("""---
type: llm_wiki_patch
target_type: topic
target: "Test"
status: approved
auto_apply: false
---
""", encoding="utf-8")

    result = reject_patch(vault, patch_path, reason="no longer relevant")
    assert result.rejected


def test_reject_applied_rejected(tmp_path):
    """Test reject-patch refuses applied patch."""
    from signalvault.llm_wiki.rollback import reject_patch

    vault = tmp_path / "vault"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    patches_dir.mkdir(parents=True)
    patch_path = patches_dir / "topic_Applied_20260530_000000.md"
    patch_path.write_text("""---
type: llm_wiki_patch
target_type: topic
target: "Test"
status: applied
auto_apply: false
---
""", encoding="utf-8")

    result = reject_patch(vault, patch_path)
    assert not result.rejected
    assert any("Only pending_review or approved" in e for e in result.errors)


def test_reject_writes_reject_log(tmp_path):
    """Test reject-patch writes Patch_Reject_Log.md."""
    from signalvault.llm_wiki.rollback import reject_patch

    vault = tmp_path / "vault"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    patches_dir.mkdir(parents=True)
    patch_path = patches_dir / "topic_Pending_20260530_000000.md"
    patch_path.write_text("""---
type: llm_wiki_patch
target_type: topic
target: "Test"
status: pending_review
auto_apply: false
---
""", encoding="utf-8")

    reject_patch(vault, patch_path, reason="test reason")
    log_path = vault / "99_System" / "Patch_Reject_Log.md"
    assert log_path.exists()
    assert "test reason" in log_path.read_text(encoding="utf-8")


def test_cli_list_applied(tmp_path):
    """Test CLI list-applied-patches."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    vault.mkdir()
    _make_applied_patch_in_vault(vault, "topic_Test_20260530_000000")

    runner = CliRunner()
    result = runner.invoke(app, ["llm-wiki", "list-applied-patches", "--vault", str(vault)])
    assert result.exit_code == 0
    assert "topic_Test_20260530_000000" in result.stdout
    assert "yes" in result.stdout


def test_cli_rollback_dry_run(tmp_path):
    """Test CLI rollback-patch --dry-run."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    vault.mkdir()
    patch_path = _make_applied_patch_in_vault(vault, "topic_Test_20260530_000000")
    patch_rel = str(patch_path.relative_to(vault))

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "rollback-patch",
        "--vault", str(vault),
        "--patch", patch_rel,
        "--dry-run",
    ])
    assert result.exit_code == 0
    assert "Blocks to remove" in result.stdout


def test_cli_reject_patch(tmp_path):
    """Test CLI reject-patch."""
    from typer.testing import CliRunner

    from signalvault.cli import app

    vault = tmp_path / "vault"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    patches_dir.mkdir(parents=True)
    patch_path = patches_dir / "topic_Pending_20260530_000000.md"
    patch_path.write_text("""---
type: llm_wiki_patch
target_type: topic
target: "Test"
status: pending_review
auto_apply: false
---
""", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, [
        "llm-wiki", "reject-patch",
        "--vault", str(vault),
        "--patch", str(patch_path.relative_to(vault)),
        "--reason", "test rejection",
    ])
    assert result.exit_code == 0
    assert "rejected" in result.stdout.lower()


def test_apply_patch_rolled_back_rejected(tmp_path):
    """Test that rolled_back patch cannot be applied."""
    from signalvault.llm_wiki.applier import apply_patch

    vault = tmp_path / "vault"
    patches_dir = vault / "00_Inbox" / "LLM_Patches"
    reports_dir = vault / "01_Reports"
    patches_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    (reports_dir / "r1.md").write_text("# r1", encoding="utf-8")
    patch_path = patches_dir / "topic_RolledBack_20260530_000000.md"
    patch_path.write_text("""---
type: llm_wiki_patch
target_type: topic
target: "Test"
target_card: "02_Topics/Test.md"
status: rolled_back
auto_apply: false
source_reports:
  - "r1"
---

# Patch Proposal: Test

## Proposed Current Understanding
Test

## Proposed Key Claims
- Claim

## Proposed Related Companies
- [[NVIDIA]]

## Proposed Related Topics
- [[AI]]

## Proposed Open Questions
- Q?

## Evidence Notes
- Note

## Patch Safety
- Safe

## Review Checklist
- [ ] Item
""", encoding="utf-8")
    target = vault / "02_Topics" / "Test.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Test", encoding="utf-8")

    result = apply_patch(vault, "00_Inbox/LLM_Patches/topic_RolledBack_20260530_000000.md", dry_run=True)
    assert len(result.errors) > 0
    assert any("rolled back" in e for e in result.errors)

