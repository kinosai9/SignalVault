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


# P2-A2.1: source_info override 合并优先级映射
# override key → source_info key（便于扩展）
_SOURCE_INFO_OVERRIDE_MAP = {
    "channel_name": "channel_name",
    "channel_url": "channel_url",
    "video_title": "title",
    "video_url": "video_url",
    "published_at": "published_at",
    "channel_tags": "channel_tags",
    "channel_default_focus": "channel_default_focus",
}


def _merge_source_info_override(source_info: dict, override: dict) -> None:
    """将 override 中的非空值合并到 source_info，覆盖空字段。

    优先级：override 非空值 > source_info 已有值。
    不影响 source_type / video_id / language 等 adapter 提供的基础字段。
    """
    for override_key, source_key in _SOURCE_INFO_OVERRIDE_MAP.items():
        val = override.get(override_key)
        if val:
            existing = source_info.get(source_key)
            if not existing:
                source_info[source_key] = val


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
    chunking_config: dict | None = None,
) -> dict:
    """共享 pipeline 逻辑：清洗 → LLM 抽取 → 渲染 → 入库 → 写出。

    P2-B chunking_config: {"enabled": bool|None, "char_limit": int, "overlap_chars": int}
      enabled=None: auto-detect long transcript
      enabled=True: force chunk
      enabled=False: force no chunk (long transcript WARNING)
    """
    from podcast_research.analysis.chunking import (
        is_long_transcript,
        chunk_transcript,
        merge_extraction_results,
    )

    ensure_dirs()
    if source_info is None:
        source_info = {}
    if episode_extra is None:
        episode_extra = {}
    if chunking_config is None:
        chunking_config = {}

    # 0. 字幕段数日志
    logger.info("输入字幕段数: %d", len(segments))
    total_chars = sum(len(s.text) for s in segments)
    logger.info("输入总字符数: %d（粗略 token 估计: ~%d）", total_chars, total_chars // 2)

    # 1. 清洗字幕
    logger.info("清洗字幕，原始段数: %d", len(segments))
    cleaned = clean_segments(segments)
    logger.info("清洗完成，段数: %d", len(cleaned))

    # --- P2-B: Chunking decision ---
    do_chunk = chunking_config.get("enabled")
    char_limit = chunking_config.get("char_limit", 30000)
    overlap_chars = chunking_config.get("overlap_chars", 2000)

    if do_chunk is None:
        do_chunk = is_long_transcript(cleaned)

    if do_chunk and len(cleaned) <= 5:
        # Too few segments to chunk meaningfully
        do_chunk = False

    if not do_chunk and is_long_transcript(cleaned):
        logger.warning(
            "长 transcript 警告（%d segments, %d chars），建议启用 --chunked 避免 token 超限",
            len(cleaned), total_chars,
        )

    # 2. LLM 抽取
    provider = get_llm_provider(provider_name)

    if do_chunk:
        # ── Chunked extraction ──────────────────────────────────────────
        logger.info("Chunked extraction: %d segments, %d chars, char_limit=%d, overlap=%d",
                    len(cleaned), total_chars, char_limit, overlap_chars)
        chunks = chunk_transcript(cleaned, char_limit=char_limit, overlap_chars=overlap_chars)
        logger.info("Transcript chunked: %d chunks", len(chunks))

        chunk_results: list[ExtractionResult] = []
        for ch in chunks:
            logger.info("Extracting chunk %d/%d (segments %d-%d, %d chars)",
                        ch.chunk_id, ch.chunk_count,
                        ch.segment_start_index, ch.segment_end_index, ch.char_count)
            try:
                ch_extraction = provider.extract_facts(
                    ch.text, ch.segments_text, focus_areas=focus_areas,
                )
                # Annotate chunk metadata
                if ch_extraction.metadata is None:
                    ch_extraction.metadata = {}
                ch_extraction.metadata["chunk_id"] = ch.chunk_id
                ch_extraction.metadata["chunk_count"] = ch.chunk_count
                ch_extraction.metadata["segment_start_index"] = ch.segment_start_index
                ch_extraction.metadata["segment_end_index"] = ch.segment_end_index
                ch_extraction.metadata["timestamp_range"] = f"{ch.start_time}-{ch.end_time}"

                chunk_results.append(ch_extraction)
                logger.info("Chunk %d/%d done: %d views, %d insights",
                            ch.chunk_id, ch.chunk_count,
                            len(ch_extraction.investment_views),
                            len(ch_extraction.tech_industry_insights))
            except Exception as e:
                logger.error("Chunk %d/%d failed: %s", ch.chunk_id, ch.chunk_count, e)
                # P2-B initial: abort on any chunk failure
                raise

        # Merge with compaction
        logger.info("Merging %d chunk results", len(chunk_results))
        extraction = merge_extraction_results(chunk_results)
        extraction.focus_areas = focus_areas
        extraction.source_info = source_info
        if not extraction.prompt_version:
            extraction.prompt_version = "tech_ai_v2"
        logger.info("Merge complete: %d views, %d insights, %d entities",
                     len(extraction.investment_views),
                     len(extraction.tech_industry_insights),
                     len(extraction.mentioned_entities))
    else:
        # ── Single-pass extraction (existing path) ────────────────────
        cleaned_text = "\n".join(s.text for s in cleaned)
        segments_text = "\n".join(
            f"[{s.start_time}-{s.end_time}] {s.text}" for s in cleaned
        )
        logger.info("LLM 事实抽取（provider: %s, prompt: tech_ai_v2）", provider_name)
        extraction = provider.extract_facts(cleaned_text, segments_text, focus_areas=focus_areas)
        extraction.focus_areas = focus_areas
        extraction.source_info = source_info
        if not extraction.prompt_version:
            extraction.prompt_version = "tech_ai_v2"

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
            session, ep_id, extraction, report_md, provider_name,
            llm_model=extraction.metadata.get("model", "mock-v1") if extraction.metadata else "mock-v1",
            analysis_depth=analysis_depth,
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

    # 5. 写出文件（v2+ 带版本后缀，避免覆盖旧版报告）
    output_dir.mkdir(parents=True, exist_ok=True)
    version_suffix = ""
    pv = extraction.prompt_version
    if pv and pv not in ("v0.1", "v1"):
        version_suffix = f"_{pv}"
    json_path = output_dir / f"{episode_title}{version_suffix}_extraction.json"
    md_path = output_dir / f"{episode_title}{version_suffix}_report.md"

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
    chunking_config: dict | None = None,
) -> dict:
    """从本地字幕文件执行完整分析 pipeline。

    P2-B chunking_config: {"enabled": bool|None, "char_limit": int, "overlap_chars": int}
    """
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
        chunking_config=chunking_config,
    )


def analyze_from_transcript(
    transcript: TranscriptResult,
    provider_name: str = "mock",
    output_dir: Path | None = None,
    focus_areas: list[str] | None = None,
    analysis_depth: str = "standard",
    source_info_override: dict | None = None,
    chunking_config: dict | None = None,
) -> dict:
    """从 TranscriptResult（YouTube 等外部数据源）执行完整分析 pipeline。

    source_info_override: 可选字典，用于覆盖 / 补充 source_info 中的字段。
    chunking_config: P2-B 分块配置 {"enabled": bool|None, "char_limit": int, "overlap_chars": int}
    """
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

    # P2-A2.1: 合并 channel metadata override（覆盖空字段）
    if source_info_override:
        _merge_source_info_override(source_info, source_info_override)

        # 如果 override 提供了比 adapter 更好的 title，更新页面标题
        if source_info_override.get("video_title"):
            episode_title = source_info_override["video_title"]

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
        chunking_config=chunking_config,
    )