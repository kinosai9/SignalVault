"""P2-B: Long Transcript Chunking + Map-Reduce Extraction.

长视频 transcript 分块 → 逐块 extract_facts → merge & compact → 单份最终报告。
"""

from __future__ import annotations

import logging
import re
from collections import OrderedDict

from signalvault.analysis.models import (
    Entity,
    Evidence,
    ExtractionResult,
    InvestmentView,
    Risk,
    SubtitleSegment,
    TechIndustryInsight,
    TrackingSignal,
    TranscriptChunk,
)

logger = logging.getLogger(__name__)

# ── 阈值常量 ──

DEFAULT_CHUNK_CHAR_LIMIT = 30000
DEFAULT_CHUNK_OVERLAP_CHARS = 2000
DEFAULT_LONG_TRANSCRIPT_CHAR_THRESHOLD = 50000
DEFAULT_LONG_TRANSCRIPT_SEGMENT_THRESHOLD = 1000

# ── Compaction 上限 ──

MAX_MERGED_INVESTMENT_VIEWS = 12
MAX_MERGED_TECH_INSIGHTS = 12
MAX_MERGED_ENTITIES = 40
MAX_MERGED_RISKS = 10
MAX_MERGED_TRACKING_SIGNALS = 10
MAX_MERGED_KEY_QUOTES = 20
MAX_MERGED_NON_FOCUS = 10
MAX_MERGED_UNCERTAIN = 10

# evidence_strength 优先级数值
_EVIDENCE_STRENGTH_ORDER = {"strong": 3, "medium": 2, "weak": 1}

# investment_relevance 优先级
_RELEVANCE_ORDER = {"high": 3, "medium": 2, "low": 1}

# implication 优先级
_IMPLICATION_ORDER = {"high": 3, "medium": 2, "low": 1, "none": 0}


# ═════════════════════════════════════════════════════════════════════════════
# Long transcript detection
# ═════════════════════════════════════════════════════════════════════════════


def is_long_transcript(
    segments: list[SubtitleSegment],
    char_threshold: int = DEFAULT_LONG_TRANSCRIPT_CHAR_THRESHOLD,
    segment_threshold: int = DEFAULT_LONG_TRANSCRIPT_SEGMENT_THRESHOLD,
) -> bool:
    """检测 transcript 是否需要分块。"""
    total_chars = sum(len(s.text) for s in segments)
    return total_chars > char_threshold or len(segments) > segment_threshold


# ═════════════════════════════════════════════════════════════════════════════
# Chunk creation
# ═════════════════════════════════════════════════════════════════════════════


def _format_chunk_header(chunk: TranscriptChunk) -> str:
    """为 chunk text 生成简短 header — 使用中文避免影响 LLM 输出语言。"""
    ts = f"{chunk.start_time}-{chunk.end_time}" if chunk.start_time else "N/A"
    return f"[第 {chunk.chunk_id}/{chunk.chunk_count} 段, 时间范围 {ts}]"


def chunk_transcript(
    segments: list[SubtitleSegment],
    char_limit: int = DEFAULT_CHUNK_CHAR_LIMIT,
    overlap_chars: int = DEFAULT_CHUNK_OVERLAP_CHARS,
) -> list[TranscriptChunk]:
    """按 segment 边界切分长 transcript，保留上下文重叠。

    Returns:
        list of TranscriptChunk with formatted text ready for extraction.
    """
    if not segments:
        return []

    total_chars = sum(len(s.text) for s in segments)
    if total_chars <= char_limit:
        # Single chunk — no splitting needed
        chunk = _build_chunk(
            chunk_id=1,
            chunk_count=1,
            seg_start=0,
            seg_end=len(segments),
            segments=segments,
            total_chunks=1,
        )
        return [chunk]

    chunks: list[TranscriptChunk] = []
    char_accum = 0
    seg_start = 0
    overlap_segments: list[SubtitleSegment] = []

    for i, seg in enumerate(segments):
        char_accum += len(seg.text)

        if char_accum >= char_limit and i > seg_start:
            # 切分：前一段作为 chunk
            seg_end = i
            chunk = _build_chunk(
                chunk_id=len(chunks) + 1,
                chunk_count=0,  # placeholder, filled later
                seg_start=seg_start,
                seg_end=seg_end,
                segments=segments[seg_start:seg_end],
                overlap_prefix=overlap_segments,
                total_chunks=0,
            )
            chunks.append(chunk)

            # 计算下一段的 overlap 起始点
            overlap_segments = _compute_overlap(
                segments, seg_end, overlap_chars
            )
            seg_start = max(seg_start, seg_end - len(overlap_segments))
            char_accum = sum(len(s.text) for s in overlap_segments)

    # 最后一段
    if seg_start < len(segments):
        final_segments = segments[seg_start:]
        chunk = _build_chunk(
            chunk_id=len(chunks) + 1,
            chunk_count=0,
            seg_start=seg_start,
            seg_end=len(segments),
            segments=final_segments,
            overlap_prefix=overlap_segments,
            total_chunks=0,
        )
        chunks.append(chunk)

    # 填充 total count（并修正 header 中的 chunk_count）
    total = len(chunks)
    for c in chunks:
        c.chunk_count = total
        # Fix placeholder "0" in header with actual count
        old_header = f"第 {c.chunk_id}/0 段"
        new_header = f"第 {c.chunk_id}/{total} 段"
        c.text = c.text.replace(old_header, new_header)

    return chunks


def _compute_overlap(
    segments: list[SubtitleSegment],
    from_index: int,
    overlap_chars: int,
) -> list[SubtitleSegment]:
    """从 from_index 向前回溯 overlap_chars 个字符的 segments。"""
    overlap: list[SubtitleSegment] = []
    chars = 0
    for s in reversed(segments[max(0, from_index - 20):from_index]):
        if chars >= overlap_chars:
            break
        overlap.insert(0, s)
        chars += len(s.text)
    return overlap


def _build_chunk(
    chunk_id: int,
    chunk_count: int,
    seg_start: int,
    seg_end: int,
    segments: list[SubtitleSegment],
    overlap_prefix: list[SubtitleSegment] | None = None,
    total_chunks: int = 1,
) -> TranscriptChunk:
    """构建单个 chunk，生成 text 和 segments_text。"""
    all_segs = (overlap_prefix or []) + segments
    cleaned_text = "\n".join(s.text for s in all_segs)
    segments_text = "\n".join(
        f"[{s.start_time}-{s.end_time}] {s.text}" for s in all_segs
    )

    start_time = segments[0].start_time if segments else ""
    end_time = segments[-1].end_time if segments else ""
    char_count = sum(len(s.text) for s in all_segs)

    # Prepend chunk header to text
    header = _format_chunk_header(TranscriptChunk(
        chunk_id=chunk_id,
        segment_start_index=seg_start,
        segment_end_index=seg_end,
        start_time=start_time,
        end_time=end_time,
        chunk_count=total_chunks or chunk_count,
    ))
    cleaned_text = f"{header}\n\n{cleaned_text}"

    return TranscriptChunk(
        chunk_id=chunk_id,
        segment_start_index=seg_start,
        segment_end_index=seg_end,
        start_time=start_time,
        end_time=end_time,
        text=cleaned_text,
        segments_text=segments_text,
        char_count=char_count,
        segment_count=len(segments),
        chunk_count=total_chunks or chunk_count,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Merge & Dedup
# ═════════════════════════════════════════════════════════════════════════════


def _view_dedup_key(v: InvestmentView) -> str:
    target = (v.normalized_target_name or v.target_name).lower().strip()
    return f"{target}|{v.view_direction}|{v.ai_value_chain_layer}|{v.business_impact}"


def _count_digits_and_terms(text: str) -> int:
    """粗略统计 source_quote 中的数字/指标信息量。"""
    digits = sum(1 for c in text if c.isdigit())
    financial_terms = len(re.findall(
        r"billion|million|trillion|percent|revenue|margin|capex|growth|valuation"
        r"|营收|利润|增速|增长|估值|市值|亿|万",
        text, re.IGNORECASE
    ))
    return digits + financial_terms * 5


def _merge_two_views(v1: InvestmentView, v2: InvestmentView) -> InvestmentView:
    """合并两个同 key 的 InvestmentView，保留更强证据的为主。"""
    s1 = _EVIDENCE_STRENGTH_ORDER.get(v1.evidence.evidence_strength, 1)
    s2 = _EVIDENCE_STRENGTH_ORDER.get(v2.evidence.evidence_strength, 1)

    if s2 > s1:
        primary, secondary = v2, v1
    elif s1 > s2:
        primary, secondary = v1, v2
    else:
        # 相同 strength，比较 source_quote 信息量
        n1 = _count_digits_and_terms(v1.source_quote)
        n2 = _count_digits_and_terms(v2.source_quote)
        if n2 > n1:
            primary, secondary = v2, v1
        else:
            primary, secondary = v1, v2

    # Merge logic_chain: 合并但不过长
    merged_logic = primary.logic_chain
    if secondary.logic_chain and secondary.logic_chain not in merged_logic:
        combined = f"{merged_logic}; {secondary.logic_chain}"
        if len(combined) <= 300:
            merged_logic = combined

    # Merge topic_tags (union)
    merged_tags = list(OrderedDict.fromkeys(
        primary.topic_tags + secondary.topic_tags
    ))

    # Keep better source_quote and timestamp
    merged = InvestmentView(
        target_name=primary.target_name,
        normalized_target_name=primary.normalized_target_name or secondary.normalized_target_name,
        target_type=primary.target_type,
        ticker=primary.ticker or secondary.ticker,
        market=primary.market or secondary.market,
        view_direction=primary.view_direction,
        view_direction_label=primary.view_direction_label or secondary.view_direction_label,
        logic_chain=merged_logic,
        time_horizon=primary.time_horizon if primary.time_horizon != "unknown" else secondary.time_horizon,
        confidence=primary.confidence,
        evidence=Evidence(
            evidence_type=primary.evidence.evidence_type,
            evidence_detail=primary.evidence.evidence_detail or secondary.evidence.evidence_detail,
            evidence_strength=primary.evidence.evidence_strength,
            missing_info=primary.evidence.missing_info,
        ),
        risk_warning=primary.risk_warning or secondary.risk_warning,
        speaker_label=primary.speaker_label if primary.speaker_label != "unknown_speaker" else secondary.speaker_label,
        speaker_role=primary.speaker_role if primary.speaker_role != "podcast_participant" else secondary.speaker_role,
        speaker_confidence=primary.speaker_confidence,
        source_quote=primary.source_quote,
        timestamp_start=primary.timestamp_start,
        timestamp_end=primary.timestamp_end or secondary.timestamp_end,
        uncertainty=primary.uncertainty,
        ai_value_chain_layer=primary.ai_value_chain_layer,
        technology_driver=primary.technology_driver or secondary.technology_driver,
        business_impact=primary.business_impact,
        investment_relevance=primary.investment_relevance,
        topic_tags=merged_tags,
        quote_support_strength=primary.quote_support_strength,
    )
    return merged


def _dedup_views(views: list[InvestmentView]) -> list[InvestmentView]:
    """按 dedup key 去重合并 investment_views。"""
    groups: dict[str, InvestmentView] = {}
    for v in views:
        key = _view_dedup_key(v)
        if key in groups:
            groups[key] = _merge_two_views(groups[key], v)
        else:
            groups[key] = v
    return list(groups.values())


def _dedup_entities(entities: list[Entity]) -> list[Entity]:
    """按 normalized_name 或 lower(name) 去重，合并 aliases。"""
    seen: dict[str, Entity] = {}
    for e in entities:
        key = (e.normalized_name or e.name).lower().strip()
        if key in seen:
            existing = seen[key]
            merged_aliases = list(OrderedDict.fromkeys(
                existing.aliases + e.aliases
            ))
            seen[key] = Entity(
                name=existing.name,
                normalized_name=existing.normalized_name or e.normalized_name,
                entity_type=existing.entity_type or e.entity_type,
                aliases=merged_aliases,
            )
        else:
            seen[key] = e
    return list(seen.values())


def _dedup_insights(insights: list[TechIndustryInsight]) -> list[TechIndustryInsight]:
    """按 ai_value_chain_layer + affected_entities overlap 去重 insights。"""
    if not insights:
        return []
    kept: list[TechIndustryInsight] = []
    for ins in insights:
        is_dup = False
        for existing in kept:
            if ins.ai_value_chain_layer == existing.ai_value_chain_layer:
                # Check affected_entities overlap
                overlap = set(ins.affected_entities) & set(existing.affected_entities)
                if overlap:
                    # Merge topic_tags
                    merged_tags = list(OrderedDict.fromkeys(
                        existing.topic_tags + ins.topic_tags
                    ))
                    existing.topic_tags = merged_tags
                    is_dup = True
                    break
        if not is_dup:
            kept.append(ins)
    return kept


def _dedup_risks(risks: list[Risk]) -> list[Risk]:
    """按 target_name + description 前 30 字符去重 risks。"""
    seen: set[str] = set()
    kept: list[Risk] = []
    for r in risks:
        key = f"{r.target_name}|{r.description[:30]}"
        if key not in seen:
            seen.add(key)
            kept.append(r)
    return kept


def _dedup_signals(signals: list[TrackingSignal]) -> list[TrackingSignal]:
    """按 target_name + signal 去重。"""
    seen: set[str] = set()
    kept: list[TrackingSignal] = []
    for s in signals:
        key = f"{s.target_name}|{s.signal[:50]}"
        if key not in seen:
            seen.add(key)
            kept.append(s)
    return kept


# ═════════════════════════════════════════════════════════════════════════════
# Compaction
# ═════════════════════════════════════════════════════════════════════════════


def _compact_views(views: list[InvestmentView], limit: int) -> list[InvestmentView]:
    """按 relevance + evidence_strength 排序，取 top-N。"""
    scored = sorted(views, key=lambda v: (
        _RELEVANCE_ORDER.get(v.investment_relevance, 1),
        _EVIDENCE_STRENGTH_ORDER.get(v.evidence.evidence_strength, 1),
    ), reverse=True)
    return scored[:limit]


def _compact_insights(insights: list[TechIndustryInsight], limit: int) -> list[TechIndustryInsight]:
    """按 implication + source_quote 信息量排序。"""
    scored = sorted(insights, key=lambda i: (
        _IMPLICATION_ORDER.get(i.investment_implication, 0),
        _count_digits_and_terms(i.source_quote),
    ), reverse=True)
    return scored[:limit]


def _compact_entities(entities: list[Entity], limit: int) -> list[Entity]:
    """优先保留 company / technology / industry_theme 类型（按优先级排序）。"""
    _entity_type_priority = {
        "company": 0, "technology": 1, "product_or_model": 2,
        "industry_theme": 3, "organization": 4, "market": 5,
        "asset_or_ticker": 6, "metric": 7, "policy_or_regulation": 8,
    }
    scored = sorted(entities, key=lambda e: _entity_type_priority.get(e.entity_type, 9))
    return scored[:limit]


def _compact_signals(signals: list[TrackingSignal], limit: int) -> list[TrackingSignal]:
    """优先保留有 trigger_condition 的。"""
    with_trigger = [s for s in signals if s.trigger_condition]
    without = [s for s in signals if not s.trigger_condition]
    return (with_trigger + without)[:limit]


# ═════════════════════════════════════════════════════════════════════════════
# Main merge entry point
# ═════════════════════════════════════════════════════════════════════════════


def merge_extraction_results(
    chunk_results: list[ExtractionResult],
    max_views: int = MAX_MERGED_INVESTMENT_VIEWS,
    max_insights: int = MAX_MERGED_TECH_INSIGHTS,
    max_entities: int = MAX_MERGED_ENTITIES,
    max_risks: int = MAX_MERGED_RISKS,
    max_signals: int = MAX_MERGED_TRACKING_SIGNALS,
    max_quotes: int = MAX_MERGED_KEY_QUOTES,
    max_non_focus: int = MAX_MERGED_NON_FOCUS,
    max_uncertain: int = MAX_MERGED_UNCERTAIN,
) -> ExtractionResult:
    """合并多个 chunk 的 ExtractionResult，去重 + compaction。

    Returns:
        单一 ExtractionResult，可直接用于 render_report。
    """
    if not chunk_results:
        return ExtractionResult(
            metadata={"chunking": True, "chunk_count": 0, "error": "No chunk results"},
        )

    if len(chunk_results) == 1:
        return chunk_results[0]

    # Collect all items
    all_views: list[InvestmentView] = []
    all_insights: list[TechIndustryInsight] = []
    all_entities: list[Entity] = []
    all_risks: list[Risk] = []
    all_signals: list[TrackingSignal] = []
    all_quotes: list[str] = []
    all_non_focus: list[str] = []
    all_uncertain: list[str] = []
    focus_areas: list[str] = []
    prompt_version = chunk_results[0].prompt_version or "tech_ai_v2"
    source_info = chunk_results[0].source_info or {}

    for cr in chunk_results:
        all_views.extend(cr.investment_views)
        all_insights.extend(cr.tech_industry_insights)
        all_entities.extend(cr.mentioned_entities)
        all_risks.extend(cr.risks)
        all_signals.extend(cr.tracking_signals)
        all_quotes.extend(cr.key_quotes)
        all_non_focus.extend(cr.non_focus_items)
        all_uncertain.extend(cr.uncertain_items)
        if cr.focus_areas:
            focus_areas = cr.focus_areas

    before = {
        "views": len(all_views), "insights": len(all_insights),
        "entities": len(all_entities), "risks": len(all_risks),
        "signals": len(all_signals), "quotes": len(all_quotes),
        "non_focus": len(all_non_focus), "uncertain": len(all_uncertain),
    }

    # Dedup
    views = _dedup_views(all_views)
    insights = _dedup_insights(all_insights)
    entities = _dedup_entities(all_entities)
    risks = _dedup_risks(all_risks)
    signals = _dedup_signals(all_signals)
    quotes = list(OrderedDict.fromkeys(all_quotes))
    non_focus = list(OrderedDict.fromkeys(all_non_focus))
    uncertain = list(OrderedDict.fromkeys(all_uncertain))

    after_dedup = {
        "views": len(views), "insights": len(insights),
        "entities": len(entities), "risks": len(risks),
        "signals": len(signals), "quotes": len(quotes),
    }

    # Compact
    views = _compact_views(views, max_views)
    # P2-N.1: When views are very sparse (< 3), keep more insights to preserve
    # technical context. They may contain investment-relevant signal even if
    # the LLM didn't classify them as formal investment views.
    effective_max_insights = max(max_insights, 12) if len(views) < 3 else max_insights
    insights = _compact_insights(insights, effective_max_insights)
    entities = _compact_entities(entities, max_entities)
    risks = risks[:max_risks]
    signals = _compact_signals(signals, max_signals)
    quotes = quotes[:max_quotes]
    non_focus = non_focus[:max_non_focus]
    uncertain = uncertain[:max_uncertain]

    after = {
        "views": len(views), "insights": len(insights),
        "entities": len(entities), "risks": len(risks),
        "signals": len(signals), "quotes": len(quotes),
    }

    logger.info("Chunk merge: before=%s, after_dedup=%s, after_compact=%s",
                before, after_dedup, after)

    metadata = {
        "chunking": True,
        "chunk_count": len(chunk_results),
        "merge": {"before": before, "after_dedup": after_dedup, "after_compact": after},
        "model": chunk_results[0].metadata.get("model", "mock-v2") if chunk_results[0].metadata else "mock-v2",
    }

    return ExtractionResult(
        metadata=metadata,
        source_info=source_info,
        focus_areas=focus_areas,
        prompt_version=prompt_version,
        mentioned_entities=entities,
        investment_views=views,
        tech_industry_insights=insights,
        risks=risks,
        tracking_signals=signals,
        key_quotes=quotes,
        uncertain_items=uncertain,
        non_focus_items=non_focus,
    )
