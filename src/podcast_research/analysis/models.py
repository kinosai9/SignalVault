from __future__ import annotations

from pydantic import BaseModel, Field


class SubtitleSegment(BaseModel):
    segment_id: str
    start_time: str
    end_time: str
    text: str


class Evidence(BaseModel):
    evidence_type: str = Field(default="未给依据", description="行业数据/个人判断/财报/政策/估值/未给依据")
    evidence_detail: str = ""
    evidence_strength: str = Field(default="medium", description="strong/medium/weak")
    missing_info: str = ""


class InvestmentView(BaseModel):
    target_name: str
    target_type: str = Field(description="stock/fund/industry/macro/asset_class")
    ticker: str = ""
    market: str = ""
    view_direction: str = Field(description="bullish/bearish/neutral")
    view_direction_label: str = ""
    logic_chain: str
    time_horizon: str = ""
    confidence: str = "cautious"
    evidence: Evidence = Field(default_factory=Evidence)
    risk_warning: str = ""
    speaker_label: str = ""
    speaker_role: str = ""
    speaker_confidence: str = "low"
    source_quote: str
    timestamp_start: str
    timestamp_end: str = ""
    uncertainty: str = ""


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
    entity_type: str = ""
    aliases: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    metadata: dict = Field(default_factory=dict)
    source_info: dict = Field(default_factory=dict, description="数据来源信息：source_type, source_url, video_id, language, is_generated, channel_name, fetched_at, transcript_segment_count")
    focus_areas: list[str] = Field(default_factory=lambda: ["通用投资研究"], description="用户关注点列表")
    mentioned_entities: list[Entity] = Field(default_factory=list)
    investment_views: list[InvestmentView] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    tracking_signals: list[TrackingSignal] = Field(default_factory=list)
    key_quotes: list[str] = Field(default_factory=list)
    uncertain_items: list[str] = Field(default_factory=list)