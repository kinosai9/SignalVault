"""P2-K.1: Analyze service — reusable wrapper for YouTube analysis pipeline."""

import contextlib
from dataclasses import dataclass

from signalvault.adapters.youtube_transcript import YouTubeTranscriptAdapter
from signalvault.analysis.pipeline import analyze_from_transcript
from signalvault.config import TRANSCRIPT_CACHE_DIR, ensure_dirs


@dataclass
class AnalyzeResult:
    success: bool
    report_id: int = 0
    message: str = ""
    error_type: str = ""  # invalid_url / no_subtitle / llm_config / token_limit / unknown


def _backfill_channel_metadata(video_id: str) -> dict | None:
    """Look up channel metadata from channel_videos + channels tables.

    Returns dict with keys matching source_info_override if found, or None.
    """
    import json
    try:
        from signalvault.db.models import Channel, ChannelVideo
        from signalvault.db.session import get_session, init_db

        init_db()
        session = get_session()
        try:
            cv = session.query(ChannelVideo).filter_by(video_id=video_id).first()
            if not cv:
                return None

            channel = session.query(Channel).filter_by(id=cv.channel_id).first()
            if not channel:
                return None

            tags = []
            if channel.tags and channel.tags != "[]":
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    tags = json.loads(channel.tags)

            return {
                "channel_name": channel.name,
                "channel_url": channel.url,
                "channel_tags": tags,
                "video_title": cv.title or "",
                "video_url": cv.url or f"https://www.youtube.com/watch?v={video_id}",
                "published_at": cv.published_at or "",
            }
        finally:
            session.close()
    except Exception:
        return None


def analyze_youtube_url(
    youtube_url: str,
    focus_areas: list[str] | None = None,
    depth: str = "standard",
    mock: bool = False,
    progress_callback=None,
) -> AnalyzeResult:
    """Analyze a YouTube video and generate a research report.

    Args:
        youtube_url: Full YouTube video URL.
        focus_areas: List of focus areas for the analysis.
        depth: Analysis depth (standard / deep).
        mock: Use mock LLM provider (for testing).
        progress_callback: Optional callable(stage, message) for progress updates.

    Returns:
        AnalyzeResult with success status, report_id, and user-friendly message.
    """
    ensure_dirs()

    if focus_areas is None:
        focus_areas = ["通用投资研究"]

    provider = "mock" if mock else "openai-compatible"

    # 1. Fetch transcript
    if progress_callback:
        progress_callback("fetching_transcript", "正在获取视频字幕")
    try:
        adapter = YouTubeTranscriptAdapter(cache_dir=TRANSCRIPT_CACHE_DIR)
        transcript = adapter.fetch(url=youtube_url)
    except Exception as e:
        msg = str(e).lower()
        if "not found" in msg or "no transcript" in msg or "subtitles are disabled" in msg:
            return AnalyzeResult(
                success=False,
                error_type="no_subtitle",
                message="该视频暂时无法获取字幕，可能是作者关闭了字幕或 YouTube 暂未生成字幕。",
            )
        return AnalyzeResult(
            success=False,
            error_type="invalid_url",
            message="无法获取该视频的字幕。请确认链接是否有效。",
        )

    # 2. Backfill channel metadata from DB (P2-L.2: fix channel metadata loss)
    video_id = transcript.video_id
    source_info_override = _backfill_channel_metadata(video_id)
    if source_info_override:
        if progress_callback:
            progress_callback(
                "backfill_channel",
                f"已匹配频道信息: {source_info_override.get('channel_name', '')}"
            )
    else:
        # No channel metadata found — log warning
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            f"No channel metadata found for video_id={video_id}. "
            f"Report will use fallback channel name."
        )

    # 3. Run pipeline
    if progress_callback:
        progress_callback("analyzing", "正在进行 AI 分析")
    try:
        result = analyze_from_transcript(
            transcript,
            provider_name=provider,
            focus_areas=focus_areas,
            analysis_depth=depth,
            source_info_override=source_info_override,  # P2-L.2: ensure channel metadata flows through
        )
        report_id = result.get("report_id", 0)
        return AnalyzeResult(
            success=True,
            report_id=report_id,
            message=f"分析完成，已生成报告 #{report_id}",
        )
    except Exception as e:
        msg = str(e).lower()
        if "api key" in msg or "unauthorized" in msg or "authentication" in msg:
            return AnalyzeResult(
                success=False,
                error_type="llm_config",
                message="AI 分析服务尚未配置，请检查 .env 中的 LLM_API_KEY。",
            )
        if "token" in msg or "too long" in msg or "maximum context" in msg:
            return AnalyzeResult(
                success=False,
                error_type="token_limit",
                message="视频较长，当前分析失败。后续将支持长视频自动分段整理。",
            )
        return AnalyzeResult(
            success=False,
            error_type="unknown",
            message=f"整理失败：{str(e)[:200]}",
        )


def analyze_pdf_file(
    file_path: str,
    focus_areas: list[str] | None = None,
    depth: str = "standard",
    mock: bool = False,
    progress_callback=None,
) -> AnalyzeResult:
    """Analyze a PDF file and generate a research report.

    Args:
        file_path: Path to the PDF file.
        focus_areas: List of focus areas for the analysis.
        depth: Analysis depth (standard / deep).
        mock: Use mock LLM provider (for testing).
        progress_callback: Optional callable(stage, message) for progress updates.

    Returns:
        AnalyzeResult with success status, report_id, and user-friendly message.
    """
    ensure_dirs()

    if focus_areas is None:
        focus_areas = ["通用投资研究"]

    provider = "mock" if mock else "openai-compatible"

    if progress_callback:
        progress_callback("extracting", "正在提取 PDF 文本")

    from signalvault.sources.pdf_analysis import analyze_pdf

    try:
        result = analyze_pdf(
            file_path=file_path,
            provider_name=provider,
            focus_areas=focus_areas,
            analysis_depth=depth,
            write_review=True,
        )
    except Exception as e:
        return AnalyzeResult(
            success=False,
            error_type="invalid_url",
            message=f"无法读取 PDF 文件：{str(e)[:200]}",
        )

    if not result.get("success"):
        reason = result.get("reason", "分析未完成")
        return AnalyzeResult(
            success=False,
            error_type="no_subtitle",
            message=f"PDF 分析未完成：{reason}",
        )

    report_id = result.get("report_id", 0)
    return AnalyzeResult(
        success=True,
        report_id=report_id,
        message=f"PDF 分析完成，已生成报告 #{report_id}",
    )
