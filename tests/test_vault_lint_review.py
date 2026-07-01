"""P3-B/C: Tests for vault lint and review queue.

Covers: ReviewItem CRUD, status transitions, lint rules (frontmatter,
wikilinks, duplicates, orphans), lint→review integration, and CLI smoke.
"""


import pytest

from podcast_research.db.session import init_db, reset_engine

# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    """Isolate DB to temp file."""
    db_path = tmp_path / "test_lint.db"
    import podcast_research.config as cfg
    monkeypatch.setattr(cfg, "DB_PATH", db_path)
    reset_engine()
    init_db(str(db_path))
    yield
    reset_engine()


@pytest.fixture
def review_mgr():
    from podcast_research.sources.review_items import ReviewItemManager
    return ReviewItemManager


@pytest.fixture
def vault_dir(tmp_path):
    """Create a minimal vault structure for lint testing."""
    vault = tmp_path / "vault"
    (vault / "01_Reports").mkdir(parents=True)
    (vault / "02_Topics").mkdir(parents=True)
    (vault / "03_Companies").mkdir(parents=True)
    (vault / "05_Channels").mkdir(parents=True)
    (vault / "06_Claims").mkdir(parents=True)
    (vault / "07_Signals").mkdir(parents=True)
    (vault / "99_System").mkdir(parents=True)
    return vault


# ═════════════════════════════════════════════════════════════════════════════
# ReviewItem CRUD
# ═════════════════════════════════════════════════════════════════════════════


class TestReviewItemCRUD:
    """Tests for ReviewItemManager create/list/get."""

    def test_create_item(self, review_mgr):
        item = review_mgr.create_item(
            item_type="lint_dead_wikilink",
            title="[[Dead Page]] 指向不存在的文件",
            severity="warning",
            description="The wikilink points to nothing",
            source_path="01_Reports/test.md",
        )
        assert item is not None
        assert item["item_type"] == "lint_dead_wikilink"
        assert item["status"] == "open"
        assert item["severity"] == "warning"

    def test_create_item_invalid_type(self, review_mgr):
        item = review_mgr.create_item(
            item_type="nonexistent_type",
            title="test",
        )
        assert item is None

    def test_list_items(self, review_mgr):
        review_mgr.create_item(item_type="lint_dead_wikilink", title="A")
        review_mgr.create_item(item_type="lint_orphan_card", title="B")
        review_mgr.create_item(item_type="manual", title="C")
        items = review_mgr.list_items()
        assert len(items) == 3

    def test_list_by_status(self, review_mgr):
        review_mgr.create_item(item_type="manual", title="Open item")
        items = review_mgr.list_items(status="open")
        assert len(items) >= 1

    def test_list_by_type(self, review_mgr):
        review_mgr.create_item(item_type="lint_dead_wikilink", title="x")
        review_mgr.create_item(item_type="lint_orphan_card", title="y")
        items = review_mgr.list_items(item_type="lint_dead_wikilink")
        assert len(items) == 1
        assert items[0]["item_type"] == "lint_dead_wikilink"

    def test_get_item(self, review_mgr):
        created = review_mgr.create_item(item_type="manual", title="Find me")
        assert created is not None
        found = review_mgr.get_item(created["id"])
        assert found is not None
        assert found["title"] == "Find me"

    def test_get_item_not_found(self, review_mgr):
        assert review_mgr.get_item(99999) is None

    def test_count_by_status(self, review_mgr):
        review_mgr.create_item(item_type="manual", title="a")
        review_mgr.create_item(item_type="manual", title="b")
        counts = review_mgr.count_by_status()
        assert counts.get("open", 0) >= 2


# ═════════════════════════════════════════════════════════════════════════════
# ReviewItem Status Transitions
# ═════════════════════════════════════════════════════════════════════════════


class TestReviewStatusTransitions:
    """Tests for accept/skip/resolve transitions."""

    def test_accept_item(self, review_mgr):
        item = review_mgr.create_item(item_type="manual", title="Test")
        assert item is not None
        result = review_mgr.accept_item(item["id"])
        assert result is not None
        assert result["status"] == "accepted"
        assert result["resolved_at"] is not None

    def test_skip_item(self, review_mgr):
        item = review_mgr.create_item(item_type="manual", title="Skip me")
        assert item is not None
        result = review_mgr.skip_item(item["id"], note="Not relevant")
        assert result is not None
        assert result["status"] == "skipped"

    def test_resolve_from_open(self, review_mgr):
        item = review_mgr.create_item(item_type="manual", title="Resolve me")
        assert item is not None
        result = review_mgr.resolve_item(item["id"])
        assert result is not None
        assert result["status"] == "resolved"

    def test_resolve_from_accepted(self, review_mgr):
        item = review_mgr.create_item(item_type="manual", title="Accept+Resolve")
        assert item is not None
        review_mgr.accept_item(item["id"])
        result = review_mgr.resolve_item(item["id"])
        assert result is not None
        assert result["status"] == "resolved"

    def test_cannot_accept_already_skipped(self, review_mgr):
        item = review_mgr.create_item(item_type="manual", title="Skipped")
        assert item is not None
        review_mgr.skip_item(item["id"])
        result = review_mgr.accept_item(item["id"])
        assert result is None

    def test_transition_nonexistent(self, review_mgr):
        assert review_mgr.accept_item(99999) is None

    def test_accept_with_note(self, review_mgr):
        item = review_mgr.create_item(item_type="manual", title="Noted")
        assert item is not None
        result = review_mgr.accept_item(item["id"], note="Fixed manually")
        assert result is not None
        assert result["resolution_note"] == "Fixed manually"

    def test_resolved_at_set_on_transition(self, review_mgr):
        item = review_mgr.create_item(item_type="manual", title="Timestamp")
        assert item is not None
        assert item["resolved_at"] is None
        result = review_mgr.skip_item(item["id"])
        assert result["resolved_at"] is not None


# ═════════════════════════════════════════════════════════════════════════════
# Vault Lint: Frontmatter
# ═════════════════════════════════════════════════════════════════════════════


class TestFrontmatterLint:
    """Tests for frontmatter lint rules."""

    def test_valid_frontmatter_no_error(self, vault_dir):
        from podcast_research.workspace.vault_lint import lint_frontmatter_invalid
        rpt = vault_dir / "01_Reports" / "good.md"
        rpt.write_text(
            "---\ntype: report\nchannel: Test\nvideo_id: abc123\nanalyzed_at: 2026-01-01\n---\n# OK\n",
            encoding="utf-8",
        )
        findings = lint_frontmatter_invalid(vault_dir)
        assert len(findings) == 0

    def test_missing_closing_delimiter(self, vault_dir):
        from podcast_research.workspace.vault_lint import lint_frontmatter_invalid
        rpt = vault_dir / "01_Reports" / "bad.md"
        rpt.write_text("---\ntype: report\n# No closing ---\n", encoding="utf-8")
        findings = lint_frontmatter_invalid(vault_dir)
        assert len(findings) >= 1
        assert any("未闭合" in f["message"] for f in findings)

    def test_yaml_parse_error(self, vault_dir):
        from podcast_research.workspace.vault_lint import lint_frontmatter_invalid
        rpt = vault_dir / "01_Reports" / "bad_yaml.md"
        rpt.write_text("---\n{invalid: yaml: [\n---\n# Bad\n", encoding="utf-8")
        findings = lint_frontmatter_invalid(vault_dir)
        assert len(findings) >= 1
        assert any("解析失败" in f["message"] for f in findings)

    def test_no_frontmatter_no_error(self, vault_dir):
        from podcast_research.workspace.vault_lint import lint_frontmatter_invalid
        rpt = vault_dir / "99_System" / "notes.md"
        rpt.write_text("# Just notes\nNo frontmatter.\n", encoding="utf-8")
        # no frontmatter is not an error for lint_frontmatter_invalid
        # (system dirs are also skipped — 90_, 99_, .trash, .obsidian)
        lint_frontmatter_invalid(vault_dir)  # should not crash


class TestRequiredFieldsLint:
    """Tests for missing required fields."""

    def test_report_missing_type(self, vault_dir):
        from podcast_research.workspace.vault_lint import (
            lint_frontmatter_missing_fields,
        )
        rpt = vault_dir / "01_Reports" / "nofield.md"
        rpt.write_text("---\ntitle: No type field\n---\n# Content\n", encoding="utf-8")
        findings = lint_frontmatter_missing_fields(vault_dir)
        assert len(findings) >= 1
        assert any("type" in f["detail"] for f in findings)

    def test_topic_missing_status(self, vault_dir):
        from podcast_research.workspace.vault_lint import (
            lint_frontmatter_missing_fields,
        )
        topic = vault_dir / "02_Topics" / "ai.md"
        topic.write_text("---\ntype: topic\nname: AI\n---\n# AI\n", encoding="utf-8")
        findings = lint_frontmatter_missing_fields(vault_dir)
        assert any("status" in f["detail"] for f in findings)

    def test_claim_missing_claim_id(self, vault_dir):
        from podcast_research.workspace.vault_lint import (
            lint_frontmatter_missing_fields,
        )
        claim = vault_dir / "06_Claims" / "claim1.md"
        claim.write_text("---\ntype: claim\nstatus: active\n---\n# Claim\n", encoding="utf-8")
        findings = lint_frontmatter_missing_fields(vault_dir)
        assert any("claim_id" in f["detail"] for f in findings)

    def test_all_fields_present_no_error(self, vault_dir):
        from podcast_research.workspace.vault_lint import (
            lint_frontmatter_missing_fields,
        )
        rpt = vault_dir / "01_Reports" / "good.md"
        rpt.write_text(
            "---\ntype: report\nsource_type: youtube\nchannel: Test\n"
            "video_id: abc\nanalyzed_at: 2026-01-01\n---\n# Good\n",
            encoding="utf-8",
        )
        findings = lint_frontmatter_missing_fields(vault_dir)
        assert len(findings) == 0


# ═════════════════════════════════════════════════════════════════════════════
# Vault Lint: Dead Wikilinks
# ═════════════════════════════════════════════════════════════════════════════


class TestDeadWikilinkLint:
    """Tests for dead wikilink detection."""

    def test_valid_wikilink_no_error(self, vault_dir):
        from podcast_research.workspace.vault_lint import lint_dead_wikilinks
        # Create the target file
        (vault_dir / "Target.md").write_text("# Target\n", encoding="utf-8")
        src = vault_dir / "01_Reports" / "ref.md"
        src.write_text("---\ntype: report\n---\nSee [[Target]]\n", encoding="utf-8")
        findings = lint_dead_wikilinks(vault_dir)
        assert len(findings) == 0

    def test_dead_wikilink_detected(self, vault_dir):
        from podcast_research.workspace.vault_lint import lint_dead_wikilinks
        src = vault_dir / "01_Reports" / "ref.md"
        src.write_text("---\ntype: report\n---\n[[Ghost]]\n", encoding="utf-8")
        findings = lint_dead_wikilinks(vault_dir)
        assert len(findings) >= 1
        assert any("Ghost" in f["detail"] for f in findings)

    def test_wikilink_with_alias(self, vault_dir):
        from podcast_research.workspace.vault_lint import lint_dead_wikilinks
        src = vault_dir / "01_Reports" / "ref.md"
        src.write_text(
            "---\ntype: report\n---\n[[Ghost|A friendly ghost]]\n", encoding="utf-8",
        )
        findings = lint_dead_wikilinks(vault_dir)
        assert len(findings) >= 1
        assert any("Ghost" in f["detail"] for f in findings)

    def test_wikilink_with_section(self, vault_dir):
        from podcast_research.workspace.vault_lint import lint_dead_wikilinks
        src = vault_dir / "01_Reports" / "ref.md"
        src.write_text(
            "---\ntype: report\n---\n[[Ghost#section]]\n", encoding="utf-8",
        )
        findings = lint_dead_wikilinks(vault_dir)
        assert len(findings) >= 1


# ═════════════════════════════════════════════════════════════════════════════
# Vault Lint: Duplicate Reports
# ═════════════════════════════════════════════════════════════════════════════


class TestDuplicateReportLint:
    """Tests for duplicate report detection."""

    def test_same_video_id_duplicate(self, vault_dir):
        from podcast_research.workspace.vault_lint import lint_duplicate_reports
        r1 = vault_dir / "01_Reports" / "a.md"
        r1.write_text(
            "---\ntype: report\nvideo_id: dup123\n---\n# Report A\n", encoding="utf-8",
        )
        r2 = vault_dir / "01_Reports" / "b.md"
        r2.write_text(
            "---\ntype: report\nvideo_id: dup123\n---\n# Report B\n", encoding="utf-8",
        )
        findings = lint_duplicate_reports(vault_dir)
        assert len(findings) >= 1
        assert any("dup123" in f["detail"] for f in findings)

    def test_unique_video_ids_no_error(self, vault_dir):
        from podcast_research.workspace.vault_lint import lint_duplicate_reports
        r1 = vault_dir / "01_Reports" / "a.md"
        r1.write_text(
            "---\ntype: report\nvideo_id: abc\n---\n# A\n", encoding="utf-8",
        )
        r2 = vault_dir / "01_Reports" / "b.md"
        r2.write_text(
            "---\ntype: report\nvideo_id: def\n---\n# B\n", encoding="utf-8",
        )
        findings = lint_duplicate_reports(vault_dir)
        assert len(findings) == 0

    def test_same_content_hash_duplicate(self, vault_dir):
        from podcast_research.workspace.vault_lint import lint_duplicate_reports
        r1 = vault_dir / "01_Reports" / "a.md"
        r1.write_text(
            "---\ntype: report\ncontent_hash: hash_abc\n---\n# A\n", encoding="utf-8",
        )
        r2 = vault_dir / "01_Reports" / "b.md"
        r2.write_text(
            "---\ntype: report\ncontent_hash: hash_abc\n---\n# B\n", encoding="utf-8",
        )
        findings = lint_duplicate_reports(vault_dir)
        assert len(findings) >= 1


# ═════════════════════════════════════════════════════════════════════════════
# Vault Lint: Orphan Cards
# ═════════════════════════════════════════════════════════════════════════════


class TestOrphanCardLint:
    """Tests for orphan card detection."""

    def test_topic_without_report_is_orphan(self, vault_dir):
        from podcast_research.workspace.vault_lint import lint_orphan_cards
        topic = vault_dir / "02_Topics" / "AI_Safety.md"
        topic.write_text(
            "---\ntype: topic\nname: AI Safety\nstatus: core\n---\n# AI Safety\n",
            encoding="utf-8",
        )
        findings = lint_orphan_cards(vault_dir)
        assert len(findings) >= 1
        assert any("AI Safety" in f["detail"] for f in findings)

    def test_topic_with_report_not_orphan(self, vault_dir):
        from podcast_research.workspace.vault_lint import lint_orphan_cards
        topic = vault_dir / "02_Topics" / "GPU.md"
        topic.write_text(
            "---\ntype: topic\nname: GPU\nstatus: core\n---\n# GPU\n",
            encoding="utf-8",
        )
        rpt = vault_dir / "01_Reports" / "test.md"
        rpt.write_text(
            "---\ntype: report\nvideo_id: v1\nchannel: C\nanalyzed_at: 2026-01-01\n"
            "topic_tags: [GPU]\n---\nSee [[GPU]] for more.\n",
            encoding="utf-8",
        )
        findings = lint_orphan_cards(vault_dir)
        # GPU is referenced in the report via topic_tags and wikilink
        gpu_findings = [f for f in findings if "GPU" in f.get("detail", "")]
        assert len(gpu_findings) == 0

    def test_company_card_without_report(self, vault_dir):
        from podcast_research.workspace.vault_lint import lint_orphan_cards
        company = vault_dir / "03_Companies" / "Startup_XYZ.md"
        company.write_text(
            "---\ntype: company\nname: Startup XYZ\nstatus: emerging\n---\n# XYZ\n",
            encoding="utf-8",
        )
        findings = lint_orphan_cards(vault_dir)
        assert any("Startup XYZ" in f.get("detail", "") for f in findings)


# ═════════════════════════════════════════════════════════════════════════════
# Vault Lint: Runner + Review Integration
# ═════════════════════════════════════════════════════════════════════════════


class TestLintRunner:
    """Tests for run_vault_lint and write_lint_to_review."""

    def test_run_all_rules(self, vault_dir):
        from podcast_research.workspace.vault_lint import run_vault_lint
        # Create a file with known issues
        rpt = vault_dir / "01_Reports" / "bad.md"
        rpt.write_text("---\ntype: report\nvideo_id: v1\n---\n[[Ghost]]\n", encoding="utf-8")
        result = run_vault_lint(vault_dir)
        assert "run_id" in result
        assert "total_findings" in result
        assert "rule_counts" in result
        assert "findings" in result

    def test_filter_rules(self, vault_dir):
        from podcast_research.workspace.vault_lint import run_vault_lint
        rpt = vault_dir / "01_Reports" / "bad.md"
        rpt.write_text("---\ntype: report\n---\n[[Ghost]]\n", encoding="utf-8")
        result = run_vault_lint(vault_dir, rules=["dead_wikilink"])
        assert "dead_wikilink" in result["rule_counts"]
        assert "frontmatter_invalid" not in result["rule_counts"]

    def test_exclude_rules(self, vault_dir):
        from podcast_research.workspace.vault_lint import run_vault_lint
        rpt = vault_dir / "01_Reports" / "bad.md"
        rpt.write_text("---\n{invalid\n---\n", encoding="utf-8")
        result = run_vault_lint(vault_dir, exclude=["frontmatter_invalid"])
        assert "frontmatter_invalid" not in result["rule_counts"]

    def test_write_lint_to_review(self, vault_dir, review_mgr):
        """Lint findings can be written as review items."""
        from podcast_research.workspace.vault_lint import (
            run_vault_lint,
            write_lint_to_review,
        )

        rpt = vault_dir / "01_Reports" / "bad.md"
        rpt.write_text("---\ntype: report\n---\n[[Ghost]]\n", encoding="utf-8")

        result = run_vault_lint(vault_dir)
        assert result["total_findings"] > 0

        created = write_lint_to_review(result["findings"])
        assert created > 0

        # Verify review items exist
        items = review_mgr.list_items()
        assert len(items) >= created

    def test_dedup_lint_findings(self, vault_dir):
        """Same lint finding twice should not create duplicate review items."""
        from podcast_research.workspace.vault_lint import (
            run_vault_lint,
            write_lint_to_review,
        )

        rpt = vault_dir / "01_Reports" / "bad.md"
        rpt.write_text("---\ntype: report\n---\n[[Ghost]]\n", encoding="utf-8")

        result = run_vault_lint(vault_dir)
        write_lint_to_review(result["findings"])
        c2 = write_lint_to_review(result["findings"])  # Same findings again
        assert c2 == 0  # No new items created


# ═════════════════════════════════════════════════════════════════════════════
# CLI Smoke Tests
# ═════════════════════════════════════════════════════════════════════════════


class TestLintCLI:
    """Smoke tests for vault-lint CLI."""

    def test_vault_lint_table_output(self, vault_dir):
        from typer.testing import CliRunner

        from podcast_research.cli import app

        rpt = vault_dir / "01_Reports" / "bad.md"
        rpt.write_text("---\ntype: report\n---\n[[Ghost]]\n", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(app, ["vault-lint", "--vault", str(vault_dir)])
        assert result.exit_code == 0
        assert "Vault Lint" in result.stdout or "发现" in result.stdout

    def test_vault_lint_json_output(self, vault_dir):
        from typer.testing import CliRunner

        from podcast_research.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["vault-lint", "--vault", str(vault_dir), "--json"])
        assert result.exit_code == 0
        # JSON output should contain expected keys
        assert '"run_id"' in result.stdout
        assert '"total_findings"' in result.stdout
        assert '"rule_counts"' in result.stdout

    def test_vault_lint_missing_path(self):
        from typer.testing import CliRunner

        from podcast_research.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["vault-lint", "--vault", "/nonexistent/path"])
        assert result.exit_code != 0

    def test_vault_lint_write_review(self, vault_dir):
        from typer.testing import CliRunner

        from podcast_research.cli import app

        rpt = vault_dir / "01_Reports" / "bad.md"
        rpt.write_text("---\ntype: report\n---\n[[Ghost]]\n", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            app, ["vault-lint", "--vault", str(vault_dir), "--write-review"],
        )
        assert result.exit_code == 0
        assert "review items" in result.stdout.lower() or "review" in result.stdout.lower()


class TestReviewCLI:
    """Smoke tests for review CLI commands."""

    def test_review_list_empty(self):
        from typer.testing import CliRunner

        from podcast_research.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["review", "list"])
        assert result.exit_code == 0

    def test_review_list_with_data(self, review_mgr):
        review_mgr.create_item(item_type="manual", title="CLI test item")
        from typer.testing import CliRunner

        from podcast_research.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["review", "list"])
        assert result.exit_code == 0

    def test_review_show_nonexistent(self):
        from typer.testing import CliRunner

        from podcast_research.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["review", "show", "99999"])
        assert result.exit_code != 0

    def test_review_show_existing(self, review_mgr):
        item = review_mgr.create_item(item_type="manual", title="Show me")
        assert item is not None
        from typer.testing import CliRunner

        from podcast_research.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["review", "show", str(item["id"])])
        assert result.exit_code == 0
        assert "Show me" in result.stdout

    def test_review_accept(self, review_mgr):
        item = review_mgr.create_item(item_type="manual", title="Accept CLI")
        assert item is not None
        from typer.testing import CliRunner

        from podcast_research.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["review", "accept", str(item["id"])])
        assert result.exit_code == 0

    def test_review_skip(self, review_mgr):
        item = review_mgr.create_item(item_type="manual", title="Skip CLI")
        assert item is not None
        from typer.testing import CliRunner

        from podcast_research.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["review", "skip", str(item["id"])])
        assert result.exit_code == 0

    def test_review_resolve(self, review_mgr):
        item = review_mgr.create_item(item_type="manual", title="Resolve CLI")
        assert item is not None
        from typer.testing import CliRunner

        from podcast_research.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["review", "resolve", str(item["id"])])
        assert result.exit_code == 0


# ═════════════════════════════════════════════════════════════════════════════
# Edge Cases
# ═════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_vault_no_crash(self, vault_dir):
        from podcast_research.workspace.vault_lint import run_vault_lint
        result = run_vault_lint(vault_dir)
        assert result["total_findings"] == 0

    def test_binary_file_in_vault(self, vault_dir):
        """Non-UTF8 files should not crash lint."""
        (vault_dir / "01_Reports" / "binary.md").write_bytes(b"\x00\x01\x02\xff\xfe")
        from podcast_research.workspace.vault_lint import lint_frontmatter_invalid
        findings = lint_frontmatter_invalid(vault_dir)
        # Should not crash
        assert isinstance(findings, list)

    def test_review_create_from_lint_dedup_by_source_path(self, vault_dir, review_mgr):
        """Same file+type should not create duplicate open items."""
        from podcast_research.workspace.vault_lint import (
            run_vault_lint,
            write_lint_to_review,
        )

        rpt = vault_dir / "01_Reports" / "dup.md"
        rpt.write_text("---\ntype: report\n---\n[[Ghost]]\n", encoding="utf-8")

        result = run_vault_lint(vault_dir)
        # Write once
        write_lint_to_review(result["findings"])
        # Write again — should dedup
        c2 = write_lint_to_review(result["findings"])
        assert c2 == 0
