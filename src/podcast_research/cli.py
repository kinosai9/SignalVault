"""CLI 入口：分析 + 报告库查询。

分析：python -m podcast_research --subtitle-file <file> 或 --youtube-url <url>
查询：python -m podcast_research reports list / show / search / targets / sources
"""

from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from podcast_research.analysis.pipeline import analyze as run_analyze
from podcast_research.analysis.pipeline import analyze_from_transcript as run_analyze_from_transcript
from podcast_research.config import LLM_PROVIDER, TRANSCRIPT_CACHE_DIR, ensure_dirs
from podcast_research.logging_config import setup_logging

console = Console()
app = typer.Typer(
    help="投资音视频研究助手 — 将音视频字幕中的投资观点结构化沉淀",
    invoke_without_command=True,
)

# --- reports 子命令组 ---
reports_app = typer.Typer(help="报告库查询与统计")
app.add_typer(reports_app, name="reports")

# --- eval 子命令组 ---
eval_app = typer.Typer(help="跨频道 Prompt 质量评估")
app.add_typer(eval_app, name="eval")


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "-"
    return dt.strftime("%m-%d %H:%M")


# ---------------------------------------------------------------------------
# 主 callback：分析命令 + 子命令守卫
# ---------------------------------------------------------------------------

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    subtitle_file: Path = typer.Option(None, help="本地字幕文件路径 (.srt/.vtt/.txt)"),
    youtube_url: str = typer.Option(None, "--youtube-url", help="YouTube 视频链接"),
    youtube_lang: str = typer.Option(None, "--youtube-lang", help="YouTube 字幕语言优先级，逗号分隔，如 'zh-Hans,en'"),
    mock: bool = typer.Option(None, help="使用 mock 规则引擎（覆盖 .env 配置）"),
    focus: str = typer.Option(None, "--focus", help="关注点，逗号分隔，如 '新能源,港股,AI算力'"),
    depth: str = typer.Option("standard", "--depth", help="分析深度: standard / deep"),
    output: Path | None = typer.Option(None, "-o", help="报告输出目录"),
    verbose: bool = typer.Option(False, "-v", help="详细日志"),
) -> None:
    """分析本地字幕文件或 YouTube 视频字幕，或使用 reports 子命令查询已有报告。"""
    level = "DEBUG" if verbose else "INFO"
    setup_logging(level)
    ensure_dirs()

    # 子命令接管：reports list / show / search / targets / sources
    if ctx.invoked_subcommand is not None:
        return

    # --- 以下为分析命令逻辑 ---
    if subtitle_file and youtube_url:
        console.print("[red]--subtitle-file 和 --youtube-url 不能同时使用[/red]")
        raise typer.Exit(code=1)
    if not subtitle_file and not youtube_url:
        console.print("请提供字幕文件或 YouTube 链接。用法:\n  python -m podcast_research --subtitle-file <file>\n  python -m podcast_research --youtube-url <url>\n  python -m podcast_research reports list")
        raise typer.Exit(code=1)

    focus_areas = [f.strip() for f in focus.split(",") if f.strip()] if focus else None

    if mock is True:
        provider = "mock"
    elif mock is False:
        provider = "openai-compatible"
    else:
        provider = LLM_PROVIDER

    if youtube_url:
        from podcast_research.adapters.youtube_transcript import YouTubeTranscriptAdapter

        lang_list = [l.strip() for l in youtube_lang.split(",") if l.strip()] if youtube_lang else None

        console.print(Panel(f"YouTube 视频: {youtube_url}\nLLM provider: {provider}", title="投资音视频研究助手"))

        try:
            adapter = YouTubeTranscriptAdapter(cache_dir=TRANSCRIPT_CACHE_DIR)
            transcript = adapter.fetch(url=youtube_url, languages=lang_list)
            console.print(f"  获取字幕成功: {transcript.video_id} (语言: {transcript.language}, 段数: {len(transcript.segments)})")
        except Exception as e:
            console.print(f"[red]YouTube 字幕获取失败: {e}[/red]")
            raise typer.Exit(code=1)

        try:
            result = run_analyze_from_transcript(
                transcript,
                provider_name=provider,
                output_dir=output,
                focus_areas=focus_areas,
                analysis_depth=depth,
            )
        except Exception as e:
            err_msg = str(e)
            if "LLM" in err_msg or "API" in err_msg or "token" in err_msg.lower():
                console.print(f"[red]LLM 分析失败: {e}[/red]")
                console.print("  提示: 检查 .env 中的 LLM 配置，或尝试 --mock 模式确认链路正常")
                console.print("  长视频可能超出 token 上限，可尝试更短的视频或减少 --depth")
            else:
                console.print(f"[red]分析失败: {e}[/red]")
            raise typer.Exit(code=1)

    else:
        if not subtitle_file.exists():
            console.print(f"[red]文件不存在: {subtitle_file}[/red]")
            raise typer.Exit(code=1)

        console.print(Panel(f"分析字幕: {subtitle_file}\nLLM provider: {provider}", title="投资音视频研究助手"))

        try:
            result = run_analyze(
                subtitle_file,
                provider_name=provider,
                output_dir=output,
                focus_areas=focus_areas,
                analysis_depth=depth,
            )
        except Exception as e:
            console.print(f"[red]分析失败: {e}[/red]")
            raise typer.Exit(code=1)

    console.print("[green]分析完成[/green]")
    if result.get("focus_areas"):
        console.print(f"  关注点: {', '.join(result['focus_areas'])}")
    console.print(f"  观点数: {result['view_count']}")
    console.print(f"  标的数: {result['entity_count']}")
    console.print(f"  报告: {result['report_path']}")
    console.print(f"  JSON: {result['extraction_path']}")


# ---------------------------------------------------------------------------
# reports 子命令
# ---------------------------------------------------------------------------


@reports_app.command("list")
def reports_list(
    limit: int = typer.Option(20, "--limit", help="最大返回数量"),
    source: str = typer.Option(None, "--source", help="按来源过滤: local / youtube"),
) -> None:
    """列出已分析报告。"""
    from podcast_research.db.repository import list_reports
    from podcast_research.db.session import get_session, init_db

    init_db()
    session = get_session()
    try:
        rows = list_reports(session, limit=limit, source_type=source)
    finally:
        session.close()

    if not rows:
        console.print("[yellow]暂无报告。先运行分析命令生成报告。[/yellow]")
        return

    table = Table(title="报告列表", show_lines=False)
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("日期", style="dim")
    table.add_column("来源")
    table.add_column("标题/视频ID", max_width=30)
    table.add_column("关注点", max_width=25)
    table.add_column("观点数", justify="right")
    table.add_column("实体数", justify="right")

    for r in rows:
        focus_str = ", ".join(r["focus_areas"][:3]) if r["focus_areas"] else "-"
        table.add_row(
            str(r["id"]),
            _fmt_dt(r["created_at"]),
            r["source_type"],
            r["episode_title"][:30],
            focus_str,
            str(r["view_count"]),
            str(r["entity_count"]),
        )

    console.print(table)


@reports_app.command("show")
def reports_show(
    report_id: int = typer.Argument(..., help="报告 ID"),
    full: bool = typer.Option(False, "--full", help="输出完整 Markdown"),
) -> None:
    """查看报告详情。"""
    from podcast_research.db.repository import get_report_detail
    from podcast_research.db.session import get_session, init_db

    init_db()
    session = get_session()
    try:
        detail = get_report_detail(session, report_id)
    finally:
        session.close()

    if not detail:
        console.print(f"[red]未找到报告 ID={report_id}[/red]")
        raise typer.Exit(code=1)

    if full:
        console.print(Panel(detail["report_markdown"], title=f"报告 #{detail['id']} 完整内容", border_style="blue"))
        return

    # 元信息
    meta_lines = [
        f"来源: {detail['source_type']}",
        f"标题/视频: {detail['episode_title']}",
    ]
    if detail["video_id"]:
        meta_lines.append(f"video_id: {detail['video_id']}")
    if detail["source_url"]:
        meta_lines.append(f"URL: {detail['source_url']}")
    meta_lines.append(f"关注点: {', '.join(detail['focus_areas']) if detail['focus_areas'] else '-'}")
    meta_lines.append(f"分析深度: {detail['analysis_depth']}")
    meta_lines.append(f"LLM: {detail['llm_provider']} / {detail['llm_model']}")
    meta_lines.append(f"创建时间: {_fmt_dt(detail['created_at'])}")
    meta_lines.append(f"观点数: {len(detail['views'])}")
    meta_lines.append(f"信号数: {len(detail['signals'])}")

    console.print(Panel("\n".join(meta_lines), title=f"报告 #{detail['id']}", border_style="green"))

    # 前 5 条观点
    views = detail["views"][:5]
    if views:
        console.print("\n[bold]核心观点（前 5 条）[/bold]")
        vtable = Table(show_lines=True)
        vtable.add_column("标的", style="cyan")
        vtable.add_column("方向")
        vtable.add_column("逻辑链", max_width=40)
        vtable.add_column("时间戳")
        for v in views:
            vtable.add_row(
                v["target_name"],
                v["view_direction"],
                v["logic_chain"][:40],
                v["timestamp_start"],
            )
        console.print(vtable)

    if len(detail["views"]) > 5:
        console.print(f"\n[dim]... 共 {len(detail['views'])} 条观点，使用 --full 查看完整报告[/dim]")


@reports_app.command("search")
def reports_search(
    keyword: str = typer.Argument(..., help="搜索关键词"),
    limit: int = typer.Option(20, "--limit", help="最大返回数量"),
) -> None:
    """搜索报告内容。"""
    from podcast_research.db.repository import search_reports
    from podcast_research.db.session import get_session, init_db

    init_db()
    session = get_session()
    try:
        rows = search_reports(session, keyword, limit=limit)
    finally:
        session.close()

    if not rows:
        console.print(f"[yellow]未找到包含 \"{keyword}\" 的报告。[/yellow]")
        return

    table = Table(title=f"搜索: {keyword}", show_lines=False)
    table.add_column("报告ID", style="cyan", justify="right")
    table.add_column("匹配类型")
    table.add_column("匹配摘要", max_width=50)
    table.add_column("来源")
    table.add_column("创建时间", style="dim")

    for r in rows:
        table.add_row(
            str(r["report_id"]),
            r["match_type"],
            r["match_excerpt"][:50],
            r["source_type"],
            _fmt_dt(r["created_at"]),
        )

    console.print(table)


@reports_app.command("targets")
def reports_targets(
    limit: int = typer.Option(50, "--limit", help="最大返回数量"),
) -> None:
    """汇总投资标的统计。"""
    from podcast_research.db.repository import list_targets
    from podcast_research.db.session import get_session, init_db

    init_db()
    session = get_session()
    try:
        rows = list_targets(session, limit=limit)
    finally:
        session.close()

    if not rows:
        console.print("[yellow]暂无投资标的记录。[/yellow]")
        return

    table = Table(title="投资标的汇总", show_lines=False)
    table.add_column("标的", style="cyan")
    table.add_column("出现次数", justify="right")
    table.add_column("最近出现", style="dim")
    table.add_column("最近方向")

    for r in rows:
        table.add_row(
            r["target_name"],
            str(r["count"]),
            _fmt_dt(r["last_seen"]),
            r["last_direction"],
        )

    console.print(table)


@reports_app.command("sources")
def reports_sources() -> None:
    """统计各来源报告数量。"""
    from podcast_research.db.repository import list_sources
    from podcast_research.db.session import get_session, init_db

    init_db()
    session = get_session()
    try:
        rows = list_sources(session)
    finally:
        session.close()

    if not rows:
        console.print("[yellow]暂无报告记录。[/yellow]")
        return

    table = Table(title="来源统计", show_lines=False)
    table.add_column("来源", style="cyan")
    table.add_column("报告数", justify="right")
    table.add_column("最近报告", style="dim")

    for r in rows:
        table.add_row(
            r["source_type"],
            str(r["count"]),
            _fmt_dt(r["last_report_at"]),
        )

    console.print(table)


@reports_app.command("rebuild-index")
def reports_rebuild_index() -> None:
    """重建全文搜索索引。"""
    from podcast_research.db.fts import rebuild_search_index
    from podcast_research.db.session import get_session, init_db

    init_db()
    session = get_session()
    try:
        count = rebuild_search_index(session)
    finally:
        session.close()

    console.print(f"[green]FTS index rebuilt[/green]")
    console.print(f"Reports indexed: {count}")


# ---------------------------------------------------------------------------
# channels 子命令组
# ---------------------------------------------------------------------------

channels_app = typer.Typer(help="YouTube 频道关注与视频管理")
app.add_typer(channels_app, name="channels")


def _parse_channel_id(url: str) -> str:
    """从 YouTube 频道 URL 提取频道标识。"""
    import re

    url = url.rstrip("/").replace("/videos", "").replace("/shorts", "").replace("/playlists", "")
    # /channel/UCxxx
    m = re.search(r"/channel/(UC[\w-]{22})", url)
    if m:
        return m.group(1)
    # /@handle
    m = re.search(r"/@([\w.-]+)", url)
    if m:
        return f"@{m.group(1)}"
    # /c/name
    m = re.search(r"/c/([\w.-]+)", url)
    if m:
        return f"c/{m.group(1)}"
    return url.split("/")[-1]


@channels_app.command("add")
def channels_add(
    url: str = typer.Argument(..., help="YouTube 频道 URL，如 https://www.youtube.com/@allin"),
    name: str = typer.Option("", "--name", help="频道别名"),
) -> None:
    """添加关注的 YouTube 频道。"""
    from podcast_research.db.channel_repository import add_channel
    from podcast_research.db.session import get_session, init_db

    channel_id = _parse_channel_id(url)
    init_db()
    session = get_session()
    try:
        cid = add_channel(session, youtube_channel_id=channel_id, url=url, name=name)
        session.commit()
    finally:
        session.close()

    console.print(f"[green]频道已添加: {name or channel_id}[/green]")
    console.print(f"  Channel ID: {channel_id}")
    console.print(f"  DB ID: {cid}")


@channels_app.command("list")
def channels_list(
    tag: str = typer.Option(None, "--tag", help="按标签过滤"),
    priority: str = typer.Option(None, "--priority", help="按优先级过滤: core / secondary / archive"),
) -> None:
    """列出已关注的频道。"""
    from podcast_research.db.channel_repository import list_channels
    from podcast_research.db.session import get_session, init_db

    init_db()
    session = get_session()
    try:
        rows = list_channels(session, tag=tag, priority=priority)
    finally:
        session.close()

    if not rows:
        filter_desc = ""
        if tag:
            filter_desc += f" (tag={tag})"
        if priority:
            filter_desc += f" (priority={priority})"
        console.print(f"[yellow]未找到匹配的频道{filter_desc}。[/yellow]")
        return

    title = "已关注频道"
    if tag:
        title += f" [tag={tag}]"
    if priority:
        title += f" [priority={priority}]"

    table = Table(title=title, show_lines=False)
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("名称")
    table.add_column("Priority", style="magenta")
    table.add_column("Tags", style="green")
    table.add_column("视频数", justify="right")
    table.add_column("最近刷新", style="dim")

    for r in rows:
        table.add_row(
            str(r["id"]),
            r["name"],
            r["priority"],
            ", ".join(r["tags"]) if r["tags"] else "-",
            str(r["video_count"]),
            _fmt_dt(r["last_refreshed_at"]) if r["last_refreshed_at"] else "-",
        )

    console.print(table)


@channels_app.command("refresh")
def channels_refresh(
    channel_id: int = typer.Argument(..., help="频道 DB ID"),
    limit: int = typer.Option(20, "--limit", help="最多获取视频数"),
) -> None:
    """刷新频道视频列表。"""
    from datetime import datetime

    from podcast_research.adapters.channel_video_adapter import ChannelVideoAdapter
    from podcast_research.db.channel_repository import get_channel, upsert_videos
    from podcast_research.db.session import get_session, init_db

    init_db()
    session = get_session()
    try:
        ch = get_channel(session, channel_id)
        if not ch:
            console.print(f"[red]频道 ID={channel_id} 不存在[/red]")
            raise typer.Exit(code=1)

        console.print(f"刷新频道: {ch['name']} ({ch['url']})")

        adapter = ChannelVideoAdapter()
        try:
            items = adapter.fetch_channel_videos(ch["url"], limit=limit)
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=1)

        videos = [
            {
                "video_id": v.video_id,
                "title": v.title,
                "url": v.url,
                "published_at": v.published_at,
                "duration_seconds": v.duration_seconds,
            }
            for v in items
        ]

        added = upsert_videos(session, channel_id, videos)

        # 更新最后刷新时间
        from podcast_research.db.models import Channel
        ch_obj = session.query(Channel).filter_by(id=channel_id).first()
        if ch_obj:
            ch_obj.last_refreshed_at = datetime.now()

        session.commit()
    finally:
        session.close()

    console.print(f"[green]刷新完成: 获取 {len(items)} 个视频，新增 {added} 个[/green]")


@channels_app.command("videos")
def channels_videos(
    channel_id: int = typer.Argument(..., help="频道 DB ID"),
    limit: int = typer.Option(50, "--limit", help="最多返回数量"),
    status: str = typer.Option(None, "--status", help="按状态过滤: new / analyzed / skipped"),
) -> None:
    """列出频道视频。"""
    from podcast_research.db.channel_repository import get_channel, list_channel_videos
    from podcast_research.db.session import get_session, init_db

    init_db()
    session = get_session()
    try:
        ch = get_channel(session, channel_id)
        if not ch:
            console.print(f"[red]频道 ID={channel_id} 不存在[/red]")
            raise typer.Exit(code=1)

        rows = list_channel_videos(session, channel_id, limit=limit, status=status)
    finally:
        session.close()

    if not rows:
        console.print(f"[yellow]频道 '{ch['name']}' 暂无视频。使用 channels refresh {channel_id} 获取。[/yellow]")
        return

    status_filter = f" (状态: {status})" if status else ""
    table = Table(title=f"频道 '{ch['name']}' 视频列表{status_filter}", show_lines=False)
    table.add_column("video_id", style="cyan", max_width=15)
    table.add_column("标题", max_width=45)
    table.add_column("发布", style="dim", max_width=10)
    table.add_column("时长", justify="right")
    table.add_column("状态")

    for r in rows:
        mins = r["duration_seconds"] // 60 if r["duration_seconds"] else 0
        dur_str = f"{mins}m"
        status_label = {"new": "[新]", "analyzed": "[已分析]", "skipped": "[跳过]"}.get(r["status"], r["status"])
        table.add_row(
            r["video_id"],
            r["title"][:45],
            r["published_at"][:10] if r["published_at"] else "-",
            dur_str,
            status_label,
        )

    console.print(table)


@channels_app.command("tag")
def channels_tag(
    channel_id: int = typer.Argument(..., help="频道 DB ID"),
    add: str = typer.Option(None, "--add", help="追加标签，逗号分隔"),
    remove: str = typer.Option(None, "--remove", help="移除标签，逗号分隔"),
    set_tags: str = typer.Option(None, "--set", help="覆盖全部标签，逗号分隔"),
) -> None:
    """管理频道标签。"""
    from podcast_research.db.channel_repository import update_channel_tags, get_channel
    from podcast_research.db.session import get_session, init_db

    if not add and not remove and not set_tags:
        console.print("[yellow]请指定 --add、--remove 或 --set 操作。[/yellow]")
        raise typer.Exit(code=1)

    init_db()
    session = get_session()
    try:
        ch = get_channel(session, channel_id)
        if not ch:
            console.print(f"[red]频道 ID={channel_id} 不存在[/red]")
            raise typer.Exit(code=1)

        op_desc = []
        add_list = [t.strip() for t in add.split(",") if t.strip()] if add else None
        remove_list = [t.strip() for t in remove.split(",") if t.strip()] if remove else None
        set_list = [t.strip() for t in set_tags.split(",") if t.strip()] if set_tags else None

        ok = update_channel_tags(
            session,
            channel_id,
            add=add_list,
            remove=remove_list,
            set_tags=set_list,
        )
        session.commit()

        ch = get_channel(session, channel_id)
        new_tags = ch["tags"]
    finally:
        session.close()

    if ok:
        console.print(f"[green]标签已更新: {ch['name']}[/green]")
        console.print(f"  Tags: {', '.join(new_tags) if new_tags else '(无)'}")
    else:
        console.print("[red]更新失败[/red]")


@channels_app.command("seed-tech-ai")
def channels_seed_tech_ai() -> None:
    """播种默认 Tech/AI 频道包（4 个核心频道）。幂等+自愈，重复执行不会重复添加。"""
    from podcast_research.db.channel_repository import seed_default_channels
    from podcast_research.db.session import get_session, init_db

    init_db()
    session = get_session()
    try:
        result = seed_default_channels(session, channel_pack="tech_ai")
        session.commit()
        # 重新加载以显示结果
        from podcast_research.db.channel_repository import list_channels
        rows = list_channels(session)
    finally:
        session.close()

    console.print(f"[green]Tech/AI 默认频道包播种完成[/green]")
    console.print(f"  新增: {result['added']}")
    console.print(f"  更新(补齐配置): {result.get('updated', 0)}")
    console.print(f"  跳过(已配置): {result['skipped']}")
    if result["errors"]:
        for e in result["errors"]:
            console.print(f"  [red]错误: {e}[/red]")

    if rows:
        table = Table(title="当前频道清单", show_lines=False)
        table.add_column("ID", style="cyan", justify="right")
        table.add_column("名称")
        table.add_column("Priority", style="magenta")
        table.add_column("Tags", style="green")

        for r in rows:
            table.add_row(
                str(r["id"]),
                r["name"],
                r["priority"],
                ", ".join(r["tags"]) if r["tags"] else "-",
            )

        console.print(table)


@channels_app.command("analyze-video")
def channels_analyze_video(
    video_id: str = typer.Option(..., "--video-id", help="YouTube video ID"),
    focus: str = typer.Option(None, "--focus", help="关注点，逗号分隔"),
    depth: str = typer.Option("standard", "--depth", help="分析深度: standard / deep"),
    no_mock: bool = typer.Option(None, "--no-mock", help="使用真实 LLM"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只检查不分析"),
) -> None:
    """分析频道中的指定视频。P2-A2.1: 自动从 channels 表补齐频道/视频元数据。"""
    from podcast_research.adapters.youtube_transcript import YouTubeTranscriptAdapter
    from podcast_research.analysis.pipeline import analyze_from_transcript
    from podcast_research.config import TRANSCRIPT_CACHE_DIR, ensure_dirs
    from podcast_research.db.channel_repository import (
        get_channel_video_by_video_id,
        get_video,
        mark_video_status,
    )
    from podcast_research.db.session import get_session, init_db

    ensure_dirs()

    if no_mock:
        provider = "openai-compatible"
    else:
        provider = "mock"

    # P2-A2.1: 查询频道元数据（channel + channel_video 联表）
    init_db()
    session = get_session()
    chan_meta = get_channel_video_by_video_id(session, video_id)
    vrec = get_video(session, video_id)
    session.close()

    # focus 优先级：--focus 显式参数 > 频道 default_focus > None
    if focus:
        focus_areas = [f.strip() for f in focus.split(",") if f.strip()]
    elif chan_meta and chan_meta.get("channel_default_focus"):
        focus_areas = [f.strip() for f in chan_meta["channel_default_focus"].split(",") if f.strip()]
    else:
        focus_areas = None

    # source_info_override：频道/视频元数据覆盖
    source_info_override = None
    if chan_meta:
        source_info_override = {
            "channel_name": chan_meta["channel_name"],
            "channel_url": chan_meta["channel_url"],
            "channel_tags": chan_meta["channel_tags"],
            "channel_default_focus": chan_meta["channel_default_focus"],
            "video_title": chan_meta["video_title"],
            "video_url": chan_meta["video_url"],
            "published_at": chan_meta["published_at"],
        }

    if vrec and vrec["status"] == "analyzed" and not dry_run:
        console.print(f"[yellow]视频 {video_id} 已分析过（报告 #{vrec['report_id']}），跳过。[/yellow]")
        console.print("  如需重新分析，请使用 --force 或其他方式。")
        return

    if dry_run:
        chan_label = chan_meta["channel_name"] if chan_meta else "?"
        title_label = chan_meta["video_title"] if chan_meta else "?"
        console.print(f"[dim][DRY-RUN] 将分析视频: {video_id}[/dim]")
        console.print(f"  频道: {chan_label}")
        console.print(f"  标题: {title_label}")
        console.print(f"  Provider: {provider}")
        console.print(f"  Focus: {focus_areas or '默认'}")
        console.print(f"  Depth: {depth}")
        return

    chan_label = f" ({chan_meta['channel_name']})" if chan_meta else ""
    console.print(Panel(f"分析频道视频: {video_id}{chan_label}\nLLM provider: {provider}", title="频道视频分析"))

    try:
        adapter = YouTubeTranscriptAdapter(cache_dir=TRANSCRIPT_CACHE_DIR)
        transcript = adapter.fetch(url=f"https://www.youtube.com/watch?v={video_id}")
        console.print(f"  字幕获取成功: {transcript.video_id} (语言: {transcript.language}, 段数: {len(transcript.segments)})")
    except Exception as e:
        console.print(f"[red]字幕获取失败: {e}[/red]")
        raise typer.Exit(code=1)

    try:
        result = analyze_from_transcript(
            transcript,
            provider_name=provider,
            focus_areas=focus_areas,
            analysis_depth=depth,
            source_info_override=source_info_override,
        )
    except Exception as e:
        err_msg = str(e)
        if "LLM" in err_msg or "API" in err_msg or "token" in err_msg.lower():
            console.print(f"[red]LLM 分析失败: {e}[/red]")
            console.print("  提示: 检查 .env 中的 LLM 配置，或使用 --mock 模式")
        else:
            console.print(f"[red]分析失败: {e}[/red]")
        raise typer.Exit(code=1)

    # 标记已分析
    init_db()
    session = get_session()
    try:
        mark_video_status(session, video_id, "analyzed", report_id=result.get("report_id"))
        session.commit()
    finally:
        session.close()

    console.print("[green]分析完成[/green]")
    if result.get("focus_areas"):
        console.print(f"  关注点: {', '.join(result['focus_areas'])}")
    console.print(f"  观点数: {result['view_count']}")
    console.print(f"  实体数: {result['entity_count']}")
    console.print(f"  报告: {result['report_path']}")


# ---------------------------------------------------------------------------
# eval 子命令 (P2-A2)
# ---------------------------------------------------------------------------


@eval_app.command("reports")
def eval_reports(
    channel: str = typer.Option(None, "--channel", help="按频道名过滤，如 'BG2Pod'"),
) -> None:
    """评估所有报告，终端表格展示统计。"""
    from podcast_research.evaluation import eval_all_reports

    results = eval_all_reports(channel_filter=channel)
    if not results:
        console.print("[yellow]暂无报告可供评估。[/yellow]")
        return

    title = f"Prompt v2 跨频道评估 ({len(results)} 份报告)"
    if channel:
        title += f" [channel={channel}]"

    table = Table(title=title, show_lines=False)
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("频道", max_width=15)
    table.add_column("Video", max_width=15)
    table.add_column("Seg", justify="right")
    table.add_column("Views", justify="right")
    table.add_column("Insights", justify="right")
    table.add_column("Entities", justify="right")
    table.add_column("Generic", justify="right")
    table.add_column("UnkSpk", justify="right")
    table.add_column("Status")

    for r in results:
        status_style = {"ok": "green", "empty": "yellow", "generic_targets": "magenta"}.get(
            r["report_status"], "white"
        )
        table.add_row(
            str(r["report_id"]),
            r["channel_name"][:15] or "-",
            r["video_id"][:15] or "-",
            str(r["transcript_segment_count"]),
            str(r["investment_view_count"]),
            str(r["tech_insight_count"]),
            str(r["entity_count"]),
            str(r["generic_target_count"]),
            str(r["unknown_speaker_count"]),
            f"[{status_style}]{r['report_status']}[/{status_style}]",
        )

    console.print(table)

    # Summary line
    total_views = sum(r["investment_view_count"] for r in results)
    total_generic = sum(r["generic_target_count"] for r in results)
    console.print(f"\n[dim]总计: {len(results)} 份报告, {total_views} 条观点, {total_generic} 个泛化标的[/dim]")


@eval_app.command("export")
def eval_export(
    output: Path = typer.Option(..., "--output", help="CSV 输出路径，如 data/eval/prompt_v2_eval.csv"),
    channel: str = typer.Option(None, "--channel", help="按频道名过滤"),
) -> None:
    """导出评估结果为 CSV。"""
    from podcast_research.evaluation import eval_all_reports, export_csv

    results = eval_all_reports(channel_filter=channel)
    path = export_csv(results, output)
    console.print(f"[green]CSV 已导出: {path}[/green]")
    console.print(f"  共 {len(results)} 条记录")


@eval_app.command("summary")
def eval_summary(
    output: Path = typer.Option(..., "--output", help="Markdown 输出路径，如 data/eval/prompt_v2_summary.md"),
    channel: str = typer.Option(None, "--channel", help="按频道名过滤"),
) -> None:
    """生成跨频道评估 Markdown 总结。"""
    from podcast_research.evaluation import eval_all_reports, generate_summary_md

    results = eval_all_reports(channel_filter=channel)
    md = generate_summary_md(results)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(md, encoding="utf-8")
    console.print(f"[green]总结已导出: {output}[/green]")
    console.print(f"  共 {len(results)} 条报告")


# ---------------------------------------------------------------------------
# serve 命令
# ---------------------------------------------------------------------------


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="绑定地址"),
    port: int = typer.Option(8000, "--port", help="监听端口"),
    reload: bool = typer.Option(False, "--reload", help="开发模式热重载"),
) -> None:
    """启动本地只读 API 服务。"""
    import uvicorn

    console.print(f"[green]启动本地 API 服务: http://{host}:{port}[/green]")
    console.print(f"  API 文档: http://{host}:{port}/docs")
    console.print(f"  健康检查: http://{host}:{port}/api/health")
    console.print("[dim]按 Ctrl+C 停止服务[/dim]")

    uvicorn.run(
        "podcast_research.api.app:create_app",
        host=host,
        port=port,
        reload=reload,
        factory=True,
    )
