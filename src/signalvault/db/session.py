import contextlib
import logging
import shutil
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from signalvault.config import DB_PATH
from signalvault.db.models import Base

_engine = None
_SessionLocal = None
# Actual DB path bound to the current engine. Tracked so that init_db can
# back up the right file even when init_engine was called earlier with a
# different path (e.g. a test fixture).
_current_db_path: str | None = None

logger = logging.getLogger(__name__)

# ── Schema versioning & data-upgrade protection (M3-C-0) ─────────────────────
# CURRENT_SCHEMA_VERSION marks the schema baseline known to this codebase.
# Increment it whenever a new _migrate_* step ships. Existing installs upgrade
# forward-only (ADD COLUMN, never DROP/RENAME), and a DB backup is taken before
# every migration run so a failed upgrade is always recoverable from backups/.
CURRENT_SCHEMA_VERSION = 3  # 1 = P0–P7 baseline; 2 = M3-C-0; 3 = M4-A Source Lifecycle

# How many pre-migration DB snapshots to retain in backups/.
MAX_DB_BACKUPS = 10


def _resolve_backup_dir() -> Path:
    """Resolve the backup directory from AppPaths.

    Kept as a thin module-level function so tests can monkeypatch it to a
    tmp directory without ever writing into the real platform user dir.
    """
    try:
        from signalvault.settings.app_paths import AppPaths
        return AppPaths.resolve().backup_dir
    except Exception:
        # Never block startup over a missing path resolver.
        return Path.cwd() / "backups"


def _create_pre_migration_backup(db_path: str) -> str | None:
    """迁移前把已有 DB 复制到 backups/，保证升级失败可回滚。

    - 首次启动或空 DB（size == 0）：跳过，返回 None。
    - 备份失败：仅记录 warning，绝不阻塞启动（返回 None）。
    - 保留最近 MAX_DB_BACKUPS 份，更老的自动清理。
    """
    from datetime import datetime

    src = Path(db_path)
    try:
        if not src.exists() or src.stat().st_size == 0:
            return None  # 首次启动或空文件，无需保护
    except OSError:
        return None

    try:
        backup_dir = _resolve_backup_dir()
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        dst = backup_dir / f"signalvault-{ts}.db"
        shutil.copy2(src, dst)

        # 只保留最近 MAX_DB_BACKUPS 份，清理更老的快照
        old = sorted(
            backup_dir.glob("signalvault-*.db"),
            key=lambda p: p.stat().st_mtime,
        )
        for stale in old[:-MAX_DB_BACKUPS]:
            with contextlib.suppress(OSError):
                stale.unlink()
        logger.info("Pre-migration DB backup created: %s", dst)
        return str(dst)
    except Exception as exc:
        logger.warning("Pre-migration DB backup failed (non-fatal): %s", exc)
        return None


def check_db_integrity() -> tuple[str, str]:
    """对当前 engine 跑 PRAGMA integrity_check。

    返回 (status, detail)，status ∈ {"ok", "warning", "error"}。
    供数据健康视图（M3-C-0.5）按需调用，不在每次启动强制执行。
    """
    if _engine is None:
        return ("error", "数据库未初始化")
    try:
        with _engine.connect() as conn:
            result = conn.execute(text("PRAGMA integrity_check"))
            rows = result.fetchall()
        msg = rows[0][0] if rows else "unknown"
        if msg == "ok":
            return ("ok", "数据库完整性检查通过")
        return ("warning", str(msg))
    except Exception as exc:
        return ("error", f"完整性检查失败: {exc}")


def init_engine(db_path: str | None = None) -> None:
    global _engine, _SessionLocal, _current_db_path
    path = db_path or str(DB_PATH)
    # Ensure parent directory exists — DB_PATH may point to a platform
    # directory that hasn't been created yet (e.g. first launch).
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(f"sqlite:///{path}", echo=False)
    _SessionLocal = sessionmaker(bind=_engine)
    _current_db_path = path


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
                    expires_at DATETIME,
                    reason VARCHAR(500) DEFAULT '',
                    is_auto BOOLEAN DEFAULT 0
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

    # M3-C-3a: add auto-processing columns to existing tables (forward-compatible)
    if "ingest_jobs" in insp.get_table_names():
        existing = {col["name"] for col in insp.get_columns("ingest_jobs")}
        with engine.begin() as conn:
            if "reason" not in existing:
                conn.execute(text(
                    "ALTER TABLE ingest_jobs ADD COLUMN reason VARCHAR(500) DEFAULT ''"
                ))
            if "is_auto" not in existing:
                conn.execute(text(
                    "ALTER TABLE ingest_jobs ADD COLUMN is_auto BOOLEAN DEFAULT 0"
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


def _migrate_source_provenance_tables(engine) -> None:
    """Source Provenance: Create source_documents and source_segments tables."""
    insp = inspect(engine)
    existing_tables = insp.get_table_names()

    if "source_documents" not in existing_tables:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE source_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_doc_id VARCHAR(64) NOT NULL UNIQUE,
                    source_type VARCHAR(30) NOT NULL,
                    title VARCHAR(500) DEFAULT '',
                    canonical_url VARCHAR(500) DEFAULT '',
                    source_url VARCHAR(500) DEFAULT '',
                    source_path VARCHAR(500) DEFAULT '',
                    content_hash VARCHAR(64) DEFAULT '',
                    language VARCHAR(20) DEFAULT '',
                    original_language VARCHAR(20) DEFAULT '',
                    translated_language VARCHAR(20) DEFAULT '',
                    status VARCHAR(20) DEFAULT 'available',
                    raw_text_path VARCHAR(500) DEFAULT '',
                    normalized_text_path VARCHAR(500) DEFAULT '',
                    translated_text_path VARCHAR(500) DEFAULT '',
                    metadata_json TEXT DEFAULT '{}',
                    access_scope VARCHAR(30) DEFAULT 'public_web',
                    retention_policy VARCHAR(30) DEFAULT 'keep_full_text',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    fetched_at DATETIME,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_sd_type ON source_documents(source_type)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_sd_hash ON source_documents(content_hash)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_sd_status ON source_documents(status)"
        ))

    if "source_segments" not in existing_tables:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE source_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_doc_id VARCHAR(64) NOT NULL,
                    segment_id VARCHAR(64) DEFAULT '',
                    sequence_index INTEGER DEFAULT 0,
                    segment_type VARCHAR(20) DEFAULT 'paragraph',
                    text_original TEXT DEFAULT '',
                    text_normalized TEXT DEFAULT '',
                    text_translated TEXT DEFAULT '',
                    start_time VARCHAR(20) DEFAULT '',
                    end_time VARCHAR(20) DEFAULT '',
                    page_number INTEGER,
                    paragraph_index INTEGER,
                    heading_path VARCHAR(300) DEFAULT '',
                    char_start INTEGER,
                    char_end INTEGER,
                    locator_json TEXT DEFAULT '{}',
                    content_hash VARCHAR(64) DEFAULT '',
                    translation_status VARCHAR(20) DEFAULT 'not_needed',
                    translation_metadata_json TEXT DEFAULT '{}',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_ss_doc ON source_segments(source_doc_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_ss_segid ON source_segments(segment_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_ss_type ON source_segments(segment_type)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_ss_page ON source_segments(page_number)"
        ))


def _migrate_source_provenance_fks(engine) -> None:
    """Add optional source_doc_id / source_segment_id FK columns to existing tables."""
    insp = inspect(engine)

    # Episode.source_doc_id
    if "episodes" in insp.get_table_names():
        existing = {col["name"] for col in insp.get_columns("episodes")}
        if "source_doc_id" not in existing:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE episodes ADD COLUMN source_doc_id VARCHAR(64)"
                ))

    # Report.source_doc_id
    if "reports" in insp.get_table_names():
        existing = {col["name"] for col in insp.get_columns("reports")}
        if "source_doc_id" not in existing:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE reports ADD COLUMN source_doc_id VARCHAR(64)"
                ))

    # InvestmentViewRecord.source_segment_id
    if "investment_views" in insp.get_table_names():
        existing = {col["name"] for col in insp.get_columns("investment_views")}
        if "source_segment_id" not in existing:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE investment_views ADD COLUMN source_segment_id VARCHAR(64)"
                ))

    # TrackingSignalRecord.source_segment_id
    if "tracking_signals" in insp.get_table_names():
        existing = {col["name"] for col in insp.get_columns("tracking_signals")}
        if "source_segment_id" not in existing:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE tracking_signals ADD COLUMN source_segment_id VARCHAR(64)"
                ))

    # OperationLog.source_doc_id
    if "operation_logs" in insp.get_table_names():
        existing = {col["name"] for col in insp.get_columns("operation_logs")}
        if "source_doc_id" not in existing:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE operation_logs ADD COLUMN source_doc_id VARCHAR(64)"
                ))


def _migrate_source_lifecycle_tables(engine) -> None:
    """M4-A: Create source_items, processing_jobs, and claims tables if not exist."""
    insp = inspect(engine)
    existing_tables = insp.get_table_names()

    # source_items 表
    if "source_items" not in existing_tables:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE source_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type TEXT NOT NULL,
                    source_uri TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    metadata TEXT DEFAULT '{}',
                    content_hash TEXT DEFAULT '',
                    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    provenance TEXT DEFAULT '',
                    status TEXT DEFAULT 'captured',
                    source_document_id TEXT,
                    user_rating TEXT DEFAULT '',
                    user_notes TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_source_items_type ON source_items(source_type)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_source_items_hash ON source_items(content_hash)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_source_items_status ON source_items(status)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_source_items_captured ON source_items(captured_at)"
        ))

    # processing_jobs 表
    if "processing_jobs" not in existing_tables:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE processing_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_item_id INTEGER NOT NULL,
                    job_type TEXT NOT NULL,
                    priority INTEGER DEFAULT 5,
                    params TEXT DEFAULT '{}',
                    status TEXT DEFAULT 'pending',
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    result_type TEXT DEFAULT '',
                    result_ref INTEGER,
                    error_message TEXT DEFAULT '',
                    llm_calls INTEGER DEFAULT 0,
                    tokens_used INTEGER DEFAULT 0,
                    duration_seconds INTEGER DEFAULT 0,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_processing_jobs_status ON processing_jobs(status)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_processing_jobs_source ON processing_jobs(source_item_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_processing_jobs_type ON processing_jobs(job_type)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_processing_jobs_priority ON processing_jobs(priority)"
        ))

    # claims 表（M4-B 前瞻）
    if "claims" not in existing_tables:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    claim_text TEXT NOT NULL,
                    claim_type TEXT DEFAULT 'prediction',
                    confidence REAL DEFAULT 0.0,
                    confidence_source TEXT DEFAULT '',
                    source_report_id INTEGER NOT NULL,
                    source_view_id INTEGER,
                    source_quote TEXT DEFAULT '',
                    timestamp TEXT DEFAULT '',
                    evidence_page INTEGER,
                    supporting_sources TEXT DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_claims_report ON claims(source_report_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_claims_type ON claims(claim_type)"
        ))


def init_db(db_path: str | None = None) -> None:
    if _engine is None:
        init_engine(db_path)
    # M3-C-0: 迁移前备份已有 DB，保证升级失败可回滚。首次启动 / 空 DB 时为 no-op。
    _create_pre_migration_backup(_current_db_path or str(DB_PATH))
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
    _migrate_source_provenance_tables(_engine)
    _migrate_source_provenance_fks(_engine)
    _migrate_source_lifecycle_tables(_engine)  # M4-A
    _track_schema_version(_engine)


def _track_schema_version(engine, target_version: int = CURRENT_SCHEMA_VERSION) -> None:
    """Ensure schema_version table records the current codebase schema baseline."""
    from datetime import datetime
    try:
        with engine.begin() as conn:
            result = conn.execute(text("SELECT MAX(version) FROM schema_version"))
            row = result.fetchone()
            current = row[0] if row and row[0] is not None else 0
            if current < target_version:
                conn.execute(
                    text(
                        "INSERT INTO schema_version (version, description, applied_at) "
                        "VALUES (:ver, :desc, :ts)"
                    ),
                    {
                        "ver": target_version,
                        "desc": (
                            f"upgraded to schema v{target_version} "
                            f"(codebase baseline={CURRENT_SCHEMA_VERSION})"
                        ),
                        "ts": datetime.now(),
                    },
                )
                logger.info("Schema version recorded: %d", target_version)
    except Exception as exc:
        # schema_version table may not exist yet (first run before create_all),
        # or this is a read-only / headless context — never block on it.
        logger.debug("schema_version tracking skipped: %s", exc)


def get_session() -> Session:
    if _SessionLocal is None:
        init_engine()
    return _SessionLocal()


def reset_engine() -> None:
    """重置全局 engine（供测试 teardown 使用）。"""
    global _engine, _SessionLocal, _current_db_path
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    _current_db_path = None
