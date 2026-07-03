from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from podcast_research.config import DB_PATH
from podcast_research.db.models import Base

_engine = None
_SessionLocal = None


def init_engine(db_path: str | None = None) -> None:
    global _engine, _SessionLocal
    path = db_path or str(DB_PATH)
    _engine = create_engine(f"sqlite:///{path}", echo=False)
    _SessionLocal = sessionmaker(bind=_engine)


def _migrate_episodes_table(engine) -> None:
    """为 episodes 表补齐 P0-B 新增列（source_url, video_id, language）。"""
    insp = inspect(engine)
    if "episodes" not in insp.get_table_names():
        return
    existing = {col["name"] for col in insp.get_columns("episodes")}
    with engine.begin() as conn:
        for col_name, col_type in [("source_url", "VARCHAR(500)"), ("video_id", "VARCHAR(50)"), ("language", "VARCHAR(20)")]:
            if col_name not in existing:
                conn.execute(text(f"ALTER TABLE episodes ADD COLUMN {col_name} {col_type} DEFAULT ''"))


def _migrate_channels_table(engine) -> None:
    """为 channels 表补齐 P1-F / P2-M.1 新增列。"""
    insp = inspect(engine)
    if "channels" not in insp.get_table_names():
        return
    existing = {col["name"] for col in insp.get_columns("channels")}
    migrations = [
        ("tags", "TEXT DEFAULT '[]'"),
        ("priority", "VARCHAR(20) DEFAULT 'secondary'"),
        ("default_focus", "TEXT DEFAULT ''"),
        ("default_limit", "INTEGER DEFAULT 10"),
        ("default_max_analyze", "INTEGER DEFAULT 3"),
        ("notes", "TEXT DEFAULT ''"),
        # P2-M.1
        ("default_depth", "VARCHAR(20) DEFAULT 'standard'"),
        ("is_active", "BOOLEAN DEFAULT 1"),
    ]
    with engine.begin() as conn:
        for col_name, col_type in migrations:
            if col_name not in existing:
                conn.execute(text(f"ALTER TABLE channels ADD COLUMN {col_name} {col_type}"))


def _migrate_channel_videos_table(engine) -> None:
    """为 channel_videos 表补齐 P2-M.1 新增列。"""
    insp = inspect(engine)
    if "channel_videos" not in insp.get_table_names():
        return
    existing = {col["name"] for col in insp.get_columns("channel_videos")}
    migrations = [
        ("last_checked_at", "DATETIME"),
        ("failure_reason", "TEXT DEFAULT ''"),
        ("active_job_id", "VARCHAR(20)"),
        ("last_job_id", "VARCHAR(20)"),
    ]
    with engine.begin() as conn:
        for col_name, col_type in migrations:
            if col_name not in existing:
                conn.execute(text(f"ALTER TABLE channel_videos ADD COLUMN {col_name} {col_type}"))


def _migrate_investment_views_table(engine) -> None:
    """为 investment_views 表补齐 P2-A1 + P4-B 新增列。"""
    insp = inspect(engine)
    if "investment_views" not in insp.get_table_names():
        return
    existing = {col["name"] for col in insp.get_columns("investment_views")}
    migrations = [
        ("ai_value_chain_layer", "VARCHAR(50) DEFAULT 'other'"),
        ("technology_driver", "TEXT DEFAULT ''"),
        ("business_impact", "VARCHAR(50) DEFAULT 'unknown'"),
        ("investment_relevance", "VARCHAR(10) DEFAULT 'medium'"),
        ("topic_tags", "TEXT DEFAULT '[]'"),
        ("quote_support_strength", "VARCHAR(10) DEFAULT 'medium'"),
        ("evidence_page", "INTEGER"),  # P4-B: PDF page number
    ]
    with engine.begin() as conn:
        for col_name, col_type in migrations:
            if col_name not in existing:
                conn.execute(text(f"ALTER TABLE investment_views ADD COLUMN {col_name} {col_type}"))


def _migrate_tracked_sources_tables(engine) -> None:
    """P2-S.3.2: Create tracked_sources and tracked_source_entries tables if needed."""
    insp = inspect(engine)
    existing_tables = insp.get_table_names()

    if "tracked_sources" not in existing_tables:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE tracked_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(500) DEFAULT '',
                    provider VARCHAR(100) DEFAULT '',
                    source_kind VARCHAR(50) DEFAULT 'external_html',
                    homepage_url VARCHAR(500) DEFAULT '',
                    adapter_name VARCHAR(100) DEFAULT '',
                    enabled BOOLEAN DEFAULT 1,
                    status VARCHAR(20) DEFAULT 'active',
                    default_import_policy VARCHAR(20) DEFAULT '',
                    last_checked_at DATETIME,
                    last_success_at DATETIME,
                    last_error TEXT DEFAULT '',
                    entries_discovered_count INTEGER DEFAULT 0,
                    entries_imported_count INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))

    # P2-S.3.2.1: Add profiling columns to existing tracked_sources table
    if "tracked_sources" in existing_tables:
        existing_cols = {c["name"] for c in insp.get_columns("tracked_sources")}
        profiling_migrations = [
            ("discovery_strategy", "VARCHAR(50) DEFAULT ''"),
            ("identity_strategy", "VARCHAR(50) DEFAULT ''"),
            ("change_detection_strategy", "VARCHAR(50) DEFAULT ''"),
            ("profile_confidence", "FLOAT"),
            ("profiled_at", "DATETIME"),
            ("profile_warnings", "TEXT DEFAULT ''"),
        ]
        with engine.begin() as conn:
            for col_name, col_type in profiling_migrations:
                if col_name not in existing_cols:
                    conn.execute(text(
                        f"ALTER TABLE tracked_sources ADD COLUMN {col_name} {col_type}"
                    ))

    if "tracked_source_entries" not in existing_tables:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE tracked_source_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tracked_source_id INTEGER NOT NULL,
                    title VARCHAR(500) DEFAULT '',
                    url VARCHAR(500) DEFAULT '',
                    slug VARCHAR(200) DEFAULT '',
                    published_at VARCHAR(30) DEFAULT '',
                    detected_youtube_video_id VARCHAR(50) DEFAULT '',
                    content_hash VARCHAR(64),
                    status VARCHAR(20) DEFAULT 'new',
                    preview_id VARCHAR(20),
                    last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    error_message TEXT DEFAULT ''
                )
            """))


def _migrate_ingest_jobs_table(engine) -> None:
    """P3-A: Create ingest_jobs table and indexes if not exist."""
    insp = inspect(engine)
    if "ingest_jobs" not in insp.get_table_names():
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE ingest_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_key VARCHAR(256) NOT NULL,
                    source_type VARCHAR(20) NOT NULL,
                    source_url VARCHAR(500) DEFAULT '',
                    source_hash VARCHAR(64) DEFAULT '',
                    source_name VARCHAR(500) DEFAULT '',
                    status VARCHAR(30) DEFAULT 'pending_preview',
                    retry_count INTEGER DEFAULT 0,
                    preview_data TEXT DEFAULT '',
                    preview_id VARCHAR(20) DEFAULT '',
                    action VARCHAR(50) DEFAULT '',
                    action_label VARCHAR(100) DEFAULT '',
                    result_path VARCHAR(500) DEFAULT '',
                    result_message TEXT DEFAULT '',
                    error_message TEXT DEFAULT '',
                    tracked_source_id INTEGER,
                    tracked_entry_id INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    confirmed_at DATETIME,
                    expires_at DATETIME
                )
            """))
    # Ensure indexes exist (runs on fresh AND upgraded DBs)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ingest_jobs_key_status "
            "ON ingest_jobs(job_key, status) "
            "WHERE status = 'pending_preview'"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_ingest_jobs_status ON ingest_jobs(status)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_ingest_jobs_source_type ON ingest_jobs(source_type)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_ingest_jobs_expires ON ingest_jobs(expires_at)"
        ))


def _migrate_review_items_table(engine) -> None:
    """P3-B/C: Create review_items table if not exists."""
    insp = inspect(engine)
    if "review_items" not in insp.get_table_names():
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE review_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_type VARCHAR(40) NOT NULL,
                    severity VARCHAR(10) DEFAULT 'warning',
                    status VARCHAR(20) DEFAULT 'open',
                    title VARCHAR(500) NOT NULL,
                    description TEXT DEFAULT '',
                    source_ref VARCHAR(200) DEFAULT '',
                    source_path VARCHAR(500) DEFAULT '',
                    suggested_action_json TEXT DEFAULT '',
                    resolution_note TEXT DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    resolved_at DATETIME
                )
            """))
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_review_status ON review_items(status)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_review_type ON review_items(item_type)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_review_severity ON review_items(severity)"
        ))


def _migrate_knowledge_graph_tables(engine) -> None:
    """P5-B: Create knowledge_nodes and knowledge_edges tables if not exist."""
    insp = inspect(engine)
    if "knowledge_nodes" not in insp.get_table_names():
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE knowledge_nodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_key VARCHAR(256) NOT NULL UNIQUE,
                    node_type VARCHAR(40) NOT NULL,
                    label VARCHAR(500) DEFAULT '',
                    normalized_label VARCHAR(500) DEFAULT '',
                    source_ref VARCHAR(200) DEFAULT '',
                    metadata_json TEXT DEFAULT '{}',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
    if "knowledge_edges" not in insp.get_table_names():
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE knowledge_edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    edge_key VARCHAR(256) NOT NULL UNIQUE,
                    source_node_key VARCHAR(256) NOT NULL,
                    target_node_key VARCHAR(256) NOT NULL,
                    edge_type VARCHAR(40) NOT NULL,
                    weight FLOAT DEFAULT 1.0,
                    evidence_ref VARCHAR(200) DEFAULT '',
                    report_id INTEGER,
                    source_type VARCHAR(20) DEFAULT '',
                    source_path VARCHAR(500) DEFAULT '',
                    page_number INTEGER,
                    timestamp VARCHAR(20) DEFAULT '',
                    metadata_json TEXT DEFAULT '{}',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_kn_type ON knowledge_nodes(node_type)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_kn_label ON knowledge_nodes(normalized_label)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_ke_type ON knowledge_edges(edge_type)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_ke_source ON knowledge_edges(source_node_key)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_ke_target ON knowledge_edges(target_node_key)"
        ))


def _migrate_operation_logs_table(engine) -> None:
    """P7-B: Create operation_logs table and indexes if not exist."""
    insp = inspect(engine)
    if "operation_logs" not in insp.get_table_names():
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE operation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_id VARCHAR(36) NOT NULL UNIQUE,
                    operation_type VARCHAR(50) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'started',
                    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    finished_at DATETIME,
                    duration_ms INTEGER,
                    source_type VARCHAR(50) DEFAULT '',
                    target_ref VARCHAR(300) DEFAULT '',
                    summary TEXT DEFAULT '',
                    error_code VARCHAR(50) DEFAULT '',
                    error_detail TEXT DEFAULT '',
                    initiated_by VARCHAR(20) DEFAULT 'user',
                    metadata_json TEXT DEFAULT '{}',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_opl_type ON operation_logs(operation_type)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_opl_status ON operation_logs(status)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_opl_created ON operation_logs(created_at)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_opl_target ON operation_logs(target_ref)"
        ))


def init_db(db_path: str | None = None) -> None:
    if _engine is None:
        init_engine(db_path)
    Base.metadata.create_all(_engine)
    _migrate_episodes_table(_engine)
    _migrate_channels_table(_engine)
    _migrate_channel_videos_table(_engine)
    _migrate_investment_views_table(_engine)
    _migrate_tracked_sources_tables(_engine)
    _migrate_ingest_jobs_table(_engine)
    _migrate_review_items_table(_engine)
    _migrate_knowledge_graph_tables(_engine)
    _migrate_operation_logs_table(_engine)


def get_session() -> Session:
    if _SessionLocal is None:
        init_engine()
    return _SessionLocal()


def reset_engine() -> None:
    """重置全局 engine（供测试 teardown 使用）。"""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
