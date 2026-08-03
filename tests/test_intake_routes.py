"""M3-C-2c: /intake Universal Intake 入口路由测试。

验证唯一用户入口：/intake 页面、识别分流、/content/new 301 收敛。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from signalvault.api.app import create_app

    return TestClient(create_app())


def test_intake_page_loads(client: TestClient) -> None:
    resp = client.get("/intake")
    assert resp.status_code == 200
    assert "添加信息" in resp.text
    assert "粘贴链接" in resp.text


def test_intake_resolve_youtube(client: TestClient) -> None:
    resp = client.get(
        "/intake/resolve",
        params={"query": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    )
    assert resp.status_code == 200
    assert "YouTube 视频" in resp.text
    assert "分析此视频" in resp.text  # YouTube 操作按钮（POST /content/analyze）


def test_intake_resolve_web_url(client: TestClient) -> None:
    resp = client.get(
        "/intake/resolve", params={"query": "https://example.com/article"}
    )
    assert resp.status_code == 200
    assert "网页" in resp.text


def test_intake_resolve_empty_redirects_to_intake(client: TestClient) -> None:
    resp = client.get("/intake/resolve", params={"query": ""}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/intake"


def test_intake_resolve_unknown_shows_warning(client: TestClient) -> None:
    resp = client.get("/intake/resolve", params={"query": "garbage input xyz"})
    assert resp.status_code == 200
    assert "未识别" in resp.text or "无法识别" in resp.text


def test_content_new_301_redirects_to_intake(client: TestClient) -> None:
    """旧 YouTube 表单页收敛到 Universal Intake（GET 301）。"""
    resp = client.get("/content/new", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/intake"


def test_intake_page_lists_supported_types(client: TestClient) -> None:
    resp = client.get("/intake")
    for label in ["PDF", "DOCX", "Markdown", "YouTube"]:
        assert label in resp.text


def test_processing_center_loads(client: TestClient) -> None:
    """M3-C-3: 处理中心可解释入口（已完成/待确认/已忽略）。"""
    resp = client.get("/processing")
    assert resp.status_code == 200
    assert "处理中心" in resp.text
    assert "已完成" in resp.text
    assert "待确认" in resp.text
    assert "已忽略" in resp.text
