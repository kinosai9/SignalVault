"""共享测试 fixtures。

⚠️ 环境隔离：conftest 在 import podcast_research 模块之前强制设置 LLM env vars，
确保所有 mock 测试不受用户本地 .env 影响，永远使用 mock provider。
"""

import os
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# P2-A1.1 测试环境 hardening：在任何 podcast_research 模块导入前，强制覆盖
# LLM 相关的环境变量。load_dotenv() 默认不覆盖已存在的 env var，所以这里先行
# 设置就能阻止 .env 中的真实 LLM 配置进入测试。
# ---------------------------------------------------------------------------
os.environ["LLM_PROVIDER"] = "mock"
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_MODEL"] = "mock-investment-analyst"

import pytest

from podcast_research.analysis.models import (
    Entity,
    ExtractionResult,
    InvestmentView,
    TrackingSignal,
)
from podcast_research.db.repository import (
    save_entities,
    save_episode,
    save_investment_views,
    save_report,
    save_tracking_signals,
)
from podcast_research.db.session import init_db, get_session, reset_engine


SAMPLE_SRT = Path(__file__).resolve().parent.parent / "data" / "subtitles" / "sample.srt"


@pytest.fixture()
def db_session():
    """创建临时数据库，yield session，结束后清理全局 engine 和临时文件。"""
    # 先重置全局 engine，防止上一个测试的 engine 残留
    reset_engine()
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(db_path)
    session = get_session()
    yield session
    session.close()
    reset_engine()
    try:
        os.unlink(db_path)
    except OSError:
        pass


def _make_extraction(target: str = "宁德时代", direction: str = "bullish") -> ExtractionResult:
    return ExtractionResult(
        focus_areas=["新能源", "港股"],
        investment_views=[
            InvestmentView(
                target_name=target,
                target_type="stock",
                view_direction=direction,
                logic_chain=f"{target}逻辑链：行业需求增长",
                source_quote=f"关于{target}的原文引用",
                timestamp_start="00:32:10",
            )
        ],
        mentioned_entities=[
            Entity(name=target, entity_type="stock"),
        ],
        tracking_signals=[
            TrackingSignal(signal=f"关注{target}出货量", target_name=target),
        ],
    )


@pytest.fixture()
def seeded_db(db_session):
    """预填充 3 条报告：2 local + 1 youtube，不同标的。"""
    session = db_session

    # 报告 1: local，宁德时代
    ep1 = save_episode(session, "新能源访谈", "test.srt", "srt", "hash1")
    ex1 = _make_extraction("宁德时代", "bullish")
    rep1 = save_report(session, ep1, ex1, f"# 新能源报告\n宁德时代储能需求增长", analysis_depth="standard")
    save_investment_views(session, rep1, ex1.investment_views)
    save_tracking_signals(session, rep1, ex1.tracking_signals)
    save_entities(session, ex1.mentioned_entities)

    # 报告 2: local，港股红利
    ep2 = save_episode(session, "港股策略", "test2.srt", "srt", "hash2")
    ex2 = _make_extraction("港股红利ETF", "neutral")
    rep2 = save_report(session, ep2, ex2, f"# 港股策略报告\n港股红利估值偏低", analysis_depth="deep")
    save_investment_views(session, rep2, ex2.investment_views)
    save_tracking_signals(session, rep2, ex2.tracking_signals)
    save_entities(session, ex2.mentioned_entities)

    # 报告 3: youtube，NVIDIA
    ep3 = save_episode(
        session, "AI Investment Talk", "youtube", "json", "hash3",
        source_url="https://www.youtube.com/watch?v=abc123",
        video_id="abc123",
        language="en",
    )
    ex3 = _make_extraction("NVIDIA", "bullish")
    rep3 = save_report(session, ep3, ex3, f"# AI Report\nNVIDIA GPU demand is strong", analysis_depth="standard")
    save_investment_views(session, rep3, ex3.investment_views)
    save_tracking_signals(session, rep3, ex3.tracking_signals)
    save_entities(session, ex3.mentioned_entities)

    session.commit()
    return session


@pytest.fixture()
def api_client(db_session):
    """创建 FastAPI TestClient，复用 db_session 的临时数据库。"""
    from fastapi.testclient import TestClient
    from podcast_research.api.app import create_app

    app = create_app()
    client = TestClient(app)
    return client
