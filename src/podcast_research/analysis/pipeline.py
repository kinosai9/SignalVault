"""分析 pipeline：串联 字幕解析 → 清洗 → LLM 抽取 → 渲染 → 入库。"""

import json
import logging
from pathlib import Path

from podcast_research.analysis.models import ExtractionResult, SubtitleSegment
from podcast_research.adapters.base import TranscriptResult
from podcast_research.config import REPORT_DIR, SUBTITLE_DIR, ensure_dirs
from podcast_research.db.repository import (
    save_entities,
    save_episode,
    save_investment_views,
    save_report,
    save_tracking_signals,
)
from podcast_research.db.session import get_session, init_db
from podcast_research.llm.base import LLMProvider
from podcast_research.llm.mock_provider import MockLLMProvider
from podcast_research.subtitles.cleaner import clean_segments
from podcast_research.subtitles.parser import parse_subtitle
from podcast_research.utils.hash import file_hash

logger = logging.getLogger(__name__)


def get_llm_provider(provider_name: str) -> LLMProvider:
    if provider_name == "mock":
        return MockLLMProvider()
    if provider_name in ("openai-compatible", "openai_compatible"):
        from podcast_research.llm.openai_compatible_provider import OpenAICompatibleProvider
        from podcast_research.config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
        if not LLM_API_KEY:
            raise ValueError("openai-compatible provider 需要配置 LLM_API_KEY（见 .env）")
        return OpenAICompatibleProvider(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            model=LLM_MODEL,
        )
    raise ValueError(f"不支持的 LLM provider: {provider_name}，可选: mock, openai-compatible")


def _run_pipeline(
    segments: list[SubtitleSegment],
    episode_title: str,
    source_path: str,
    subtitle_format: str,
    subtitle_hash: str,
    provider_name: str,
    output_dir: Path,
    focus_areas: list[str],
    analysis_depth: str,
    source_info: dict | None = None,
    episode_extra: dict | None = None,
) -> dict:
    """共享 pipeline 逻辑：清洗 → LLM 抽取 → 渲染 → 入库 → 写出。"""
    ensure_dirs()
    if source_info is None:
        source_info = {}
    if episode_extra is None:
        episode_extra = {}

    # 0. 字幕段数日志
    logger.info("输入字幕段数: %d", len(segments))
    total_chars = sum(len(s.text) for s in segments)
    logger.info("输入总字符数: %d（粗略 token 估计: ~%d）", total_chars, total_chars // 2)
    if len(segments) > 1000:
        logger.warning("长字幕警告: %d 段字幕，真实 LLM 可能触发 token 上限（当前未实现分块处理）", len(segments))
    if total_chars > 50000:
        logger.warning("长文本警告: %d 字符，建议后续实现 map-reduce 抽取", total_chars)

    # 1. 清洗字幕
    logger.info("清洗字幕，原始段数: %d", len(segments))
    cleaned = clean_segments(segments)
    logger.info("清洗完成，段数: %d", len(cleaned))

    cleaned_text = "\n".join(s.text for s in cleaned)
    segments_text = "\n".join(
        f"[{s.start_time}-{s.end_time}] {s.text}" for s in cleaned
    )

    # 2. LLM 抽取
    provider = get_llm_provider(provider_name)
    logger.info("LLM 事实抽取（provider: %s）", provider_name)
    extraction = provider.extract_facts(cleaned_text, segments_text)
    extraction.focus_areas = focus_areas
    extraction.source_info = source_info

    # 3. 生成报告
    logger.info("生成 Markdown 报告")
    report_md = provider.render_report(extraction)

    # 4. 入库
    init_db()
    session = get_session()
    try:
        ep_id = save_episode(
            session, episode_title, source_path, subtitle_format, subtitle_hash,
            source=episode_extra.get("source", "local"),
            source_url=episode_extra.get("source_url", ""),
            video_id=episode_extra.get("video_id", ""),
            language=episode_extra.get("language", ""),
        )
        rep_id = save_report(
            session, ep_id, extraction, report_md, provider_name, "mock-v1", analysis_depth
        )
        save_investment_views(session, rep_id, extraction.investment_views)
        save_tracking_signals(session, rep_id, extraction.tracking_signals)
        save_entities(session, extraction.mentioned_entities)
        session.commit()
        logger.info("入库完成，episode_id=%d, report_id=%d", ep_id, rep_id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    # 5. 写出文件
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{episode_title}_extraction.json"
    md_path = output_dir / f"{episode_title}_report.md"

    json_path.write_text(
        json.dumps(extraction.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(report_md, encoding="utf-8")
    logger.info("报告已写出: %s, %s", json_path, md_path)

    return {
        "episode_id": ep_id,
        "report_id": rep_id,
        "extraction_path": str(json_path),
        "report_path": str(md_path),
        "view_count": len(extraction.investment_views),
        "entity_count": len(extraction.mentioned_entities),
        "focus_areas": focus_areas,
    }


def analyze(
    subtitle_path: Path,
    provider_name: str = "mock",
    output_dir: Path | None = None,
    focus_areas: list[str] | None = None,
    analysis_depth: str = "standard",
) -> dict:
    """从本地字幕文件执行完整分析 pipeline。"""
    if focus_areas is None:
        focus_areas = ["通用投资研究"]

    logger.info("解析字幕: %s", subtitle_path)
    segments = parse_subtitle(subtitle_path)

    return _run_pipeline(
        segments=segments,
        episode_title=subtitle_path.stem,
        source_path=str(subtitle_path),
        subtitle_format=subtitle_path.suffix.lower().lstrip("."),
        subtitle_hash=file_hash(subtitle_path),
        provider_name=provider_name,
        output_dir=output_dir or REPORT_DIR,
        focus_areas=focus_areas,
        analysis_depth=analysis_depth,
        source_info={"source_type": "local", "source_path": str(subtitle_path)},
        episode_extra={"source": "local"},
    )


def analyze_from_transcript(
    transcript: TranscriptResult,
    provider_name: str = "mock",
    output_dir: Path | None = None,
    focus_areas: list[str] | None = None,
    analysis_depth: str = "standard",
) -> dict:
    """从 TranscriptResult（YouTube 等外部数据源）执行完整分析 pipeline。"""
    if focus_areas is None:
        focus_areas = ["通用投资研究"]

    episode_title = transcript.title or transcript.video_id or "unknown"
    source_path = transcript.source_url

    source_info = {
        "source_type": transcript.source_type,
        "source_url": transcript.source_url,
        "video_id": transcript.video_id,
        "language": transcript.language,
        "title": transcript.title,
        "channel_name": transcript.channel_name,
        "is_generated": transcript.is_generated,
        "fetched_at": transcript.fetched_at,
        "transcript_segment_count": transcript.transcript_segment_count,
    }

    episode_extra = {
        "source": transcript.source_type,
        "source_url": transcript.source_url,
        "video_id": transcript.video_id,
        "language": transcript.language,
    }

    return _run_pipeline(
        segments=transcript.segments,
        episode_title=episode_title,
        source_path=source_path,
        subtitle_format=transcript.source_type,
        subtitle_hash="",
        provider_name=provider_name,
        output_dir=output_dir or REPORT_DIR,
        focus_areas=focus_areas,
        analysis_depth=analysis_depth,
        source_info=source_info,
        episode_extra=episode_extra,
    )