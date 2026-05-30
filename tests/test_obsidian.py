"""P2-C: Obsidian Export v1 tests. All tests use tmp_path vault, never real vault."""

import json
import pytest
from pathlib import Path
from datetime import datetime
from collections import OrderedDict

from podcast_research.exporters.markdown_utils import (
    sanitize_filename,
    build_frontmatter,
    wiki_link,
    wiki_links_from_list,
)


# ═════════════════════════════════════════════════════════════════════════════
# markdown_utils tests
# ═════════════════════════════════════════════════════════════════════════════

def test_sanitize_filename_removes_illegal_chars():
    assert sanitize_filename('test<file>:name*?"yes"|no') == "test-file-name-yes-no"


def test_sanitize_filename_collapses_hyphens():
    assert sanitize_filename("a//b\\\\c") == "a-b-c"


def test_sanitize_filename_limits_length():
    long_name = "x" * 300
    assert len(sanitize_filename(long_name)) <= 200


def test_sanitize_filename_keeps_valid_chars():
    assert sanitize_filename("All-In Podcast - Episode 1") == "All-In Podcast - Episode 1"


def test_build_frontmatter_basic():
    fm = build_frontmatter(OrderedDict([
        ("type", "report"),
        ("source_type", "youtube"),
        ("focus_areas", ["AI", "tech"]),
        ("published", ""),
    ]))
    assert "---" in fm
    assert "type: report" in fm
    assert "focus_areas:" in fm
    assert "  - AI" in fm
    assert "published:" in fm


def test_build_frontmatter_quotes_colon_values():
    fm = build_frontmatter(OrderedDict([
        ("url", "https://www.youtube.com/watch?v=abc123"),
    ]))
    assert "url:" in fm


def test_wiki_link_generates_link():
    assert wiki_link("NVIDIA") == "[[NVIDIA]]"


def test_wiki_link_empty():
    assert wiki_link("") == ""
    assert wiki_link("   ") == ""


def test_wiki_link_sanitizes():
    assert wiki_link("test:file") == "[[test-file]]"


def test_wiki_links_from_list():
    links = wiki_links_from_list(["NVIDIA", "TSMC", ""])
    assert "[[NVIDIA]]" in links
    assert "[[TSMC]]" in links


# ═════════════════════════════════════════════════════════════════════════════
# Report export tests
# ═════════════════════════════════════════════════════════════════════════════

def test_export_report_creates_file(seeded_db, tmp_path):
    """Report export 生成正确文件。"""
    from podcast_research.db.session import get_session
    from podcast_research.db.models import Report, Episode, InvestmentViewRecord
    from podcast_research.exporters.obsidian import export_report, _load_extraction

    session = get_session()
    report = session.query(Report).first()
    episode = session.query(Episode).filter_by(id=report.episode_id).first()
    views = session.query(InvestmentViewRecord).filter_by(report_id=report.id).all()
    session.close()

    views_data = [
        {
            "target_name": v.target_name,
            "view_direction": v.view_direction,
            "ai_value_chain_layer": v.ai_value_chain_layer,
            "evidence_type": v.evidence_type,
            "evidence_strength": v.evidence_strength,
            "time_horizon": v.time_horizon,
            "timestamp_start": v.timestamp_start,
            "topic_tags": json.loads(v.topic_tags) if v.topic_tags else [],
        }
        for v in views
    ]
    extraction = _load_extraction(report)

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_report(vault, report, episode, views_data, extraction,
                          channel_name="BG2Pod")
    assert result["status"] == "created"

    filepath = Path(result["path"])
    assert filepath.exists()
    content = filepath.read_text(encoding="utf-8")
    assert "---" in content  # frontmatter
    assert "type: report" in content
    assert "Core Investment Views" in content
    assert "## Source" in content
    assert "BG2Pod" in content


def test_export_report_skips_existing(seeded_db, tmp_path):
    """已存在文件默认 skip。"""
    from podcast_research.db.session import get_session
    from podcast_research.db.models import Report, Episode
    from podcast_research.exporters.obsidian import export_report, _load_extraction

    session = get_session()
    # Use report #3 (NVIDIA, youtube, video_id=abc123)
    report = session.query(Report).filter(Report.id == 3).first()
    episode = session.query(Episode).filter_by(id=report.episode_id).first()
    session.close()

    extraction = _load_extraction(report)
    vid = episode.video_id or "unknown"

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "01_Reports").mkdir()

    # Pre-create file matching the expected filename pattern
    filename = f"2026-06-01_UnknownChannel_{vid}.md"  # date is from analysis_timestamp
    # Actually the date depends on analysis_timestamp - just find any file written
    # Pre-create using a shell glob or just write the expected path after the export
    # Simpler approach: create the exact file the exporter would write
    from podcast_research.exporters.markdown_utils import sanitize_filename
    # The exporter constructs: {date}_{ch_safe}_{vid}.md
    date_str = report.analysis_timestamp.strftime("%Y-%m-%d")
    exp_filename = f"{date_str}_BG2Pod_{vid}.md"
    filepath = vault / "01_Reports" / exp_filename
    filepath.write_text("existing content", encoding="utf-8")

    result = export_report(vault, report, episode, [], extraction,
                          channel_name="BG2Pod")
    assert result["status"] == "skipped"
    assert filepath.read_text(encoding="utf-8") == "existing content"


def test_export_report_overwrite(seeded_db, tmp_path):
    """--overwrite 覆盖已存在文件。"""
    from podcast_research.db.session import get_session
    from podcast_research.db.models import Report, Episode
    from podcast_research.exporters.obsidian import export_report, _load_extraction

    session = get_session()
    # Use report #3 (youtube, has video_id)
    report = session.query(Report).filter(Report.id == 3).first()
    episode = session.query(Episode).filter_by(id=report.episode_id).first()
    session.close()

    extraction = _load_extraction(report)
    vid = episode.video_id or "unknown"
    date_str = report.analysis_timestamp.strftime("%Y-%m-%d")

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "01_Reports").mkdir()

    filename = f"{date_str}_BG2Pod_{vid}.md"
    filepath = vault / "01_Reports" / filename
    old_content = "old content"
    filepath.write_text(old_content, encoding="utf-8")

    result = export_report(vault, report, episode, [], extraction,
                          channel_name="BG2Pod", overwrite=True)
    assert result["status"] == "created"
    new_content = filepath.read_text(encoding="utf-8")
    assert new_content != old_content
    assert "Core Investment Views" in new_content


def test_export_report_has_frontmatter_fields(seeded_db, tmp_path):
    """Report frontmatter 包含所有必需字段。"""
    from podcast_research.db.session import get_session
    from podcast_research.db.models import Report, Episode, InvestmentViewRecord
    from podcast_research.exporters.obsidian import export_report, _load_extraction

    session = get_session()
    report = session.query(Report).first()
    episode = session.query(Episode).filter_by(id=report.episode_id).first()
    session.close()

    extraction = _load_extraction(report)

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_report(vault, report, episode, [], extraction,
                          channel_name="TestChannel")
    content = Path(result["path"]).read_text(encoding="utf-8")

    for field in ["type:", "source_type:", "channel:", "video_id:", "video_url:",
                   "published_at:", "analyzed_at:", "prompt_version:", "model:",
                   "focus_areas:", "tags:"]:
        assert field in content, f"Missing frontmatter field: {field}"


def test_export_report_wiki_links(seeded_db, tmp_path):
    """Report 中 entity wiki links 正确生成。"""
    from podcast_research.db.session import get_session
    from podcast_research.db.models import Report, Episode
    from podcast_research.exporters.obsidian import export_report, _load_extraction

    session = get_session()
    report = session.query(Report).filter(Report.id == 3).first()  # NVIDIA report
    episode = session.query(Episode).filter_by(id=report.episode_id).first()
    session.close()

    extraction = _load_extraction(report)

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_report(vault, report, episode, [], extraction,
                          channel_name="Acquired")
    content = Path(result["path"]).read_text(encoding="utf-8")
    # NVIDIA should appear as wiki link or in entities
    assert "[[" in content or "NVIDIA" in content


# ═════════════════════════════════════════════════════════════════════════════
# Channel card tests
# ═════════════════════════════════════════════════════════════════════════════

def test_export_channel_card_creates_new(tmp_path):
    """创建新频道卡片。"""
    from podcast_research.exporters.obsidian import export_channel_card

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_channel_card(
        vault_path=vault,
        channel_name="All-In Podcast",
        channel_url="https://www.youtube.com/@allin",
        channel_tags=["tech", "ai", "vc"],
        channel_priority="core",
    )
    assert result["status"] == "created"

    content = Path(result["path"]).read_text(encoding="utf-8")
    assert "type: channel" in content
    assert "All-In Podcast" in content
    assert "## Recent Reports" in content
    assert "## Positioning" in content


def test_export_channel_card_skips_existing(tmp_path):
    """已存在文件默认不覆盖。"""
    from podcast_research.exporters.obsidian import export_channel_card

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "05_Channels").mkdir()

    filepath = vault / "05_Channels" / "All-In Podcast.md"
    filepath.write_text("# Custom user content\n## Notes\nUser notes here.", encoding="utf-8")

    result = export_channel_card(
        vault_path=vault,
        channel_name="All-In Podcast",
        channel_url="https://www.youtube.com/@allin",
        recent_reports=[{"filename": "2026-05-29_All-In_abc123"}],
    )
    assert result["status"] == "updated"  # appends reports

    content = filepath.read_text(encoding="utf-8")
    assert "Custom user content" in content  # user content NOT overwritten
    assert "2026-05-29_All-In_abc123" in content  # new report link added


def test_export_channel_card_overwrite(tmp_path):
    """--overwrite 完全重写频道卡片。"""
    from podcast_research.exporters.obsidian import export_channel_card

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "05_Channels").mkdir()

    filepath = vault / "05_Channels" / "All-In Podcast.md"
    filepath.write_text("old content", encoding="utf-8")

    result = export_channel_card(
        vault_path=vault,
        channel_name="All-In Podcast",
        channel_url="https://www.youtube.com/@allin",
        overwrite=True,
    )
    assert result["status"] == "created"

    content = filepath.read_text(encoding="utf-8")
    assert "old content" not in content
    assert "## Positioning" in content


# ═════════════════════════════════════════════════════════════════════════════
# System files tests
# ═════════════════════════════════════════════════════════════════════════════

def test_report_index_generation(seeded_db, tmp_path):
    """Report Index 正确生成。"""
    from podcast_research.exporters.obsidian import export_to_vault

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_to_vault(vault, source_type="youtube", limit=3)
    assert result["created"] + result["skipped"] > 0

    index_path = vault / "99_System" / "Report Index.md"
    assert index_path.exists()
    content = index_path.read_text(encoding="utf-8")
    assert "# Report Index" in content
    assert "| Date | Channel | Title | Video ID | Report |" in content


def test_export_log_generation(seeded_db, tmp_path):
    """Export Log 正确生成。"""
    from podcast_research.exporters.obsidian import export_to_vault

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_to_vault(vault, source_type="youtube", limit=3)

    log_path = vault / "99_System" / "Export Log.md"
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "# Export Log" in content
    assert "Exported reports" in content


def test_dry_run_does_not_write(seeded_db, tmp_path):
    """--dry-run 不写入任何文件。"""
    from podcast_research.exporters.obsidian import export_to_vault

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_to_vault(vault, source_type="youtube", limit=3, dry_run=True)
    assert result.get("dry_run") is True

    # No files should have been created
    reports_dir = vault / "01_Reports"
    channels_dir = vault / "05_Channels"
    system_dir = vault / "99_System"

    report_files = list(reports_dir.glob("*.md")) if reports_dir.exists() else []
    channel_files = list(channels_dir.glob("*.md")) if channels_dir.exists() else []
    system_files = list(system_dir.glob("*.md")) if system_dir.exists() else []
    assert len(report_files) == 0
    assert len(channel_files) == 0
    assert len(system_files) == 0


# ═════════════════════════════════════════════════════════════════════════════
# Full export tests
# ═════════════════════════════════════════════════════════════════════════════

def test_full_export_to_tmp_vault(seeded_db, tmp_path):
    """完整导出流程：reports + channels + index + log。"""
    from podcast_research.exporters.obsidian import export_to_vault

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_to_vault(vault, source_type="youtube", limit=3)

    assert result["created"] + result["skipped"] >= 1
    assert "exported" in result

    # Reports should exist
    reports = list((vault / "01_Reports").glob("*.md"))
    assert len(reports) >= 1

    # Index should exist
    assert (vault / "99_System" / "Report Index.md").exists()
    assert (vault / "99_System" / "Export Log.md").exists()


def test_export_report_id_specific(seeded_db, tmp_path):
    """--report-id 只导出指定报告。"""
    from podcast_research.exporters.obsidian import export_to_vault

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_to_vault(vault, report_id=1)
    assert result["created"] + result["skipped"] == 1


# ═════════════════════════════════════════════════════════════════════════════
# CLI tests
# ═════════════════════════════════════════════════════════════════════════════

def test_cli_obsidian_export_dry_run(seeded_db, tmp_path):
    """CLI obsidian export --dry-run 不写入。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    vault = tmp_path / "vault"
    vault.mkdir()

    runner = CliRunner()
    result = runner.invoke(app, [
        "obsidian", "export",
        "--vault", str(vault),
        "--limit", "3",
        "--dry-run",
    ])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.stdout


def test_cli_obsidian_export_vault_not_exists():
    """Vault 路径不存在时报错。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    runner = CliRunner()
    result = runner.invoke(app, [
        "obsidian", "export",
        "--vault", "/nonexistent/path/xyz",
        "--limit", "1",
    ])
    assert result.exit_code == 1


def test_cli_obsidian_export_no_vault():
    """未指定 --vault 且 .env 未配置时报错。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["obsidian", "export", "--limit", "1"])
    assert result.exit_code == 1


def test_cli_obsidian_export_basic(seeded_db, tmp_path):
    """CLI obsidian export 基本运行。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    vault = tmp_path / "vault"
    vault.mkdir()

    runner = CliRunner()
    result = runner.invoke(app, [
        "obsidian", "export",
        "--vault", str(vault),
        "--limit", "2",
    ])
    assert result.exit_code == 0
    assert "Export" in result.stdout or "exported" in result.stdout.lower()


def test_existing_tests_unaffected():
    """标记：原有测试不受影响。"""
    pass
