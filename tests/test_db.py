"""SQLite 数据库测试。"""

import tempfile

from podcast_research.analysis.models import (
    Entity,
    ExtractionResult,
    InvestmentView,
    TrackingSignal,
)
from podcast_research.db.models import Episode, InvestmentViewRecord, Report
from podcast_research.db.repository import (
    save_episode,
    save_investment_views,
    save_report,
)
from podcast_research.db.session import get_session, init_db, reset_engine


def _make_extraction() -> ExtractionResult:
    return ExtractionResult(
        investment_views=[
            InvestmentView(
                target_name="宁德时代",
                target_type="stock",
                view_direction="bullish",
                logic_chain="储能需求增长",
                source_quote="原文引用",
                timestamp_start="00:32:10",
            )
        ],
        mentioned_entities=[
            Entity(name="宁德时代", entity_type="stock"),
        ],
        tracking_signals=[
            TrackingSignal(signal="关注储能数据", target_name="宁德时代"),
        ],
    )


def test_init_db_creates_tables() -> None:
    db = tempfile.mktemp(suffix=".db")
    init_db(db)
    session = get_session()
    from podcast_research.db.models import Base
    tables = Base.metadata.tables.keys()
    assert "episodes" in tables
    assert "reports" in tables
    assert "investment_views" in tables
    assert "tracking_signals" in tables
    assert "entities" in tables
    session.close()
    reset_engine()


def test_save_and_query_episode() -> None:
    db = tempfile.mktemp(suffix=".db")
    init_db(db)
    session = get_session()

    ep_id = save_episode(session, "测试播客", "test.srt", "srt", "hash123")
    session.commit()

    ep = session.query(Episode).filter_by(id=ep_id).first()
    assert ep is not None
    assert ep.title == "测试播客"
    assert ep.subtitle_format == "srt"
    session.close()
    reset_engine()


def test_save_and_query_report() -> None:
    db = tempfile.mktemp(suffix=".db")
    init_db(db)
    session = get_session()

    ep_id = save_episode(session, "测试播客", "test.srt", "srt", "hash123")
    extraction = _make_extraction()
    rep_id = save_report(session, ep_id, extraction, "# report")
    save_investment_views(session, rep_id, extraction.investment_views)
    session.commit()

    rep = session.query(Report).filter_by(id=rep_id).first()
    assert rep is not None
    assert rep.episode_id == ep_id
    assert rep.llm_provider == "mock"

    view = session.query(InvestmentViewRecord).filter_by(report_id=rep_id).first()
    assert view is not None
    assert view.target_name == "宁德时代"
    assert view.view_direction == "bullish"
    session.close()
    reset_engine()
