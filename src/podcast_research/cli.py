"""CLI 入口：python -m podcast_research --subtitle-file <file> 或 --youtube-url <url>"""

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from podcast_research.analysis.pipeline import analyze as run_analyze
from podcast_research.analysis.pipeline import analyze_from_transcript as run_analyze_from_transcript
from podcast_research.config import LLM_PROVIDER, TRANSCRIPT_CACHE_DIR, ensure_dirs
from podcast_research.logging_config import setup_logging

console = Console()
app = typer.Typer(
    help="投资音视频研究助手 — 将音视频字幕中的投资观点结构化沉淀",
    invoke_without_command=True,
)


@app.callback()
def main(
    subtitle_file: Path = typer.Option(None, help="本地字幕文件路径 (.srt/.txt)"),
    youtube_url: str = typer.Option(None, "--youtube-url", help="YouTube 视频链接"),
    youtube_lang: str = typer.Option(None, "--youtube-lang", help="YouTube 字幕语言优先级，逗号分隔，如 'zh-Hans,en'"),
    mock: bool = typer.Option(None, help="使用 mock 规则引擎（覆盖 .env 配置）"),
    focus: str = typer.Option(None, "--focus", help="关注点，逗号分隔，如 '新能源,港股,AI算力'"),
    depth: str = typer.Option("standard", "--depth", help="分析深度: standard / deep"),
    output: Path | None = typer.Option(None, "-o", help="报告输出目录"),
    verbose: bool = typer.Option(False, "-v", help="详细日志"),
) -> None:
    """分析本地字幕文件或 YouTube 视频字幕，生成结构化投资研究报告。"""
    # 互斥检查
    if subtitle_file and youtube_url:
        console.print("[red]--subtitle-file 和 --youtube-url 不能同时使用[/red]")
        raise typer.Exit(code=1)
    if not subtitle_file and not youtube_url:
        console.print("请提供字幕文件或 YouTube 链接。用法:\n  python -m podcast_research --subtitle-file <file>\n  python -m podcast_research --youtube-url <url>")
        raise typer.Exit(code=1)

    # 解析 focus_areas
    focus_areas = [f.strip() for f in focus.split(",") if f.strip()] if focus else None

    level = "DEBUG" if verbose else "INFO"
    setup_logging(level)
    ensure_dirs()

    # 确定 provider
    if mock is True:
        provider = "mock"
    elif mock is False:
        provider = "openai-compatible"
    else:
        provider = LLM_PROVIDER

    if youtube_url:
        # YouTube 模式
        from podcast_research.adapters.youtube_transcript import YouTubeTranscriptAdapter
        from podcast_research.utils.youtube import extract_video_id

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
        # 本地字幕模式
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