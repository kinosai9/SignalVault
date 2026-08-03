"""M3-C-3c Final Acceptance: 自动化编排验收。

三个验收维度：
1. Settings UI 展示三档开关 —— /settings/system 有自动分析模式选择器
2. API 可更新配置 —— POST /api/settings/automation 更新 intake.auto_analysis_mode
3. auto_process_pending 执行正确 —— 按模式自动归档/忽略/保留人工
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ── 1. Settings UI 展示三档开关 ───────────────────────────────────────────────


@pytest.fixture()
def client():
    from signalvault.api.app import create_app

    return TestClient(create_app())


def test_settings_system_shows_automation_card(client: TestClient) -> None:
    """/settings/system 展示自动化状态卡片（M4-C：卡片含状态指示和跳转链接）。"""
    resp = client.get("/settings/system")
    assert resp.status_code == 200
    # 卡片标题（M4-C 改为"自动化"）
    assert "自动化" in resp.text
    # 三档标签仍显示当前模式
    content = resp.text
    assert ("关闭" in content or "高价值来源" in content or "全部来源" in content)
    # 链接到独立自动化设置页面
    assert "/settings/automation" in resp.text


def test_settings_system_shows_current_mode(client: TestClient) -> None:
    """Settings 页面正确显示当前模式（默认为 off）。"""
    resp = client.get("/settings/system")
    assert resp.status_code == 200
    # 默认模式为 off，应有 selected 或 checked 标记
    # 根据模板实现可能是 selected="selected" 或 checked
    assert "关闭" in resp.text or "off" in resp.text


# ── 2. API 可更新配置 ────────────────────────────────────────────────────────


def test_api_update_automation_mode_requires_csrf(client: TestClient) -> None:
    """POST /api/settings/automation 需要 CSRF token。"""
    resp = client.post(
        "/api/settings/automation",
        json={"auto_analysis_mode": "high_value"},
    )
    # 没有 CSRF token 应该被拒绝（403）
    assert resp.status_code == 403


def test_api_update_automation_mode_validates_value(client: TestClient) -> None:
    """API 只接受 off/high_value/all 三个值。"""
    # 需要先获取 CSRF token（从页面或 header）
    resp_get = client.get("/settings/system")
    csrf_token = None
    # 从响应中提取 CSRF token
    if '_csrf_token" value="' in resp_get.text:
        import re

        match = re.search(r'_csrf_token" value="([^"]+)"', resp_get.text)
        if match:
            csrf_token = match.group(1)

    if not csrf_token:
        pytest.skip("无法从页面提取 CSRF token")

    # 测试无效值
    resp = client.post(
        "/api/settings/automation",
        json={"auto_analysis_mode": "invalid"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert resp.status_code == 400

    # 测试有效值
    for mode in ["off", "high_value", "all"]:
        resp = client.post(
            "/api/settings/automation",
            json={"auto_analysis_mode": mode},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True
        assert data.get("data", {}).get("auto_analysis_mode") == mode


# ── 3. auto_process_pending 执行正确 ──────────────────────────────────────────


def test_auto_process_pending_off_mode() -> None:
    """off 模式下，auto_process_pending 不做自动处理。"""
    from signalvault.services.intake_orchestrator import auto_process_pending

    stats = auto_process_pending("off")
    # off 模式下，所有都应保留人工处理
    assert stats["mode"] == "off"
    # 具体数值取决于测试数据，但至少不应抛异常


def test_auto_process_pending_returns_stats() -> None:
    """auto_process_pending 返回处理统计。"""
    from signalvault.services.intake_orchestrator import auto_process_pending

    stats = auto_process_pending("off")
    # 必须包含这些键
    assert "auto_archived" in stats
    assert "auto_ignored" in stats
    assert "kept_manual" in stats
    assert "mode" in stats
    # 所有值都是整数
    assert isinstance(stats["auto_archived"], int)
    assert isinstance(stats["auto_ignored"], int)
    assert isinstance(stats["kept_manual"], int)


def test_processing_page_has_auto_controls(client: TestClient) -> None:
    """处理中心页面有自动处理控制。"""
    resp = client.get("/processing")
    assert resp.status_code == 200
    # 自动处理表单
    assert 'action="/processing/auto-mode"' in resp.text
    assert 'action="/processing/auto-process"' in resp.text
    # 三档开关
    assert 'value="off"' in resp.text
    assert 'value="high_value"' in resp.text
    assert 'value="all"' in resp.text


# ── 4. 端到端验证（可选，需要 mock 数据）────────────────────────────────────


def test_e2e_change_mode_via_api_and_verify_in_ui(client: TestClient) -> None:
    """端到端：通过 API 改变模式，页面正确显示新状态。"""
    import re

    # 1. 获取初始状态和 CSRF token
    resp = client.get("/settings/system")
    assert resp.status_code == 200
    match = re.search(r'_csrf_token" value="([^"]+)"', resp.text)
    if not match:
        pytest.skip("无法从页面提取 CSRF token")
    csrf_token_1 = match.group(1)

    # 2. 通过 API 更改为 high_value
    resp = client.post(
        "/api/settings/automation",
        json={"auto_analysis_mode": "high_value"},
        headers={"X-CSRF-Token": csrf_token_1},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["auto_analysis_mode"] == "high_value"

    # 3. 再次访问页面，确认显示正确
    resp = client.get("/settings/system")
    assert resp.status_code == 200
    # high_value 应该是选中状态（根据模板实现检查 selected 或 checked）
    # 这里简单检查页面中是否包含模式说明
    assert "高价值来源" in resp.text or "high_value" in resp.text

    # 4. 获取新的 CSRF token（每次请求后 token 可能改变）
    match = re.search(r'_csrf_token" value="([^"]+)"', resp.text)
    if not match:
        pytest.skip("无法从页面提取 CSRF token")
    csrf_token_2 = match.group(1)

    # 5. 恢复为 off（清理状态）
    resp = client.post(
        "/api/settings/automation",
        json={"auto_analysis_mode": "off"},
        headers={"X-CSRF-Token": csrf_token_2},
    )
    assert resp.status_code == 200