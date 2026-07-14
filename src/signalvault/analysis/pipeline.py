"""分析 pipeline：串联 字幕解析 → 清洗 → LLM 抽取 → 渲染 → 入库。"""

import json
import logging
from pathlib import Path

from signalvault.adapters.base import TranscriptResult
from signalvault.analysis.models import ExtractionResult, SubtitleSegment
from signalvault.config import REPORT_DIR, ensure_dirs
from signalvault.db.repository import (
    save_entities,
    save_episode,
    save_investment_views,
    save_report,
    save_tracking_signals,
)
from signalvault.db.session import get_session, init_db
from signalvault.llm.base import LLMProvider
from signalvault.llm.mock_provider import MockLLMProvider
from signalvault.subtitles.cleaner import clean_segments
from signalvault.subtitles.parser import parse_subtitle
from signalvault.utils.hash import file_hash

logger = logging.getLogger(__name__)


# ── YouTube transcript provenance persistence ───────────────────────────

def _persist_youtube_provenance(transcript: TranscriptResult, pipeline_result: dict) -> None:
    """Persist a YouTube transcript as SourceDocument + SourceSegments.

    Best-effort: failures are logged but never break the analysis pipeline.
    """
    try:
        from signalvault.db.source_provenance import (
            compute_content_hash,
            create_source_document,
            create_source_segments,
            upsert_source_document,
        )

        session = get_session()
        full_text = " ".join(s.text for s in transcript.segments)
        content_hash = compute_content_hash(full_text)

        # Upsert: skip if the same transcript is already persisted
        doc_id, is_new = upsert_source_document(
            session,
            source_type="youtube_transcript",
            content_hash=content_hash,
            title=transcript.title or transcript.video_id or "",
            canonical_url=transcript.source_url or "",
            source_url=transcript.source_url or "",
            language=transcript.language or "",
            original_language=transcript.language or "",
            access_scope="public_web",
            fetched_at=transcript.fetched_at,
        )

        if not is_new:
            logger.debug("SourceDocument already exists for transcript %s", doc_id)
            return

        # Create segments from transcript
        seg_dicts = []
        for i, seg in enumerate(transcript.segments):
            seg_dicts.append({
                "segment_id": getattr(seg, "segment_id", f"yt_{i:04d}"),
                "sequence_index": i,
                "segment_type": "timestamp",
                "text_original": seg.text,
                "start_time": getattr(seg, "start_time", ""),
                "end_time": getattr(seg, "end_time", ""),
                "content_hash": compute_content_hash(seg.text),
            })

        created = create_source_segments(session, doc_id, seg_dicts)
        logger.info(
            "Persisted YouTube transcript: doc=%s segments=%d",
            doc_id, created,
        )

        # Link Episode to SourceDocument
        episode_id = pipeline_result.get("episode_id")
        if episode_id:
            from signalvault.db.models import Episode
            ep = session.query(Episode).filter(Episode.id == episode_id).first()
            if ep is not None:
                ep.source_doc_id = doc_id
                session.flush()

        # Link Report to SourceDocument
        report_id = pipeline_result.get("report_id")
        if report_id:
            from signalvault.db.models import Report
            rp = session.query(Report).filter(Report.id == report_id).first()
            if rp is not None:
                rp.source_doc_id = doc_id
                session.flush()

    except Exception:
        logger.warning("Failed to persist YouTube transcript provenance", exc_info=True)


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
        from signalvault.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
        from signalvault.llm.openai_compatible_provider import (
            OpenAICompatibleProvider,
        )
        if not LLM_API_KEY:
            raise ValueError("openai-compatible provider 需要配置 LLM_API_KEY（见 .env）")
        return OpenAICompatibleProvider(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            model=LLM_MODEL,
        )
    raise ValueError(f"不支持的 LLM provider: {provider_name}，可选: mock, openai-compatible")


def _validate_report_language(report_md: str, episode_title: str) -> None:
    """P2-L.2: Validate report language consistency.

    Checks that the report has a reasonable Chinese character ratio.
    Source quotes (blockquotes) are excluded from the check since they
    may legitimately be in the original transcript language.
    """
    # Remove frontmatter (--- blocks)
    body = report_md
    while body.startswith("---"):
        end = body.find("---", 3)
        if end == -1:
            break
        body = body[end + 3:]

    # Remove source quote lines (> blockquotes)
    lines = body.split("\n")
    check_lines = [
        l for l in lines
        if not l.strip().startswith(">")
        and not l.strip().startswith("|")
        and not l.strip().startswith("[[")
        and not l.strip().startswith("- [[")
        and len(l.strip()) > 10
    ]
    check_text = "\n".join(check_lines)

    # Count Chinese characters
    total_alpha = sum(1 for ch in check_text if ch.isalpha())
    chinese_chars = sum(1 for ch in check_text if '一' <= ch <= '鿿')

    if total_alpha == 0 and chinese_chars == 0:
        return  # Empty report, skip

    chinese_ratio = chinese_chars / max(total_alpha + chinese_chars, 1)

    if chinese_ratio < 0.10:
        logger.warning(
            "Report language consistency LOW for '%s': Chinese ratio %.1f%% (total %d chars). "
            "Report may contain untranslated English sections. "
            "Consider re-running or checking LLM prompt compliance.",
            episode_title, chinese_ratio * 100, len(check_text),
        )
    else:
        logger.info(
            "Report language check passed for '%s': Chinese ratio %.1f%%",
            episode_title, chinese_ratio * 100,
        )


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
    from signalvault.analysis.chunking import (
        chunk_transcript,
        is_long_transcript,
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
        failed_chunks: list[dict] = []
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
                # P2-B: collect failure, continue with remaining chunks
                failed_chunks.append({"chunk_id": ch.chunk_id, "error": str(e)})

        if not chunk_results:
            raise RuntimeError(
                f"All {len(chunks)} chunks failed — no results to merge. "
                f"First error: {failed_chunks[0]['error'] if failed_chunks else 'unknown'}"
            )

        # Merge with compaction
        logger.info("Merging %d/%d chunk results (%d failed)",
                     len(chunk_results), len(chunks), len(failed_chunks))
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

    # P2-L.2: Language consistency validation
    _validate_report_language(report_md, episode_title)

    # 4. 入库
    init_db()
    session = get_session()

    # P2-N.1: Dedup — skip if this video already has a report
    video_id_for_dedup = episode_extra.get("video_id", "")
    force_reanalyze = episode_extra.get("force", False)
    if video_id_for_dedup and not force_reanalyze:
        from signalvault.db.repository import find_report_by_video_id
        existing = find_report_by_video_id(session, video_id_for_dedup)
        if existing:
            logger.info("Video %s already has report_id=%d, skipping duplicate.", video_id_for_dedup, existing["id"])
            return {
                "episode_id": existing["episode_id"],
                "report_id": existing["id"],
                "skipped": True,
                "existing_report": True,
                "view_count": 0,
                "entity_count": 0,
                "report_path": "",
                "focus_areas": [],
            }
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

    # 5. 写出文件（v2+ 带版本后缀，避免覆盖旧版报告；P2-N.4.1: sanitize filename）
    output_dir.mkdir(parents=True, exist_ok=True)
    version_suffix = ""
    pv = extraction.prompt_version
    if pv and pv not in ("v0.1", "v1"):
        version_suffix = f"_{pv}"

    from signalvault.exporters.markdown_utils import (
        sanitize_filename,
        unique_filename,
    )

    safe_title = sanitize_filename(episode_title, fallback=episode_extra.get("video_id", f"report_{rep_id}" if 'rep_id' in dir() else "untitled"))
    video_id_for_file = episode_extra.get("video_id", "")

    json_name = unique_filename(output_dir, safe_title, f"{version_suffix}_extraction.json", video_id=video_id_for_file)
    md_name = unique_filename(output_dir, safe_title, f"{version_suffix}_report.md", video_id=video_id_for_file)

    json_path = output_dir / json_name
    md_path = output_dir / md_name

    try:
        json_path.write_text(
            json.dumps(extraction.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        md_path.write_text(report_md, encoding="utf-8")
        logger.info("报告已写出: %s, %s", json_path, md_path)
    except OSError as e:
        logger.warning("报告文件写入失败（DB 已入库）: %s", e)

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

    result = _run_pipeline(
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

    # Source Provenance: persist full transcript as SourceDocument + SourceSegments
    _persist_youtube_provenance(transcript, result)

    return result
