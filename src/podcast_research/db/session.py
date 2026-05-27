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


def init_db(db_path: str | None = None) -> None:
    if _engine is None:
        init_engine(db_path)
    Base.metadata.create_all(_engine)
    _migrate_episodes_table(_engine)


def get_session() -> Session:
    if _SessionLocal is None:
        init_engine()
    return _SessionLocal()