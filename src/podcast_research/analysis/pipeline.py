"""分析 pipeline：串联 字幕解析 → 清洗 → LLM 抽取 → 渲染 → 入库。"""

import json
import logging
from pathlib import Path

from podcast_research.analysis.models import ExtractionResult, SubtitleSegment
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


def analyze(
    subtitle_path: Path,
    provider_name: str = "mock",
    output_dir: Path | None = None,
) -> dict:
    """执行完整分析 pipeline，返回结果摘要。"""
    ensure_dirs()
    out_dir = output_dir or REPORT_DIR

    # 1. 解析字幕
    logger.info("解析字幕: %s", subtitle_path)
    segments = parse_subtitle(subtitle_path)
    subtitle_fmt = subtitle_path.suffix.lower().lstrip(".")
    h = file_hash(subtitle_path)

    # 2. 清洗字幕
    logger.info("清洗字幕，原始段数: %d", len(segments))
    cleaned = clean_segments(segments)
    logger.info("清洗完成，段数: %d", len(cleaned))

    cleaned_text = "\n".join(s.text for s in cleaned)
    segments_text = "\n".join(
        f"[{s.start_time}-{s.end_time}] {s.text}" for s in cleaned
    )

    # 3. LLM 抽取
    provider = get_llm_provider(provider_name)
    logger.info("LLM 事实抽取（provider: %s）", provider_name)
    extraction = provider.extract_facts(cleaned_text, segments_text)

    # 4. 生成报告
    logger.info("生成 Markdown 报告")
    report_md = provider.render_report(extraction)

    # 5. 入库
    init_db()
    session = get_session()
    try:
        ep_id = save_episode(
            session, subtitle_path.stem, str(subtitle_path), subtitle_fmt, h
        )
        rep_id = save_report(
            session, ep_id, extraction, report_md, provider_name, "mock-v1"
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

    # 6. 写出文件
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{subtitle_path.stem}_extraction.json"
    md_path = out_dir / f"{subtitle_path.stem}_report.md"

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
    }