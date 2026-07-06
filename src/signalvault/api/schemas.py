"""Pydantic response schemas for FastAPI."""

from datetime import datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    app: str
    database: str


class ReportItem(BaseModel):
    id: int
    created_at: datetime | None
    source_type: str
    title: str
    video_id: str
    source_url: str
    focus_areas: list[str]
    analysis_depth: str
    view_count: int
    entity_count: int


class ReportListResponse(BaseModel):
    items: list[ReportItem]
    count: int


class InvestmentViewOut(BaseModel):
    target_name: str
    target_type: str
    view_direction: str
    logic_chain: str
    source_quote: str
    timestamp_start: str
    risk_warning: str
    evidence_strength: str = ""
    evidence_type: str = ""
    confidence: str = ""
    speaker_label: str = ""


class TrackingSignalOut(BaseModel):
    target_name: str
    signal: str
    trigger_condition: str
    source_quote: str = ""
    timestamp: str = ""


class ReportDetailResponse(BaseModel):
    id: int
    episode_title: str
    source_type: str
    source_url: str
    video_id: str
    language: str
    focus_areas: list[str]
    analysis_depth: str
    llm_provider: str
    llm_model: str
    created_at: datetime | None
    report_markdown: str
    views: list[InvestmentViewOut]
    signals: list[TrackingSignalOut]


class EntityItem(BaseModel):
    name: str
    normalized_name: str
    entity_type: str
    aliases: list[str]


class TargetItem(BaseModel):
    target_name: str
    count: int
    last_seen: datetime | None
    last_direction: str


class SourceItem(BaseModel):
    source_type: str
    count: int
    last_report_at: datetime | None


class SearchResultItem(BaseModel):
    report_id: int
    match_type: str
    match_excerpt: str
    source_type: str
    created_at: datetime | None


class SearchResponse(BaseModel):
    keyword: str
    results: list[SearchResultItem]
    count: int
