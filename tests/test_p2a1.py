"""P2-A1: Tech/AI Prompt v2 + model extension tests."""

import json

# --- Model backward compatibility ---

def test_investment_view_defaults_v2():
    """新字段有合理默认值，不影响旧调用。"""
    from podcast_research.analysis.models import InvestmentView
    v = InvestmentView(
        target_name="NVIDIA",
        view_direction="bullish",
        logic_chain="GPU demand continues to grow",
        source_quote="We're seeing unprecedented demand",
        timestamp_start="00:12:30",
    )
    assert v.time_horizon == "unknown"
    assert v.speaker_label == "unknown_speaker"
    assert v.speaker_role == "podcast_participant"
    assert v.ai_value_chain_layer == "other"
    assert v.business_impact == "unknown"
    assert v.investment_relevance == "medium"
    assert v.topic_tags == []
    assert v.quote_support_strength == "medium"
    assert v.normalized_target_name == ""


def test_evidence_type_enum_v2():
    """evidence_type 用新枚举值。"""
    from podcast_research.analysis.models import Evidence
    e = Evidence(evidence_type="financial_metric", evidence_detail="Q3 revenue $35.1B")
    assert e.evidence_type == "financial_metric"


def test_extraction_result_has_v2_fields():
    """ExtractionResult 包含 prompt_version / tech_industry_insights / non_focus_items。"""
    from podcast_research.analysis.models import ExtractionResult
    e = ExtractionResult()
    assert e.prompt_version == "tech_ai_v2"
    assert e.tech_industry_insights == []
    assert e.non_focus_items == []


def test_tech_industry_insight_serializable():
    from podcast_research.analysis.models import TechIndustryInsight
    ins = TechIndustryInsight(
        insight="Reasoning models are reducing inference costs by 10x year-over-year",
        ai_value_chain_layer="model",
        affected_entities=["OpenAI", "Anthropic"],
        investment_implication="high",
        source_quote="the cost of reasoning is dropping dramatically",
        timestamp="00:15:30",
    )
    d = ins.model_dump()
    assert d["insight"]
    assert d["ai_value_chain_layer"] == "model"
    assert "OpenAI" in d["affected_entities"]


def test_non_focus_items_serializable():
    from podcast_research.analysis.models import ExtractionResult
    e = ExtractionResult(non_focus_items=["洛杉矶市政预算讨论", "纽约第二居所税提案"])
    d = e.model_dump()
    assert len(d["non_focus_items"]) == 2


def test_entity_type_enum_v2():
    from podcast_research.analysis.models import Entity
    e = Entity(name="NVIDIA", normalized_name="NVIDIA", entity_type="company")
    assert e.entity_type == "company"


# --- Backward compat: old JSON without new fields ---

def test_extraction_result_from_old_json():
    """旧 JSON（无 prompt_version/tech_industry_insights/non_focus_items）仍可加载。"""
    from podcast_research.analysis.models import ExtractionResult
    old_json = {
        "metadata": {"source": "test"},
        "focus_areas": ["新能源"],
        "mentioned_entities": [{"name": "宁德时代", "entity_type": "stock"}],
        "investment_views": [{
            "target_name": "宁德时代",
            "target_type": "stock",
            "view_direction": "bullish",
            "logic_chain": "储能需求增长",
            "source_quote": "关于宁德时代的原文",
            "timestamp_start": "00:32:10",
        }],
        "risks": [],
        "tracking_signals": [],
        "key_quotes": [],
        "uncertain_items": [],
    }
    result = ExtractionResult.model_validate(old_json)
    assert result.prompt_version == "tech_ai_v2"  # default
    assert result.tech_industry_insights == []
    assert result.non_focus_items == []
    assert len(result.investment_views) == 1


def test_investment_view_from_old_json():
    """旧 JSON（无时间范围/speaker fallback 字段）仍可加载。"""
    from podcast_research.analysis.models import InvestmentView
    old_json = {
        "target_name": "NVIDIA",
        "view_direction": "bullish",
        "logic_chain": "GPU demand strong",
        "source_quote": "We are seeing demand",
        "timestamp_start": "00:10:00",
    }
    v = InvestmentView.model_validate(old_json)
    assert v.time_horizon == "unknown"
    assert v.speaker_label == "unknown_speaker"


# --- Prompt content tests ---

def test_prompt_contains_investment_boundary_rules():
    from podcast_research.llm.prompts import EXTRACT_FACTS_SYSTEM
    assert "investment_views" in EXTRACT_FACTS_SYSTEM
    assert "tech_industry_insights" in EXTRACT_FACTS_SYSTEM
    assert "non_focus_items" in EXTRACT_FACTS_SYSTEM
    assert "ai_value_chain_layer" in EXTRACT_FACTS_SYSTEM
    assert "evidence_type" in EXTRACT_FACTS_SYSTEM
    assert "financial_metric" in EXTRACT_FACTS_SYSTEM
    assert "unsupported_claim" in EXTRACT_FACTS_SYSTEM


def test_prompt_contains_speaker_fallback():
    from podcast_research.llm.prompts import EXTRACT_FACTS_SYSTEM
    assert "unknown_speaker" in EXTRACT_FACTS_SYSTEM
    assert "podcast_participant" in EXTRACT_FACTS_SYSTEM


def test_prompt_contains_time_horizon_rules():
    from podcast_research.llm.prompts import EXTRACT_FACTS_SYSTEM
    assert "immediate" in EXTRACT_FACTS_SYSTEM
    assert "short_term" in EXTRACT_FACTS_SYSTEM
    assert "medium_term" in EXTRACT_FACTS_SYSTEM
    assert "long_term" in EXTRACT_FACTS_SYSTEM
    assert "unknown" in EXTRACT_FACTS_SYSTEM


def test_prompt_contains_entity_normalization():
    from podcast_research.llm.prompts import EXTRACT_FACTS_SYSTEM
    assert "NVIDIA" in EXTRACT_FACTS_SYSTEM
    assert "Alphabet" in EXTRACT_FACTS_SYSTEM


def test_prompt_contains_report_structure():
    from podcast_research.llm.prompts import RENDER_REPORT_SYSTEM
    assert "免责声明" in RENDER_REPORT_SYSTEM or "disclaimer" in RENDER_REPORT_SYSTEM.lower()
    assert "Tech/Industry Insights" in RENDER_REPORT_SYSTEM
    assert "Non-focus" in RENDER_REPORT_SYSTEM


def test_prompt_contains_focus_areas_placeholder():
    from podcast_research.llm.prompts import EXTRACT_FACTS_USER
    assert "{focus_areas}" in EXTRACT_FACTS_USER


# --- Mock provider v2 tests ---

def test_mock_provider_outputs_v2_fields():
    """mock provider 输出包含新字段。"""
    from pathlib import Path

    from podcast_research.llm.mock_provider import MockLLMProvider
    from podcast_research.subtitles.cleaner import clean_segments
    from podcast_research.subtitles.parser import parse_subtitle

    sample_path = Path(__file__).resolve().parent.parent / "data" / "subtitles" / "sample.srt"
    segments = parse_subtitle(sample_path)
    cleaned = clean_segments(segments)
    segments_text = "\n".join(f"[{s.start_time}-{s.end_time}] {s.text}" for s in cleaned)

    provider = MockLLMProvider()
    result = provider.extract_facts("", segments_text)

    assert result.prompt_version == "tech_ai_v2"
    assert hasattr(result, "tech_industry_insights")
    assert result.non_focus_items == []


def test_mock_report_contains_tech_insights_section():
    """mock 报告包含 Tech/Industry Insights 章节。"""
    from podcast_research.analysis.models import ExtractionResult, TechIndustryInsight
    from podcast_research.llm.mock_provider import MockLLMProvider

    extraction = ExtractionResult(
        metadata={"source": "mock"},
        prompt_version="tech_ai_v2",
        tech_industry_insights=[
            TechIndustryInsight(
                insight="推理成本每年下降 10x",
                ai_value_chain_layer="model",
                investment_implication="high",
                source_quote="reasoning cost dropping 10x per year",
                timestamp="00:15:00",
            )
        ],
    )
    provider = MockLLMProvider()
    md = provider.render_report(extraction)
    assert "Tech/Industry Insights" in md
    assert "推理成本每年下降 10x" in md


def test_mock_report_contains_non_focus_items_section():
    """mock 报告包含 Non-focus Items 章节。"""
    from podcast_research.analysis.models import ExtractionResult
    from podcast_research.llm.mock_provider import MockLLMProvider

    extraction = ExtractionResult(
        metadata={"source": "mock"},
        prompt_version="tech_ai_v2",
        non_focus_items=["洛杉矶市政预算", "纽约第二居所税"],
    )
    provider = MockLLMProvider()
    md = provider.render_report(extraction)
    assert "Non-focus Items" in md
    assert "洛杉矶市政预算" in md


def test_mock_report_v2_has_expanded_columns():
    """mock 报告矩阵表格包含 AI 价值链/商业影响/证据强度/时间范围列。"""
    from podcast_research.analysis.models import (
        ExtractionResult,
        InvestmentView,
    )
    from podcast_research.llm.mock_provider import MockLLMProvider

    extraction = ExtractionResult(
        metadata={"source": "mock"},
        prompt_version="tech_ai_v2",
        investment_views=[
            InvestmentView(
                target_name="NVIDIA",
                view_direction="bullish",
                logic_chain="GPU demand growing",
                source_quote="We see strong demand",
                timestamp_start="00:10:00",
                time_horizon="medium_term",
                ai_value_chain_layer="semiconductor",
                business_impact="revenue_growth",
            )
        ],
    )
    provider = MockLLMProvider()
    md = provider.render_report(extraction)
    assert "AI价值链" in md
    assert "商业影响" in md


# --- Repository tests ---

def test_save_investment_views_v2_fields(db_session):
    """入库的 investment_view 包含 P2-A1 新字段。"""
    from podcast_research.analysis.models import (
        Evidence,
        ExtractionResult,
        InvestmentView,
    )
    from podcast_research.db.models import InvestmentViewRecord
    from podcast_research.db.repository import (
        save_episode,
        save_investment_views,
        save_report,
    )

    ep_id = save_episode(db_session, "test", "test.srt", "srt", "hash")
    extraction = ExtractionResult(
        metadata={"source": "test"},
        focus_areas=["AI投资"],
        prompt_version="tech_ai_v2",
        investment_views=[
            InvestmentView(
                target_name="NVIDIA",
                normalized_target_name="NVIDIA",
                view_direction="bullish",
                logic_chain="强劲 GPU 需求",
                source_quote="demand is incredible",
                timestamp_start="00:10:00",
                time_horizon="medium_term",
                ai_value_chain_layer="semiconductor",
                business_impact="revenue_growth",
                investment_relevance="high",
                topic_tags=["ai-infra", "nvidia"],
                quote_support_strength="strong",
                evidence=Evidence(evidence_type="financial_metric", evidence_detail="Q3 rev $35.1B", evidence_strength="strong"),
            )
        ],
    )
    rep_id = save_report(db_session, ep_id, extraction, "# Test Report", "mock", llm_model="mock-v2")
    save_investment_views(db_session, rep_id, extraction.investment_views)
    db_session.commit()

    rec = db_session.query(InvestmentViewRecord).filter_by(report_id=rep_id).first()
    assert rec.ai_value_chain_layer == "semiconductor"
    assert rec.business_impact == "revenue_growth"
    assert rec.investment_relevance == "high"
    assert rec.quote_support_strength == "strong"
    assert json.loads(rec.topic_tags) == ["ai-infra", "nvidia"]


# --- P2-A1 Hardening tests ---

def test_prompt_contains_broad_target_restriction():
    """prompt 禁止过于宽泛的 target_name。"""
    from podcast_research.llm.prompts import EXTRACT_FACTS_SYSTEM
    assert "Broad Market" in EXTRACT_FACTS_SYSTEM
    assert "target_name 限制" in EXTRACT_FACTS_SYSTEM
    assert "AI Industry" in EXTRACT_FACTS_SYSTEM
    assert "Technology Sector" in EXTRACT_FACTS_SYSTEM
    assert "Economy" in EXTRACT_FACTS_SYSTEM
    assert "S&P 500" in EXTRACT_FACTS_SYSTEM  # concrete alternative


def test_prompt_contains_investment_relevance_grading():
    """prompt 包含 investment_relevance 分级规则。"""
    from podcast_research.llm.prompts import EXTRACT_FACTS_SYSTEM
    assert "investment_relevance 分级规则" in EXTRACT_FACTS_SYSTEM
    assert "40%" in EXTRACT_FACTS_SYSTEM  # 不超过 40% high
    assert "unsupported_claim" in EXTRACT_FACTS_SYSTEM
    assert "不得高于 medium" in EXTRACT_FACTS_SYSTEM


def test_tech_industry_insight_has_topic_tags():
    """TechIndustryInsight 模型包含 topic_tags 字段。"""
    from podcast_research.analysis.models import TechIndustryInsight
    ins = TechIndustryInsight(
        insight="推理成本下降",
        topic_tags=["model", "inference"],
    )
    assert ins.topic_tags == ["model", "inference"]
    d = ins.model_dump()
    assert "topic_tags" in d
    assert d["topic_tags"] == ["model", "inference"]


def test_tech_industry_insight_topic_tags_default():
    """TechIndustryInsight topic_tags 默认为空列表。"""
    from podcast_research.analysis.models import TechIndustryInsight
    ins = TechIndustryInsight(insight="test")
    assert ins.topic_tags == []


def test_mock_report_shows_insight_topic_tags():
    """mock 报告展示 insight topic_tags。"""
    from podcast_research.analysis.models import ExtractionResult, TechIndustryInsight
    from podcast_research.llm.mock_provider import MockLLMProvider

    extraction = ExtractionResult(
        metadata={"source": "mock"},
        prompt_version="tech_ai_v2",
        tech_industry_insights=[
            TechIndustryInsight(
                insight="推理成本每年下降 10x",
                ai_value_chain_layer="model",
                topic_tags=["model", "inference"],
                investment_implication="high",
            )
        ],
    )
    provider = MockLLMProvider()
    md = provider.render_report(extraction)
    assert "#model" in md
    assert "#inference" in md


def test_mock_insights_have_topic_tags():
    """mock provider 的 _extract_insights 生成 topic_tags。"""
    from pathlib import Path

    from podcast_research.llm.mock_provider import MockLLMProvider
    from podcast_research.subtitles.cleaner import clean_segments
    from podcast_research.subtitles.parser import parse_subtitle

    sample_path = Path(__file__).resolve().parent.parent / "data" / "subtitles" / "sample.srt"
    segments = parse_subtitle(sample_path)
    cleaned = clean_segments(segments)
    segments_text = "\n".join(f"[{s.start_time}-{s.end_time}] {s.text}" for s in cleaned)

    provider = MockLLMProvider()
    result = provider.extract_facts("", segments_text)
    for ins in result.tech_industry_insights:
        assert isinstance(ins.topic_tags, list)


def test_prompt_schema_has_insight_topic_tags():
    """JSON schema 中的 tech_industry_insights 包含 topic_tags。"""
    from podcast_research.llm.prompts import EXTRACT_FACTS_SYSTEM
    # tech_industry_insights schema block should list topic_tags
    assert '"topic_tags": [...]' in EXTRACT_FACTS_SYSTEM


# --- Provider base test ---

def test_llm_provider_extract_facts_supports_focus_areas():
    from podcast_research.llm.mock_provider import MockLLMProvider
    provider = MockLLMProvider()
    result = provider.extract_facts("一些文本", "[00:00-00:05] 一些文本", focus_areas=["AI投资"])
    assert result is not None
