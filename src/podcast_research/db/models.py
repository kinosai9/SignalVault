from sqlalchemy import Column, Integer, String, Text, Boolean, Date, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime


class Base(DeclarativeBase):
    pass


class Episode(Base):
    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(50), default="local")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    subtitle_path: Mapped[str] = mapped_column(String(500), default="")
    subtitle_format: Mapped[str] = mapped_column(String(10), default="")
    subtitle_hash: Mapped[str] = mapped_column(String(64), default="")
    source_url: Mapped[str] = mapped_column(String(500), default="")
    video_id: Mapped[str] = mapped_column(String(50), default="")
    language: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[int] = mapped_column(Integer, nullable=False)
    report_version: Mapped[int] = mapped_column(Integer, default=1)
    focus_areas: Mapped[str] = mapped_column(Text, default="")
    analysis_depth: Mapped[str] = mapped_column(String(20), default="standard")
    llm_provider: Mapped[str] = mapped_column(String(50), default="mock")
    llm_model: Mapped[str] = mapped_column(String(100), default="mock-v1")
    prompt_version: Mapped[str] = mapped_column(String(50), default="v0.1")
    extraction_json: Mapped[str] = mapped_column(Text, nullable=False)
    report_markdown: Mapped[str] = mapped_column(Text, default="")
    executive_summary: Mapped[str] = mapped_column(Text, default="")
    analysis_timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class InvestmentViewRecord(Base):
    __tablename__ = "investment_views"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_name: Mapped[str] = mapped_column(String(200), default="")
    normalized_target_name: Mapped[str] = mapped_column(String(200), default="")
    target_type: Mapped[str] = mapped_column(String(50), default="")
    ticker: Mapped[str] = mapped_column(String(50), default="")
    market: Mapped[str] = mapped_column(String(50), default="")
    view_direction: Mapped[str] = mapped_column(String(50), default="")
    confidence: Mapped[str] = mapped_column(String(50), default="")
    time_horizon: Mapped[str] = mapped_column(String(50), default="")
    logic_chain: Mapped[str] = mapped_column(Text, default="")
    evidence_type: Mapped[str] = mapped_column(String(100), default="")
    evidence_detail: Mapped[str] = mapped_column(Text, default="")
    evidence_strength: Mapped[str] = mapped_column(String(50), default="")
    missing_info: Mapped[str] = mapped_column(Text, default="")
    risk_warning: Mapped[str] = mapped_column(Text, default="")
    speaker_label: Mapped[str] = mapped_column(String(100), default="")
    speaker_role: Mapped[str] = mapped_column(String(50), default="")
    speaker_confidence: Mapped[str] = mapped_column(String(50), default="")
    source_quote: Mapped[str] = mapped_column(Text, default="")
    timestamp_start: Mapped[str] = mapped_column(String(20), default="")
    timestamp_end: Mapped[str] = mapped_column(String(20), default="")
    # P2-A1: Tech/AI 专用字段
    ai_value_chain_layer: Mapped[str] = mapped_column(String(50), default="other")
    technology_driver: Mapped[str] = mapped_column(Text, default="")
    business_impact: Mapped[str] = mapped_column(String(50), default="unknown")
    investment_relevance: Mapped[str] = mapped_column(String(10), default="medium")
    topic_tags: Mapped[str] = mapped_column(Text, default="[]")
    quote_support_strength: Mapped[str] = mapped_column(String(10), default="medium")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class TrackingSignalRecord(Base):
    __tablename__ = "tracking_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_name: Mapped[str] = mapped_column(String(200), default="")
    signal: Mapped[str] = mapped_column(Text, default="")
    trigger_condition: Mapped[str] = mapped_column(Text, default="")
    expected_date: Mapped[str] = mapped_column(String(50), default="")
    status: Mapped[str] = mapped_column(String(20), default="open")
    source_quote: Mapped[str] = mapped_column(Text, default="")
    timestamp: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class EntityRecord(Base):
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), default="")
    entity_type: Mapped[str] = mapped_column(String(50), default="")
    aliases: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Channel(Base):
    """P1-F: 关注的 YouTube 频道（tags/priority/default_focus/limits）"""

    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    youtube_channel_id: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(500), default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    tags: Mapped[str] = mapped_column(Text, default="[]")
    priority: Mapped[str] = mapped_column(String(20), default="secondary")
    default_focus: Mapped[str] = mapped_column(Text, default="")
    default_limit: Mapped[int] = mapped_column(Integer, default=10)
    default_max_analyze: Mapped[int] = mapped_column(Integer, default=3)
    notes: Mapped[str] = mapped_column(Text, default="")
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChannelVideo(Base):
    """P1-E: 频道视频列表（元数据，非字幕）"""

    __tablename__ = "channel_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(Integer, nullable=False)
    video_id: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    published_at: Mapped[str] = mapped_column(String(30), default="")
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="new")
    report_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)