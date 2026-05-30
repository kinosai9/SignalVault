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

# --- obsidian 子命令组 ---
obsidian_app = typer.Typer(help="Obsidian Vault 导出")
app.add_typer(obsidian_app, name="obsidian")

# --- llm-wiki 子命令组 ---
llm_wiki_app = typer.Typer(help="LLM-WIKI 动态维护（patch review 模式）")
app.add_typer(llm_wiki_app, name="llm-wiki")


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
    # P2-B chunking options
    chunked: bool = typer.Option(None, "--chunked", help="强制启用长视频分块分析"),
    no_chunking: bool = typer.Option(None, "--no-chunking", help="禁用分块分析（长视频时 WARNING）"),
    chunk_size: int = typer.Option(30000, "--chunk-size", help="每块字符上限"),
    chunk_overlap: int = typer.Option(2000, "--chunk-overlap", help="块间重叠字符数"),
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

    # P2-B: chunking config
    chunking_config = {}
    if chunked:
        chunking_config["enabled"] = True
    elif no_chunking:
        chunking_config["enabled"] = False
    # else: None → auto-detect
    chunking_config["char_limit"] = chunk_size
    chunking_config["overlap_chars"] = chunk_overlap

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
                chunking_config=chunking_config,
            )
        except Exception as e:
            err_msg = str(e)
            if "LLM" in err_msg or "API" in err_msg or "token" in err_msg.lower():
                console.print(f"[red]LLM 分析失败: {e}[/red]")
                console.print("  提示: 检查 .env 中的 LLM 配置，或尝试 --mock 模式确认链路正常")
                console.print("  长视频可能超出 token 上限，可尝试 --chunked 或更短的视频")
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
                chunking_config=chunking_config,
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
    # P2-B chunking options
    chunked: bool = typer.Option(None, "--chunked", help="强制启用长视频分块分析"),
    no_chunking: bool = typer.Option(None, "--no-chunking", help="禁用分块分析"),
    chunk_size: int = typer.Option(30000, "--chunk-size", help="每块字符上限"),
    chunk_overlap: int = typer.Option(2000, "--chunk-overlap", help="块间重叠字符数"),
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

    # P2-B: chunking config
    chunking_config = {}
    if chunked:
        chunking_config["enabled"] = True
    elif no_chunking:
        chunking_config["enabled"] = False
    chunking_config["char_limit"] = chunk_size
    chunking_config["overlap_chars"] = chunk_overlap

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
            chunking_config=chunking_config,
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
# obsidian 子命令 (P2-C)
# ---------------------------------------------------------------------------


@obsidian_app.command("export")
def obsidian_export(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    source: str = typer.Option(None, "--source", help="按来源过滤: youtube (v1 仅支持 youtube)"),
    prompt_version: str = typer.Option(None, "--prompt-version", help="按 prompt 版本过滤"),
    report_id: int = typer.Option(None, "--report-id", help="仅导出指定报告 ID"),
    limit: int = typer.Option(None, "--limit", help="最多导出报告数"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只预览不写入"),
    overwrite: bool = typer.Option(False, "--overwrite", help="覆盖已存在文件"),
    channel: str = typer.Option(None, "--channel", help="按频道名过滤（大小写不敏感，部分匹配）"),
    only_with_channel: bool = typer.Option(False, "--only-with-channel", help="跳过无频道信息的报告"),
) -> None:
    """导出报告到 Obsidian Vault。P2-C v1: 仅导出 YouTube 报告和频道卡片。"""
    from pathlib import Path
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.exporters.obsidian import export_to_vault

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径或在 .env 中配置 OBSIDIAN_VAULT_PATH[/red]")
        raise typer.Exit(code=1)

    vault_path = Path(vault_path_str)
    if not vault_path.exists():
        console.print(f"[red]Vault 路径不存在: {vault_path}[/red]")
        raise typer.Exit(code=1)

    if dry_run:
        console.print(f"[dim][DRY-RUN] Vault: {vault_path}[/dim]")

    result = export_to_vault(
        vault_path=vault_path,
        source_type=source or "youtube",
        prompt_version=prompt_version,
        report_id=report_id,
        limit=limit,
        overwrite=overwrite,
        dry_run=dry_run,
        channel_filter=channel,
        only_with_channel=only_with_channel,
    )

    if dry_run:
        exported = result["exported"]
        to_export = [r for r in exported if r.get("action") != "skip"]
        to_skip = [r for r in exported if r.get("action") == "skip"]
        console.print(
            f"\n[dim][DRY-RUN] 将导出 {len(to_export)} 份报告，"
            f"跳过 {len(to_skip)} 份（不写入）[/dim]"
        )
        table = Table(title="Preview: 待导出报告")
        table.add_column("ID", style="cyan", justify="right")
        table.add_column("Channel")
        table.add_column("Title")
        table.add_column("Video ID")
        table.add_column("Prompt Ver")
        table.add_column("Action", style="bold")
        table.add_column("Reason", style="dim")
        for r in exported[:30]:
            action = r.get("action", "export")
            reason = r.get("reason", "")
            action_style = "green" if action == "export" else "yellow"
            table.add_row(
                str(r["report_id"]),
                r.get("channel", "-")[:20] or "[dim]UnknownChannel[/dim]",
                r.get("title", "-")[:40],
                r.get("video_id", "-") or "-",
                r.get("prompt_version", "-")[:12],
                f"[{action_style}]{action}[/{action_style}]",
                reason,
            )
        console.print(table)
        return

    console.print(f"[green]Obsidian Export 完成[/green]")
    console.print(f"  Vault: {vault_path}")
    console.print(f"  Reports exported: {result['created']}")
    console.print(f"  Reports skipped: {result['skipped']}")
    console.print(f"  Channel cards: {result['channel_cards']}")


@obsidian_app.command("cleanup-unknown")
def obsidian_cleanup_unknown(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只检测不修改"),
    apply: bool = typer.Option(False, "--apply", help="执行迁移（旧文件移到 backup）"),
    overwrite: bool = typer.Option(False, "--overwrite", help="覆盖已存在的目标文件"),
) -> None:
    """检测和清理 UnknownChannel 导出文件。

    扫描 01_Reports/*UnknownChannel*.md 和 05_Channels/UnknownChannel.md，
    通过 video_id 查询 channel_videos + channels 尝试补齐频道信息。
    apply 模式将旧文件移到 99_System/UnknownChannel_Backup/，不直接删除。
    """
    from pathlib import Path
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.exporters.obsidian import cleanup_unknown_channel_files

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径或在 .env 中配置 OBSIDIAN_VAULT_PATH[/red]")
        raise typer.Exit(code=1)

    vault_path = Path(vault_path_str)
    if not vault_path.exists():
        console.print(f"[red]Vault 路径不存在: {vault_path}[/red]")
        raise typer.Exit(code=1)

    result = cleanup_unknown_channel_files(
        vault_path=vault_path,
        dry_run=dry_run,
        apply=apply,
        overwrite=overwrite,
    )

    results = result["results"]

    if dry_run:
        console.print(f"[dim][DRY-RUN] Vault: {vault_path}[/dim]")
        console.print(f"[dim]发现 {len(results)} 个 UnknownChannel 文件[/dim]")

        table = Table(title="UnknownChannel Cleanup Preview")
        table.add_column("File", style="cyan", max_width=35)
        table.add_column("Video ID")
        table.add_column("Channel")
        table.add_column("Suggested Name", max_width=35)
        table.add_column("Action", style="bold")
        table.add_column("Reason", style="dim")

        for r in results:
            fname = r["file"].name
            action = r["action"]
            action_style = "green" if action == "rename_or_reexport" else "yellow"
            table.add_row(
                fname[:35],
                r.get("video_id", "-") or "-",
                r.get("channel_name", "-") or "-",
                r.get("suggested_filename", "-")[:35] or "-",
                f"[{action_style}]{action}[/{action_style}]",
                r.get("reason", ""),
            )
        console.print(table)
        return

    if apply:
        console.print(f"[green]UnknownChannel Cleanup 完成[/green]")
        console.print(f"  Vault: {vault_path}")
        console.print(f"  Renamed/Re-exported: {result['renamed']}")
        console.print(f"  Moved to backup: {result['moved']}")
        console.print(f"  Skipped: {result['skipped']}")
    else:
        # No --dry-run and no --apply: show results as info only
        console.print(f"[yellow]提示：使用 --apply 执行迁移，--dry-run 预览[/yellow]")
        console.print(f"  发现 {len(results)} 个 UnknownChannel 文件")
        for r in results:
            status = "✓" if r["action"] == "rename_or_reexport" else "?"
            console.print(f"  {status} {r['file'].name} → {r.get('channel_name', '?')} ({r['action']})")


@obsidian_app.command("sync-channel-cards")
def obsidian_sync_channel_cards(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只预览不写入"),
    channel: str = typer.Option(None, "--channel", help="只同步指定频道（大小写不敏感，部分匹配）"),
    overwrite: bool = typer.Option(False, "--overwrite", help="覆盖已有频道卡片"),
) -> None:
    """同步频道卡片。扫描 01_Reports/ 的 frontmatter，创建或更新 05_Channels/ 频道卡。"""
    from pathlib import Path
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.exporters.obsidian import sync_channel_cards

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径或在 .env 中配置 OBSIDIAN_VAULT_PATH[/red]")
        raise typer.Exit(code=1)

    vault_path = Path(vault_path_str)
    if not vault_path.exists():
        console.print(f"[red]Vault 路径不存在: {vault_path}[/red]")
        raise typer.Exit(code=1)

    result = sync_channel_cards(
        vault_path=vault_path,
        dry_run=dry_run,
        channel_filter=channel,
        overwrite=overwrite,
    )

    if dry_run:
        console.print(f"[dim][DRY-RUN] Vault: {vault_path}[/dim]")
        console.print(f"[dim]发现 {len(result['results'])} 个频道[/dim]")

        table = Table(title="Channel Card Sync Preview")
        table.add_column("Channel", style="cyan")
        table.add_column("Reports", justify="right")
        table.add_column("Card Exists")
        table.add_column("Action", style="bold")
        table.add_column("Reason", style="dim")

        for r in result["results"]:
            action = r["action"]
            action_style = "green" if action == "create" else ("yellow" if action == "update" else "dim")
            table.add_row(
                r["channel"][:25],
                str(r["reports_count"]),
                "Yes" if r["card_exists"] else "No",
                f"[{action_style}]{action}[/{action_style}]",
                r["reason"],
            )
        console.print(table)
        return

    console.print(f"[green]Channel Card Sync 完成[/green]")
    console.print(f"  Vault: {vault_path}")
    console.print(f"  Created: {result['created']}")
    console.print(f"  Updated: {result['updated']}")
    console.print(f"  Skipped: {result['skipped']}")


@obsidian_app.command("generate-cards")
def obsidian_generate_cards(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只预览不写入"),
    topics_only: bool = typer.Option(False, "--topics-only", help="只生成 Topic Cards"),
    companies_only: bool = typer.Option(False, "--companies-only", help="只生成 Company Cards"),
    channel: str = typer.Option(None, "--channel", help="只处理指定频道的报告（大小写不敏感，部分匹配）"),
    overwrite: bool = typer.Option(False, "--overwrite", help="覆盖已有卡片"),
    limit: int = typer.Option(None, "--limit", help="最多处理 N 份报告"),
) -> None:
    """生成 Topic / Company Cards。扫描 01_Reports/ 提取主题和公司实体，创建或更新 02_Topics/ 和 03_Companies/ 卡片。"""
    from pathlib import Path
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.exporters.obsidian import generate_cards

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径或在 .env 中配置 OBSIDIAN_VAULT_PATH[/red]")
        raise typer.Exit(code=1)

    vault_path = Path(vault_path_str)
    if not vault_path.exists():
        console.print(f"[red]Vault 路径不存在: {vault_path}[/red]")
        raise typer.Exit(code=1)

    if topics_only and companies_only:
        console.print("[red]--topics-only 和 --companies-only 不能同时使用[/red]")
        raise typer.Exit(code=1)

    result = generate_cards(
        vault_path=vault_path,
        dry_run=dry_run,
        topics_only=topics_only,
        companies_only=companies_only,
        channel_filter=channel,
        overwrite=overwrite,
        limit=limit,
    )

    if dry_run:
        console.print(f"[dim][DRY-RUN] Vault: {vault_path}[/dim]")
        console.print(f"[dim]扫描到 {len(result['results'])} 个卡片[/dim]")

        table = Table(title="Card Generation Preview")
        table.add_column("Type", style="cyan")
        table.add_column("Name")
        table.add_column("Reports", justify="right")
        table.add_column("Card Exists")
        table.add_column("Action", style="bold")
        table.add_column("Reason", style="dim")

        for r in result["results"]:
            action = r["action"]
            action_style = "green" if action == "create" else ("yellow" if action == "update" else "dim")
            table.add_row(
                r["type"],
                r["name"][:25],
                str(r["reports_count"]),
                "Yes" if r["card_exists"] else "No",
                f"[{action_style}]{action}[/{action_style}]",
                r["reason"],
            )
        console.print(table)
        return

    console.print(f"[green]Card Generation 完成[/green]")
    console.print(f"  Vault: {vault_path}")
    console.print(f"  Topics created: {result['topics_created']}")
    console.print(f"  Topics updated: {result['topics_updated']}")
    console.print(f"  Companies created: {result['companies_created']}")
    console.print(f"  Companies updated: {result['companies_updated']}")
    console.print(f"  Skipped: {result['skipped']}")


@obsidian_app.command("cleanup-cards")
def obsidian_cleanup_cards(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只预览不修改"),
    apply: bool = typer.Option(False, "--apply", help="执行清理（迁移 + 合并）"),
    topics_only: bool = typer.Option(False, "--topics-only", help="只清理 Topic Cards"),
    companies_only: bool = typer.Option(False, "--companies-only", help="只清理 Company Cards"),
    overwrite: bool = typer.Option(False, "--overwrite", help="覆盖已有目标卡片"),
) -> None:
    """清理 Topic / Company Cards 分类。检测非公司实体并迁移到 Topic，合并同义 Topic 别名。"""
    from pathlib import Path
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.exporters.obsidian import cleanup_cards

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径或在 .env 中配置 OBSIDIAN_VAULT_PATH[/red]")
        raise typer.Exit(code=1)

    vault_path = Path(vault_path_str)
    if not vault_path.exists():
        console.print(f"[red]Vault 路径不存在: {vault_path}[/red]")
        raise typer.Exit(code=1)

    if topics_only and companies_only:
        console.print("[red]--topics-only 和 --companies-only 不能同时使用[/red]")
        raise typer.Exit(code=1)

    result = cleanup_cards(
        vault_path=vault_path,
        dry_run=dry_run,
        apply=apply,
        topics_only=topics_only,
        companies_only=companies_only,
        overwrite=overwrite,
    )

    if dry_run:
        console.print(f"[dim][DRY-RUN] Vault: {vault_path}[/dim]")
        console.print(f"[dim]扫描到 {len(result['results'])} 个需要处理的卡片[/dim]")

        table = Table(title="Card Cleanup Preview")
        table.add_column("Type", style="cyan")
        table.add_column("Name", max_width=25)
        table.add_column("Suggested", style="yellow", max_width=20)
        table.add_column("Action", style="bold")
        table.add_column("Reason", style="dim")

        for r in result["results"]:
            action = r["action"]
            if action == "keep":
                action_style = "dim"
            elif action in ("migrate_to_topic", "merge_topic"):
                action_style = "green"
            else:
                action_style = "yellow"

            suggested = r.get("suggested_name", "")
            if suggested == r["name"]:
                suggested = "-"

            table.add_row(
                r["type"],
                r["name"][:25],
                suggested[:20],
                f"[{action_style}]{action}[/{action_style}]",
                r.get("reason", ""),
            )
        console.print(table)
        console.print(f"\n[dim]Summary: keep={result['kept']}, migrate={len([r for r in result['results'] if r['action'] == 'migrate_to_topic'])}, merge={len([r for r in result['results'] if r['action'] == 'merge_topic'])}, manual_review={result['manual_review']}[/dim]")
        return

    if apply:
        console.print(f"[green]Card Cleanup 完成[/green]")
        console.print(f"  Vault: {vault_path}")
        console.print(f"  Migrated (company → topic): {result['migrated']}")
        console.print(f"  Merged (topic aliases): {result['merged']}")
        console.print(f"  Kept as company: {result['kept']}")
        console.print(f"  Manual review needed: {result['manual_review']}")
    else:
        console.print(f"[yellow]提示：使用 --apply 执行清理，--dry-run 预览[/yellow]")
        console.print(f"  发现 {len(result['results'])} 个需要处理的卡片")
        for r in result["results"][:10]:
            symbol = "✓" if r["action"] == "keep" else ("→" if r["action"] in ("migrate_to_topic", "merge_topic") else "?")
            suggested = r.get("suggested_name", "")
            extra = f" → {suggested}" if suggested != r["name"] and suggested else ""
            console.print(f"  {symbol} [{r['type']}] {r['name']}{extra} ({r['action']})")
        if len(result["results"]) > 10:
            console.print(f"  ... and {len(result['results']) - 10} more")


@obsidian_app.command("consolidate-topics")
def obsidian_consolidate_topics(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只预览不修改"),
    apply: bool = typer.Option(False, "--apply", help="执行 topic taxonomy 整合"),
    core_only: bool = typer.Option(False, "--core-only", help="只处理 core topics"),
    merge_aliases: bool = typer.Option(True, "--merge-aliases/--no-merge-aliases", help="合并同义 topic 别名"),
    mark_status: bool = typer.Option(True, "--mark-status/--no-mark-status", help="标记 topic status"),
    overwrite: bool = typer.Option(False, "--overwrite", help="覆盖已有文件"),
) -> None:
    """整合 Topic taxonomy：合并别名、标记 status、生成 taxonomy index。"""
    from pathlib import Path
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.exporters.obsidian import consolidate_topics

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径或在 .env 中配置 OBSIDIAN_VAULT_PATH[/red]")
        raise typer.Exit(code=1)

    vault_path = Path(vault_path_str)
    if not vault_path.exists():
        console.print(f"[red]Vault 路径不存在: {vault_path}[/red]")
        raise typer.Exit(code=1)

    result = consolidate_topics(
        vault_path=vault_path,
        dry_run=dry_run,
        apply=apply,
        core_only=core_only,
        merge_aliases=merge_aliases,
        mark_status=mark_status,
        overwrite=overwrite,
    )

    if dry_run:
        console.print(f"[dim][DRY-RUN] Vault: {vault_path}[/dim]")
        console.print(f"[dim]扫描到 {len(result['results'])} 个 topic cards[/dim]")

        table = Table(title="Topic Taxonomy Consolidation Preview")
        table.add_column("Topic", style="cyan", max_width=30)
        table.add_column("Reports", justify="right")
        table.add_column("Status", style="yellow")
        table.add_column("Canonical", style="yellow", max_width=20)
        table.add_column("Action", style="bold")
        table.add_column("Reason", style="dim")

        for r in result["results"]:
            action = r["action"]
            if action == "merge_topic":
                action_style = "green"
            elif action == "mark_core":
                action_style = "bold green"
            elif action in ("mark_emerging", "mark_long_tail"):
                action_style = "yellow"
            elif action == "manual_review":
                action_style = "red"
            else:
                action_style = "dim"

            suggested = r.get("suggested_name", "")
            if suggested == r["name"] or not suggested:
                suggested = "-"

            table.add_row(
                r["name"][:30],
                str(r["report_count"]),
                r["status"],
                suggested[:20],
                f"[{action_style}]{action}[/{action_style}]",
                r.get("reason", ""),
            )
        console.print(table)
        console.print(
            f"\n[dim]Summary: "
            f"core={result['core_count']}, "
            f"emerging={result['emerging_count']}, "
            f"long_tail={result['long_tail_count']}, "
            f"manual_review={result['manual_review_count']}, "
            f"merged={result['merged_count']}[/dim]"
        )
        return

    if apply:
        console.print(f"[green]Topic Taxonomy Consolidation 完成[/green]")
        console.print(f"  Vault: {vault_path}")
        console.print(f"  Core topics: {result['core_count']}")
        console.print(f"  Emerging topics: {result['emerging_count']}")
        console.print(f"  Long-tail topics: {result['long_tail_count']}")
        console.print(f"  Manual review: {result['manual_review_count']}")
        console.print(f"  Merged (alias → canonical): {result['merged_count']}")
    else:
        console.print(f"[yellow]提示：使用 --apply 执行整合，--dry-run 预览[/yellow]")
        console.print(f"  发现 {len(result['results'])} 个 topic cards")
        for r in result["results"][:10]:
            status_symbol = {"core": "★", "emerging": "◐", "long_tail": "○", "manual_review": "?"}.get(r["status"], " ")
            action_symbol = "→" if r["action"] == "merge_topic" else "✓"
            suggested = r.get("suggested_name", "")
            extra = f" → {suggested}" if suggested != r["name"] and suggested else ""
            console.print(
                f"  {status_symbol} {action_symbol} {r['name']}{extra} "
                f"[{r['status']}] (reports: {r['report_count']})"
            )
        if len(result["results"]) > 10:
            console.print(f"  ... and {len(result['results']) - 10} more")


@obsidian_app.command("generate-claims-signals")
def obsidian_generate_claims_signals(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只预览不写入"),
    claims_only: bool = typer.Option(False, "--claims-only", help="只生成 Claim Cards"),
    signals_only: bool = typer.Option(False, "--signals-only", help="只生成 Signal Cards"),
    source: str = typer.Option("all", "--source", help="数据来源: reports / patches / all"),
    limit: int = typer.Option(50, "--limit", help="每种类型最多提取数量"),
    overwrite: bool = typer.Option(False, "--overwrite", help="覆盖已有卡片"),
) -> None:
    """从 Reports 和 applied Patches 中提取 Claim 和 Signal，生成卡片。

    写入 06_Claims/ 和 07_Signals/。Deterministic 规则提取，不调用 LLM。
    """
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.claim_signal.generator import generate_all

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径或在 .env 中配置 OBSIDIAN_VAULT_PATH[/red]")
        raise typer.Exit(code=1)

    vault_path = Path(vault_path_str)
    if not vault_path.exists():
        console.print(f"[red]Vault 路径不存在: {vault_path}[/red]")
        raise typer.Exit(code=1)

    if claims_only and signals_only:
        console.print("[red]--claims-only 和 --signals-only 不能同时使用[/red]")
        raise typer.Exit(code=1)

    if source not in ("reports", "patches", "all"):
        console.print("[red]--source 必须是 reports / patches / all[/red]")
        raise typer.Exit(code=1)

    if dry_run:
        console.print(f"[dim][DRY-RUN] Vault: {vault_path}[/dim]")

    result = generate_all(
        vault_path=vault_path,
        dry_run=dry_run,
        source=source,
        claims_only=claims_only,
        signals_only=signals_only,
        limit=limit,
        overwrite=overwrite,
    )

    if dry_run:
        table = Table(title="Claim / Signal Generation Preview")
        table.add_column("Type", style="cyan")
        table.add_column("Statement", max_width=50)
        table.add_column("Source", max_width=25)
        table.add_column("Action", style="bold")
        table.add_column("Reason", style="dim")

        for r in result.results:
            action_style = "green" if r.action == "create" else ("yellow" if r.action == "overwrite" else "dim")
            table.add_row(
                r.card_type,
                r.statement[:50],
                r.source[:25],
                f"[{action_style}]{r.action}[/{action_style}]",
                r.reason,
            )
        console.print(table)
        console.print(f"\n[dim]Claims: {result.claims_created} new, {result.claims_overwritten} overwrite, {result.claims_skipped} skip[/dim]")
        console.print(f"[dim]Signals: {result.signals_created} new, {result.signals_overwritten} overwrite, {result.signals_skipped} skip[/dim]")
        return

    console.print(f"[green]Claim / Signal Generation 完成[/green]")
    console.print(f"  Claims created: {result.claims_created}")
    console.print(f"  Claims skipped: {result.claims_skipped}")
    console.print(f"  Signals created: {result.signals_created}")
    console.print(f"  Signals skipped: {result.signals_skipped}")
    console.print(f"  Indexes: 99_System/Claim Index.md, Signal Index.md, Claim_Signal_Generation_Log.md")


# --- claims / signals 子命令组 ---
claims_app = typer.Typer(help="Claim 卡片管理")
app.add_typer(claims_app, name="claims")

signals_app = typer.Typer(help="Signal 卡片管理")
app.add_typer(signals_app, name="signals")


@claims_app.command("list")
def claims_list(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    status: str = typer.Option(None, "--status", help="按状态过滤: active / verified / challenged / outdated / archived"),
    limit: int = typer.Option(None, "--limit", help="最多返回数量"),
) -> None:
    """列出 06_Claims/ 中的 Claim 卡片。"""
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.claim_signal.review import list_claims

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径[/red]")
        raise typer.Exit(code=1)
    vault_path = Path(vault_path_str)
    if status and status not in {"active", "verified", "challenged", "outdated", "archived"}:
        console.print(f"[red]无效状态: {status}[/red]")
        raise typer.Exit(code=1)

    results = list_claims(vault_path, status=status, limit=limit)
    if not results:
        console.print("[yellow]No claims found.[/yellow]")
        return

    table = Table(title="Claims", show_lines=False)
    table.add_column("ID", style="cyan", max_width=45)
    table.add_column("Status")
    table.add_column("Statement", max_width=50)
    table.add_column("Source")
    table.add_column("Updated")
    for r in results:
        table.add_row(r.card_id[:45], r.status, r.statement[:50],
                       r.source_reports[0][:20] if r.source_reports else "-",
                       r.updated_at[:10] if r.updated_at else "-")
    console.print(table)


@claims_app.command("show")
def claims_show(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    claim_id: str = typer.Argument(..., help="Claim card ID（文件名 stem）"),
) -> None:
    """查看单个 Claim 卡片完整内容。"""
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.claim_signal.review import get_claim

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径[/red]")
        raise typer.Exit(code=1)
    vault_path = Path(vault_path_str)
    content = get_claim(vault_path, claim_id)
    if not content:
        console.print(f"[red]Claim 不存在: {claim_id}[/red]")
        raise typer.Exit(code=1)
    console.print(Panel(content[:3000], title=f"Claim: {claim_id}", border_style="green"))


@claims_app.command("update-status")
def claims_update_status(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    claim_id: str = typer.Argument(..., help="Claim card ID（文件名 stem）"),
    status: str = typer.Option(..., "--status", help="新状态: active / verified / challenged / outdated / archived"),
    note: str = typer.Option("", "--note", help="审阅备注"),
) -> None:
    """更新 Claim 卡片状态。追加 Review History，更新 Index，写 log。"""
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.claim_signal.review import update_claim_status

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径[/red]")
        raise typer.Exit(code=1)
    vault_path = Path(vault_path_str)

    ok = update_claim_status(vault_path, claim_id, status, note=note)
    if not ok:
        console.print(f"[red]更新失败：claim 不存在或状态非法。[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]Claim '{claim_id}' status updated to {status}[/green]")


@signals_app.command("list")
def signals_list(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    status: str = typer.Option(None, "--status", help="按状态过滤: open / watching / resolved / invalidated / archived"),
    limit: int = typer.Option(None, "--limit", help="最多返回数量"),
) -> None:
    """列出 07_Signals/ 中的 Signal 卡片。"""
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.claim_signal.review import list_signals

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径[/red]")
        raise typer.Exit(code=1)
    vault_path = Path(vault_path_str)
    if status and status not in {"open", "watching", "resolved", "invalidated", "archived"}:
        console.print(f"[red]无效状态: {status}[/red]")
        raise typer.Exit(code=1)

    results = list_signals(vault_path, status=status, limit=limit)
    if not results:
        console.print("[yellow]No signals found.[/yellow]")
        return

    table = Table(title="Signals", show_lines=False)
    table.add_column("ID", style="cyan", max_width=45)
    table.add_column("Status")
    table.add_column("Statement", max_width=50)
    table.add_column("Source")
    table.add_column("Updated")
    for r in results:
        table.add_row(r.card_id[:45], r.status, r.statement[:50],
                       r.source_reports[0][:20] if r.source_reports else "-",
                       r.updated_at[:10] if r.updated_at else "-")
    console.print(table)


@signals_app.command("show")
def signals_show(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    signal_id: str = typer.Argument(..., help="Signal card ID（文件名 stem）"),
) -> None:
    """查看单个 Signal 卡片完整内容。"""
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.claim_signal.review import get_signal

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径[/red]")
        raise typer.Exit(code=1)
    vault_path = Path(vault_path_str)
    content = get_signal(vault_path, signal_id)
    if not content:
        console.print(f"[red]Signal 不存在: {signal_id}[/red]")
        raise typer.Exit(code=1)
    console.print(Panel(content[:3000], title=f"Signal: {signal_id}", border_style="green"))


@signals_app.command("update-status")
def signals_update_status(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    signal_id: str = typer.Argument(..., help="Signal card ID（文件名 stem）"),
    status: str = typer.Option(..., "--status", help="新状态: open / watching / resolved / invalidated / archived"),
    note: str = typer.Option("", "--note", help="审阅备注"),
) -> None:
    """更新 Signal 卡片状态。追加 Updates，更新 Index，写 log。"""
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.claim_signal.review import update_signal_status

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径[/red]")
        raise typer.Exit(code=1)
    vault_path = Path(vault_path_str)

    ok = update_signal_status(vault_path, signal_id, status, note=note)
    if not ok:
        console.print(f"[red]更新失败：signal 不存在或状态非法。[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]Signal '{signal_id}' status updated to {status}[/green]")


@claims_app.command("update-meta")
def claims_update_meta(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    claim_id: str = typer.Argument(..., help="Claim card ID（文件名 stem）"),
    quality: str = typer.Option(None, "--quality", help="high / medium / low"),
    review_priority: str = typer.Option(None, "--review-priority", help="high / normal / low"),
    granularity: str = typer.Option(None, "--granularity", help="atomic / broad / duplicate / unclear"),
) -> None:
    """更新 Claim 卡片的 quality / review_priority / granularity metadata。"""
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.claim_signal.review import update_claim_meta

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径[/red]")
        raise typer.Exit(code=1)
    vault_path = Path(vault_path_str)

    if not any([quality, review_priority, granularity]):
        console.print("[red]请至少指定 --quality / --review-priority / --granularity 之一[/red]")
        raise typer.Exit(code=1)

    ok = update_claim_meta(vault_path, claim_id, quality=quality,
                           review_priority=review_priority, granularity=granularity)
    if not ok:
        console.print(f"[red]更新失败：claim 不存在或参数非法。[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]Claim '{claim_id}' metadata updated[/green]")


@signals_app.command("update-meta")
def signals_update_meta(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    signal_id: str = typer.Argument(..., help="Signal card ID（文件名 stem）"),
    quality: str = typer.Option(None, "--quality", help="high / medium / low"),
    review_priority: str = typer.Option(None, "--review-priority", help="high / normal / low"),
    signal_type: str = typer.Option(None, "--signal-type", help="competition / technology_bottleneck / regulation / adoption / business_model / pricing / infrastructure / market_structure / financial_metric / unknown"),
) -> None:
    """更新 Signal 卡片的 quality / review_priority / signal_type metadata。"""
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.claim_signal.review import update_signal_meta

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径[/red]")
        raise typer.Exit(code=1)
    vault_path = Path(vault_path_str)

    if not any([quality, review_priority, signal_type]):
        console.print("[red]请至少指定 --quality / --review-priority / --signal-type 之一[/red]")
        raise typer.Exit(code=1)

    ok = update_signal_meta(vault_path, signal_id, quality=quality,
                            review_priority=review_priority, signal_type=signal_type)
    if not ok:
        console.print(f"[red]更新失败：signal 不存在或参数非法。[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]Signal '{signal_id}' metadata updated[/green]")


@claims_app.command("find-similar")
def claims_find_similar(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
) -> None:
    """查找相似的 Claim 对（基于 token overlap）。不修改任何文件。"""
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.claim_signal.review import find_similar_claims

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径[/red]")
        raise typer.Exit(code=1)
    vault_path = Path(vault_path_str)

    pairs = find_similar_claims(vault_path)
    if not pairs:
        console.print("[yellow]No similar claims found.[/yellow]")
        return

    table = Table(title="Similar Claims")
    table.add_column("Item A", style="cyan", max_width=40)
    table.add_column("Item B", style="cyan", max_width=40)
    table.add_column("Similarity", max_width=20)
    table.add_column("Suggested", style="bold")
    for p in pairs:
        action_style = "magenta" if p.suggested_action == "possible_duplicate" else "yellow"
        table.add_row(p.item_a, p.item_b, p.similarity_reason,
                       f"[{action_style}]{p.suggested_action}[/{action_style}]")
    console.print(table)
    console.print(f"\n[dim]共 {len(pairs)} 对相似候选[/dim]")


@signals_app.command("find-similar")
def signals_find_similar(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
) -> None:
    """查找相似的 Signal 对（基于 token overlap）。不修改任何文件。"""
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.claim_signal.review import find_similar_signals

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径[/red]")
        raise typer.Exit(code=1)
    vault_path = Path(vault_path_str)

    pairs = find_similar_signals(vault_path)
    if not pairs:
        console.print("[yellow]No similar signals found.[/yellow]")
        return

    table = Table(title="Similar Signals")
    table.add_column("Item A", style="cyan", max_width=40)
    table.add_column("Item B", style="cyan", max_width=40)
    table.add_column("Similarity", max_width=20)
    table.add_column("Suggested", style="bold")
    for p in pairs:
        action_style = "magenta" if p.suggested_action == "possible_duplicate" else "yellow"
        table.add_row(p.item_a, p.item_b, p.similarity_reason,
                       f"[{action_style}]{p.suggested_action}[/{action_style}]")
    console.print(table)
    console.print(f"\n[dim]共 {len(pairs)} 对相似候选[/dim]")


@claims_app.command("backlog")
def claims_backlog(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
) -> None:
    """生成 Claim Review Backlog（按 priority 排序，写入 99_System/）。"""
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.claim_signal.review import generate_claim_backlog

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径[/red]")
        raise typer.Exit(code=1)
    vault_path = Path(vault_path_str)

    generate_claim_backlog(vault_path)
    console.print("[green]Claim Review Backlog written to 99_System/Claim Review Backlog.md[/green]")


@signals_app.command("backlog")
def signals_backlog(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
) -> None:
    """生成 Signal Review Backlog（按 priority 排序，写入 99_System/）。"""
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.claim_signal.review import generate_signal_backlog

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径[/red]")
        raise typer.Exit(code=1)
    vault_path = Path(vault_path_str)

    generate_signal_backlog(vault_path)
    console.print("[green]Signal Review Backlog written to 99_System/Signal Review Backlog.md[/green]")


@signals_app.command("update-tracking")
def signals_update_tracking(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    signal_id: str = typer.Argument(..., help="Signal card ID（文件名 stem）"),
    tracking_status: str = typer.Option(None, "--tracking-status", help="not_started / active / paused / resolved / invalidated / archived"),
    tracking_method: str = typer.Option(None, "--tracking-method", help="manual / news / earnings / product_release / metric / expert_commentary / youtube / rss / unknown"),
    tracking_query: str = typer.Option(None, "--tracking-query", help="搜索查询关键词"),
    resolution_criteria: str = typer.Option(None, "--resolution-criteria", help="达成何种条件可标记 resolved"),
    invalidation_criteria: str = typer.Option(None, "--invalidation-criteria", help="何种条件下标记 invalidated"),
) -> None:
    """设置 Signal 的 tracking 元数据。更新 frontmatter，写 log。"""
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.claim_signal.review import update_signal_tracking

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径[/red]")
        raise typer.Exit(code=1)
    vault_path = Path(vault_path_str)

    ok = update_signal_tracking(vault_path, signal_id,
                                tracking_status=tracking_status,
                                tracking_method=tracking_method,
                                tracking_query=tracking_query,
                                resolution_criteria=resolution_criteria,
                                invalidation_criteria=invalidation_criteria)
    if not ok:
        console.print(f"[red]更新失败：signal 不存在或参数非法。[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]Signal '{signal_id}' tracking updated[/green]")


@signals_app.command("add-update")
def signals_add_update(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    signal_id: str = typer.Argument(..., help="Signal card ID（文件名 stem）"),
    note: str = typer.Option(..., "--note", help="更新内容"),
    source: str = typer.Option("", "--source", help="信息来源"),
    evidence_url: str = typer.Option("", "--evidence-url", help="证据 URL"),
    status: str = typer.Option(None, "--status", help="可选：同时更新 signal status"),
    checked_at: str = typer.Option(None, "--checked-at", help="检查时间 ISO"),
) -> None:
    """向 Signal Card 追加一条人工更新记录。"""
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.claim_signal.review import add_signal_update

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径[/red]")
        raise typer.Exit(code=1)
    vault_path = Path(vault_path_str)

    ok = add_signal_update(vault_path, signal_id, note=note, source=source,
                           evidence_url=evidence_url, new_status=status, checked_at=checked_at)
    if not ok:
        console.print(f"[red]更新失败：signal 不存在。[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]Signal '{signal_id}' update added[/green]")


@signals_app.command("tracking-backlog")
def signals_tracking_backlog(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
) -> None:
    """生成 Signal Tracking Backlog（按 tracking 优先级排序，写入 99_System/）。"""
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.claim_signal.review import generate_signal_tracking_backlog

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径[/red]")
        raise typer.Exit(code=1)
    vault_path = Path(vault_path_str)

    generate_signal_tracking_backlog(vault_path)
    console.print("[green]Signal Tracking Backlog written to 99_System/Signal Tracking Backlog.md[/green]")


# ---------------------------------------------------------------------------
# llm-wiki 命令
# ---------------------------------------------------------------------------


@llm_wiki_app.command("generate-patches")
def llm_wiki_generate_patches(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只显示将处理哪些 topics/companies，不调用 LLM"),
    topic: str = typer.Option(None, "--topic", help="只处理指定 topic（精确匹配）"),
    company: str = typer.Option(None, "--company", help="只处理指定 company（精确匹配）"),
    core_only: bool = typer.Option(False, "--core-only", help="只处理 core topics（company 不适用）"),
    max_reports: int = typer.Option(5, "--max-reports", help="每个 topic/company 最多使用几个 source reports"),
    mock: bool = typer.Option(None, "--mock/--no-mock", help="使用 mock 模式生成占位 patch（测试用）"),
    output_dir: str = typer.Option("00_Inbox/LLM_Patches", "--output-dir", help="Patch 输出目录（相对 vault 路径）"),
) -> None:
    """为 Topic Cards 或 Company Cards 生成 LLM patch proposals。

    扫描 topics/companies，读取 source reports，调用 LLM 生成 patch proposal，
    写入 00_Inbox/LLM_Patches/ 供人工审阅。不直接修改卡片。
    """
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.llm_wiki import (
        find_core_topics,
        build_topic_context,
        generate_topic_patch,
        write_patch_file,
    )

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径或在 .env 中配置 OBSIDIAN_VAULT_PATH[/red]")
        raise typer.Exit(code=1)

    vault_path = Path(vault_path_str)
    if not vault_path.exists():
        console.print(f"[red]Vault 路径不存在: {vault_path}[/red]")
        raise typer.Exit(code=1)

    # Determine provider
    if mock is True:
        provider = "mock"
    elif mock is False:
        provider = "openai_compatible"
    else:
        # Default to mock for safety
        provider = "mock"

    # Get LLM config if using real LLM
    api_key = ""
    base_url = ""
    model = "gpt-4o-mini"
    if provider == "openai_compatible":
        from podcast_research.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
        api_key = LLM_API_KEY
        base_url = LLM_BASE_URL
        model = LLM_MODEL
        if not api_key or not base_url:
            console.print("[red]使用真实 LLM 需要配置 LLM_API_KEY 和 LLM_BASE_URL[/red]")
            raise typer.Exit(code=1)

    # Mutual exclusion
    if topic and company:
        console.print("[red]--topic 和 --company 不能同时使用[/red]")
        raise typer.Exit(code=1)

    # --- Company branch ---
    if company:
        from podcast_research.llm_wiki import (
            find_companies,
            build_company_context,
            generate_company_patch,
        )
        company_path = vault_path / "03_Companies" / f"{company}.md"
        if not company_path.exists():
            console.print(f"[red]Company card 不存在: {company_path}[/red]")
            raise typer.Exit(code=1)

        if dry_run:
            console.print(f"[dim][DRY-RUN] Company: {company}[/dim]")
            console.print(f"[dim]Provider: {provider}[/dim]")
            context = build_company_context(vault_path, company_path, max_reports)
            console.print(f"[cyan]Company: {company}[/cyan]")
            console.print(f"  Source reports: {len(context.source_reports)}")
            for r in context.source_reports:
                console.print(f"    - [[{r.filename}]] ({r.channel})")
            return

        console.print(f"[green]生成 company patch: {company}[/green]")
        try:
            context = build_company_context(vault_path, company_path, max_reports)
            if not context.source_reports:
                console.print(f"[yellow]跳过：无 source reports[/yellow]")
                raise typer.Exit(code=0)

            patch_md = generate_company_patch(
                company_context=context,
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
            patch_path = write_patch_file(
                vault_path, company, patch_md, output_dir, patch_prefix="company",
            )
            console.print(f"  [OK] Written to: {patch_path.relative_to(vault_path)}")
        except Exception as e:
            console.print(f"  [ERR] Error: {e}")
            raise typer.Exit(code=1)
        return

    # --- Topic branch ---
    # Find topics to process
    if topic:
        topic_path = vault_path / "02_Topics" / f"{topic}.md"
        if not topic_path.exists():
            console.print(f"[red]Topic card 不存在: {topic_path}[/red]")
            raise typer.Exit(code=1)
        topic_paths = [topic_path]
    elif core_only:
        topic_paths = find_core_topics(vault_path)
        if not topic_paths:
            console.print("[yellow]未找到 core topics[/yellow]")
            raise typer.Exit(code=0)
    else:
        topic_paths = find_core_topics(vault_path)
        if not topic_paths:
            console.print("[yellow]未找到 core topics[/yellow]")
            raise typer.Exit(code=0)

    if dry_run:
        console.print(f"[dim][DRY-RUN] 将处理 {len(topic_paths)} 个 topics[/dim]")
        console.print(f"[dim]Provider: {provider}[/dim]")
        console.print(f"[dim]Max reports per topic: {max_reports}[/dim]\n")

        for topic_path in topic_paths:
            topic_name = topic_path.stem
            context = build_topic_context(vault_path, topic_path, max_reports)
            console.print(f"[cyan]Topic: {topic_name}[/cyan]")
            console.print(f"  Source reports: {len(context.source_reports)}")
            for r in context.source_reports:
                console.print(f"    - [[{r.filename}]] ({r.channel})")
            console.print()

        console.print(f"[dim]共 {len(topic_paths)} 个 topics，每个最多 {max_reports} 个 source reports[/dim]")
        return

    # Generate patches
    console.print(f"[green]开始生成 patches ({len(topic_paths)} 个 topics)[/green]")
    console.print(f"  Provider: {provider}")
    console.print(f"  Max reports per topic: {max_reports}\n")

    generated = 0
    for topic_path in topic_paths:
        topic_name = topic_path.stem
        console.print(f"[cyan]Processing: {topic_name}[/cyan]")

        try:
            # Build context
            context = build_topic_context(vault_path, topic_path, max_reports)
            if not context.source_reports:
                console.print(f"  [yellow]跳过：无 source reports[/yellow]")
                continue

            console.print(f"  Source reports: {len(context.source_reports)}")

            # Generate patch
            patch_md = generate_topic_patch(
                topic_context=context,
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
            )

            # Write patch file
            patch_path = write_patch_file(
                vault_path, topic_name, patch_md, output_dir,
            )
            rel_path = patch_path.relative_to(vault_path)
            console.print(f"  [OK] Written to: {rel_path}")
            generated += 1

        except Exception as e:
            console.print(f"  [ERR] Error: {e}")
            continue

    console.print(f"\n[green]完成：生成 {generated} 个 patches[/green]")


@llm_wiki_app.command("validate-patches")
def llm_wiki_validate_patches(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    patch: str = typer.Option(None, "--patch", help="只验证指定 patch 文件（相对于 vault 的路径）"),
) -> None:
    """验证 00_Inbox/LLM_Patches/ 中的 patch 文件结构完整性。

    检查 frontmatter、target card 存在性、source reports 存在性、必要章节、Review Checklist。
    """
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.llm_wiki.validator import validate_patches

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径或在 .env 中配置 OBSIDIAN_VAULT_PATH[/red]")
        raise typer.Exit(code=1)

    vault_path = Path(vault_path_str)
    if not vault_path.exists():
        console.print(f"[red]Vault 路径不存在: {vault_path}[/red]")
        raise typer.Exit(code=1)

    # Resolve specific patch if given
    patch_path = None
    if patch:
        patch_path = vault_path / patch
        if not patch_path.exists():
            console.print(f"[red]Patch 文件不存在: {patch_path}[/red]")
            raise typer.Exit(code=1)

    results = validate_patches(vault_path, patch_path=patch_path)

    if not results:
        console.print("[yellow]00_Inbox/LLM_Patches/ 中没有 patch 文件。[/yellow]")
        return

    # Build Rich table
    table = Table(title="Patch Validation Results", show_lines=False)
    table.add_column("Patch", style="cyan", max_width=35)
    table.add_column("Target", max_width=18)
    table.add_column("Reports", justify="right")
    table.add_column("Status", style="yellow")
    table.add_column("Valid", style="bold")
    table.add_column("Issues", style="dim", max_width=50)

    valid_count = 0
    for r in results:
        valid_label = "[green]Yes[/green]" if r.is_valid else "[red]No[/red]"
        issues_str = "; ".join(r.issues) if r.issues else "-"
        reports_count = len(r.source_reports) if isinstance(r.source_reports, list) else 0

        table.add_row(
            r.patch_filename[:35],
            r.target[:18],
            str(reports_count),
            r.status or "-",
            valid_label,
            issues_str[:50],
        )

        if r.is_valid:
            valid_count += 1

    console.print(table)
    console.print(f"\n[dim]{len(results)} patches, {valid_count} valid, {len(results) - valid_count} with issues[/dim]")


@llm_wiki_app.command("apply-patch")
def llm_wiki_apply_patch(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    patch: str = typer.Option(..., "--patch", help="Patch 文件路径（相对于 vault，如 00_Inbox/LLM_Patches/topic_AI_Agents_xxx.md）"),
    dry_run: bool = typer.Option(True, "--dry-run/--apply", help="dry-run 不写文件（默认），--apply 执行写入"),
    confirm_reviewed: bool = typer.Option(False, "--confirm-reviewed", help="确认已人工审阅 patch 内容（pending_review 状态必须）"),
    force: bool = typer.Option(False, "--force", help="跳过 pending_review 限制（但仍拒绝 invalid patch）"),
) -> None:
    """将已审阅通过的 LLM patch 应用到目标 Topic Card。

    安全规则：
    - 默认 dry-run，不写文件
    - 必须显式 --apply + --confirm-reviewed 才执行
    - 不允许 auto_apply=true 的 patch
    - 不允许重复 apply
    - 使用 LLM-WIKI marker 追踪变更（可回滚）
    """
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.llm_wiki.applier import apply_patch

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径或在 .env 中配置 OBSIDIAN_VAULT_PATH[/red]")
        raise typer.Exit(code=1)

    vault_path = Path(vault_path_str)
    if not vault_path.exists():
        console.print(f"[red]Vault 路径不存在: {vault_path}[/red]")
        raise typer.Exit(code=1)

    # Resolve patch path
    patch_path = vault_path / patch
    if not patch_path.exists():
        console.print(f"[red]Patch 文件不存在: {patch_path}[/red]")
        raise typer.Exit(code=1)

    if dry_run:
        console.print(f"[dim][DRY-RUN] Patch: {patch}[/dim]\n")

    result = apply_patch(
        vault_path=vault_path,
        patch_rel_path=patch,
        dry_run=dry_run,
        confirm_reviewed=confirm_reviewed,
        force=force,
    )

    if result.errors:
        console.print(f"[red]Apply 被拒绝:[/red]")
        for err in result.errors:
            console.print(f"  [red]- {err}[/red]")

        if not dry_run:
            raise typer.Exit(code=1)
        # In dry-run, show errors but also show what would happen
        console.print()

    # Show summary
    table = Table(title="Patch Apply" + (" [DRY-RUN]" if dry_run else ""), show_lines=False)
    table.add_column("Field", style="cyan")
    table.add_column("Value")

    table.add_row("Patch", result.patch_id[:45])
    table.add_row("Target", result.target_name or "-")
    target_rel = str(result.target_card_path.relative_to(vault_path)) if result.target_card_path else "-"
    table.add_row("Target Card", target_rel)
    table.add_row("Sections to apply", "\n".join(result.sections_applied) if result.sections_applied else "(none)")
    table.add_row("Sections skipped", "\n".join(result.sections_skipped) if result.sections_skipped else "(none)")
    if result.warnings:
        table.add_row("Warnings", "\n".join(result.warnings))
    if result.errors:
        table.add_row("Errors", "\n".join(result.errors))

    console.print(table)

    if result.applied:
        console.print(f"\n[green]Patch applied successfully[/green]")
        console.print(f"  Target: {target_rel}")
        console.print(f"  Sections: {len(result.sections_applied)}")
        console.print(f"  Log: 99_System/Patch_Apply_Log.md")

    if dry_run and not result.errors:
        console.print(f"\n[dim]使用 --apply --confirm-reviewed 执行写入[/dim]")


@llm_wiki_app.command("list-applied-patches")
def llm_wiki_list_applied(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
) -> None:
    """列出所有 status=applied 的 patches，检查 marker 存在性。"""
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.llm_wiki.rollback import list_applied_patches

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径或在 .env 中配置 OBSIDIAN_VAULT_PATH[/red]")
        raise typer.Exit(code=1)

    vault_path = Path(vault_path_str)
    results = list_applied_patches(vault_path)

    if not results:
        console.print("[yellow]No applied patches found.[/yellow]")
        return

    table = Table(title="Applied Patches", show_lines=False)
    table.add_column("Patch ID", style="cyan", max_width=35)
    table.add_column("Type")
    table.add_column("Target")
    table.add_column("Applied At")
    table.add_column("Marker", style="bold")

    for r in results:
        marker_style = "green" if r.marker_exists == "yes" else ("red" if r.marker_exists == "missing" else "yellow")
        table.add_row(
            r.patch_id[:35],
            r.target_type,
            r.target_name,
            r.applied_at[:16] if r.applied_at else "-",
            f"[{marker_style}]{r.marker_exists}[/{marker_style}]",
        )

    console.print(table)


@llm_wiki_app.command("rollback-patch")
def llm_wiki_rollback(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    patch: str = typer.Option(None, "--patch", help="Patch 文件路径（相对于 vault）"),
    patch_id: str = typer.Option(None, "--patch-id", help="按 patch ID 查找（文件名 stem）"),
    dry_run: bool = typer.Option(True, "--dry-run/--apply", help="dry-run 不写文件（默认），--apply 执行回滚"),
) -> None:
    """回滚已应用的 patch：从目标卡片中移除 LLM-WIKI marker block。

    必须显式 --apply 才执行。只支持 status=applied 的 patch。
    """
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.llm_wiki.rollback import rollback_patch

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径或在 .env 中配置 OBSIDIAN_VAULT_PATH[/red]")
        raise typer.Exit(code=1)

    vault_path = Path(vault_path_str)

    if not patch and not patch_id:
        console.print("[red]请指定 --patch 或 --patch-id[/red]")
        raise typer.Exit(code=1)

    if dry_run:
        console.print("[dim][DRY-RUN] Rollback[/dim]")

    patch_path = None
    if patch:
        patch_path = vault_path / patch
    result = rollback_patch(vault_path, patch_path=patch_path, patch_id=patch_id, dry_run=dry_run)

    if result.errors:
        for err in result.errors:
            console.print(f"  [red]- {err}[/red]")
        return

    table = Table(title="Rollback" + (" [DRY-RUN]" if dry_run else " [APPLIED]"), show_lines=False)
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Patch ID", result.patch_id)
    table.add_row("Target", result.target_name)
    table.add_row("Blocks to remove", str(result.blocks_removed))
    console.print(table)

    if dry_run and result.blocks_removed > 0:
        console.print(f"\n[dim]使用 --apply 执行回滚[/dim]")


@llm_wiki_app.command("reject-patch")
def llm_wiki_reject(
    vault: str = typer.Option(None, "--vault", help="Obsidian Vault 路径（覆盖 .env 配置）"),
    patch: str = typer.Option(..., "--patch", help="Patch 文件路径（相对于 vault）"),
    reason: str = typer.Option("", "--reason", help="拒绝原因"),
) -> None:
    """拒绝一个 pending_review/approved patch。

    更新 patch status 为 rejected，不修改 target card。
    """
    from podcast_research.config import OBSIDIAN_VAULT_PATH
    from podcast_research.llm_wiki.rollback import reject_patch

    vault_path_str = vault or OBSIDIAN_VAULT_PATH
    if not vault_path_str:
        console.print("[red]请指定 --vault 路径或在 .env 中配置 OBSIDIAN_VAULT_PATH[/red]")
        raise typer.Exit(code=1)

    vault_path = Path(vault_path_str)
    patch_path = vault_path / patch
    if not patch_path.exists():
        console.print(f"[red]Patch 文件不存在: {patch_path}[/red]")
        raise typer.Exit(code=1)

    if not reason:
        console.print("[yellow]建议使用 --reason 说明拒绝原因[/yellow]")

    result = reject_patch(vault_path, patch_path, reason=reason)

    if result.errors:
        for err in result.errors:
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[green]Patch rejected: {result.patch_id}[/green]")
    if reason:
        console.print(f"  Reason: {reason}")


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
