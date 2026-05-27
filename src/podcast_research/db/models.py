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