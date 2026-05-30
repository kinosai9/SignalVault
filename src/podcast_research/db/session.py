from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, Session

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
    """为 channels 表补齐 P1-F 新增列（tags/priority/default_focus/limits/notes）。"""
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
    ]
    with engine.begin() as conn:
        for col_name, col_type in migrations:
            if col_name not in existing:
                conn.execute(text(f"ALTER TABLE channels ADD COLUMN {col_name} {col_type}"))


def _migrate_investment_views_table(engine) -> None:
    """为 investment_views 表补齐 P2-A1 新增列。"""
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
    ]
    with engine.begin() as conn:
        for col_name, col_type in migrations:
            if col_name not in existing:
                conn.execute(text(f"ALTER TABLE investment_views ADD COLUMN {col_name} {col_type}"))


def init_db(db_path: str | None = None) -> None:
    if _engine is None:
        init_engine(db_path)
    Base.metadata.create_all(_engine)
    _migrate_episodes_table(_engine)
    _migrate_channels_table(_engine)
    _migrate_investment_views_table(_engine)


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