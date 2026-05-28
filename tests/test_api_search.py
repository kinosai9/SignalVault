"""GET /api/search 测试。"""


def test_api_search_finds_results(api_client, seeded_db) -> None:
    response = api_client.get("/api/search?q=宁德时代")
    assert response.status_code == 200
    data = response.json()
    assert data["keyword"] == "宁德时代"
    assert data["count"] > 0
    for r in data["results"]:
        assert "report_id" in r
        assert "match_type" in r
        assert "match_excerpt" in r


def test_api_search_no_match(api_client, seeded_db) -> None:
    response = api_client.get("/api/search?q=ZZZZZZNOTEXIST")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0
    assert data["results"] == []


def test_api_search_missing_q_returns_422(api_client, seeded_db) -> None:
    response = api_client.get("/api/search")
    assert response.status_code == 422


def test_api_search_with_limit(api_client, seeded_db) -> None:
    response = api_client.get("/api/search?q=报告&limit=1")
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) <= 1
