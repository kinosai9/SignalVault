"""P2-A1: Pydantic 数据模型 — Tech/AI Investing Prompt v2 扩展。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SubtitleSegment(BaseModel):
    segment_id: str
    start_time: str
    end_time: str
    text: str


class Evidence(BaseModel):
    evidence_type: str = Field(default="unsupported_claim",
        description="financial_metric/valuation_metric/growth_metric/capex_or_infrastructure/market_structure/policy_or_regulation/technical_claim/expert_judgment/anecdotal_claim/unsupported_claim")
    evidence_detail: str = ""
    evidence_strength: str = Field(default="medium", description="strong/medium/weak")
    missing_info: str = ""


class InvestmentView(BaseModel):
    target_name: str
    normalized_target_name: str = ""
    target_type: str = Field(default="stock", description="stock/industry/macro/asset_class/product_or_model/technology")
    ticker: str = ""
    market: str = ""
    view_direction: str = Field(description="bullish/bearish/neutral")
    view_direction_label: str = ""
    logic_chain: str
    time_horizon: str = Field(default="unknown", description="immediate/short_term/medium_term/long_term/unknown")
    confidence: str = "cautious"
    evidence: Evidence = Field(default_factory=Evidence)
    risk_warning: str = ""
    speaker_label: str = Field(default="unknown_speaker")
    speaker_role: str = Field(default="podcast_participant")
    speaker_confidence: str = "low"
    source_quote: str
    timestamp_start: str
    timestamp_end: str = ""
    uncertainty: str = ""
    # P2-A1: Tech/AI 专用字段
    ai_value_chain_layer: str = Field(default="other",
        description="model/compute/semiconductor/cloud/data_center/power/application/agent/enterprise/robotics/regulation/capital_market/other")
    technology_driver: str = ""
    business_impact: str = Field(default="unknown",
        description="revenue_growth/margin_expansion/capex_demand/market_share/valuation_rerating/moat_expansion/disruption_risk/supply_constraint/policy_risk/unknown")
    investment_relevance: str = Field(default="medium", description="high/medium/low")
    topic_tags: list[str] = Field(default_factory=list)
    quote_support_strength: str = Field(default="medium", description="strong/medium/weak — source_quote 对观点的支撑程度")


class TechIndustryInsight(BaseModel):
    """P2-A1: 技术/产业洞察（尚未构成明确投资观点但有价值的趋势信息）。"""
    insight: str
    ai_value_chain_layer: str = "other"
    affected_entities: list[str] = Field(default_factory=list)
    investment_implication: str = Field(default="medium", description="high/medium/low/none")
    topic_tags: list[str] = Field(default_factory=list)
    source_quote: str = ""
    timestamp: str = ""


class Risk(BaseModel):
    description: str
    target_name: str = ""
    speaker_label: str = ""
    source_quote: str = ""
    timestamp: str = ""


class TrackingSignal(BaseModel):
    target_name: str = ""
    signal: str
    trigger_condition: str = ""
    expected_date: str = ""
    source_quote: str = ""
    timestamp: str = ""


class Entity(BaseModel):
    name: str
    normalized_name: str = ""
    entity_type: str = Field(default="",
        description="company/person/product_or_model/technology/industry_theme/asset_or_ticker/policy_or_regulation/metric/organization")
    aliases: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    metadata: dict = Field(default_factory=dict)
    source_info: dict = Field(default_factory=dict, description="数据来源信息")
    focus_areas: list[str] = Field(default_factory=lambda: ["通用投资研究"], description="用户关注点列表")
    prompt_version: str = Field(default="tech_ai_v2", description="使用的 prompt 版本标识")
    mentioned_entities: list[Entity] = Field(default_factory=list)
    investment_views: list[InvestmentView] = Field(default_factory=list)
    tech_industry_insights: list[TechIndustryInsight] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    tracking_signals: list[TrackingSignal] = Field(default_factory=list)
    key_quotes: list[str] = Field(default_factory=list)
    uncertain_items: list[str] = Field(default_factory=list)
    non_focus_items: list[str] = Field(default_factory=list)
