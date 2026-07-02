from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
    evidence_page: Mapped[int | None] = mapped_column(Integer, nullable=True)  # P4-B: PDF page number
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
    """P1-F / P2-M.1: 关注的 YouTube 频道（tags/priority/default_focus/limits/is_active/default_depth）"""

    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    youtube_channel_id: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(500), default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    tags: Mapped[str] = mapped_column(Text, default="[]")
    priority: Mapped[str] = mapped_column(String(20), default="secondary")  # core / watch / archive
    default_focus: Mapped[str] = mapped_column(Text, default="")
    default_depth: Mapped[str] = mapped_column(String(20), default="standard")  # P2-M.1
    default_limit: Mapped[int] = mapped_column(Integer, default=10)
    default_max_analyze: Mapped[int] = mapped_column(Integer, default=3)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # P2-M.1
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChannelVideo(Base):
    """P1-E / P2-M.1: 频道视频列表（元数据，非字幕）"""

    __tablename__ = "channel_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(Integer, nullable=False)
    video_id: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    published_at: Mapped[str] = mapped_column(String(30), default="")
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="new")  # new / analyzed / synced / skipped / failed
    report_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # P2-M.1
    failure_reason: Mapped[str] = mapped_column(Text, default="")  # P2-M.1
    active_job_id: Mapped[str | None] = mapped_column(String(20), nullable=True)  # P2-M.2
    last_job_id: Mapped[str | None] = mapped_column(String(20), nullable=True)  # P2-M.4.1
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Job(Base):
    """P2-O.2: Persisted background job record (analysis / sync / full_flow / channel_refresh)."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    job_type: Mapped[str] = mapped_column(String(20), default="analysis")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    stage: Mapped[str] = mapped_column(String(50), default="queued")
    title: Mapped[str] = mapped_column(String(200), default="")
    source_url: Mapped[str] = mapped_column(String(500), default="")
    youtube_url: Mapped[str] = mapped_column(String(500), default="")
    focus_areas: Mapped[str] = mapped_column(Text, default="[]")
    depth: Mapped[str] = mapped_column(String(20), default="standard")
    mock: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_sync: Mapped[bool] = mapped_column(Boolean, default=False)
    report_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source_type: Mapped[str] = mapped_column(String(20), default="")
    source_channel_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_id: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class JobEvent(Base):
    """P2-O.2: Persisted job event log (timeline / failure diagnosis)."""

    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    level: Mapped[str] = mapped_column(String(10), default="info")  # info / warning / error
    stage: Mapped[str] = mapped_column(String(50), default="")
    message: Mapped[str] = mapped_column(String(500), default="")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class TrackedSource(Base):
    """P2-S.3.2 / P2-S.3.2.1: Persistent tracked external source (e.g. allin-podcast-zh-notes)."""

    __tablename__ = "tracked_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(500), default="")
    provider: Mapped[str] = mapped_column(String(100), default="")
    source_kind: Mapped[str] = mapped_column(String(50), default="external_html")
    homepage_url: Mapped[str] = mapped_column(String(500), default="")
    adapter_name: Mapped[str] = mapped_column(String(100), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active/degraded/failed/disabled
    default_import_policy: Mapped[str] = mapped_column(String(20), default="")
    # P2-S.3.2.1: Profiling metadata
    discovery_strategy: Mapped[str] = mapped_column(String(50), default="")
    identity_strategy: Mapped[str] = mapped_column(String(50), default="")
    change_detection_strategy: Mapped[str] = mapped_column(String(50), default="")
    profile_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    profiled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    profile_warnings: Mapped[str] = mapped_column(Text, default="")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    entries_discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    entries_imported_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class TrackedSourceEntry(Base):
    """P2-S.3.2: Individual entry discovered from a tracked source."""

    __tablename__ = "tracked_source_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tracked_source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    slug: Mapped[str] = mapped_column(String(200), default="")
    published_at: Mapped[str] = mapped_column(String(30), default="")
    detected_youtube_video_id: Mapped[str] = mapped_column(String(50), default="")
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="new")  # new/existing/preview_ready/imported/skipped/failed
    preview_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    error_message: Mapped[str] = mapped_column(Text, default="")


class IngestJob(Base):
    """P3-A: Persistent ingest job — replaces _preview_store / _file_preview_store.

    Each ingest task (URL import, file upload, tracked source entry, source profile)
    is a row in this table. Survives server restart.
    """

    __tablename__ = "ingest_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Identity
    job_key: Mapped[str] = mapped_column(String(256), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
        # url_import / file_upload / tracked_entry / source_profile
    source_url: Mapped[str] = mapped_column(String(500), default="")
    source_hash: Mapped[str] = mapped_column(String(64), default="")
    source_name: Mapped[str] = mapped_column(String(500), default="")

    # Status
    status: Mapped[str] = mapped_column(String(30), default="pending_preview")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    # Preview data (JSON-serialized ImportPreview / FileImportPreview / SourceProfile)
    preview_data: Mapped[str] = mapped_column(Text, default="")
    preview_id: Mapped[str] = mapped_column(String(20), default="")

    # User action
    action: Mapped[str] = mapped_column(String(50), default="")
    action_label: Mapped[str] = mapped_column(String(100), default="")

    # Result
    result_path: Mapped[str] = mapped_column(String(500), default="")
    result_message: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str] = mapped_column(Text, default="")

    # References
    tracked_source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tracked_entry_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ReviewItem(Base):
    """P3-B/C: Review item for human-triage of lint issues, duplicates, patches, etc.

    Unified review queue across vault lint, patch proposals, entity merge candidates,
    duplicate reports, and manual items.
    """

    __tablename__ = "review_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    item_type: Mapped[str] = mapped_column(String(40), nullable=False)
        # lint_frontmatter_invalid / lint_frontmatter_missing / lint_dead_wikilink
        # lint_duplicate_report / lint_orphan_card / entity_duplicate_candidate
        # patch_review / manual

    severity: Mapped[str] = mapped_column(String(10), default="warning")
        # error / warning / info

    status: Mapped[str] = mapped_column(String(20), default="open")
        # open / accepted / skipped / resolved

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")

    # Source reference
    source_ref: Mapped[str] = mapped_column(String(200), default="")
        # e.g. "lint:frontmatter_invalid" or "patch:patch_id_xxx"
    source_path: Mapped[str] = mapped_column(String(500), default="")
        # vault-relative path to the file that triggered this item

    # Suggested action (JSON)
    suggested_action_json: Mapped[str] = mapped_column(Text, default="")

    # Resolution
    resolution_note: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class KnowledgeNode(Base):
    """P5-B: Lightweight knowledge graph node.

    Each row represents one entity in the knowledge graph: a report, source,
    company, topic, person, investment_view, tracking_signal, or evidence.
    node_key is globally unique and used for edge references.
    """

    __tablename__ = "knowledge_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_key: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    node_type: Mapped[str] = mapped_column(String(40), nullable=False)
        # report / source / company / topic / person /
        # investment_view / tracking_signal / evidence
    label: Mapped[str] = mapped_column(String(500), default="")
    normalized_label: Mapped[str] = mapped_column(String(500), default="")
    source_ref: Mapped[str] = mapped_column(String(200), default="")
        # e.g. "report:15" or "entity:NVIDIA"
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class KnowledgeEdge(Base):
    """P5-B: Lightweight knowledge graph edge.

    Each row represents a directed relationship between two nodes.
    edge_key is globally unique and used for dedup on rebuild.
    """

    __tablename__ = "knowledge_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    edge_key: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    source_node_key: Mapped[str] = mapped_column(String(256), nullable=False)
    target_node_key: Mapped[str] = mapped_column(String(256), nullable=False)
    edge_type: Mapped[str] = mapped_column(String(40), nullable=False)
        # mentioned_in / derived_from / supports / related_to /
        # tracks / cites_page / cites_timestamp
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    evidence_ref: Mapped[str] = mapped_column(String(200), default="")
        # e.g. "view:123" or "signal:45"
    report_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_type: Mapped[str] = mapped_column(String(20), default="")
    source_path: Mapped[str] = mapped_column(String(500), default="")
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timestamp: Mapped[str] = mapped_column(String(20), default="")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
