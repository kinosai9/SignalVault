"""Repository 查询层测试（P1-A）。"""


from signalvault.db.repository import (
    get_report,
    get_report_detail,
    list_reports,
    list_sources,
    list_targets,
    search_reports,
)


def test_list_reports_count(seeded_db) -> None:
    """创建 3 条报告，list 返回 3。"""
    rows = list_reports(seeded_db)
    assert len(rows) == 3


def test_list_reports_fields(seeded_db) -> None:
    """list 返回的每条记录包含必要字段。"""
    rows = list_reports(seeded_db)
    for r in rows:
        assert "id" in r
        assert "episode_title" in r
        assert "source_type" in r
        assert "created_at" in r
        assert "view_count" in r
        assert "entity_count" in r
        assert "focus_areas" in r


def test_list_reports_filter_source_local(seeded_db) -> None:
    """source_type=local 只返回 local 报告。"""
    rows = list_reports(seeded_db, source_type="local")
    assert len(rows) == 2
    assert all(r["source_type"] == "local" for r in rows)


def test_list_reports_filter_source_youtube(seeded_db) -> None:
    """source_type=youtube 只返回 YouTube 报告。"""
    rows = list_reports(seeded_db, source_type="youtube")
    assert len(rows) == 1
    assert rows[0]["source_type"] == "youtube"
    assert rows[0]["episode_title"] == "abc123"


def test_list_reports_limit(seeded_db) -> None:
    """limit 参数生效。"""
    rows = list_reports(seeded_db, limit=2)
    assert len(rows) == 2


def test_get_report_basic(seeded_db) -> None:
    """get_report 返回基本信息。"""
    rows = list_reports(seeded_db)
    report_id = rows[0]["id"]
    r = get_report(seeded_db, report_id)
    assert r is not None
    assert r["id"] == report_id
    assert r["source_type"] in ("local", "youtube")
    assert "report_markdown" in r


def test_get_report_not_found(seeded_db) -> None:
    """不存在的 ID 返回 None。"""
    assert get_report(seeded_db, 9999) is None


def test_get_report_detail_returns_views(seeded_db) -> None:
    """detail 包含 views 和 signals。"""
    rows = list_reports(seeded_db)
    report_id = rows[0]["id"]
    d = get_report_detail(seeded_db, report_id)
    assert d is not None
    assert len(d["views"]) > 0
    assert len(d["signals"]) > 0
    assert d["views"][0]["target_name"] != ""


def test_get_report_detail_not_found(seeded_db) -> None:
    assert get_report_detail(seeded_db, 9999) is None


def test_search_reports_matches_markdown(seeded_db) -> None:
    """搜索 report_markdown 中的关键词。"""
    results = search_reports(seeded_db, "宁德时代")
    assert len(results) > 0
    assert any(r["match_type"] in ("fts", "like-fallback", "报告内容") for r in results)


def test_search_reports_matches_target(seeded_db) -> None:
    """搜索 investment_views.target_name。"""
    results = search_reports(seeded_db, "NVIDIA")
    assert len(results) > 0
    assert any(r["match_type"] in ("fts", "like-fallback", "投资标的", "报告内容") for r in results)


def test_search_reports_no_match(seeded_db) -> None:
    """无匹配返回空。"""
    results = search_reports(seeded_db, "不存在的关键词XYZABC")
    assert len(results) == 0


def test_search_reports_limit(seeded_db) -> None:
    """limit 参数生效。"""
    results = search_reports(seeded_db, "报告", limit=1)
    assert len(results) <= 1


def test_list_targets_aggregation(seeded_db) -> None:
    """统计标的出现次数。"""
    targets = list_targets(seeded_db)
    assert len(targets) >= 3  # 宁德时代, 港股红利ETF, NVIDIA
    names = [t["target_name"] for t in targets]
    assert "宁德时代" in names
    assert "NVIDIA" in names
    for t in targets:
        assert t["count"] >= 1
        assert t["last_direction"] != ""


def test_list_sources(seeded_db) -> None:
    """统计 local / youtube 来源。"""
    sources = list_sources(seeded_db)
    source_map = {s["source_type"]: s for s in sources}
    assert "local" in source_map
    assert "youtube" in source_map
    assert source_map["local"]["count"] == 2
    assert source_map["youtube"]["count"] == 1
