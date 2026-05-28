"""GET /api/health 测试。"""


def test_api_health_ok(api_client) -> None:
    response = api_client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "podcast_research"
    assert data["database"] == "ok"
