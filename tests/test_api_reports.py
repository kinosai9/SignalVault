"""GET /api/reports/*, /api/entities, /api/targets, /api/sources 测试。"""

import re


def test_api_reports_list(api_client, seeded_db) -> None:
    response = api_client.get("/api/reports")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 3
    assert len(data["items"]) == 3
    for item in data["items"]:
        assert "id" in item
        assert "source_type" in item
        assert "title" in item
        assert "video_id" in item
        assert "source_url" in item
        assert "focus_areas" in item
        assert "view_count" in item
        assert "entity_count" in item


def test_api_reports_list_filter_source_youtube(api_client, seeded_db) -> None:
    response = api_client.get("/api/reports?source=youtube")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["items"][0]["source_type"] == "youtube"
    assert data["items"][0]["video_id"] == "abc123"


def test_api_reports_list_filter_source_local(api_client, seeded_db) -> None:
    response = api_client.get("/api/reports?source=local")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    for item in data["items"]:
        assert item["source_type"] == "local"


def test_api_reports_list_with_limit(api_client, seeded_db) -> None:
    response = api_client.get("/api/reports?limit=1")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1


def test_api_reports_empty_db(api_client, db_session) -> None:
    """空数据库时列表不崩溃。"""
    response = api_client.get("/api/reports")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0
    assert data["items"] == []


def test_api_reports_detail(api_client, seeded_db) -> None:
    from signalvault.db.repository import list_reports
    rows = list_reports(seeded_db)
    rid = rows[0]["id"]

    response = api_client.get(f"/api/reports/{rid}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == rid
    assert "views" in data
    assert "signals" in data
    assert "report_markdown" in data


def test_api_reports_detail_not_found(api_client, seeded_db) -> None:
    response = api_client.get("/api/reports/9999")
    assert response.status_code == 404
    assert "不存在" in response.json()["detail"]


def test_api_reports_views(api_client, seeded_db) -> None:
    from signalvault.db.repository import list_reports
    rows = list_reports(seeded_db)
    rid = rows[0]["id"]

    response = api_client.get(f"/api/reports/{rid}/views")
    assert response.status_code == 200
    data = response.json()
    assert data["report_id"] == rid
    assert data["count"] > 0
    assert len(data["views"]) > 0
    assert "target_name" in data["views"][0]
    assert "view_direction" in data["views"][0]


def test_api_reports_views_not_found(api_client, seeded_db) -> None:
    response = api_client.get("/api/reports/9999/views")
    assert response.status_code == 404


def test_api_reports_signals(api_client, seeded_db) -> None:
    from signalvault.db.repository import list_reports
    rows = list_reports(seeded_db)
    rid = rows[0]["id"]

    response = api_client.get(f"/api/reports/{rid}/signals")
    assert response.status_code == 200
    data = response.json()
    assert data["report_id"] == rid
    assert data["count"] > 0
    assert len(data["signals"]) > 0
    assert "target_name" in data["signals"][0]


def test_api_reports_signals_not_found(api_client, seeded_db) -> None:
    response = api_client.get("/api/reports/9999/signals")
    assert response.status_code == 404


def test_api_entities(api_client, seeded_db) -> None:
    response = api_client.get("/api/entities")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] > 0
    assert "name" in data["items"][0]
    assert "entity_type" in data["items"][0]


def test_api_entities_with_type_filter(api_client, seeded_db) -> None:
    response = api_client.get("/api/entities?type=stock")
    assert response.status_code == 200
    data = response.json()
    for item in data["items"]:
        assert item["entity_type"] == "stock"


def test_api_targets(api_client, seeded_db) -> None:
    response = api_client.get("/api/targets")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] >= 3
    names = [t["target_name"] for t in data["items"]]
    assert "宁德时代" in names
    assert "NVIDIA" in names


def test_api_sources(api_client, seeded_db) -> None:
    response = api_client.get("/api/sources")
    assert response.status_code == 200
    data = response.json()
    source_types = [s["source_type"] for s in data["items"]]
    assert "local" in source_types
    assert "youtube" in source_types


def test_serve_command_help() -> None:
    from typer.testing import CliRunner

    from signalvault.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    # Strip Rich ANSI escape codes (present on Linux, absent on Windows)
    output = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "启动" in output
    assert "--host" in output
    assert "--port" in output
