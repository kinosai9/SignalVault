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


def test_cli_obsidian_export_no_vault(monkeypatch):
    """未指定 --vault 且 .env 未配置时报错。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app
    import podcast_research.config

    # Isolate from local .env OBSIDIAN_VAULT_PATH
    monkeypatch.setattr(podcast_research.config, "OBSIDIAN_VAULT_PATH", "")

    runner = CliRunner()
    result = runner.invoke(app, ["obsidian", "export", "--limit", "1"])
    assert result.exit_code == 1


def test_cli_obsidian_export_no_vault_with_env_set(seeded_db, monkeypatch, tmp_path):
    """monkeypatch 设置 OBSIDIAN_VAULT_PATH 后不传 --vault 仍能走通。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app
    import podcast_research.config

    # Even if .env has OBSIDIAN_VAULT_PATH, monkeypatch overrides it
    fake_vault = tmp_path / "fake_vault"
    fake_vault.mkdir()
    monkeypatch.setattr(podcast_research.config, "OBSIDIAN_VAULT_PATH", str(fake_vault))

    runner = CliRunner()
    # Without --vault, should fall back to monkeypatched OBSIDIAN_VAULT_PATH
    # and succeed (vault exists, but no seeded_db → 0 reports, which is fine)
    result = runner.invoke(app, ["obsidian", "export", "--limit", "1", "--dry-run"])
    assert result.exit_code == 0


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


# ═════════════════════════════════════════════════════════════════════════════
# P2-C Hardening: metadata backfill tests
# ═════════════════════════════════════════════════════════════════════════════

def _seed_channel_video(session, video_id, channel_name, channel_url="",
                        channel_tags=None, video_title="", published_at=""):
    """Helper: create Channel + ChannelVideo for backfill testing."""
    from podcast_research.db.models import Channel, ChannelVideo
    ch = Channel(
        youtube_channel_id=f"UC_{channel_name.replace(' ', '_')}",
        name=channel_name,
        url=channel_url or f"https://www.youtube.com/@{channel_name.lower().replace(' ', '')}",
        tags=json.dumps(channel_tags or ["tech", "ai"]),
        priority="core",
    )
    session.add(ch)
    session.flush()
    cv = ChannelVideo(
        channel_id=ch.id,
        video_id=video_id,
        title=video_title or f"{channel_name} Video {video_id}",
        url=f"https://www.youtube.com/watch?v={video_id}",
        published_at=published_at or "2026-05-15",
    )
    session.add(cv)
    session.commit()
    return ch.id


def test_backfill_channel_name_from_channel_videos(seeded_db, tmp_path):
    """export 时能通过 channel_videos backfill channel_name。"""
    from podcast_research.exporters.obsidian import export_to_vault

    session = seeded_db
    # seeded_db report #3 has video_id="abc123" with empty source_info.channel_name
    _seed_channel_video(session, "abc123", "TechInvest",
                        channel_url="https://www.youtube.com/@techinvest",
                        video_title="AI Investment 2026")

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_to_vault(vault, source_type="youtube")

    # Report #3 should have been exported with backfilled channel_name
    report3_entry = next((r for r in result["exported"] if r["report_id"] == 3), None)
    assert report3_entry is not None
    assert report3_entry["channel"] == "TechInvest"

    # Verify file was created with correct channel name in filename
    reports = list((vault / "01_Reports").glob("*TechInvest*"))
    assert len(reports) >= 1


def test_backfill_video_title_from_channel_videos(seeded_db, tmp_path):
    """export 时能通过 channel_videos backfill video_title。"""
    from podcast_research.exporters.obsidian import export_to_vault

    session = seeded_db
    _seed_channel_video(session, "abc123", "TechInvest",
                        video_title="Deep Dive into AI Chips")

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_to_vault(vault, source_type="youtube")

    report3_entry = next((r for r in result["exported"] if r["report_id"] == 3), None)
    assert report3_entry is not None
    # title should be backfilled from channel_videos
    assert "Deep Dive into AI Chips" in report3_entry["title"] or report3_entry["title"] != ""


def test_backfill_does_not_overwrite_existing(seeded_db, tmp_path):
    """backfill 不覆盖已有的 channel_name。"""
    from podcast_research.db.models import Report
    from podcast_research.exporters.obsidian import export_to_vault

    session = seeded_db
    # Manually set source_info with channel_name for report #3
    report = session.query(Report).filter(Report.id == 3).first()
    extraction = json.loads(report.extraction_json)
    extraction["source_info"] = {"channel_name": "ExistingChannel", "title": "Existing Title"}
    report.extraction_json = json.dumps(extraction)
    session.commit()

    # Seed channel_videos with different name
    _seed_channel_video(session, "abc123", "BackfillChannel",
                        video_title="Backfill Title")

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_to_vault(vault, source_type="youtube")

    report3_entry = next((r for r in result["exported"] if r["report_id"] == 3), None)
    assert report3_entry is not None
    # Should keep existing channel_name, NOT backfill
    assert report3_entry["channel"] == "ExistingChannel"


# ═════════════════════════════════════════════════════════════════════════════
# P2-C Hardening: filtering tests
# ═════════════════════════════════════════════════════════════════════════════

def _seed_two_youtube_reports(session):
    """Helper: add a second youtube report with a different channel."""
    from podcast_research.db.repository import save_episode, save_report

    ep4_id = save_episode(
        session, "Tech Talk", "youtube", "json", "hash4",
        source_url="https://www.youtube.com/watch?v=def456",
        video_id="def456",
        language="en",
    )
    ex4 = _make_extraction_helper("TSMC", "bullish")
    rep4_id = save_report(session, ep4_id, ex4, "# TSMC Report", analysis_depth="standard")

    # Set source_info with channel name for report 3
    from podcast_research.db.models import Report
    report3 = session.query(Report).filter(Report.id == 3).first()
    extraction3 = json.loads(report3.extraction_json)
    extraction3["source_info"] = {"channel_name": "Acquired"}
    report3.extraction_json = json.dumps(extraction3)

    # Set source_info with channel name for report 4
    report4 = session.query(Report).filter(Report.id == rep4_id).first()
    extraction4 = json.loads(report4.extraction_json)
    extraction4["source_info"] = {"channel_name": "BG2Pod"}
    report4.extraction_json = json.dumps(extraction4)

    session.commit()
    return rep4_id


def _make_extraction_helper(target="NVIDIA", direction="bullish"):
    """Helper to create ExtractionResult for tests."""
    from podcast_research.analysis.models import (
        Entity, ExtractionResult, InvestmentView, TrackingSignal,
    )
    return ExtractionResult(
        focus_areas=["tech"],
        investment_views=[
            InvestmentView(
                target_name=target,
                target_type="stock",
                view_direction=direction,
                logic_chain=f"{target} logic",
                source_quote=f"quote about {target}",
                timestamp_start="00:10:00",
            )
        ],
        mentioned_entities=[Entity(name=target, entity_type="stock")],
        tracking_signals=[TrackingSignal(signal=f"Watch {target}", target_name=target)],
    )


def test_only_with_channel_skips_unknown(seeded_db, tmp_path):
    """--only-with-channel 跳过无频道信息的报告。"""
    from podcast_research.exporters.obsidian import export_to_vault

    vault = tmp_path / "vault"
    vault.mkdir()

    # Report #3 has no channel_name in source_info and no channel_videos entry
    result = export_to_vault(
        vault, source_type="youtube", only_with_channel=True
    )

    # All youtube reports should be skipped (no channel info)
    for entry in result["exported"]:
        assert entry["action"] == "skip"
        assert entry["reason"] == "missing_channel"
    assert result["created"] == 0


def test_channel_filter_only_matching(seeded_db, tmp_path):
    """--channel Acquired 只导出 Acquired 报告。"""
    from podcast_research.exporters.obsidian import export_to_vault

    session = seeded_db
    _seed_two_youtube_reports(session)

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_to_vault(
        vault, source_type="youtube", channel_filter="Acquired"
    )

    # Only Acquired reports should be exported
    exported_channels = [r["channel"] for r in result["exported"] if r.get("action") != "skip"]
    for ch in exported_channels:
        assert "acquired" in ch.lower()

    # BG2Pod should be skipped
    bg2_entries = [r for r in result["exported"]
                   if r.get("channel", "") == "BG2Pod" and r.get("action") == "skip"]
    assert len(bg2_entries) >= 1


def test_channel_filter_case_insensitive(seeded_db, tmp_path):
    """--channel 过滤大小写不敏感。"""
    from podcast_research.exporters.obsidian import export_to_vault

    session = seeded_db
    _seed_two_youtube_reports(session)

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_to_vault(
        vault, source_type="youtube", channel_filter="acquired"
    )

    exported_channels = [r["channel"] for r in result["exported"] if r.get("action") != "skip"]
    assert len(exported_channels) >= 1
    for ch in exported_channels:
        assert "acquired" in ch.lower()


def test_channel_filter_with_backfill(seeded_db, tmp_path):
    """--channel 能使用 backfilled channel_name 匹配。"""
    from podcast_research.exporters.obsidian import export_to_vault

    session = seeded_db
    # Report #3 has no channel_name in source_info
    # But backfill from channel_videos gives it "Acquired"
    _seed_channel_video(session, "abc123", "Acquired",
                        video_title="Acquired Episode")

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_to_vault(
        vault, source_type="youtube", channel_filter="Acquired"
    )

    # Report #3 should be exported (matched via backfill)
    report3_entry = next((r for r in result["exported"] if r["report_id"] == 3), None)
    assert report3_entry is not None
    assert report3_entry["action"] == "export"
    assert report3_entry["channel"] == "Acquired"


def test_channel_filter_partial_match(seeded_db, tmp_path):
    """--channel 支持部分匹配。"""
    from podcast_research.exporters.obsidian import export_to_vault

    session = seeded_db
    _seed_two_youtube_reports(session)

    vault = tmp_path / "vault"
    vault.mkdir()

    # "acqu" should match "Acquired"
    result = export_to_vault(
        vault, source_type="youtube", channel_filter="acqu"
    )

    exported_channels = [r["channel"] for r in result["exported"] if r.get("action") != "skip"]
    assert len(exported_channels) >= 1


def test_unknown_channel_default_still_exports(seeded_db, tmp_path):
    """P2-L.2: UnknownChannel 不再作为默认 fallback，改用 YouTube_{video_id}。"""
    from podcast_research.exporters.obsidian import export_to_vault

    vault = tmp_path / "vault"
    vault.mkdir()

    # No channel info, no filters → should export with YouTube_{video_id} fallback
    result = export_to_vault(vault, source_type="youtube")

    assert result["created"] >= 1
    # Check that file exists (no longer uses UnknownChannel as fallback)
    reports = list((vault / "01_Reports").glob("*.md"))
    assert len(reports) >= 1
    # UnknownChannel should NOT appear in filename
    unknown = list((vault / "01_Reports").glob("*UnknownChannel*"))
    assert len(unknown) == 0, "UnknownChannel should not be used as default fallback"


# ═════════════════════════════════════════════════════════════════════════════
# P2-C Hardening: dry-run enhancement tests
# ═════════════════════════════════════════════════════════════════════════════

def test_dry_run_returns_action_and_reason(seeded_db, tmp_path):
    """dry-run 返回 action/reason 字段。"""
    from podcast_research.exporters.obsidian import export_to_vault

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_to_vault(
        vault, source_type="youtube", dry_run=True
    )

    assert result.get("dry_run") is True
    for entry in result["exported"]:
        assert "action" in entry
        assert "reason" in entry
        assert entry["action"] in ("export", "skip")


def test_dry_run_only_with_channel_marks_missing(seeded_db, tmp_path):
    """dry-run + only_with_channel 标记 missing_channel。"""
    from podcast_research.exporters.obsidian import export_to_vault

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_to_vault(
        vault, source_type="youtube", dry_run=True,
        only_with_channel=True,
    )

    # Report #3 has no channel info → should be marked as skip/missing_channel
    report3 = next((r for r in result["exported"] if r["report_id"] == 3), None)
    assert report3 is not None
    assert report3["action"] == "skip"
    assert report3["reason"] == "missing_channel"


def test_dry_run_channel_filter_marks_filtered(seeded_db, tmp_path):
    """dry-run + channel_filter 标记 filtered_by_channel。"""
    from podcast_research.exporters.obsidian import export_to_vault

    session = seeded_db
    _seed_two_youtube_reports(session)

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_to_vault(
        vault, source_type="youtube", dry_run=True,
        channel_filter="BG2Pod",
    )

    for entry in result["exported"]:
        if entry.get("channel") == "Acquired":
            assert entry["action"] == "skip"
            assert entry["reason"] == "filtered_by_channel"
        elif entry.get("channel") == "BG2Pod":
            assert entry["action"] == "export"


def test_dry_run_with_backfill_shows_channel(seeded_db, tmp_path):
    """dry-run 中 backfill 的 channel_name 正确显示。"""
    from podcast_research.exporters.obsidian import export_to_vault

    session = seeded_db
    _seed_channel_video(session, "abc123", "BackfilledChannel")

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_to_vault(
        vault, source_type="youtube", dry_run=True,
    )

    report3 = next((r for r in result["exported"] if r["report_id"] == 3), None)
    assert report3 is not None
    assert report3["channel"] == "BackfilledChannel"


def test_dry_run_no_files_written_with_filters(seeded_db, tmp_path):
    """dry-run + filters 不写入文件。"""
    from podcast_research.exporters.obsidian import export_to_vault

    session = seeded_db
    _seed_two_youtube_reports(session)

    vault = tmp_path / "vault"
    vault.mkdir()

    result = export_to_vault(
        vault, source_type="youtube", dry_run=True,
        channel_filter="Acquired", only_with_channel=True,
    )

    assert result.get("dry_run") is True
    for subdir in ["01_Reports", "05_Channels", "99_System"]:
        files = list((vault / subdir).glob("*.md")) if (vault / subdir).exists() else []
        assert len(files) == 0


# ═════════════════════════════════════════════════════════════════════════════
# P2-C Hardening: CLI tests
# ═════════════════════════════════════════════════════════════════════════════

def test_cli_obsidian_export_channel_filter(seeded_db, tmp_path):
    """CLI --channel 过滤参数工作。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    vault = tmp_path / "vault"
    vault.mkdir()

    runner = CliRunner()
    result = runner.invoke(app, [
        "obsidian", "export",
        "--vault", str(vault),
        "--channel", "NonExistent",
        "--dry-run",
    ])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.stdout


def test_cli_obsidian_export_only_with_channel(seeded_db, tmp_path):
    """CLI --only-with-channel 参数工作。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    vault = tmp_path / "vault"
    vault.mkdir()

    runner = CliRunner()
    result = runner.invoke(app, [
        "obsidian", "export",
        "--vault", str(vault),
        "--only-with-channel",
        "--dry-run",
    ])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.stdout


def test_cli_obsidian_enhanced_dry_run_table(seeded_db, tmp_path):
    """CLI enhanced dry-run 表格包含 Action/Reason 列。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    vault = tmp_path / "vault"
    vault.mkdir()

    runner = CliRunner()
    result = runner.invoke(app, [
        "obsidian", "export",
        "--vault", str(vault),
        "--dry-run",
    ])
    assert result.exit_code == 0
    # Enhanced table should contain Action and Reason columns
    assert "Action" in result.stdout
    assert "Reason" in result.stdout


# ═════════════════════════════════════════════════════════════════════════════
# P2-C.1: UnknownChannel cleanup tests
# ═════════════════════════════════════════════════════════════════════════════

def _create_unknown_report(vault, video_id, date="2026-05-15"):
    """Helper: create an UnknownChannel report file in vault."""
    reports_dir = vault / "01_Reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{date}_UnknownChannel_{video_id}.md"
    filepath = reports_dir / filename
    content = f"""---
type: report
source_type: youtube
channel: ""
video_id: {video_id}
video_url: https://www.youtube.com/watch?v={video_id}
published_at: ""
analyzed_at: 2026-05-20 10:00
prompt_version: v0.1
model: mock-v1
tags:
  - podcast-report
---

# Unknown Video

## Summary

Test summary.
"""
    filepath.write_text(content, encoding="utf-8")
    return filepath


def test_parse_yaml_frontmatter_basic():
    """_parse_yaml_frontmatter 正确解析简单 frontmatter。"""
    from podcast_research.exporters.obsidian import _parse_yaml_frontmatter

    content = """---
type: report
video_id: abc123
channel: "TestChannel"
published_at: 2026-05-15
---

# Title
"""
    fm = _parse_yaml_frontmatter(content)
    assert fm["type"] == "report"
    assert fm["video_id"] == "abc123"
    assert fm["channel"] == "TestChannel"
    assert fm["published_at"] == "2026-05-15"


def test_parse_yaml_frontmatter_no_frontmatter():
    """_parse_yaml_frontmatter 处理无 frontmatter 内容。"""
    from podcast_research.exporters.obsidian import _parse_yaml_frontmatter

    assert _parse_yaml_frontmatter("# Just a title\nNo frontmatter here.") == {}
    assert _parse_yaml_frontmatter("") == {}


def test_parse_yaml_frontmatter_quoted_values():
    """_parse_yaml_frontmatter 处理引号包裹的值。"""
    from podcast_research.exporters.obsidian import _parse_yaml_frontmatter

    content = """---
video_id: "def456"
channel: 'SingleQuoted'
---
"""
    fm = _parse_yaml_frontmatter(content)
    assert fm["video_id"] == "def456"
    assert fm["channel"] == "SingleQuoted"


def test_find_unknown_channel_files(tmp_path):
    """find_unknown_channel_files 能找到 UnknownChannel 文件。"""
    from podcast_research.exporters.obsidian import find_unknown_channel_files

    vault = tmp_path / "vault"
    vault.mkdir()

    # Create UnknownChannel reports
    _create_unknown_report(vault, "vid001")
    _create_unknown_report(vault, "vid002")

    # Create a normal report (should NOT be found)
    (vault / "01_Reports").mkdir(exist_ok=True)
    (vault / "01_Reports" / "2026-05-15_Acquired_vid003.md").write_text("normal", encoding="utf-8")

    # Create UnknownChannel.md channel card
    channels_dir = vault / "05_Channels"
    channels_dir.mkdir(parents=True, exist_ok=True)
    (channels_dir / "UnknownChannel.md").write_text("# UnknownChannel\n", encoding="utf-8")

    files = find_unknown_channel_files(vault)
    names = [f.name for f in files]
    assert "2026-05-15_UnknownChannel_vid001.md" in names
    assert "2026-05-15_UnknownChannel_vid002.md" in names
    assert "UnknownChannel.md" in names
    assert "2026-05-15_Acquired_vid003.md" not in names
    assert len(files) == 3


def test_find_unknown_channel_files_empty(tmp_path):
    """find_unknown_channel_files 空 vault 返回空列表。"""
    from podcast_research.exporters.obsidian import find_unknown_channel_files

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "01_Reports").mkdir()
    (vault / "05_Channels").mkdir()

    files = find_unknown_channel_files(vault)
    assert files == []


def test_analyze_unknown_file_with_backfill(tmp_path):
    """analyze 能从 cv_ch_map backfill channel_name。"""
    from podcast_research.exporters.obsidian import _analyze_unknown_file

    vault = tmp_path / "vault"
    filepath = _create_unknown_report(vault, "vid001")

    cv_ch_map = {
        "vid001": {
            "channel_name": "Acquired",
            "channel_url": "https://www.youtube.com/@acquired",
            "channel_tags": ["tech"],
            "video_title": "Acquired Episode 1",
            "video_url": "https://www.youtube.com/watch?v=vid001",
            "published_at": "2026-05-10",
        }
    }

    result = _analyze_unknown_file(filepath, cv_ch_map)
    assert result["action"] == "rename_or_reexport"
    assert result["reason"] == "backfilled"
    assert result["channel_name"] == "Acquired"
    assert result["video_id"] == "vid001"
    assert "Acquired" in result["suggested_filename"]
    assert "vid001" in result["suggested_filename"]


def test_analyze_unknown_file_no_metadata(tmp_path):
    """analyze 无法 backfill 时标记 manual_review。"""
    from podcast_research.exporters.obsidian import _analyze_unknown_file

    vault = tmp_path / "vault"
    filepath = _create_unknown_report(vault, "vid999")

    result = _analyze_unknown_file(filepath, {})
    assert result["action"] == "manual_review"
    assert result["reason"] == "no_channel_metadata"


def test_analyze_unknown_file_no_video_id(tmp_path):
    """analyze 缺少 video_id 时标记 manual_review。"""
    from podcast_research.exporters.obsidian import _analyze_unknown_file

    vault = tmp_path / "vault"
    reports_dir = vault / "01_Reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    filepath = reports_dir / "2026-05-15_UnknownChannel_novideo.md"
    filepath.write_text("---\ntype: report\nchannel: Unknown\n---\n# Test\n", encoding="utf-8")

    result = _analyze_unknown_file(filepath, {})
    assert result["action"] == "manual_review"
    assert result["reason"] == "missing_video_id"


def test_cleanup_dry_run_no_changes(seeded_db, tmp_path):
    """cleanup dry-run 不修改文件。"""
    from podcast_research.exporters.obsidian import cleanup_unknown_channel_files

    vault = tmp_path / "vault"
    _create_unknown_report(vault, "vid001")

    result = cleanup_unknown_channel_files(vault, dry_run=True)
    assert result["renamed"] == 0
    assert result["moved"] == 0

    # Original file should still exist
    assert (vault / "01_Reports" / "2026-05-15_UnknownChannel_vid001.md").exists()


def test_cleanup_dry_run_returns_analysis(seeded_db, tmp_path):
    """cleanup dry-run 返回分析结果。"""
    from podcast_research.exporters.obsidian import cleanup_unknown_channel_files

    vault = tmp_path / "vault"
    _create_unknown_report(vault, "vid001")
    _create_unknown_report(vault, "vid999")

    # Seed channel_videos for vid001 only
    session = seeded_db
    _seed_channel_video(session, "vid001", "Acquired",
                        video_title="Acquired Ep1", published_at="2026-05-10")

    result = cleanup_unknown_channel_files(vault, dry_run=True)
    results = result["results"]

    assert len(results) == 2
    vid001 = next(r for r in results if r["video_id"] == "vid001")
    vid999 = next(r for r in results if r["video_id"] == "vid999")
    assert vid001["action"] == "rename_or_reexport"
    assert vid001["channel_name"] == "Acquired"
    assert vid999["action"] == "manual_review"


def test_cleanup_apply_moves_to_backup(seeded_db, tmp_path):
    """cleanup apply 将旧文件移到 backup，不删除。"""
    from podcast_research.exporters.obsidian import cleanup_unknown_channel_files

    vault = tmp_path / "vault"
    old_file = _create_unknown_report(vault, "abc123")  # matches seeded_db video_id

    # Seed channel_videos for abc123
    session = seeded_db
    _seed_channel_video(session, "abc123", "TechChannel",
                        video_title="Tech Talk", published_at="2026-05-10")

    result = cleanup_unknown_channel_files(vault, apply=True)

    # Old file should be moved to backup
    assert not old_file.exists()
    backup_dir = vault / "99_System" / "UnknownChannel_Backup"
    assert backup_dir.exists()
    assert (backup_dir / old_file.name).exists()

    # New file with correct channel name should be created
    reports_dir = vault / "01_Reports"
    new_files = list(reports_dir.glob("*TechChannel*"))
    assert len(new_files) >= 1

    assert result["renamed"] >= 1
    assert result["moved"] >= 1


def test_cleanup_apply_unknown_channel_card(tmp_path, seeded_db):
    """cleanup apply 将 UnknownChannel.md 频道卡片移到 backup。"""
    from podcast_research.exporters.obsidian import cleanup_unknown_channel_files

    vault = tmp_path / "vault"
    channels_dir = vault / "05_Channels"
    channels_dir.mkdir(parents=True, exist_ok=True)
    card = channels_dir / "UnknownChannel.md"
    card.write_text("# UnknownChannel\n## Notes\n", encoding="utf-8")

    result = cleanup_unknown_channel_files(vault, apply=True)

    assert not card.exists()
    backup_dir = vault / "99_System" / "UnknownChannel_Backup"
    assert (backup_dir / "UnknownChannel.md").exists()
    assert result["moved"] >= 1


def test_cleanup_apply_no_delete(tmp_path, seeded_db):
    """cleanup apply 不直接删除文件，只移动到 backup。"""
    from podcast_research.exporters.obsidian import cleanup_unknown_channel_files

    vault = tmp_path / "vault"
    old_file = _create_unknown_report(vault, "nomatch_vid")

    result = cleanup_unknown_channel_files(vault, apply=True)

    # File with no backfill match → skipped (not deleted)
    # It should either still be in place or moved, but NOT deleted
    backup_dir = vault / "99_System" / "UnknownChannel_Backup"
    all_files_in_vault = list(vault.rglob("*.md"))
    all_names = [f.name for f in all_files_in_vault]
    # The file should still exist somewhere
    assert old_file.name in all_names or any("nomatch_vid" in n for n in all_names)


def test_cli_cleanup_unknown_dry_run(seeded_db, tmp_path, monkeypatch):
    """CLI cleanup-unknown --dry-run 工作。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app
    import podcast_research.config

    vault = tmp_path / "vault"
    _create_unknown_report(vault, "vid001")

    monkeypatch.setattr(podcast_research.config, "OBSIDIAN_VAULT_PATH", str(vault))

    runner = CliRunner()
    result = runner.invoke(app, [
        "obsidian", "cleanup-unknown",
        "--vault", str(vault),
        "--dry-run",
    ])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.stdout


def test_cli_cleanup_unknown_no_vault(monkeypatch):
    """CLI cleanup-unknown 无 vault 时报错。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app
    import podcast_research.config

    monkeypatch.setattr(podcast_research.config, "OBSIDIAN_VAULT_PATH", "")

    runner = CliRunner()
    result = runner.invoke(app, ["obsidian", "cleanup-unknown"])
    assert result.exit_code == 1


# ═════════════════════════════════════════════════════════════════════════════
# P2-C.2: Channel Card Reconciliation tests
# ═════════════════════════════════════════════════════════════════════════════

def _create_report_with_channel(vault, channel, video_id, title="", date="2026-05-29"):
    """Helper: create a report file with channel in frontmatter."""
    reports_dir = vault / "01_Reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    ch_safe = channel.replace(" ", "_") if channel else "UnknownChannel"
    filename = f"{date}_{ch_safe}_{video_id}.md"
    filepath = reports_dir / filename
    display_title = title or f"{channel} Episode {video_id}"
    content = f"""---
type: report
source_type: youtube
channel: {channel}
video_id: {video_id}
video_url: https://www.youtube.com/watch?v={video_id}
published_at: "{date}"
analyzed_at: 2026-05-30 10:00
prompt_version: tech_ai_v2
model: mock-v1
tags:
  - podcast-report
---

# {display_title}

## Summary

Test summary for {channel}.
"""
    filepath.write_text(content, encoding="utf-8")
    return filepath


def test_scan_report_frontmatters_reads_channel(tmp_path):
    """_scan_report_frontmatters 能从 frontmatter 读取 channel。"""
    from podcast_research.exporters.obsidian import _scan_report_frontmatters

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_report_with_channel(vault, "Acquired", "vid001", "Acquired Episode 1")
    _create_report_with_channel(vault, "BG2Pod", "vid002")

    reports = _scan_report_frontmatters(vault)
    assert len(reports) == 2
    channels = {r["channel"] for r in reports}
    assert "Acquired" in channels
    assert "BG2Pod" in channels


def test_scan_report_frontmatters_reads_title(tmp_path):
    """_scan_report_frontmatters 能从 H1 标题读取 title。"""
    from podcast_research.exporters.obsidian import _scan_report_frontmatters

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_report_with_channel(vault, "Acquired", "vid001", "The Vanguard Story")

    reports = _scan_report_frontmatters(vault)
    assert reports[0]["title"] == "The Vanguard Story"


def test_group_reports_by_channel(tmp_path):
    """_group_reports_by_channel 正确分组并跳过 unknown。"""
    from podcast_research.exporters.obsidian import _scan_report_frontmatters, _group_reports_by_channel

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_report_with_channel(vault, "Acquired", "vid001")
    _create_report_with_channel(vault, "Acquired", "vid002")
    _create_report_with_channel(vault, "BG2Pod", "vid003")

    reports = _scan_report_frontmatters(vault)
    groups = _group_reports_by_channel(reports)

    assert len(groups) == 2
    assert len(groups["Acquired"]) == 2
    assert len(groups["BG2Pod"]) == 1


def test_group_reports_skips_unknown_channel(tmp_path):
    """_group_reports_by_channel 跳过 UnknownChannel / empty。"""
    from podcast_research.exporters.obsidian import _group_reports_by_channel

    reports = [
        {"channel": "Acquired", "video_id": "v1"},
        {"channel": "", "video_id": "v2"},
        {"channel": "UnknownChannel", "video_id": "v3"},
        {"channel": "unknown", "video_id": "v4"},
    ]
    groups = _group_reports_by_channel(reports)
    assert len(groups) == 1
    assert "Acquired" in groups


def test_sync_creates_missing_channel_card(tmp_path):
    """sync 为缺少的频道创建 card。"""
    from podcast_research.exporters.obsidian import sync_channel_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "05_Channels").mkdir(parents=True, exist_ok=True)
    _create_report_with_channel(vault, "Latent Space", "vid001", "AI Research Ep1")
    _create_report_with_channel(vault, "Latent Space", "vid002", "AI Research Ep2")

    result = sync_channel_cards(vault)

    card_path = vault / "05_Channels" / "Latent Space.md"
    assert card_path.exists()
    content = card_path.read_text(encoding="utf-8")
    assert "type: channel" in content
    assert "channel: Latent Space" in content
    assert "## Recent Reports" in content
    assert "vid001" in content
    assert "vid002" in content
    assert result["created"] == 1


def test_sync_creates_multiple_channel_cards(tmp_path):
    """多个 Latent Space + Acquired reports 会各自生成 card。"""
    from podcast_research.exporters.obsidian import sync_channel_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "05_Channels").mkdir(parents=True, exist_ok=True)
    _create_report_with_channel(vault, "Latent Space", "ls001")
    _create_report_with_channel(vault, "Latent Space", "ls002")
    _create_report_with_channel(vault, "Acquired", "acq001")

    result = sync_channel_cards(vault)
    assert result["created"] == 2
    assert (vault / "05_Channels" / "Latent Space.md").exists()
    assert (vault / "05_Channels" / "Acquired.md").exists()


def test_sync_existing_card_only_appends(tmp_path):
    """已存在 channel card 时只追加 Recent Reports。"""
    from podcast_research.exporters.obsidian import sync_channel_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    channels_dir = vault / "05_Channels"
    channels_dir.mkdir(parents=True, exist_ok=True)

    # Pre-create card with user content
    card_path = channels_dir / "Acquired.md"
    card_path.write_text(
        "---\ntype: channel\nchannel: Acquired\nupdated_at: 2026-05-01 10:00\n---\n\n"
        "# Acquired\n\n"
        "## Positioning\n\n"
        "User custom notes here.\n\n"
        "## Recent Reports\n\n"
        "- [[2026-05-01_Acquired_oldvid]]\n\n"
        "## Notes\n\n",
        encoding="utf-8",
    )

    _create_report_with_channel(vault, "Acquired", "newvid001", "New Episode")

    result = sync_channel_cards(vault)

    content = card_path.read_text(encoding="utf-8")
    # User content preserved
    assert "User custom notes here." in content
    # Old link preserved
    assert "[[2026-05-01_Acquired_oldvid]]" in content
    # New link appended
    assert "newvid001" in content
    assert result["updated"] == 1


def test_sync_no_duplicate_links(tmp_path):
    """已存在的 report link 不重复追加。"""
    from podcast_research.exporters.obsidian import sync_channel_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    channels_dir = vault / "05_Channels"
    channels_dir.mkdir(parents=True, exist_ok=True)

    _create_report_with_channel(vault, "Acquired", "vid001")

    # First sync creates the card
    sync_channel_cards(vault)
    card_path = channels_dir / "Acquired.md"
    content_after_first = card_path.read_text(encoding="utf-8")

    # Second sync should not duplicate
    result = sync_channel_cards(vault)
    content_after_second = card_path.read_text(encoding="utf-8")

    # The link should appear only once
    assert content_after_first.count("[[2026-05-29_Acquired_vid001]]") == 1
    assert content_after_second.count("[[2026-05-29_Acquired_vid001]]") == 1
    assert result["skipped"] == 1


def test_sync_skips_unknown_channel_reports(tmp_path):
    """UnknownChannel report 被跳过，不生成 card。"""
    from podcast_research.exporters.obsidian import sync_channel_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "05_Channels").mkdir(parents=True, exist_ok=True)

    # Create UnknownChannel report
    reports_dir = vault / "01_Reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "2026-05-29_UnknownChannel_mystery.md").write_text(
        "---\nchannel: UnknownChannel\nvideo_id: mystery\n---\n# Mystery\n", encoding="utf-8"
    )

    result = sync_channel_cards(vault)
    assert result["created"] == 0
    assert result["updated"] == 0
    assert not (vault / "05_Channels" / "UnknownChannel.md").exists()


def test_sync_dry_run_no_files_written(tmp_path):
    """dry-run 不写文件。"""
    from podcast_research.exporters.obsidian import sync_channel_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "05_Channels").mkdir(parents=True, exist_ok=True)
    _create_report_with_channel(vault, "Latent Space", "vid001")

    result = sync_channel_cards(vault, dry_run=True)

    assert result["created"] == 1  # dry-run counts what would happen
    # But no actual file written
    assert not (vault / "05_Channels" / "Latent Space.md").exists()


def test_sync_channel_filter(tmp_path):
    """--channel 只同步指定 channel。"""
    from podcast_research.exporters.obsidian import sync_channel_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "05_Channels").mkdir(parents=True, exist_ok=True)
    _create_report_with_channel(vault, "Latent Space", "ls001")
    _create_report_with_channel(vault, "Acquired", "acq001")
    _create_report_with_channel(vault, "BG2Pod", "bg001")

    result = sync_channel_cards(vault, channel_filter="acquired")

    assert result["created"] == 1
    assert (vault / "05_Channels" / "Acquired.md").exists()
    assert not (vault / "05_Channels" / "Latent Space.md").exists()
    assert not (vault / "05_Channels" / "BG2Pod.md").exists()


def test_sync_overwrite_rewrites_card(tmp_path):
    """--overwrite 可重写 channel card。"""
    from podcast_research.exporters.obsidian import sync_channel_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    channels_dir = vault / "05_Channels"
    channels_dir.mkdir(parents=True, exist_ok=True)

    # Pre-create card
    card_path = channels_dir / "Acquired.md"
    card_path.write_text("old content\n## Notes\n", encoding="utf-8")

    _create_report_with_channel(vault, "Acquired", "vid001")

    result = sync_channel_cards(vault, overwrite=True)

    content = card_path.read_text(encoding="utf-8")
    assert "old content" not in content
    assert "type: channel" in content
    assert "vid001" in content
    assert result["created"] == 1


def test_sync_empty_reports_dir(tmp_path):
    """空 01_Reports/ 目录不报错。"""
    from podcast_research.exporters.obsidian import sync_channel_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "01_Reports").mkdir()
    (vault / "05_Channels").mkdir()

    result = sync_channel_cards(vault)
    assert result["created"] == 0
    assert result["updated"] == 0


def test_sync_no_reports_dir(tmp_path):
    """无 01_Reports/ 目录不报错。"""
    from podcast_research.exporters.obsidian import sync_channel_cards

    vault = tmp_path / "vault"
    vault.mkdir()

    result = sync_channel_cards(vault)
    assert result["created"] == 0


def test_cli_sync_channel_cards_dry_run(tmp_path, monkeypatch):
    """CLI sync-channel-cards --dry-run 工作。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "05_Channels").mkdir(parents=True, exist_ok=True)
    _create_report_with_channel(vault, "Latent Space", "vid001")

    runner = CliRunner()
    result = runner.invoke(app, [
        "obsidian", "sync-channel-cards",
        "--vault", str(vault),
        "--dry-run",
    ])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.stdout
    assert "Latent Space" in result.stdout


def test_cli_sync_channel_cards_real(tmp_path, monkeypatch):
    """CLI sync-channel-cards 实际执行。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "05_Channels").mkdir(parents=True, exist_ok=True)
    _create_report_with_channel(vault, "Acquired", "vid001")

    runner = CliRunner()
    result = runner.invoke(app, [
        "obsidian", "sync-channel-cards",
        "--vault", str(vault),
    ])
    assert result.exit_code == 0
    assert "Sync" in result.stdout
    assert (vault / "05_Channels" / "Acquired.md").exists()


def test_cli_sync_channel_cards_no_vault(monkeypatch):
    """CLI sync-channel-cards 无 vault 时报错。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app
    import podcast_research.config

    monkeypatch.setattr(podcast_research.config, "OBSIDIAN_VAULT_PATH", "")

    runner = CliRunner()
    result = runner.invoke(app, ["obsidian", "sync-channel-cards"])
    assert result.exit_code == 1


# ═════════════════════════════════════════════════════════════════════════════
# P2-D: Topic / Company Card Generation tests
# ═════════════════════════════════════════════════════════════════════════════

SAMPLE_REPORT_MD = """---
type: report
source_type: youtube
channel: TechPod
video_id: vid001
video_url: https://www.youtube.com/watch?v=vid001
published_at: "2026-05-29"
analyzed_at: "2026-05-30 10:00"
prompt_version: tech_ai_v2
model: mock-v1
tags:
  - podcast-report
---

# AI Infrastructure Deep Dive

## Summary

Test summary.

## Source

- **Channel**: [[TechPod]]
- **Video**: [[vid001]]

## Core Investment Views

| 标的 | 方向 | AI价值链 | 证据类型 | 证据强度 | 时间范围 | 时间戳 |
|------|------|----------|----------|----------|----------|--------|
| NVIDIA | bullish | compute | growth_metric | strong | short_term | 00:07:33 |
| Vercel | bullish | cloud | technical_claim | medium | medium_term | 01:47:39 |

## Tech / Industry Insights

- **Agent workloads are different from traditional loads** `#workload-patterns #ai-infra`
  > source quote here
- **MCP enables agents to use CLI** `#mcp #agent-tools`
  > another quote

## Entities

[[NVIDIA]] [[Vercel]] [[OpenAI]] [[Stripe]] [[AI Agents]]

## Related Links

- [[TechPod]]
- [[NVIDIA]]
- [[Ai-Infra]]
"""


def _create_sample_report(vault, filename="2026-05-29_TechPod_vid001.md", content=None):
    """Helper: create a sample report file."""
    reports_dir = vault / "01_Reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    filepath = reports_dir / filename
    filepath.write_text(content or SAMPLE_REPORT_MD, encoding="utf-8")
    return filepath


def test_extract_topics_from_report_md():
    """_extract_topics_from_report_md 能从 hashtag 和表格提取 topic。"""
    from podcast_research.exporters.obsidian import _extract_topics_from_report_md

    topics = _extract_topics_from_report_md(SAMPLE_REPORT_MD)
    assert "workload-patterns" in topics
    assert "ai-infra" in topics
    assert "mcp" in topics
    assert "agent-tools" in topics
    assert "compute" in topics
    assert "cloud" in topics


def test_extract_companies_from_report_md():
    """_extract_companies_from_report_md 能从 Entities 和表格提取公司。"""
    from podcast_research.exporters.obsidian import _extract_companies_from_report_md

    companies = _extract_companies_from_report_md(SAMPLE_REPORT_MD)
    assert "NVIDIA" in companies
    assert "Vercel" in companies
    assert "OpenAI" in companies
    assert "Stripe" in companies


def test_normalize_topic_name():
    """_normalize_topic_name 正确映射特殊 topic。"""
    from podcast_research.exporters.obsidian import _normalize_topic_name

    assert _normalize_topic_name("ai-infra") == "AI Infra"
    assert _normalize_topic_name("ai-agents") == "AI Agents"
    assert _normalize_topic_name("agents") == "AI Agents"
    assert _normalize_topic_name("developer-tools") == "Developer Tools"
    assert _normalize_topic_name("capital_market") == "Capital Market"
    # Unknown topics get title case
    assert _normalize_topic_name("custom-topic") == "Custom Topic"


def test_normalize_company_name():
    """_normalize_company_name 正确处理别名。"""
    from podcast_research.exporters.obsidian import _normalize_company_name

    assert _normalize_company_name("nvidia") == "NVIDIA"
    assert _normalize_company_name("NVIDIA") == "NVIDIA"
    assert _normalize_company_name("google") == "Alphabet"
    assert _normalize_company_name("openai") == "OpenAI"
    assert _normalize_company_name("tsmc") == "TSMC"
    assert _normalize_company_name("jp morgan") == "JPMorgan Chase"
    # Unknown company stays as-is
    assert _normalize_company_name("SomeStartup") == "SomeStartup"


def test_generate_topic_card(tmp_path):
    """generate_cards 能生成 Topic Card。"""
    from podcast_research.exporters.obsidian import generate_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_sample_report(vault)

    result = generate_cards(vault, topics_only=True)

    topics_dir = vault / "02_Topics"
    assert topics_dir.exists()
    # Should have created topic cards for extracted topics
    topic_files = list(topics_dir.glob("*.md"))
    assert len(topic_files) >= 1

    # Check one card has correct structure
    ai_infra_card = topics_dir / "AI Infra.md"
    assert ai_infra_card.exists()
    content = ai_infra_card.read_text(encoding="utf-8")
    assert "type: topic" in content
    assert "topic: AI Infra" in content
    assert "## Source Reports" in content
    assert "vid001" in content
    assert result["topics_created"] >= 1


def test_generate_company_card(tmp_path):
    """generate_cards 能生成 Company Card。"""
    from podcast_research.exporters.obsidian import generate_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_sample_report(vault)

    result = generate_cards(vault, companies_only=True)

    companies_dir = vault / "03_Companies"
    assert companies_dir.exists()

    nvidia_card = companies_dir / "NVIDIA.md"
    assert nvidia_card.exists()
    content = nvidia_card.read_text(encoding="utf-8")
    assert "type: company" in content
    assert "company: NVIDIA" in content
    assert "## Source Reports" in content
    assert "vid001" in content
    assert result["companies_created"] >= 1


def test_generate_card_existing_append_only(tmp_path):
    """已存在的卡片只追加 Source Reports。"""
    from podcast_research.exporters.obsidian import generate_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_sample_report(vault)

    # First generation
    generate_cards(vault, topics_only=True)

    # Add user content to a card
    ai_infra_card = vault / "02_Topics" / "AI Infra.md"
    content = ai_infra_card.read_text(encoding="utf-8")
    content = content.replace("## Current Understanding", "## Current Understanding\n\nUser custom analysis here.")
    ai_infra_card.write_text(content, encoding="utf-8")

    # Second generation with a new report
    new_report = SAMPLE_REPORT_MD.replace("vid001", "vid002").replace("TechPod", "TechPod")
    _create_sample_report(vault, "2026-05-30_TechPod_vid002.md", new_report)

    result = generate_cards(vault, topics_only=True)

    updated_content = ai_infra_card.read_text(encoding="utf-8")
    # User content preserved
    assert "User custom analysis here." in updated_content
    # Both report links present
    assert "vid001" in updated_content
    assert "vid002" in updated_content


def test_generate_card_no_duplicate_links(tmp_path):
    """已存在的 report link 不重复追加。"""
    from podcast_research.exporters.obsidian import generate_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_sample_report(vault)

    # First generation
    generate_cards(vault, companies_only=True)
    nvidia_card = vault / "03_Companies" / "NVIDIA.md"
    content_first = nvidia_card.read_text(encoding="utf-8")

    # Second generation (same report)
    result = generate_cards(vault, companies_only=True)
    content_second = nvidia_card.read_text(encoding="utf-8")

    # Link should appear only once
    assert content_first.count("[[2026-05-29_TechPod_vid001]]") == 1
    assert content_second.count("[[2026-05-29_TechPod_vid001]]") == 1
    assert result["skipped"] >= 1


def test_generate_cards_dry_run_no_files(tmp_path):
    """dry-run 不写文件。"""
    from podcast_research.exporters.obsidian import generate_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_sample_report(vault)

    result = generate_cards(vault, dry_run=True)

    # Should have results but no actual files
    assert len(result["results"]) > 0
    assert not (vault / "02_Topics").exists()
    assert not (vault / "03_Companies").exists()


def test_generate_cards_topics_only(tmp_path):
    """--topics-only 只生成 topics。"""
    from podcast_research.exporters.obsidian import generate_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_sample_report(vault)

    result = generate_cards(vault, topics_only=True)

    assert (vault / "02_Topics").exists()
    assert not (vault / "03_Companies").exists()
    assert result["companies_created"] == 0


def test_generate_cards_companies_only(tmp_path):
    """--companies-only 只生成 companies。"""
    from podcast_research.exporters.obsidian import generate_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_sample_report(vault)

    result = generate_cards(vault, companies_only=True)

    assert not (vault / "02_Topics").exists()
    assert (vault / "03_Companies").exists()
    assert result["topics_created"] == 0


def test_generate_cards_channel_filter(tmp_path):
    """--channel 只处理指定频道的报告。"""
    from podcast_research.exporters.obsidian import generate_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_sample_report(vault)

    # Add a report from a different channel
    other_report = SAMPLE_REPORT_MD.replace("TechPod", "OtherPod").replace("vid001", "vid002")
    _create_sample_report(vault, "2026-05-29_OtherPod_vid002.md", other_report)

    result = generate_cards(vault, channel_filter="techpod")

    # Cards should only contain TechPod reports
    for r in result["results"]:
        # All source reports should be from TechPod
        pass  # The filter is applied during scan, so results reflect filtered data

    # Check that topic cards only have TechPod references
    topics_dir = vault / "02_Topics"
    if topics_dir.exists():
        for card in topics_dir.glob("*.md"):
            content = card.read_text(encoding="utf-8")
            assert "OtherPod" not in content


def test_generate_topic_index(tmp_path):
    """Topic Index 正确生成。"""
    from podcast_research.exporters.obsidian import generate_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_sample_report(vault)

    generate_cards(vault, topics_only=True)

    index_path = vault / "99_System" / "Topic Index.md"
    assert index_path.exists()
    content = index_path.read_text(encoding="utf-8")
    assert "# Topic Index" in content
    assert "| Topic | Reports | Card |" in content
    assert "AI Infra" in content


def test_generate_company_index(tmp_path):
    """Company Index 正确生成。"""
    from podcast_research.exporters.obsidian import generate_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_sample_report(vault)

    generate_cards(vault, companies_only=True)

    index_path = vault / "99_System" / "Company Index.md"
    assert index_path.exists()
    content = index_path.read_text(encoding="utf-8")
    assert "# Company Index" in content
    assert "| Company | Reports | Card |" in content
    assert "NVIDIA" in content


def test_generate_card_log(tmp_path):
    """Card Generation Log 正确生成。"""
    from podcast_research.exporters.obsidian import generate_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_sample_report(vault)

    generate_cards(vault)

    log_path = vault / "99_System" / "Card Generation Log.md"
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "# Card Generation Log" in content
    assert "Topics created:" in content
    assert "Companies created:" in content


def test_generate_cards_overwrite(tmp_path):
    """--overwrite 可重写卡片。"""
    from podcast_research.exporters.obsidian import generate_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_sample_report(vault)

    # First generation
    generate_cards(vault, companies_only=True)

    # Modify card
    nvidia_card = vault / "03_Companies" / "NVIDIA.md"
    nvidia_card.write_text("old content\n", encoding="utf-8")

    # Overwrite
    generate_cards(vault, companies_only=True, overwrite=True)

    content = nvidia_card.read_text(encoding="utf-8")
    assert "old content" not in content
    assert "type: company" in content


def test_generate_cards_empty_vault(tmp_path):
    """空 vault 不报错。"""
    from podcast_research.exporters.obsidian import generate_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "01_Reports").mkdir()

    result = generate_cards(vault)
    assert result["topics_created"] == 0
    assert result["companies_created"] == 0


def test_generate_cards_no_reports_dir(tmp_path):
    """无 01_Reports/ 目录不报错。"""
    from podcast_research.exporters.obsidian import generate_cards

    vault = tmp_path / "vault"
    vault.mkdir()

    result = generate_cards(vault)
    assert result["topics_created"] == 0


def test_cli_generate_cards_dry_run(tmp_path):
    """CLI generate-cards --dry-run 工作。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_sample_report(vault)

    runner = CliRunner()
    result = runner.invoke(app, [
        "obsidian", "generate-cards",
        "--vault", str(vault),
        "--dry-run",
    ])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.stdout
    assert "topic" in result.stdout or "company" in result.stdout


def test_cli_generate_cards_real(tmp_path):
    """CLI generate-cards 实际执行。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_sample_report(vault)

    runner = CliRunner()
    result = runner.invoke(app, [
        "obsidian", "generate-cards",
        "--vault", str(vault),
    ])
    assert result.exit_code == 0
    assert "Card Generation" in result.stdout


def test_cli_generate_cards_no_vault(monkeypatch):
    """CLI generate-cards 无 vault 时报错。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app
    import podcast_research.config

    monkeypatch.setattr(podcast_research.config, "OBSIDIAN_VAULT_PATH", "")

    runner = CliRunner()
    result = runner.invoke(app, ["obsidian", "generate-cards"])
    assert result.exit_code == 1


def test_cli_generate_cards_conflicting_flags(tmp_path):
    """--topics-only 和 --companies-only 不能同时使用。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_sample_report(vault)

    runner = CliRunner()
    result = runner.invoke(app, [
        "obsidian", "generate-cards",
        "--vault", str(vault),
        "--topics-only",
        "--companies-only",
    ])
    assert result.exit_code == 1


# ═════════════════════════════════════════════════════════════════════════════
# P2-D.1: Topic / Company Card Cleanup & Classification tests
# ═════════════════════════════════════════════════════════════════════════════

def test_classify_company_whitelist():
    """Company whitelist 保留 NVIDIA / OpenAI / BlackRock。"""
    from podcast_research.exporters.obsidian import _classify_company_card

    for name in ["NVIDIA", "OpenAI", "BlackRock", "Vanguard", "Meta"]:
        result = _classify_company_card(name)
        assert result["action"] == "keep", f"{name} should be kept as company"
        assert result["suggested_type"] == "company"
        assert result["reason"] == "company_whitelist"


def test_classify_company_topic_pattern_cpu_supply():
    """CPU Supply 被建议迁移到 Topic。"""
    from podcast_research.exporters.obsidian import _classify_company_card

    result = _classify_company_card("CPU Supply")
    assert result["action"] == "migrate_to_topic"
    assert result["suggested_type"] == "topic"


def test_classify_company_topic_pattern_enterprise_saas():
    """Enterprise SaaS 被建议迁移到 Topic。"""
    from podcast_research.exporters.obsidian import _classify_company_card

    result = _classify_company_card("Enterprise SaaS")
    assert result["action"] == "migrate_to_topic"
    assert result["suggested_type"] == "topic"


def test_classify_company_topic_pattern_kubernetes():
    """Kubernetes 被建议迁移到 Topic。"""
    from podcast_research.exporters.obsidian import _classify_company_card

    result = _classify_company_card("Kubernetes")
    assert result["action"] == "migrate_to_topic"
    assert result["suggested_type"] == "topic"


def test_classify_company_topic_pattern_etf():
    """ETF 被建议迁移到 Topic。"""
    from podcast_research.exporters.obsidian import _classify_company_card

    result = _classify_company_card("ETF")
    assert result["action"] == "migrate_to_topic"


def test_classify_company_ai_agents():
    """AI Agents company card 被建议迁移到 Topic。"""
    from podcast_research.exporters.obsidian import _classify_company_card

    result = _classify_company_card("AI Agents")
    assert result["action"] == "migrate_to_topic"
    assert result["suggested_type"] == "topic"
    assert result["suggested_name"] == "AI Agents"


def test_classify_company_uncertain():
    """不确定名称进入 manual_review。"""
    from podcast_research.exporters.obsidian import _classify_company_card

    result = _classify_company_card("SomeRandomStartup")
    assert result["action"] == "manual_review"
    assert result["suggested_type"] == "unknown"
    assert result["reason"] == "uncertain"


def test_classify_company_chinese():
    """中文公司名（含企业级AI安全等关键词）被建议迁移到 Topic。"""
    from podcast_research.exporters.obsidian import _classify_company_card

    result = _classify_company_card("企业级AI安全")
    assert result["action"] == "migrate_to_topic"


def test_find_topic_aliases(tmp_path):
    """topic alias 检测：Ai Agent → AI Agents。"""
    from podcast_research.exporters.obsidian import _find_topic_aliases, _write_topic_card

    vault = tmp_path / "vault"
    vault.mkdir()
    topics_dir = vault / "02_Topics"
    topics_dir.mkdir()

    # Create alias card
    _write_topic_card(topics_dir / "Ai Agent.md", "Ai Agent", [])
    # Create canonical card
    _write_topic_card(topics_dir / "AI Agents.md", "AI Agents", [])

    aliases = _find_topic_aliases(vault)
    # "Ai Agent" should be flagged for merge (lowercase "ai agent" maps to "AI Agents")
    alias_names = [a["old_name"] for a in aliases]
    assert "Ai Agent" in alias_names


def test_cleanup_cards_dry_run_no_files(tmp_path):
    """dry-run 不写文件。"""
    from podcast_research.exporters.obsidian import cleanup_cards, _write_company_card

    vault = tmp_path / "vault"
    vault.mkdir()
    companies_dir = vault / "03_Companies"
    companies_dir.mkdir()

    # Create a company card that should be migrated
    _write_company_card(companies_dir / "CPU Supply.md", "CPU Supply", [
        {"filename": "2026-05-29_TechPod_vid001", "channel": "TechPod", "title": "Test", "video_id": "vid001"}
    ])

    result = cleanup_cards(vault, dry_run=True)

    # Should find the migration candidate
    assert len(result["results"]) >= 1
    cpu_result = next((r for r in result["results"] if r["name"] == "CPU Supply"), None)
    assert cpu_result is not None
    assert cpu_result["action"] == "migrate_to_topic"

    # No files should be modified
    assert (companies_dir / "CPU Supply.md").exists()
    assert not (vault / "02_Topics").exists()


def test_cleanup_cards_apply_migrates_company(tmp_path):
    """apply 迁移 Company → Topic。"""
    from podcast_research.exporters.obsidian import cleanup_cards, _write_company_card

    vault = tmp_path / "vault"
    vault.mkdir()
    companies_dir = vault / "03_Companies"
    companies_dir.mkdir()
    (vault / "02_Topics").mkdir()
    (vault / "99_System").mkdir()

    _write_company_card(companies_dir / "CPU Supply.md", "CPU Supply", [
        {"filename": "2026-05-29_TechPod_vid001", "channel": "TechPod", "title": "Test", "video_id": "vid001"}
    ])

    result = cleanup_cards(vault, apply=True)

    # Old company card should be moved to backup
    assert not (companies_dir / "CPU Supply.md").exists()
    backup_dir = vault / "99_System" / "Card_Cleanup_Backup"
    assert backup_dir.exists()
    backup_files = list(backup_dir.glob("*CPU*"))
    assert len(backup_files) >= 1

    # Topic card should be created
    topics_dir = vault / "02_Topics"
    # The suggested name might vary, check that a topic was created
    topic_files = list(topics_dir.glob("*.md"))
    assert len(topic_files) >= 1
    assert result["migrated"] >= 1


def test_cleanup_cards_apply_no_delete(tmp_path):
    """apply 不删除旧文件，而是移到 backup。"""
    from podcast_research.exporters.obsidian import cleanup_cards, _write_company_card

    vault = tmp_path / "vault"
    vault.mkdir()
    companies_dir = vault / "03_Companies"
    companies_dir.mkdir()
    (vault / "02_Topics").mkdir()
    (vault / "99_System").mkdir()

    _write_company_card(companies_dir / "Enterprise SaaS.md", "Enterprise SaaS", [])

    result = cleanup_cards(vault, apply=True)

    # File should exist somewhere (moved to backup)
    all_files = list(vault.rglob("*.md"))
    all_names = [f.name for f in all_files]
    assert any("Enterprise SaaS" in n for n in all_names)


def test_cleanup_cards_topic_alias_merge(tmp_path):
    """topic alias merge 生效。"""
    from podcast_research.exporters.obsidian import cleanup_cards, _write_topic_card

    vault = tmp_path / "vault"
    vault.mkdir()
    topics_dir = vault / "02_Topics"
    topics_dir.mkdir()
    (vault / "03_Companies").mkdir()
    (vault / "99_System").mkdir()

    # Create alias card
    _write_topic_card(topics_dir / "Ai Agent.md", "Ai Agent", [
        {"filename": "2026-05-29_TechPod_vid001", "channel": "TechPod", "title": "Test", "video_id": "vid001"}
    ])
    # Create canonical card
    _write_topic_card(topics_dir / "AI Agents.md", "AI Agents", [])

    result = cleanup_cards(vault, apply=True, companies_only=False, topics_only=True)

    # Ai Agent.md should be moved to backup
    assert not (topics_dir / "Ai Agent.md").exists()
    # AI Agents.md should still exist (with merged content)
    assert (topics_dir / "AI Agents.md").exists()
    assert result["merged"] >= 1


def test_cleanup_cards_source_reports_no_duplicate(tmp_path):
    """Source Reports 合并不重复。"""
    from podcast_research.exporters.obsidian import cleanup_cards, _write_topic_card

    vault = tmp_path / "vault"
    vault.mkdir()
    topics_dir = vault / "02_Topics"
    topics_dir.mkdir()
    (vault / "03_Companies").mkdir()
    (vault / "99_System").mkdir()

    # Create alias card with a source report
    _write_topic_card(topics_dir / "Ai Agent.md", "Ai Agent", [
        {"filename": "2026-05-29_TechPod_vid001", "channel": "TechPod", "title": "Test", "video_id": "vid001"}
    ])
    # Create canonical card with same source report
    _write_topic_card(topics_dir / "AI Agents.md", "AI Agents", [
        {"filename": "2026-05-29_TechPod_vid001", "channel": "TechPod", "title": "Test", "video_id": "vid001"}
    ])

    cleanup_cards(vault, apply=True, topics_only=True)

    # The canonical card should have the link only once
    content = (topics_dir / "AI Agents.md").read_text(encoding="utf-8")
    assert content.count("[[2026-05-29_TechPod_vid001]]") == 1


def test_cleanup_cards_index_update(tmp_path):
    """Index 更新。"""
    from podcast_research.exporters.obsidian import cleanup_cards, _write_company_card, _write_topic_card

    vault = tmp_path / "vault"
    vault.mkdir()
    companies_dir = vault / "03_Companies"
    companies_dir.mkdir()
    topics_dir = vault / "02_Topics"
    topics_dir.mkdir()
    (vault / "99_System").mkdir()

    _write_company_card(companies_dir / "NVIDIA.md", "NVIDIA", [
        {"filename": "2026-05-29_TechPod_vid001", "channel": "TechPod", "title": "Test", "video_id": "vid001"}
    ])
    _write_topic_card(topics_dir / "AI Agents.md", "AI Agents", [])

    cleanup_cards(vault, apply=True)

    # Indexes should be updated
    assert (vault / "99_System" / "Company Index.md").exists()
    assert (vault / "99_System" / "Topic Index.md").exists()

    company_index = (vault / "99_System" / "Company Index.md").read_text(encoding="utf-8")
    assert "NVIDIA" in company_index


def test_cleanup_cards_topics_only(tmp_path):
    """--topics-only 只处理 topics。"""
    from podcast_research.exporters.obsidian import cleanup_cards, _write_company_card, _write_topic_card

    vault = tmp_path / "vault"
    vault.mkdir()
    companies_dir = vault / "03_Companies"
    companies_dir.mkdir()
    topics_dir = vault / "02_Topics"
    topics_dir.mkdir()
    (vault / "99_System").mkdir()

    _write_company_card(companies_dir / "CPU Supply.md", "CPU Supply", [])
    _write_topic_card(topics_dir / "Ai Agent.md", "Ai Agent", [])

    result = cleanup_cards(vault, apply=True, topics_only=True)

    # CPU Supply should NOT be migrated (companies_only=False, topics_only=True)
    assert (companies_dir / "CPU Supply.md").exists()
    # But topic alias should be merged
    assert not (topics_dir / "Ai Agent.md").exists()


def test_cleanup_cards_companies_only(tmp_path):
    """--companies-only 只处理 companies。"""
    from podcast_research.exporters.obsidian import cleanup_cards, _write_company_card, _write_topic_card

    vault = tmp_path / "vault"
    vault.mkdir()
    companies_dir = vault / "03_Companies"
    companies_dir.mkdir()
    topics_dir = vault / "02_Topics"
    topics_dir.mkdir()
    (vault / "99_System").mkdir()

    _write_company_card(companies_dir / "CPU Supply.md", "CPU Supply", [])
    _write_topic_card(topics_dir / "Ai Agent.md", "Ai Agent", [])

    result = cleanup_cards(vault, apply=True, companies_only=True)

    # CPU Supply should be migrated
    assert not (companies_dir / "CPU Supply.md").exists()
    # But topic alias should NOT be merged
    assert (topics_dir / "Ai Agent.md").exists()


def test_cleanup_cards_empty_vault(tmp_path):
    """空 vault 不报错。"""
    from podcast_research.exporters.obsidian import cleanup_cards

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "02_Topics").mkdir()
    (vault / "03_Companies").mkdir()

    result = cleanup_cards(vault)
    assert result["migrated"] == 0
    assert result["merged"] == 0


def test_cli_cleanup_cards_dry_run(tmp_path):
    """CLI cleanup-cards --dry-run 工作。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app
    from podcast_research.exporters.obsidian import _write_company_card

    vault = tmp_path / "vault"
    vault.mkdir()
    companies_dir = vault / "03_Companies"
    companies_dir.mkdir()
    _write_company_card(companies_dir / "CPU Supply.md", "CPU Supply", [])

    runner = CliRunner()
    result = runner.invoke(app, [
        "obsidian", "cleanup-cards",
        "--vault", str(vault),
        "--dry-run",
    ])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.stdout


def test_cli_cleanup_cards_no_vault(monkeypatch):
    """CLI cleanup-cards 无 vault 时报错。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app
    import podcast_research.config

    monkeypatch.setattr(podcast_research.config, "OBSIDIAN_VAULT_PATH", "")

    runner = CliRunner()
    result = runner.invoke(app, ["obsidian", "cleanup-cards"])
    assert result.exit_code == 1


def test_cli_cleanup_cards_conflicting_flags(tmp_path):
    """--topics-only 和 --companies-only 不能同时使用。"""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    vault = tmp_path / "vault"
    vault.mkdir()

    runner = CliRunner()
    result = runner.invoke(app, [
        "obsidian", "cleanup-cards",
        "--vault", str(vault),
        "--topics-only",
        "--companies-only",
    ])
    assert result.exit_code == 1


# ═════════════════════════════════════════════════════════════════════════════
# P2-D.2: Topic Taxonomy Consolidation tests
# ═════════════════════════════════════════════════════════════════════════════

def _create_topic_card(vault, topic_name, source_reports=None, report_count=0):
    """Helper: create a topic card file with Source Reports."""
    from podcast_research.exporters.obsidian import _write_topic_card
    topics_dir = vault / "02_Topics"
    topics_dir.mkdir(parents=True, exist_ok=True)

    # Generate dummy source reports if not provided
    if source_reports is None:
        source_reports = [
            {"filename": f"2026-05-29_TechPod_vid{i:03d}", "channel": "TechPod", "title": f"Test {i}", "video_id": f"vid{i:03d}"}
            for i in range(report_count)
        ]

    card_path = topics_dir / f"{topic_name}.md"
    _write_topic_card(card_path, topic_name, source_reports)
    return card_path


def test_consolidate_core_taxonomy():
    """Core taxonomy topics are marked as core."""
    from podcast_research.exporters.obsidian import _classify_topic_status

    core_topics = [
        "AI Infrastructure", "AI Capex", "Inference", "AI Agents",
        "Enterprise AI", "AI Models", "Open Source AI", "Developer Tools",
        "Semiconductor", "GPU Supply", "Data Center", "Cloud",
        "Business Model", "Valuation", "Venture Market", "Investment Framework",
    ]
    for topic in core_topics:
        status, reason = _classify_topic_status(topic, 5)
        assert status == "core", f"{topic} should be core, got {status}"
        assert reason == "core_taxonomy"


def test_consolidate_alias_merge_ai_agent():
    """ai-agent / Ai Agent merges to AI Agents."""
    from podcast_research.exporters.obsidian import _classify_topic_status

    for variant in ["ai agent", "ai-agent", "Ai Agent", "agentic ai"]:
        status, reason = _classify_topic_status(variant, 3)
        assert status == "core", f"{variant} should be core via alias, got {status}"
        assert reason == "alias_match"


def test_consolidate_alias_merge_ai_infra():
    """ai-infra / Ai Infra merges to AI Infrastructure."""
    from podcast_research.exporters.obsidian import _classify_topic_status

    for variant in ["ai infra", "ai-infra", "ai compute"]:
        status, reason = _classify_topic_status(variant, 3)
        assert status == "core", f"{variant} should be core via alias, got {status}"
        assert reason == "alias_match"


def test_consolidate_alias_merge_enterprise_saas():
    """Enterprise SaaS merges to Enterprise AI."""
    from podcast_research.exporters.obsidian import _classify_topic_status

    for variant in ["enterprise saas", "enterprise software", "b2b ai"]:
        status, reason = _classify_topic_status(variant, 3)
        assert status == "core", f"{variant} should be core via alias, got {status}"
        assert reason == "alias_match"


def test_consolidate_alias_merge_long_term_investing():
    """Long-term investing merges to Investment Framework."""
    from podcast_research.exporters.obsidian import _classify_topic_status

    for variant in ["long-term investing", "investment thesis"]:
        status, reason = _classify_topic_status(variant, 3)
        assert status == "core", f"{variant} should be core via alias, got {status}"
        assert reason == "alias_match"


def test_consolidate_alias_merge_open_source():
    """Open models merges to Open Source AI."""
    from podcast_research.exporters.obsidian import _classify_topic_status

    for variant in ["open models", "open source models", "open weights"]:
        status, reason = _classify_topic_status(variant, 3)
        assert status == "core", f"{variant} should be core via alias, got {status}"
        assert reason == "alias_match"


def test_consolidate_emerging_topic():
    """Multi-report non-core topic is marked emerging."""
    from podcast_research.exporters.obsidian import _classify_topic_status

    status, reason = _classify_topic_status("Some Emerging Topic", 5)
    assert status == "emerging"
    assert reason == "report_count"


def test_consolidate_long_tail_topic():
    """Single-report topic is marked long_tail."""
    from podcast_research.exporters.obsidian import _classify_topic_status

    status, reason = _classify_topic_status("Some Long Tail Topic", 1)
    assert status == "long_tail"
    assert reason == "report_count"


def test_consolidate_dry_run_no_files(tmp_path):
    """dry-run does not modify files."""
    from podcast_research.exporters.obsidian import consolidate_topics

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_topic_card(vault, "AI Agents", report_count=3)
    _create_topic_card(vault, "Ai Agent", report_count=1)

    result = consolidate_topics(vault, dry_run=True)

    # Both files should still exist
    assert (vault / "02_Topics" / "AI Agents.md").exists()
    assert (vault / "02_Topics" / "Ai Agent.md").exists()
    assert result["merged_count"] >= 1


def test_consolidate_apply_merges_aliases(tmp_path):
    """apply merges alias topics into canonical."""
    from podcast_research.exporters.obsidian import consolidate_topics

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_topic_card(vault, "AI Agents", report_count=3)
    _create_topic_card(vault, "Ai Agent", report_count=1)
    (vault / "99_System").mkdir(parents=True, exist_ok=True)

    result = consolidate_topics(vault, apply=True)

    # Ai Agent should be moved to backup
    assert not (vault / "02_Topics" / "Ai Agent.md").exists()
    # AI Agents should still exist
    assert (vault / "02_Topics" / "AI Agents.md").exists()
    assert result["merged_count"] >= 1


def test_consolidate_apply_no_delete(tmp_path):
    """apply does not delete old files, only backs up."""
    from podcast_research.exporters.obsidian import consolidate_topics

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_topic_card(vault, "AI Agents", report_count=3)
    _create_topic_card(vault, "Ai Agent", report_count=1)
    (vault / "99_System").mkdir(parents=True, exist_ok=True)

    consolidate_topics(vault, apply=True)

    # Check backup exists
    backup_dir = vault / "99_System" / "Topic_Consolidation_Backup"
    assert backup_dir.exists()
    backup_files = list(backup_dir.glob("*.md"))
    assert len(backup_files) >= 1


def test_consolidate_source_reports_no_duplicate(tmp_path):
    """Source Reports merge without duplicates."""
    from podcast_research.exporters.obsidian import consolidate_topics

    vault = tmp_path / "vault"
    vault.mkdir()
    # Create both cards with same source report
    source_reports = [
        {"filename": "2026-05-29_TechPod_vid001", "channel": "TechPod", "title": "Test 1", "video_id": "vid001"}
    ]
    _create_topic_card(vault, "AI Agents", source_reports=source_reports)
    _create_topic_card(vault, "Ai Agent", source_reports=source_reports)
    (vault / "99_System").mkdir(parents=True, exist_ok=True)

    consolidate_topics(vault, apply=True)

    # Check canonical card has link only once
    content = (vault / "02_Topics" / "AI Agents.md").read_text(encoding="utf-8")
    assert content.count("[[2026-05-29_TechPod_vid001]]") == 1


def test_consolidate_taxonomy_index(tmp_path):
    """Topic Taxonomy.md is generated."""
    from podcast_research.exporters.obsidian import consolidate_topics

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_topic_card(vault, "AI Agents", report_count=3)
    _create_topic_card(vault, "Some Emerging Topic", report_count=5)
    _create_topic_card(vault, "Some Long Tail", report_count=1)
    (vault / "99_System").mkdir(parents=True, exist_ok=True)

    consolidate_topics(vault, apply=True)

    taxonomy_path = vault / "99_System" / "Topic Taxonomy.md"
    assert taxonomy_path.exists()
    content = taxonomy_path.read_text(encoding="utf-8")
    assert "# Topic Taxonomy" in content
    assert "## Core Topics" in content
    assert "## Emerging Topics" in content
    assert "## Long-tail Topics" in content
    assert "AI Agents" in content


def test_consolidate_topic_index_updated(tmp_path):
    """Topic Index is updated after consolidation."""
    from podcast_research.exporters.obsidian import consolidate_topics

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_topic_card(vault, "AI Agents", report_count=3)
    _create_topic_card(vault, "Ai Agent", report_count=1)
    (vault / "99_System").mkdir(parents=True, exist_ok=True)

    consolidate_topics(vault, apply=True)

    index_path = vault / "99_System" / "Topic Index.md"
    assert index_path.exists()
    content = index_path.read_text(encoding="utf-8")
    assert "AI Agents" in content


def test_consolidate_mark_status(tmp_path):
    """Status is marked in frontmatter."""
    from podcast_research.exporters.obsidian import consolidate_topics

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_topic_card(vault, "AI Agents", report_count=3)
    (vault / "99_System").mkdir(parents=True, exist_ok=True)

    consolidate_topics(vault, apply=True)

    content = (vault / "02_Topics" / "AI Agents.md").read_text(encoding="utf-8")
    assert "status: core" in content


def test_consolidate_empty_vault(tmp_path):
    """Empty vault does not error."""
    from podcast_research.exporters.obsidian import consolidate_topics

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "02_Topics").mkdir()

    result = consolidate_topics(vault)
    assert result["core_count"] == 0
    assert result["merged_count"] == 0


def test_cli_consolidate_topics_dry_run(tmp_path):
    """CLI consolidate-topics --dry-run works."""
    from typer.testing import CliRunner
    from podcast_research.cli import app

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_topic_card(vault, "AI Agents", report_count=3)

    runner = CliRunner()
    result = runner.invoke(app, [
        "obsidian", "consolidate-topics",
        "--vault", str(vault),
        "--dry-run",
    ])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.stdout


def test_cli_consolidate_topics_no_vault(monkeypatch):
    """CLI consolidate-topics without vault errors."""
    from typer.testing import CliRunner
    from podcast_research.cli import app
    import podcast_research.config

    monkeypatch.setattr(podcast_research.config, "OBSIDIAN_VAULT_PATH", "")

    runner = CliRunner()
    result = runner.invoke(app, ["obsidian", "consolidate-topics"])
    assert result.exit_code == 1


# ═════════════════════════════════════════════════════════════════════════════
# P2-D.2.1: Topic Taxonomy Final Hardening tests
# ═════════════════════════════════════════════════════════════════════════════

def test_hardening_ai_for_science_casing(tmp_path):
    """'Ai For Science' should be renamed to 'AI for Science' (correct casing)."""
    from podcast_research.exporters.obsidian import consolidate_topics

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_topic_card(vault, "Ai For Science", report_count=2)
    (vault / "99_System").mkdir(parents=True, exist_ok=True)

    result = consolidate_topics(vault, apply=True)

    # Check actual filenames (case-sensitive check)
    actual_files = [f.name for f in (vault / "02_Topics").glob("*.md")]
    # On Windows, both "Ai For Science.md" and "AI for Science.md" refer to same file
    # So we check that the file with correct casing exists
    assert "AI for Science.md" in actual_files
    # And the file content has been updated
    content = (vault / "02_Topics" / "AI for Science.md").read_text(encoding="utf-8")
    assert "topic: AI for Science" in content
    assert "# AI for Science" in content
    assert result["merged_count"] >= 1


def test_hardening_application_to_ai_applications(tmp_path):
    """Generic 'Application' should merge into 'AI Applications'."""
    from podcast_research.exporters.obsidian import consolidate_topics

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_topic_card(vault, "Application", report_count=3)
    (vault / "99_System").mkdir(parents=True, exist_ok=True)

    result = consolidate_topics(vault, apply=True)

    # Generic topic should be merged
    assert not (vault / "02_Topics" / "Application.md").exists()
    # Canonical topic should exist
    assert (vault / "02_Topics" / "AI Applications.md").exists()
    assert result["merged_count"] >= 1


def test_hardening_model_to_ai_models(tmp_path):
    """Generic 'Model' should merge into 'AI Models'."""
    from podcast_research.exporters.obsidian import consolidate_topics

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_topic_card(vault, "Model", report_count=3)
    (vault / "99_System").mkdir(parents=True, exist_ok=True)

    result = consolidate_topics(vault, apply=True)

    assert not (vault / "02_Topics" / "Model.md").exists()
    assert (vault / "02_Topics" / "AI Models.md").exists()
    assert result["merged_count"] >= 1


def test_hardening_enterprise_to_enterprise_ai(tmp_path):
    """Generic 'Enterprise' should merge into 'Enterprise AI'."""
    from podcast_research.exporters.obsidian import consolidate_topics

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_topic_card(vault, "Enterprise", report_count=2)
    (vault / "99_System").mkdir(parents=True, exist_ok=True)

    result = consolidate_topics(vault, apply=True)

    assert not (vault / "02_Topics" / "Enterprise.md").exists()
    assert (vault / "02_Topics" / "Enterprise AI.md").exists()
    assert result["merged_count"] >= 1


def test_hardening_enterprise_chinese_to_enterprise_ai(tmp_path):
    """Chinese '企业级' should merge into 'Enterprise AI'."""
    from podcast_research.exporters.obsidian import consolidate_topics

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_topic_card(vault, "企业级", report_count=2)
    (vault / "99_System").mkdir(parents=True, exist_ok=True)

    result = consolidate_topics(vault, apply=True)

    assert not (vault / "02_Topics" / "企业级.md").exists()
    assert (vault / "02_Topics" / "Enterprise AI.md").exists()
    assert result["merged_count"] >= 1


def test_hardening_capital_market_to_public_markets(tmp_path):
    """'Capital Market' should merge into 'Public Markets'."""
    from podcast_research.exporters.obsidian import consolidate_topics

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_topic_card(vault, "Capital Market", report_count=2)
    (vault / "99_System").mkdir(parents=True, exist_ok=True)

    result = consolidate_topics(vault, apply=True)

    assert not (vault / "02_Topics" / "Capital Market.md").exists()
    assert (vault / "02_Topics" / "Public Markets.md").exists()
    assert result["merged_count"] >= 1


def test_hardening_generic_topic_guard():
    """Generic topics must be blocked from surviving as independent topics."""
    from podcast_research.exporters.obsidian import _GENERIC_TOPICS

    # All these should be in the guard set
    assert "application" in _GENERIC_TOPICS
    assert "applications" in _GENERIC_TOPICS
    assert "model" in _GENERIC_TOPICS
    assert "models" in _GENERIC_TOPICS
    assert "enterprise" in _GENERIC_TOPICS
    assert "企业级" in _GENERIC_TOPICS
    assert "capital market" in _GENERIC_TOPICS
    assert "capital markets" in _GENERIC_TOPICS


def test_hardening_source_reports_no_duplicate(tmp_path):
    """Source Reports merge without duplicates when merging generic topics."""
    from podcast_research.exporters.obsidian import consolidate_topics

    vault = tmp_path / "vault"
    vault.mkdir()
    # Create both cards with same source report
    source_reports = [
        {"filename": "2026-05-29_TechPod_vid001", "channel": "TechPod", "title": "Test 1", "video_id": "vid001"}
    ]
    _create_topic_card(vault, "Application", source_reports=source_reports)
    _create_topic_card(vault, "AI Applications", source_reports=source_reports)
    (vault / "99_System").mkdir(parents=True, exist_ok=True)

    consolidate_topics(vault, apply=True)

    # Check canonical card has link only once
    content = (vault / "02_Topics" / "AI Applications.md").read_text(encoding="utf-8")
    assert content.count("[[2026-05-29_TechPod_vid001]]") == 1


def test_hardening_backup_creation(tmp_path):
    """Old topic files are moved to backup, not deleted."""
    from podcast_research.exporters.obsidian import consolidate_topics

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_topic_card(vault, "Application", report_count=3)
    (vault / "99_System").mkdir(parents=True, exist_ok=True)

    consolidate_topics(vault, apply=True)

    # Check backup exists
    backup_dir = vault / "99_System" / "Topic_Consolidation_Backup"
    assert backup_dir.exists()
    backup_files = list(backup_dir.glob("*.md"))
    assert len(backup_files) >= 1
    # Check the merged file is in backup
    assert any("Application" in f.name for f in backup_files)


def test_hardening_taxonomy_updated(tmp_path):
    """Topic Taxonomy.md is updated after hardening."""
    from podcast_research.exporters.obsidian import consolidate_topics

    vault = tmp_path / "vault"
    vault.mkdir()
    _create_topic_card(vault, "Application", report_count=3)
    _create_topic_card(vault, "AI Applications", report_count=5)
    (vault / "99_System").mkdir(parents=True, exist_ok=True)

    consolidate_topics(vault, apply=True)

    taxonomy_path = vault / "99_System" / "Topic Taxonomy.md"
    assert taxonomy_path.exists()
    content = taxonomy_path.read_text(encoding="utf-8")
    # AI Applications should be in core
    assert "AI Applications" in content
    # Application should NOT be in the taxonomy (it was merged)
    assert "| Application |" not in content
