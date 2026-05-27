"""CLI 入口：python -m podcast_research <subtitle_file>"""

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from podcast_research.analysis.pipeline import analyze as run_analyze
from podcast_research.config import LLM_PROVIDER, ensure_dirs
from podcast_research.logging_config import setup_logging

console = Console()
app = typer.Typer(
    help="投资播客研究助手 — 将播客字幕中的投资观点结构化沉淀",
    invoke_without_command=True,
)


@app.callback()
def main(
    subtitle_file: Path = typer.Option(None, help="字幕文件路径 (.srt/.txt)"),
    mock: bool = typer.Option(None, help="使用 mock 规则引擎（覆盖 .env 配置）"),
    output: Path | None = typer.Option(None, "-o", help="报告输出目录"),
    verbose: bool = typer.Option(False, "-v", help="详细日志"),
) -> None:
    """分析本地字幕文件，生成结构化投资研究报告。"""
    if subtitle_file is None:
        console.print("请提供字幕文件路径。用法: python -m podcast_research --subtitle-file <file>")
        raise typer.Exit(code=1)

    if not subtitle_file.exists():
        console.print(f"[red]文件不存在: {subtitle_file}[/red]")
        raise typer.Exit(code=1)

    level = "DEBUG" if verbose else "INFO"
    setup_logging(level)
    ensure_dirs()

    # 确定 provider：--mock 强制 mock，否则从 .env 读取
    if mock is True:
        provider = "mock"
    elif mock is False:
        provider = "openai-compatible"
    else:
        provider = LLM_PROVIDER

    console.print(Panel(f"分析字幕: {subtitle_file}\nLLM provider: {provider}", title="投资播客研究助手"))

    try:
        result = run_analyze(subtitle_file, provider_name=provider, output_dir=output)
    except Exception as e:
        console.print(f"[red]分析失败: {e}[/red]")
        raise typer.Exit(code=1)

    console.print("[green]分析完成[/green]")
    console.print(f"  观点数: {result['view_count']}")
    console.print(f"  标的数: {result['entity_count']}")
    console.print(f"  报告: {result['report_path']}")
    console.print(f"  JSON: {result['extraction_path']}")