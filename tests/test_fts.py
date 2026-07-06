"""P1-D: FTS5 全文搜索测试"""



def test_ensure_fts_table_creates_table(db_session):
    from signalvault.db.fts import ensure_fts_table

    ok = ensure_fts_table(db_session)
    assert ok is True

    from sqlalchemy import text
    tables = db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='report_search_fts'")
    ).fetchall()
    assert len(tables) == 1


def test_rebuild_search_index_indexes_seeded(db_session, seeded_db):
    from signalvault.db.fts import rebuild_search_index

    count = rebuild_search_index(seeded_db)
    assert count == 3


def test_fts_search_report_markdown(db_session, seeded_db):
    _ensure_index(seeded_db)

    from signalvault.db.fts import search_fts
    results = search_fts(seeded_db, "NVIDIA")
    assert results is not None
    assert len(results) >= 1


def test_fts_search_target_name(db_session, seeded_db):
    _ensure_index(seeded_db)

    from signalvault.db.fts import search_fts
    results = search_fts(seeded_db, "宁德时代")
    assert results is not None
    assert len(results) >= 1


def test_fts_search_entity_name(db_session, seeded_db):
    _ensure_index(seeded_db)

    from signalvault.db.fts import search_fts
    results = search_fts(seeded_db, "港股")
    assert results is not None
    assert len(results) >= 1


def test_fts_search_signal(db_session, seeded_db):
    _ensure_index(seeded_db)

    from signalvault.db.fts import search_fts
    results = search_fts(seeded_db, "出货量")
    assert results is not None
    assert len(results) >= 1


def test_search_reports_uses_fts(db_session, seeded_db):
    _ensure_index(seeded_db)

    from signalvault.db.repository import search_reports
    results = search_reports(seeded_db, "新能源", limit=10)
    assert len(results) >= 1
    # 当 FTS 可用时 match_type 应为 "fts"
    assert any(r["match_type"] == "fts" for r in results)


def test_search_reports_auto_creates_fts(db_session, seeded_db):
    """FTS 表不存在时，search_reports 自动创建并索引。"""
    from signalvault.db.repository import search_reports
    results = search_reports(seeded_db, "NVIDIA", limit=10)
    assert len(results) >= 1


def test_cli_rebuild_index(db_session, seeded_db):
    from typer.testing import CliRunner

    from signalvault.cli import app

    # 确保 engine 指向临时数据库
    runner = CliRunner()
    result = runner.invoke(app, ["reports", "rebuild-index"])
    assert result.exit_code == 0
    assert "FTS index rebuilt" in result.stdout


def test_api_search_still_works(api_client, seeded_db):
    resp = api_client.get("/api/search?q=NVIDIA")
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data


def test_html_search_still_works(api_client, seeded_db):
    resp = api_client.get("/search?q=NVIDIA")
    assert resp.status_code == 200
    assert "NVIDIA" in resp.text


def test_fts_no_results(db_session):
    from signalvault.db.repository import search_reports
    results = search_reports(db_session, "zzz_nonexistent_xyz", limit=10)
    assert results == []


# --- helpers ---

def _ensure_index(session):
    from signalvault.db.fts import rebuild_search_index
    rebuild_search_index(session)
