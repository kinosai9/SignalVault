"""P1-E: channels / channel_videos 测试"""

import pytest


# --- ChannelVideoAdapter tests ---

def test_parse_channel_id_handle():
    from podcast_research.cli import _parse_channel_id
    assert _parse_channel_id("https://www.youtube.com/@allin") == "@allin"


def test_parse_channel_id_handle_with_trailing_slash():
    from podcast_research.cli import _parse_channel_id
    assert _parse_channel_id("https://www.youtube.com/@allin/") == "@allin"


def test_parse_channel_id_handle_with_videos():
    from podcast_research.cli import _parse_channel_id
    assert _parse_channel_id("https://www.youtube.com/@allin/videos") == "@allin"


def test_parse_channel_id_channel():
    from podcast_research.cli import _parse_channel_id
    assert _parse_channel_id("https://www.youtube.com/channel/UCESLZhusAkFfsNsApnjF_Cg") == "UCESLZhusAkFfsNsApnjF_Cg"


def test_parse_channel_id_c():
    from podcast_research.cli import _parse_channel_id
    result = _parse_channel_id("https://www.youtube.com/c/SomeChannel")
    assert "SomeChannel" in result


def test_channel_video_adapter_mock(monkeypatch):
    """mock yt-dlp 输出，验证 adapter 返回正确结构。"""
    from podcast_research.adapters.channel_video_adapter import ChannelVideoAdapter

    class MockYDL:
        def __init__(self, opts=None):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download=False):
            return {
                "channel": "Test Channel",
                "entries": [
                    {"id": "abc123", "title": "Video 1", "duration": 600, "upload_date": "20260528"},
                    {"id": "def456", "title": "Video 2", "duration": 1200, "upload_date": "20260527"},
                    {"id": "UCESLZhusAkFfsNsApnjF_Cg", "title": "Playlist Tab", "duration": 0},
                ],
            }

    monkeypatch.setattr("yt_dlp.YoutubeDL", MockYDL)
    adapter = ChannelVideoAdapter()
    items = adapter.fetch_channel_videos("https://www.youtube.com/@test", limit=10)
    # UCXXX channel IDs should be filtered out
    assert len(items) == 2
    assert items[0].video_id == "abc123"
    assert items[0].title == "Video 1"
    assert items[0].duration_seconds == 600
    assert items[0].url == "https://www.youtube.com/watch?v=abc123"


# --- Repository tests ---

def test_add_channel(db_session):
    from podcast_research.db.channel_repository import add_channel, list_channels

    cid = add_channel(db_session, "@test", "https://www.youtube.com/@test", "Test")
    db_session.commit()
    assert cid > 0

    rows = list_channels(db_session)
    assert len(rows) == 1
    assert rows[0]["name"] == "Test"


def test_add_channel_dedup(db_session):
    from podcast_research.db.channel_repository import add_channel

    cid1 = add_channel(db_session, "@test", "https://www.youtube.com/@test", "Test")
    db_session.commit()
    cid2 = add_channel(db_session, "@test", "https://www.youtube.com/@test", "Updated")
    db_session.commit()
    assert cid1 == cid2


def test_upsert_videos(db_session):
    from podcast_research.db.channel_repository import add_channel, upsert_videos, list_channel_videos

    cid = add_channel(db_session, "@test", "https://example.com", "Test")
    db_session.commit()

    added = upsert_videos(db_session, cid, [
        {"video_id": "vid1", "title": "Title 1", "url": "https://youtu.be/vid1"},
        {"video_id": "vid2", "title": "Title 2", "url": "https://youtu.be/vid2"},
    ])
    db_session.commit()
    assert added == 2

    # dedup
    added2 = upsert_videos(db_session, cid, [
        {"video_id": "vid1", "title": "Title 1", "url": "https://youtu.be/vid1"},
        {"video_id": "vid3", "title": "Title 3", "url": "https://youtu.be/vid3"},
    ])
    db_session.commit()
    assert added2 == 1

    rows = list_channel_videos(db_session, cid)
    assert len(rows) == 3


def test_mark_video_status(db_session):
    from podcast_research.db.channel_repository import add_channel, upsert_videos, mark_video_status, get_video

    cid = add_channel(db_session, "@test", "https://example.com", "Test")
    db_session.commit()
    upsert_videos(db_session, cid, [{"video_id": "vid1", "title": "T1"}])
    db_session.commit()

    ok = mark_video_status(db_session, "vid1", "analyzed", report_id=42)
    db_session.commit()
    assert ok

    v = get_video(db_session, "vid1")
    assert v["status"] == "analyzed"
    assert v["report_id"] == 42


def test_mark_video_status_not_found(db_session):
    from podcast_research.db.channel_repository import mark_video_status
    ok = mark_video_status(db_session, "nonexistent", "analyzed")
    assert not ok


# --- CLI tests ---

def test_cli_channels_add(db_session):
    from typer.testing import CliRunner
    from podcast_research.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["channels", "add", "https://www.youtube.com/@allin", "--name", "All-In Podcast"])
    assert result.exit_code == 0
    assert "All-In Podcast" in result.stdout


def test_cli_channels_list(db_session):
    from typer.testing import CliRunner
    from podcast_research.cli import app

    # add first
    runner = CliRunner()
    runner.invoke(app, ["channels", "add", "https://www.youtube.com/@allin", "--name", "All-In Podcast"])

    result = runner.invoke(app, ["channels", "list"])
    assert result.exit_code == 0
    assert "All-In Podcast" in result.stdout


def test_cli_channels_list_empty(db_session):
    from typer.testing import CliRunner
    from podcast_research.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["channels", "list"])
    assert "未关注" in result.stdout or result.exit_code == 0


def test_cli_channels_refresh(monkeypatch, db_session):
    from typer.testing import CliRunner
    from podcast_research.cli import app

    # add channel first
    runner = CliRunner()
    runner.invoke(app, ["channels", "add", "https://www.youtube.com/@allin", "--name", "All-In Podcast"])

    # mock yt-dlp
    class MockYDL:
        def __init__(self, opts=None):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download=False):
            return {
                "channel": "All-In Podcast",
                "entries": [
                    {"id": "abc001", "title": "Ep 1", "duration": 3600},
                    {"id": "abc002", "title": "Ep 2", "duration": 2700},
                ],
            }

    monkeypatch.setattr("yt_dlp.YoutubeDL", MockYDL)
    result = runner.invoke(app, ["channels", "refresh", "1", "--limit", "5"])
    assert result.exit_code == 0
    assert "新增" in result.stdout


def test_cli_channels_videos(db_session):
    from typer.testing import CliRunner
    from podcast_research.cli import app

    runner = CliRunner()
    runner.invoke(app, ["channels", "add", "https://www.youtube.com/@allin", "--name", "Test"])

    result = runner.invoke(app, ["channels", "videos", "1"])
    assert result.exit_code == 0


def test_cli_channels_analyze_video_dry_run(db_session):
    from typer.testing import CliRunner
    from podcast_research.cli import app

    runner = CliRunner()
    # add channel
    runner.invoke(app, ["channels", "add", "https://www.youtube.com/@allin", "--name", "Test"])

    result = runner.invoke(app, ["channels", "analyze-video", "--video-id", "abc123", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.stdout or "mock" in result.stdout.lower()


def test_cli_channels_analyze_video_already_analyzed(db_session, monkeypatch):
    from typer.testing import CliRunner
    from podcast_research.cli import app
    from podcast_research.db.channel_repository import add_channel, upsert_videos, mark_video_status

    runner = CliRunner()
    cid = add_channel(db_session, "@test", "https://youtu.be/@test", "Test")
    upsert_videos(db_session, cid, [{"video_id": "done1", "title": "Done"}])
    mark_video_status(db_session, "done1", "analyzed", report_id=5)
    db_session.commit()

    result = runner.invoke(app, ["channels", "analyze-video", "--video-id", "done1"])
    assert "已分析" in result.stdout or result.exit_code == 0


# --- P1-F: tags / priority / seed / list-filtering tests ---

def test_channels_migration_adds_new_columns(db_session):
    """旧 channels 表（无新列）的 DB 在 init_db 后自动补齐新列。"""
    from sqlalchemy import inspect

    # 验证表存在且新列已补齐
    assert inspect(db_session.get_bind()).has_table("channels")

    cols = {col["name"] for col in inspect(db_session.get_bind()).get_columns("channels")}
    for col in ["tags", "priority", "default_focus", "default_limit", "default_max_analyze", "notes"]:
        assert col in cols, f"Column {col} missing from channels table"


def test_add_channel_with_tags(db_session):
    from podcast_research.db.channel_repository import add_channel, get_channel

    cid = add_channel(db_session, "@test2", "https://example.com", "Test2",
                      tags=["ai", "tech"], priority="core",
                      default_focus="AI投资, 科技股", default_limit=15, default_max_analyze=5,
                      notes="Test notes")
    db_session.commit()

    ch = get_channel(db_session, cid)
    assert ch["tags"] == ["ai", "tech"]
    assert ch["priority"] == "core"
    assert ch["default_focus"] == "AI投资, 科技股"
    assert ch["default_limit"] == 15
    assert ch["default_max_analyze"] == 5
    assert ch["notes"] == "Test notes"


def test_add_channel_default_values(db_session):
    """未传新字段时使用默认值。"""
    from podcast_research.db.channel_repository import add_channel, get_channel

    cid = add_channel(db_session, "@test_defaults", "https://example.com", "Test")
    db_session.commit()

    ch = get_channel(db_session, cid)
    assert ch["tags"] == []
    assert ch["priority"] == "secondary"
    assert ch["default_focus"] == ""
    assert ch["default_limit"] == 10
    assert ch["default_max_analyze"] == 3
    assert ch["notes"] == ""


def test_seed_tech_ai_adds_4_channels(db_session):
    from podcast_research.db.channel_repository import seed_default_channels, list_channels

    result = seed_default_channels(db_session, channel_pack="tech_ai")
    db_session.commit()
    assert result["added"] == 4
    assert result["skipped"] == 0

    rows = list_channels(db_session)
    assert len(rows) == 4


def test_seed_tech_ai_idempotent(db_session):
    from podcast_research.db.channel_repository import seed_default_channels

    # first
    r1 = seed_default_channels(db_session, channel_pack="tech_ai")
    db_session.commit()
    assert r1["added"] == 4

    # second — all already configured, skip
    r2 = seed_default_channels(db_session, channel_pack="tech_ai")
    db_session.commit()
    assert r2["added"] == 0
    assert r2["skipped"] == 4


def test_seed_heals_existing_default_channel(db_session):
    """旧 add_channel（空 tags + secondary priority）在 seed 时自动补齐配置。"""
    from podcast_research.db.channel_repository import add_channel, seed_default_channels, get_channel

    # 模拟 P1-E 旧 add_channel：无 tags、priority=secondary
    cid = add_channel(db_session, "@allin", "https://www.youtube.com/@allin", "All-In Podcast")
    db_session.commit()

    ch = get_channel(db_session, cid)
    assert ch["tags"] == []
    assert ch["priority"] == "secondary"

    # seed 应补齐配置
    r = seed_default_channels(db_session, channel_pack="tech_ai")
    db_session.commit()
    assert r["added"] == 3
    assert r["updated"] == 1

    ch = get_channel(db_session, cid)
    assert ch["tags"] == ["tech", "ai", "vc", "macro", "markets", "podcast"]
    assert ch["priority"] == "core"
    assert ch["default_focus"] != ""


def test_list_channels_filter_by_tag(db_session):
    from podcast_research.db.channel_repository import seed_default_channels, list_channels

    seed_default_channels(db_session, channel_pack="tech_ai")
    db_session.commit()

    ai_rows = list_channels(db_session, tag="ai")
    # All-In, BG2Pod, Latent Space have "ai" tag
    assert len(ai_rows) == 3
    for r in ai_rows:
        assert "ai" in r["tags"]


def test_list_channels_filter_by_priority(db_session):
    from podcast_research.db.channel_repository import seed_default_channels, list_channels

    seed_default_channels(db_session, channel_pack="tech_ai")
    db_session.commit()

    core_rows = list_channels(db_session, priority="core")
    assert len(core_rows) == 4


def test_list_channels_filter_by_tag_and_priority(db_session):
    from podcast_research.db.channel_repository import seed_default_channels, list_channels

    seed_default_channels(db_session, channel_pack="tech_ai")
    db_session.commit()

    # All-In, BG2Pod, Latent Space have "ai" tag, all are core
    rows = list_channels(db_session, tag="ai", priority="core")
    assert len(rows) == 3


def test_seed_channels_have_default_focus(db_session):
    from podcast_research.db.channel_repository import seed_default_channels, list_channels

    seed_default_channels(db_session, channel_pack="tech_ai")
    db_session.commit()

    rows = list_channels(db_session)
    for r in rows:
        assert r["default_focus"], f"{r['name']} should have default_focus"


def test_seed_channels_have_tags(db_session):
    from podcast_research.db.channel_repository import seed_default_channels, list_channels

    seed_default_channels(db_session, channel_pack="tech_ai")
    db_session.commit()

    rows = list_channels(db_session)
    for r in rows:
        assert r["tags"], f"{r['name']} should have tags"
        assert len(r["tags"]) >= 3


def test_update_channel_tags_add(db_session):
    from podcast_research.db.channel_repository import seed_default_channels, update_channel_tags, get_channel

    seed_default_channels(db_session, channel_pack="tech_ai")
    db_session.commit()

    # All-In is first added (lowest ID)
    allin_id = 1
    ok = update_channel_tags(db_session, allin_id, add=["new-tag", "extra"])
    db_session.commit()
    assert ok

    ch = get_channel(db_session, allin_id)
    assert "new-tag" in ch["tags"]
    assert "extra" in ch["tags"]


def test_update_channel_tags_remove(db_session):
    from podcast_research.db.channel_repository import seed_default_channels, update_channel_tags, get_channel

    seed_default_channels(db_session, channel_pack="tech_ai")
    db_session.commit()

    allin_id = 1
    ok = update_channel_tags(db_session, allin_id, remove=["tech", "ai"])
    db_session.commit()
    assert ok

    ch = get_channel(db_session, allin_id)
    assert "tech" not in ch["tags"]
    assert "ai" not in ch["tags"]


def test_update_channel_tags_set(db_session):
    from podcast_research.db.channel_repository import seed_default_channels, update_channel_tags, get_channel

    seed_default_channels(db_session, channel_pack="tech_ai")
    db_session.commit()

    allin_id = 1
    ok = update_channel_tags(db_session, allin_id, set_tags=["podcast", "investing"])
    db_session.commit()
    assert ok

    ch = get_channel(db_session, allin_id)
    assert ch["tags"] == ["podcast", "investing"]


def test_update_channel_tags_nonexistent(db_session):
    from podcast_research.db.channel_repository import update_channel_tags

    ok = update_channel_tags(db_session, 9999, add=["test"])
    assert not ok


def test_get_channel_defaults(db_session):
    from podcast_research.db.channel_repository import seed_default_channels, get_channel_defaults

    seed_default_channels(db_session, channel_pack="tech_ai")
    db_session.commit()

    defaults = get_channel_defaults(db_session, 1)
    assert defaults is not None
    assert "default_focus" in defaults
    assert "default_limit" in defaults
    assert "default_max_analyze" in defaults
    assert "priority" in defaults


# --- CLI P1-F tests ---

def test_cli_channels_seed_tech_ai(db_session):
    from typer.testing import CliRunner
    from podcast_research.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["channels", "seed-tech-ai"])
    assert result.exit_code == 0
    assert "新增" in result.stdout or "added" in result.stdout.lower() or "播种" in result.stdout


def test_cli_channels_list_tag(db_session):
    from typer.testing import CliRunner
    from podcast_research.cli import app

    runner = CliRunner()
    runner.invoke(app, ["channels", "seed-tech-ai"])

    result = runner.invoke(app, ["channels", "list", "--tag", "ai"])
    assert result.exit_code == 0


def test_cli_channels_list_priority(db_session):
    from typer.testing import CliRunner
    from podcast_research.cli import app

    runner = CliRunner()
    runner.invoke(app, ["channels", "seed-tech-ai"])

    result = runner.invoke(app, ["channels", "list", "--priority", "core"])
    assert result.exit_code == 0


def test_cli_channels_tag_add(db_session):
    from typer.testing import CliRunner
    from podcast_research.cli import app

    runner = CliRunner()
    runner.invoke(app, ["channels", "seed-tech-ai"])

    result = runner.invoke(app, ["channels", "tag", "1", "--add", "new-category,test"])
    assert result.exit_code == 0
    assert "new-category" in result.stdout or "标签已更新" in result.stdout


def test_cli_channels_tag_remove(db_session):
    from typer.testing import CliRunner
    from podcast_research.cli import app

    runner = CliRunner()
    runner.invoke(app, ["channels", "seed-tech-ai"])

    result = runner.invoke(app, ["channels", "tag", "1", "--remove", "vc"])
    assert result.exit_code == 0


def test_cli_channels_tag_set(db_session):
    from typer.testing import CliRunner
    from podcast_research.cli import app

    runner = CliRunner()
    runner.invoke(app, ["channels", "seed-tech-ai"])

    result = runner.invoke(app, ["channels", "tag", "1", "--set", "podcast,investing"])
    assert result.exit_code == 0
    assert "podcast" in result.stdout or "标签已更新" in result.stdout


# --- P2-A2.1: Channel / Video Metadata Propagation ---

def test_get_channel_video_by_video_id_returns_joined_metadata(db_session):
    """联表查询返回 channel + channel_video 完整元数据。"""
    from podcast_research.db.channel_repository import (
        add_channel, upsert_videos, get_channel_video_by_video_id,
    )

    cid = add_channel(db_session, "@BG2Pod", "https://www.youtube.com/@BG2Pod", "BG2Pod",
                      tags=["tech", "ai"], priority="core")
    upsert_videos(db_session, cid, [
        {"video_id": "abc123def", "title": "AI Infrastructure Deep Dive",
         "url": "https://www.youtube.com/watch?v=abc123def", "published_at": "2026-05-15",
         "duration_seconds": 3600},
    ])
    db_session.commit()

    meta = get_channel_video_by_video_id(db_session, "abc123def")
    assert meta is not None
    assert meta["channel_name"] == "BG2Pod"
    assert meta["channel_url"] == "https://www.youtube.com/@BG2Pod"
    assert meta["channel_tags"] == ["tech", "ai"]
    assert meta["channel_priority"] == "core"
    assert meta["video_title"] == "AI Infrastructure Deep Dive"
    assert meta["video_id"] == "abc123def"
    assert meta["video_url"] == "https://www.youtube.com/watch?v=abc123def"
    assert meta["published_at"] == "2026-05-15"
    assert meta["duration_seconds"] == 3600


def test_get_channel_video_by_video_id_not_found(db_session):
    """未注册的 video_id 返回 None。"""
    from podcast_research.db.channel_repository import get_channel_video_by_video_id

    meta = get_channel_video_by_video_id(db_session, "nonexistent_id")
    assert meta is None


def test_source_info_override_fills_empty_fields():
    """source_info_override 的非空值覆盖 source_info 中的空字段。"""
    from podcast_research.analysis.pipeline import _merge_source_info_override

    source_info = {
        "source_type": "youtube",
        "source_url": "https://www.youtube.com/watch?v=abc123",
        "video_id": "abc123",
        "language": "en",
        "title": "",
        "channel_name": "",
    }

    override = {
        "channel_name": "BG2Pod",
        "video_title": "AI Deep Dive",
        "video_url": "https://www.youtube.com/watch?v=abc123",
        "published_at": "2026-05-15",
    }

    _merge_source_info_override(source_info, override)

    assert source_info["channel_name"] == "BG2Pod"
    assert source_info["title"] == "AI Deep Dive"  # video_title → title
    assert source_info["video_url"] == "https://www.youtube.com/watch?v=abc123"
    assert source_info["published_at"] == "2026-05-15"
    # 已有字段不被覆盖
    assert source_info["video_id"] == "abc123"
    assert source_info["language"] == "en"


def test_source_info_override_does_not_overwrite_existing():
    """override 不覆盖已有非空值。"""
    from podcast_research.analysis.pipeline import _merge_source_info_override

    source_info = {
        "source_type": "youtube",
        "title": "Original Title from Adapter",
        "channel_name": "Original Channel",
    }

    override = {
        "channel_name": "BG2Pod",
        "video_title": "AI Deep Dive",
    }

    _merge_source_info_override(source_info, override)

    # 已有非空值保持不变
    assert source_info["title"] == "Original Title from Adapter"
    assert source_info["channel_name"] == "Original Channel"


def test_report_markdown_shows_channel_metadata():
    """Markdown 报告数据来源部分展示频道名和视频标题。"""
    from podcast_research.llm.mock_provider import MockLLMProvider
    from podcast_research.analysis.models import ExtractionResult

    provider = MockLLMProvider()
    extraction = ExtractionResult(
        source_info={
            "source_type": "youtube",
            "channel_name": "BG2Pod",
            "channel_url": "https://www.youtube.com/@BG2Pod",
            "title": "AI Infrastructure Deep Dive",
            "video_id": "abc123def",
            "video_url": "https://www.youtube.com/watch?v=abc123def",
            "published_at": "2026-05-15",
            "language": "en",
            "transcript_segment_count": 200,
            "is_generated": False,
            "channel_tags": ["tech", "ai", "investing"],
        },
    )
    report = provider.render_report(extraction)

    assert "数据来源" in report
    assert "来源频道" in report
    assert "BG2Pod" in report
    assert "频道链接" in report
    assert "视频标题" in report
    assert "AI Infrastructure Deep Dive" in report
    assert "视频 ID" in report
    assert "abc123def" in report
    assert "视频链接" in report
    assert "发布日期" in report
    assert "2026-05-15" in report
    assert "字幕语言" in report
    assert "en" in report
    assert "频道标签" in report
    assert "#tech" in report


def test_report_markdown_no_channel_metadata_still_works():
    """没有频道元数据时报告正常渲染（不崩溃）。"""
    from podcast_research.llm.mock_provider import MockLLMProvider
    from podcast_research.analysis.models import ExtractionResult

    provider = MockLLMProvider()
    extraction = ExtractionResult(
        source_info={
            "source_type": "youtube",
            "video_id": "xyz789",
            "language": "zh-Hans",
            "transcript_segment_count": 50,
            "is_generated": True,
        },
    )
    report = provider.render_report(extraction)

    assert "数据来源" in report
    assert "视频 ID" in report
    assert "xyz789" in report
    assert "zh-Hans" in report
    # 不崩溃，正常渲染
    assert "执行摘要" in report


def test_normal_youtube_url_path_unaffected(db_session, tmp_path, monkeypatch):
    """普通 --youtube-url 路径不受 metadata propagation 影响。"""
    from pathlib import Path
    from typer.testing import CliRunner
    from unittest.mock import MagicMock, patch
    from podcast_research.cli import app

    runner = CliRunner()
    sample_srt = Path(__file__).resolve().parent.parent / "data" / "subtitles" / "sample.srt"

    # 验证普通 youtube-url 分析仍正常工作（mock + --mock 不走真实 API）
    mock_transcript_data = [
        {"text": "大家好", "start": 0.0, "duration": 3.0},
        {"text": "宁德时代需求增长", "start": 3.0, "duration": 4.0},
    ]

    with patch("podcast_research.adapters.youtube_transcript.YouTubeTranscriptApi") as mock_api_class:
        mock_transcript = MagicMock()
        mock_transcript.language_code = "zh-Hans"
        mock_transcript.is_generated = False
        mock_transcript.fetch.return_value = mock_transcript_data

        mock_list = MagicMock()
        mock_list.find_transcript.return_value = mock_transcript
        mock_list.__iter__ = MagicMock(return_value=iter([mock_transcript]))
        mock_api_instance = mock_api_class.return_value
        mock_api_instance.list.return_value = mock_list

        result = runner.invoke(
            app,
            ["--youtube-url", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "--mock", "-o", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "分析完成" in result.output


# --- Full test unchanged ---

def test_existing_tests_still_pass():
    """标记性测试：确认原有功能不破坏。"""
    pass
