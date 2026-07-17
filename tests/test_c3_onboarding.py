"""C3 first-run onboarding: flow, persistence, service boundaries, and safety."""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from signalvault.api.app import create_app

    return TestClient(create_app())


def _csrf(client: TestClient, path: str = "/setup/welcome") -> str:
    response = client.get(path)
    assert response.status_code == 200
    match = re.search(r'name="_csrf_token" value="([^"]+)"', response.text)
    assert match, f"CSRF token missing from {path}"
    assert client.cookies.get("signalvault_csrf")
    return match.group(1)


def _post(client: TestClient, path: str, data: dict | None = None, *, page=None):
    token = _csrf(client, page or "/setup/welcome")
    return client.post(path, data={"_csrf_token": token, **(data or {})})


class TestOnboardingState:
    def test_new_user_enters_wizard(self, client):
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/setup/welcome"

    def test_state_defaults_and_persists(self):
        from signalvault.services.onboarding_service import (
            complete_onboarding,
            get_onboarding_state,
        )
        from signalvault.settings.service import get_config_service

        initial = get_onboarding_state()
        assert initial.completed is False
        assert initial.version == 0

        completed = complete_onboarding()
        assert completed.completed is True
        assert completed.version == 1
        assert completed.completed_at.endswith("Z")

        get_config_service().reload()
        assert get_onboarding_state() == completed

    def test_completed_user_goes_to_dashboard(self, client):
        from signalvault.services.onboarding_service import complete_onboarding

        complete_onboarding()
        response = client.get("/", follow_redirects=False)
        assert response.headers["location"] == "/dashboard"

    def test_global_skip_is_final_user_decision(self, client):
        response = _post(client, "/setup/skip")
        assert response.url.path == "/dashboard"

        from signalvault.services.onboarding_service import get_onboarding_state

        state = get_onboarding_state()
        assert state.completed is True
        assert state.skipped_ai is True
        assert state.skipped_obsidian is True

    def test_health_changes_do_not_reopen_wizard(self):
        from signalvault.services.ai_settings_service import update_ai_settings
        from signalvault.services.onboarding_service import (
            complete_onboarding,
            should_enter_onboarding,
        )

        complete_onboarding()
        update_ai_settings({"provider": "openai-compatible", "base_url": ""})
        assert should_enter_onboarding() is False


class TestWizardPages:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/setup/welcome", "数据留在本机"),
            ("/setup/ai", "选择 AI 使用方式"),
            ("/setup/obsidian", "SQLite 始终是"),
            ("/setup/complete", "设置摘要"),
        ],
    )
    def test_pages_render_with_progress_and_csrf(self, client, path, expected):
        response = client.get(path)
        assert response.status_code == 200
        assert expected in response.text
        assert 'aria-label="设置进度"' in response.text
        assert 'name="_csrf_token"' in response.text

    def test_welcome_continue(self, client):
        response = _post(client, "/setup/welcome")
        assert response.url.path == "/setup/ai"

    def test_settings_center_can_reopen_wizard(self, client):
        response = client.get("/settings")
        assert response.status_code == 200
        assert 'href="/setup/welcome"' in response.text
        assert "首次使用向导" in response.text

    def test_complete_summary_contains_no_vault_path(self, client, tmp_path):
        from signalvault.services.obsidian_settings_service import (
            update_obsidian_settings,
        )

        secret_path = tmp_path / "private-vault-name"
        secret_path.mkdir()
        update_obsidian_settings({"vault_path": str(secret_path)})
        response = client.get("/setup/complete")
        assert response.status_code == 200
        assert str(secret_path) not in response.text
        assert "已保存 Vault 路径" in response.text

    def test_complete_submit_finishes_and_dashboard_works_without_obsidian(self, client):
        response = _post(client, "/setup/complete", page="/setup/complete")
        assert response.url.path == "/dashboard"
        assert response.status_code == 200
        assert "SQLite" in response.text


class TestAIWizard:
    def test_mock_save_path(self, client):
        response = _post(
            client,
            "/setup/ai",
            {"provider": "mock", "base_url": "", "model": "mock-v1"},
            page="/setup/ai",
        )
        assert response.url.path == "/setup/obsidian"

        from signalvault.services.onboarding_service import get_onboarding_state

        assert get_onboarding_state().skipped_ai is False

    def test_mock_save_and_test_success(self, client):
        response = _post(
            client,
            "/setup/ai/test",
            {"provider": "mock", "base_url": "", "model": "mock-v1"},
            page="/setup/ai",
        )
        assert response.status_code == 200
        assert "连接验证成功" in response.text
        assert 'value="mock-v1"' in response.text

    def test_real_configuration_calls_existing_services(self, client, monkeypatch):
        import signalvault.services.ai_settings_service as service

        calls: list[tuple[str, object]] = []

        def fake_update(values):
            calls.append(("update", values.copy()))
            return {"ok": True}

        def fake_secret(value):
            calls.append(("secret", value))
            return {"ok": True}

        monkeypatch.setattr(service, "update_ai_settings", fake_update)
        monkeypatch.setattr(service, "replace_llm_secret", fake_secret)

        response = _post(
            client,
            "/setup/ai",
            {
                "provider": "openai-compatible",
                "base_url": "https://provider.example/v1",
                "model": "model-a",
                "api_key": "key-for-service-only",
            },
            page="/setup/ai",
        )
        assert response.url.path == "/setup/obsidian"
        assert calls[0][0] == "update"
        assert calls[1] == ("secret", "key-for-service-only")

    def test_failed_test_preserves_fields_but_never_key(self, client, monkeypatch):
        import signalvault.services.ai_settings_service as service

        async def failed(**_kwargs):
            return {"ok": False, "user_message": "服务暂时不可达"}

        monkeypatch.setattr(service, "test_llm_connection", failed)
        api_key = "sk-do-not-render-123456789"
        response = _post(
            client,
            "/setup/ai/test",
            {
                "provider": "openai-compatible",
                "base_url": "https://unreachable.example/v1",
                "model": "long-model-name",
                "api_key": api_key,
            },
            page="/setup/ai",
        )
        assert response.status_code == 200
        assert "服务暂时不可达" in response.text
        assert "https://unreachable.example/v1" in response.text
        assert "long-model-name" in response.text
        assert api_key not in response.text
        assert 'id="setup-api-key" name="api_key" type="password" value=""' in response.text

    def test_ai_failure_can_still_continue(self, client, monkeypatch):
        import signalvault.services.ai_settings_service as service

        async def failed(**_kwargs):
            return {"ok": False, "error": "鉴权失败"}

        monkeypatch.setattr(service, "test_llm_connection", failed)
        failed_response = _post(
            client,
            "/setup/ai/test",
            {"provider": "mock", "base_url": "", "model": "mock-v1"},
            page="/setup/ai",
        )
        assert "稍后配置" in failed_response.text
        token = re.search(
            r'name="_csrf_token" value="([^"]+)"', failed_response.text
        ).group(1)
        response = client.post(
            "/setup/ai", data={"_csrf_token": token, "intent": "skip"}
        )
        assert response.url.path == "/setup/obsidian"


class TestObsidianWizard:
    def test_skip_obsidian(self, client):
        response = _post(
            client,
            "/setup/obsidian",
            {"intent": "skip"},
            page="/setup/obsidian",
        )
        assert response.url.path == "/setup/complete"

        from signalvault.services.onboarding_service import get_onboarding_state

        assert get_onboarding_state().skipped_obsidian is True

    def test_validate_and_preview(self, client, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        response = _post(
            client,
            "/setup/obsidian/validate",
            {"vault_path": str(vault)},
            page="/setup/obsidian",
        )
        assert response.status_code == 200
        assert "路径验证通过" in response.text
        assert "初始化预览" in response.text
        assert "初始化 Vault" in response.text

    def test_initialize_uses_service_and_saves_path(self, client, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        response = _post(
            client,
            "/setup/obsidian/initialize",
            {"vault_path": str(vault)},
            page="/setup/obsidian",
        )
        assert response.status_code == 200
        assert "初始化完成" in response.text
        assert "Vault 已就绪，无需重复初始化" in response.text
        assert ">初始化 Vault</button>" not in response.text
        assert (vault / "99_System" / "signalvault_manifest.json").exists()

        from signalvault.settings.service import get_config_service

        assert get_config_service().get("obsidian.vault_path") == str(vault)

    def test_manifest_conflict_is_readable_and_non_destructive(self, client, tmp_path):
        vault = tmp_path / "conflict"
        system = vault / "99_System"
        system.mkdir(parents=True)
        manifest = system / "signalvault_manifest.json"
        original = json.dumps({"managed_by": "other_tool", "vault_schema_version": 1})
        manifest.write_text(original, encoding="utf-8")

        response = _post(
            client,
            "/setup/obsidian/validate",
            {"vault_path": str(vault)},
            page="/setup/obsidian",
        )
        assert response.status_code == 200
        assert "Manifest 冲突" in response.text
        assert manifest.read_text(encoding="utf-8") == original


class TestWizardSecurity:
    POST_ROUTES = [
        "/setup/welcome",
        "/setup/skip",
        "/setup/ai",
        "/setup/ai/test",
        "/setup/obsidian",
        "/setup/obsidian/validate",
        "/setup/obsidian/initialize",
        "/setup/complete",
    ]

    @pytest.mark.parametrize("path", POST_ROUTES)
    def test_every_post_requires_csrf(self, client, path):
        response = client.post(path, data={})
        assert response.status_code == 403
        assert "请求已失效" in response.text
        assert 'name="_csrf_token"' not in response.text

    def test_invalid_csrf_is_rejected_without_leaks(self, client):
        _csrf(client)
        response = client.post(
            "/setup/ai/test",
            data={"_csrf_token": "invalid", "api_key": "sk-sensitive-value"},
        )
        assert response.status_code == 403
        assert "sk-sensitive-value" not in response.text
        assert "signalvault_csrf" not in response.text

    def test_non_local_origin_is_rejected(self, client):
        token = _csrf(client)
        response = client.post(
            "/setup/welcome",
            data={"_csrf_token": token},
            headers={"Origin": "http://127.0.0.1.attacker.example"},
        )
        assert response.status_code == 403

    def test_existing_c2_settings_pages_do_not_regress(self, client):
        for path in (
            "/settings",
            "/settings/ai",
            "/settings/obsidian",
            "/settings/system",
            "/settings/about",
        ):
            response = client.get(path)
            assert response.status_code == 200, path
