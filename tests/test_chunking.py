"""P2-B: Long Transcript Chunking + Map-Reduce tests.

All tests use mock provider — no real LLM API calls.
"""

from pathlib import Path

from podcast_research.analysis.chunking import (
    MAX_MERGED_ENTITIES,
    MAX_MERGED_INVESTMENT_VIEWS,
    _compact_entities,
    _compact_insights,
    _compact_signals,
    _compact_views,
    _dedup_entities,
    _dedup_insights,
    _dedup_risks,
    _dedup_signals,
    _dedup_views,
    chunk_transcript,
    is_long_transcript,
    merge_extraction_results,
)
from podcast_research.analysis.models import (
    Entity,
    Evidence,
    ExtractionResult,
    InvestmentView,
    Risk,
    SubtitleSegment,
    TechIndustryInsight,
    TrackingSignal,
)

# ── Helpers ──

def _make_segments(count: int, chars_per_seg: int = 20) -> list[SubtitleSegment]:
    """Generate synthetic subtitle segments for testing."""
    segments = []
    for i in range(count):
        t_start = i * 5
        t_end = t_start + 4
        text = f"Segment {i:04d} " + "X" * (chars_per_seg - 15)
        segments.append(SubtitleSegment(
            segment_id=f"seg{i:04d}",
            start_time=f"00:{t_start // 60:02d}:{t_start % 60:02d}.000",
            end_time=f"00:{t_end // 60:02d}:{t_end % 60:02d}.000",
            text=text,
        ))
    return segments


def _make_view(target="NVIDIA", direction="bullish", strength="medium",
               relevance="medium", ai_layer="semiconductor", business="revenue_growth",
               source_quote="Revenue grew 50% YoY", timestamp="00:05:00") -> InvestmentView:
    return InvestmentView(
        target_name=target,
        normalized_target_name=target,
        view_direction=direction,
        logic_chain=f"{target} demand growing",
        source_quote=source_quote,
        timestamp_start=timestamp,
        evidence=Evidence(evidence_type="financial_metric", evidence_strength=strength),
        ai_value_chain_layer=ai_layer,
        business_impact=business,
        investment_relevance=relevance,
        topic_tags=["GPU", "datacenter"],
    )


# ═════════════════════════════════════════════════════════════════════════════
# Detection tests
# ═════════════════════════════════════════════════════════════════════════════

def test_is_long_transcript_false_for_short():
    """短 transcript 不触发 chunking。"""
    segs = _make_segments(20, chars_per_seg=30)  # ~600 chars, 20 segments
    assert not is_long_transcript(segs)


def test_is_long_transcript_true_for_many_segments():
    """超过 1000 segment 触发 chunking。"""
    segs = _make_segments(1001, chars_per_seg=5)  # ~5005 chars but >1000 segments
    assert is_long_transcript(segs)


def test_is_long_transcript_true_for_high_chars():
    """超过 50000 字符触发 chunking。"""
    segs = _make_segments(10, chars_per_seg=6000)  # ~60K chars
    assert is_long_transcript(segs)


# ═════════════════════════════════════════════════════════════════════════════
# Chunk creation tests
# ═════════════════════════════════════════════════════════════════════════════

def test_chunk_transcript_single_chunk_for_short():
    """短 transcript 返回单个 chunk。"""
    segs = _make_segments(5, chars_per_seg=50)
    chunks = chunk_transcript(segs, char_limit=10000, overlap_chars=500)
    assert len(chunks) == 1
    assert chunks[0].chunk_id == 1
    assert chunks[0].chunk_count == 1
    assert chunks[0].segment_start_index == 0
    assert chunks[0].segment_end_index == 5


def test_chunk_transcript_splits_at_char_limit():
    """按 char_limit 切分为多个 chunk。"""
    segs = _make_segments(60, chars_per_seg=200)  # ~12K chars
    chunks = chunk_transcript(segs, char_limit=3000, overlap_chars=200)
    assert len(chunks) >= 3  # should get ~4 chunks
    # Verify chunk numbering
    for i, c in enumerate(chunks):
        assert c.chunk_id == i + 1
        assert c.chunk_count == len(chunks)
    # Verify continuity: each chunk's segment_end is >= previous or next chunk's segment_start
    for i in range(len(chunks) - 1):
        # With overlap, chunks may overlap segment ranges; but segment order should be increasing
        assert chunks[i].segment_start_index <= chunks[i + 1].segment_start_index
    # All segments covered
    assert chunks[0].segment_start_index == 0
    assert chunks[-1].segment_end_index == len(segs)


def test_chunk_has_metadata():
    """每个 chunk 包含正确的元数据字段。"""
    segs = _make_segments(80, chars_per_seg=200)
    chunks = chunk_transcript(segs, char_limit=3000, overlap_chars=200)
    for c in chunks:
        assert c.chunk_id > 0
        assert c.chunk_count == len(chunks)
        assert c.segment_start_index >= 0
        assert c.segment_end_index > c.segment_start_index
        assert c.start_time
        assert c.end_time
        assert c.char_count > 0
        assert c.segment_count > 0
        assert c.text  # should have text with header


def test_chunk_text_has_header():
    """Chunk text 包含格式化的 header。"""
    segs = _make_segments(80, chars_per_seg=200)
    chunks = chunk_transcript(segs, char_limit=3000, overlap_chars=200)
    for c in chunks:
        # Chinese header format: [第 N/M 段, 时间范围 HH:MM:SS-HH:MM:SS]
        assert "段" in c.text  # 表明有中文分段信息
        assert "时间范围" in c.text
        assert f"{c.chunk_id}/{c.chunk_count}" in c.text


def test_chunk_segments_text_format():
    """segments_text 格式为 [start-end] text。"""
    segs = _make_segments(10, chars_per_seg=50)
    chunks = chunk_transcript(segs, char_limit=2000, overlap_chars=100)
    for c in chunks:
        for line in c.segments_text.splitlines()[:1]:
            assert line.startswith("[")
            assert "] " in line


def test_chunk_overlap():
    """Overlap 生效：相邻 chunk 的 segment ranges 有重叠。"""
    segs = _make_segments(100, chars_per_seg=200)  # 20K chars
    chunks = chunk_transcript(segs, char_limit=3000, overlap_chars=400)
    assert len(chunks) >= 3
    # 相邻 chunks 的 segment_start 应该各递增（overlap 让下一个 chunk start 比上一个 chunk end 小）
    for i in range(len(chunks) - 1):
        # chunk[i].segment_end_index should be >= chunk[i+1].segment_start_index
        # because of overlap (next chunk starts before current ends)
        assert chunks[i].segment_end_index >= chunks[i + 1].segment_start_index


def test_chunk_empty_returns_empty():
    """空 segments 返回空列表。"""
    chunks = chunk_transcript([], char_limit=3000, overlap_chars=200)
    assert chunks == []


# ═════════════════════════════════════════════════════════════════════════════
# Dedup tests
# ═════════════════════════════════════════════════════════════════════════════

def test_dedup_views_same_key_merges():
    """同 key 的 views 去重合并。"""
    v1 = _make_view("NVIDIA", "bullish", strength="medium", ai_layer="semiconductor",
                    business="revenue_growth", source_quote="Revenue grew 50%")
    v2 = _make_view("NVIDIA", "bullish", strength="strong", ai_layer="semiconductor",
                    business="revenue_growth", source_quote="Revenue up 80%, margins expanding")

    deduped = _dedup_views([v1, v2])
    assert len(deduped) == 1
    # 应该保留 strong evidence 的 (v2)
    assert "strong" in deduped[0].evidence.evidence_strength
    # topic_tags 合并
    assert "GPU" in deduped[0].topic_tags
    assert "datacenter" in deduped[0].topic_tags


def test_dedup_views_different_keys_kept():
    """不同 key 的 views 保持不变。"""
    v1 = _make_view("NVIDIA", "bullish", ai_layer="semiconductor", business="revenue_growth")
    v2 = _make_view("TSMC", "bullish", ai_layer="semiconductor", business="capex_demand")
    v3 = _make_view("NVIDIA", "bearish", ai_layer="semiconductor", business="revenue_growth")

    deduped = _dedup_views([v1, v2, v3])
    assert len(deduped) == 3


def test_dedup_entities_by_normalized_name():
    """按 normalized_name 去重 entities，合并 aliases。"""
    e1 = Entity(name="NVIDIA Corp", normalized_name="NVIDIA", entity_type="company",
                aliases=["NVDA", "Nvidia"])
    e2 = Entity(name="NVIDIA Corporation", normalized_name="NVIDIA", entity_type="company",
                aliases=["Nvidia Corp", "Team Green"])

    deduped = _dedup_entities([e1, e2])
    assert len(deduped) == 1
    assert "NVDA" in deduped[0].aliases
    assert "Team Green" in deduped[0].aliases


def test_dedup_insights_merges_topic_tags():
    """同 ai_value_chain_layer + affected_entities overlap → 合并 topic_tags。"""
    i1 = TechIndustryInsight(
        insight="GPU supply improving",
        ai_value_chain_layer="semiconductor",
        affected_entities=["NVIDIA", "TSMC"],
        topic_tags=["GPU", "supply-chain"],
    )
    i2 = TechIndustryInsight(
        insight="Chip demand surging",
        ai_value_chain_layer="semiconductor",
        affected_entities=["NVIDIA", "AMD"],
        topic_tags=["GPU", "demand"],
    )

    deduped = _dedup_insights([i1, i2])
    assert len(deduped) == 1
    assert "supply-chain" in deduped[0].topic_tags
    assert "demand" in deduped[0].topic_tags


def test_dedup_risks_by_prefix():
    """同 target_name + description 前缀去重 risks。"""
    r1 = Risk(description="Supply chain disruption risk in Taiwan", target_name="TSMC")
    r2 = Risk(description="Supply chain disruption risk in China", target_name="TSMC")

    deduped = _dedup_risks([r1, r2])
    assert len(deduped) == 1  # same prefix → deduped


def test_dedup_signals_by_target_signal():
    """同 target_name + signal 去重。"""
    s1 = TrackingSignal(target_name="NVIDIA", signal="Watch Q2 earnings report")
    s2 = TrackingSignal(target_name="NVIDIA", signal="Watch Q2 earnings report")

    deduped = _dedup_signals([s1, s2])
    assert len(deduped) == 1


# ═════════════════════════════════════════════════════════════════════════════
# Compaction tests
# ═════════════════════════════════════════════════════════════════════════════

def test_compact_views_enforces_limit():
    """compaction 限制 views 数量。"""
    views = [_make_view(f"Target{i}", relevance=["high", "medium", "low"][i % 3])
             for i in range(20)]
    compacted = _compact_views(views, 5)
    assert len(compacted) == 5
    # high relevance should come first
    for v in compacted[:3]:
        assert v.investment_relevance == "high"


def test_compact_entities_prioritizes_company():
    """compaction 优先保留 company/technology 类型。"""
    entities = [
        Entity(name="NVIDIA", entity_type="company"),
        Entity(name="AI Industry", entity_type="industry_theme"),
        Entity(name="GDP", entity_type="metric"),
        Entity(name="TSMC", entity_type="company"),
        Entity(name="NASDAQ", entity_type="market"),
    ]
    compacted = _compact_entities(entities, 3)
    assert len(compacted) == 3
    # First 2 should be the company types
    assert compacted[0].entity_type == "company"
    assert compacted[1].entity_type == "company"


def test_compact_insights_prioritizes_high_implication():
    """compaction 优先高 implication insights。"""
    insights = [
        TechIndustryInsight(insight="Low impact", investment_implication="low"),
        TechIndustryInsight(insight="High impact", investment_implication="high"),
        TechIndustryInsight(insight="Medium impact", investment_implication="medium"),
    ]
    compacted = _compact_insights(insights, 2)
    assert len(compacted) == 2
    assert compacted[0].investment_implication == "high"
    assert compacted[1].investment_implication == "medium"


def test_compact_signals_prioritizes_with_trigger():
    """compaction 优先有 trigger_condition 的 signals。"""
    signals = [
        TrackingSignal(signal="Signal A", target_name="NVIDIA", trigger_condition=""),
        TrackingSignal(signal="Signal B", target_name="TSMC", trigger_condition="Q2 earnings"),
        TrackingSignal(signal="Signal C", target_name="AMD", trigger_condition=""),
        TrackingSignal(signal="Signal D", target_name="Intel", trigger_condition="New fab opening"),
    ]
    compacted = _compact_signals(signals, 3)
    assert len(compacted) == 3
    # First 2 should have trigger conditions
    assert compacted[0].trigger_condition
    assert compacted[1].trigger_condition


# ═════════════════════════════════════════════════════════════════════════════
# Merge tests
# ═════════════════════════════════════════════════════════════════════════════

def test_merge_empty_returns_empty():
    """空 chunk_results 返回空 ExtractionResult。"""
    merged = merge_extraction_results([])
    assert merged.investment_views == []
    assert merged.mentioned_entities == []
    assert merged.metadata.get("chunking") is True


def test_merge_single_result_passthrough():
    """单个 chunk 直接返回。"""
    result = ExtractionResult(
        investment_views=[_make_view("NVIDIA")],
        mentioned_entities=[Entity(name="NVIDIA", entity_type="company")],
        prompt_version="tech_ai_v2",
    )
    merged = merge_extraction_results([result])
    assert merged is result  # same object for single chunk
    assert len(merged.investment_views) == 1
    assert len(merged.mentioned_entities) == 1


def test_merge_dedups_cross_chunk_views():
    """跨 chunk 的同 key views 被合并。"""
    r1 = ExtractionResult(
        investment_views=[
            _make_view("NVIDIA", "bullish", ai_layer="semiconductor", business="revenue_growth",
                       strength="medium", source_quote="Revenue up 50%"),
        ],
        prompt_version="tech_ai_v2",
    )
    r2 = ExtractionResult(
        investment_views=[
            _make_view("NVIDIA", "bullish", ai_layer="semiconductor", business="revenue_growth",
                       strength="strong", source_quote="Revenue up 80%, record margins"),
        ],
        prompt_version="tech_ai_v2",
    )

    merged = merge_extraction_results([r1, r2])
    assert len(merged.investment_views) == 1
    assert merged.investment_views[0].evidence.evidence_strength == "strong"


def test_merge_preserves_total_count_in_metadata():
    """Merge metadata 包含 before/after 计数。"""
    r1 = ExtractionResult(
        investment_views=[_make_view(f"T{i}") for i in range(15)],
        mentioned_entities=[Entity(name=f"E{i}") for i in range(30)],
        prompt_version="tech_ai_v2",
    )
    r2 = ExtractionResult(
        investment_views=[_make_view(f"T{i+10}") for i in range(15)],
        mentioned_entities=[Entity(name=f"E{i+20}") for i in range(30)],
        prompt_version="tech_ai_v2",
    )

    merged = merge_extraction_results([r1, r2])
    meta = merged.metadata
    assert meta["chunking"] is True
    assert meta["chunk_count"] == 2
    assert meta["merge"]["before"]["views"] == 30
    assert meta["merge"]["after_compact"]["views"] <= MAX_MERGED_INVESTMENT_VIEWS


def test_merge_compaction_enforces_limits():
    """合并后不超过 compaction 上限。"""
    results = []
    for _i in range(5):
        extraction = ExtractionResult(
            investment_views=[_make_view(f"Target{j}") for j in range(10)],
            mentioned_entities=[Entity(name=f"Entity{j}") for j in range(30)],
            key_quotes=[f"Quote {j}" for j in range(20)],
            prompt_version="tech_ai_v2",
        )
        results.append(extraction)

    merged = merge_extraction_results(results)
    assert len(merged.investment_views) <= MAX_MERGED_INVESTMENT_VIEWS
    assert len(merged.mentioned_entities) <= MAX_MERGED_ENTITIES
    assert len(merged.key_quotes) <= 20


# ═════════════════════════════════════════════════════════════════════════════
# Pipeline integration tests (mock provider)
# ═════════════════════════════════════════════════════════════════════════════

def test_pipeline_short_transcript_no_chunking(db_session, tmp_path):
    """短字幕默认不走 chunking。"""
    from podcast_research.analysis.pipeline import analyze

    sample = Path(__file__).resolve().parent.parent / "data" / "subtitles" / "sample.srt"
    result = analyze(sample, provider_name="mock", output_dir=tmp_path)
    assert result["view_count"] > 0
    assert result["report_id"] > 0
    report_path = Path(result["report_path"])
    assert report_path.exists()


def test_pipeline_long_transcript_auto_chunking(db_session, tmp_path):
    """长字幕自动启用 chunking。"""
    # 生成超过 1000 段的合成字幕
    long_segs = _make_segments(1200, chars_per_seg=60)  # ~72K chars, >1000 segments

    from podcast_research.analysis.pipeline import _run_pipeline
    from podcast_research.config import ensure_dirs
    ensure_dirs()

    result = _run_pipeline(
        segments=long_segs,
        episode_title="long_test",
        source_path="test.txt",
        subtitle_format="txt",
        subtitle_hash="",
        provider_name="mock",
        output_dir=tmp_path,
        focus_areas=["AI投资"],
        analysis_depth="standard",
    )
    assert result["view_count"] >= 0
    assert result["report_id"] > 0
    report_path = Path(result["report_path"])
    assert report_path.exists()


def test_pipeline_chunked_config_forced(db_session, tmp_path):
    """chunking_config enabled=True 强制启用 chunking。"""
    from podcast_research.analysis.pipeline import analyze

    sample = Path(__file__).resolve().parent.parent / "data" / "subtitles" / "sample.srt"
    result = analyze(
        sample, provider_name="mock", output_dir=tmp_path,
        chunking_config={"enabled": True},
    )
    assert result["view_count"] > 0
    assert result["report_id"] > 0


def test_pipeline_no_chunking_config_forced(db_session, tmp_path):
    """chunking_config enabled=False 禁用 chunking。"""
    from podcast_research.analysis.pipeline import analyze

    sample = Path(__file__).resolve().parent.parent / "data" / "subtitles" / "sample.srt"
    result = analyze(
        sample, provider_name="mock", output_dir=tmp_path,
        chunking_config={"enabled": False},
    )
    assert result["view_count"] > 0
    assert result["report_id"] > 0


# ═════════════════════════════════════════════════════════════════════════════
# CLI chunking tests
# ═════════════════════════════════════════════════════════════════════════════

def test_cli_chunked_flag(db_session, tmp_path):
    """CLI --chunked 参数可用。"""
    from typer.testing import CliRunner

    from podcast_research.cli import app

    sample = Path(__file__).resolve().parent.parent / "data" / "subtitles" / "sample.srt"
    runner = CliRunner()
    result = runner.invoke(app, [
        "--subtitle-file", str(sample),
        "--mock",
        "--chunked",
        "-o", str(tmp_path),
    ])
    assert result.exit_code == 0
    assert "分析完成" in result.output


def test_cli_no_chunking_flag(db_session, tmp_path):
    """CLI --no-chunking 参数可用。"""
    from typer.testing import CliRunner

    from podcast_research.cli import app

    sample = Path(__file__).resolve().parent.parent / "data" / "subtitles" / "sample.srt"
    runner = CliRunner()
    result = runner.invoke(app, [
        "--subtitle-file", str(sample),
        "--mock",
        "--no-chunking",
        "-o", str(tmp_path),
    ])
    assert result.exit_code == 0
    assert "分析完成" in result.output
