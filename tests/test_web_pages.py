"""P1-C: HTML 页面测试 — 复用 seeded_db + api_client fixtures"""


def test_index_redirects(api_client):
    """GET / 返回 302 重定向到 /reports"""
    resp = api_client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/reports"


def test_reports_list_ok(api_client, seeded_db):
    """GET /reports 返回 200 并包含 seeded report"""
    resp = api_client.get("/reports")
    assert resp.status_code == 200
    html = resp.text
    assert "报告库" in html
    assert "宁德时代" in html or "新能源" in html


def test_reports_list_with_source_filter(api_client, seeded_db):
    """GET /reports?source=youtube 过滤来源"""
    resp = api_client.get("/reports?source=youtube")
    assert resp.status_code == 200
    html = resp.text
    assert "abc123" in html or "youtube" in html.lower()


def test_report_detail_ok(api_client, seeded_db):
    """GET /reports/{id} 返回 200 并包含核心观点"""
    resp = api_client.get("/reports/1")
    assert resp.status_code == 200
    html = resp.text
    assert "核心观点矩阵" in html
    assert "宁德时代" in html


def test_report_detail_not_found(api_client):
    """不存在的 report_id 返回 HTML 404"""
    resp = api_client.get("/reports/99999")
    assert resp.status_code == 404
    html = resp.text
    assert "404" in html
    assert "不存在" in html


def test_search_with_query(api_client, seeded_db):
    """GET /search?q=宁德 返回 200 并有结果"""
    resp = api_client.get("/search?q=宁德")
    assert resp.status_code == 200
    html = resp.text
    assert "宁德" in html


def test_search_empty_query(api_client):
    """GET /search 不带 q 返回 200 并显示搜索框"""
    resp = api_client.get("/search")
    assert resp.status_code == 200
    html = resp.text
    assert "搜索" in html


def test_api_endpoints_still_work(api_client, seeded_db):
    """原有 /api/* 路径不受影响"""
    # health
    resp = api_client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"

    # reports list
    resp = api_client.get("/api/reports")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data

    # report detail
    resp = api_client.get("/api/reports/1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 1
    assert len(data["views"]) >= 0

    # search
    resp = api_client.get("/api/search?q=宁德")
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
