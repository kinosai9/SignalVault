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
