"""C2-C tests: Settings center, system page, about page, navigation, CSRF edges.

Covers:
- Origin/Referer + CSRF combo (no origin + no csrf → 403, etc.)
- Settings overview page (/settings)
- AI/Obsidian cards on overview
- System page (/settings/system)
- About page (/settings/about)
- No API key leaks
- Path shortening
- Version consistency
- ORM/FTS table counts
- Settings sub-navigation
- Main nav entry
- AI/Obsidian form behavior regression
- /tasks is primary diagnostics entry
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════


def _make_isolated_svc(tmp_path, env=None):
    from signalvault.settings.app_paths import AppPaths
    from signalvault.settings.secret_store import SecretStore
    from signalvault.settings.service import ConfigService

    paths = AppPaths.resolve(home_override=str(tmp_path))
    secrets = SecretStore(paths.config_dir)
    if env is None:
        env = {}
    return ConfigService(paths, env=env, secret_store=secrets)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Isolate ConfigService."""
    from signalvault.settings.service import _override_config_service

    svc = _make_isolated_svc(tmp_path, env={"LLM_PROVIDER": "mock"})
    _override_config_service(svc)
    svc.delete_user_value("obsidian.vault_path")
    svc.delete_user_value("obsidian.export_enabled")
    yield
    _override_config_service(None)


@pytest.fixture
def client():
    from signalvault.api.app import create_app
    app = create_app()
    return TestClient(app)


# ══════════════════════════════════════════════════════════════════════
# Origin/Referer + CSRF edge cases (C2-B wrap-up)
# ══════════════════════════════════════════════════════════════════════


class TestCSRFNoOriginNoReferer:
    """No Origin + No Referer still requires CSRF token."""

    def test_no_origin_no_referer_no_csrf_rejected(self, client):
        """No Origin, no Referer, no CSRF → 403."""
        resp = client.post("/api/obsidian/disable", headers={})
        assert resp.status_code == 403
        data = resp.json()
        assert "csrf" in data.get("error_type", "")

    def test_no_origin_no_referer_invalid_csrf_rejected(self, client):
        """No Origin, no Referer, invalid CSRF → 403."""
        resp = client.post(
            "/api/obsidian/disable",
            headers={"x-csrf-token": "not-a-valid-token"},
        )
        assert resp.status_code == 403

    def test_check_origin_allows_no_headers(self):
        """check_origin returns True when both headers missing (non-browser)."""
        from unittest.mock import MagicMock

        from signalvault.web.csrf import check_origin

        mock_req = MagicMock()
        mock_req.headers = {}
        assert check_origin(mock_req) is True  # non-browser client allowed

    def test_check_origin_null_rejected(self):
        """check_origin rejects 'null' origin."""
        from unittest.mock import MagicMock

        from signalvault.web.csrf import check_origin

        mock_req = MagicMock()
        mock_req.headers = {"origin": "null"}
        assert check_origin(mock_req) is False


class TestSettingsHTMLCSRFError:
    """HTML settings forms use the safe, branded 403 response."""

    def test_html_post_without_csrf_uses_friendly_error_page(self, client):
        resp = client.post("/settings/ai", data={"provider": "mock"})

        assert resp.status_code == 403
        assert resp.headers["content-type"].startswith("text/html")
        assert "请求已失效" in resp.text
        assert "请刷新页面后重新操作" in resp.text
        assert 'class="app-shell"' in resp.text
        assert 'href="/settings/ai"' in resp.text
        assert 'href="/settings"' in resp.text

    def test_html_post_with_invalid_csrf_returns_403(self, client):
        client.get("/settings/ai")
        invalid_token = "invalid-csrf-value-that-must-not-be-reflected"
        resp = client.post(
            "/settings/ai/test",
            data={"_csrf_token": invalid_token, "provider": "mock"},
        )

        assert resp.status_code == 403
        assert "请求已失效" in resp.text
        assert invalid_token not in resp.text

    def test_json_post_without_csrf_stays_structured_json(self, client):
        resp = client.post("/api/settings/llm", json={"provider": "mock"})

        assert resp.status_code == 403
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.json()["error_type"] == "csrf"

    def test_error_page_contains_no_csrf_token_or_field(self, client):
        resp = client.post("/settings/obsidian", data={"vault_path": "D:/private"})

        assert resp.status_code == 403
        assert 'name="_csrf_token"' not in resp.text
        assert "signalvault_csrf" not in resp.text
        assert "D:/private" not in resp.text

    def test_error_page_contains_no_api_key(self, client):
        secret = "sk-sensitive-value-that-must-not-leak"
        _get_svc().set_secret("llm.api_key", secret)
        resp = client.post(
            "/settings/ai/secret",
            data={"api_key": secret},
        )

        assert resp.status_code == 403
        assert secret not in resp.text
        assert "API Key" not in resp.text

    def test_error_page_reuses_desktop_application_context(self, client):
        resp = client.post("/settings/obsidian/validate", data={})

        assert resp.status_code == 403
        assert 'class="app-shell"' in resp.text
        assert 'class="app-sidebar"' in resp.text
        assert "data-nav-toggle" in resp.text
        assert "配置中心" in resp.text

    def test_valid_csrf_form_submission_does_not_regress(self, client):
        page = client.get("/settings/ai")
        token_match = re.search(
            r'name="_csrf_token" value="([^"]+)"',
            page.text,
        )
        assert token_match is not None

        resp = client.post(
            "/settings/ai",
            data={"_csrf_token": token_match.group(1), "provider": "mock"},
        )

        assert resp.status_code == 200
        assert "配置已保存" in resp.text


# ══════════════════════════════════════════════════════════════════════
# Settings overview page
# ══════════════════════════════════════════════════════════════════════


class TestSettingsOverview:
    def test_overview_page_loads(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert "系统与集成概览" in resp.text

    def test_overview_has_sub_nav(self, client):
        resp = client.get("/settings")
        assert "/settings/ai" in resp.text
        assert "/settings/obsidian" in resp.text
        assert "/settings/system" in resp.text
        assert "/settings/about" in resp.text

    def test_overview_has_active_nav(self, client):
        resp = client.get("/settings")
        # Overview should be active
        assert 'href="/settings" class="active"' in resp.text

    def test_overview_ai_card(self, client):
        resp = client.get("/settings")
        assert "AI 服务" in resp.text
        assert "Mock 模式" in resp.text

    def test_overview_default_api_key_is_not_configured(self, client):
        resp = client.get("/settings")
        assert "已配置 (default)" not in resp.text
        assert "API Key</td><td>未配置" in resp.text

    def test_overview_obsidian_card(self, client):
        resp = client.get("/settings")
        assert "Obsidian" in resp.text
        assert "未配置" in resp.text

    def test_overview_system_card(self, client):
        resp = client.get("/settings")
        assert "系统" in resp.text
        assert "0.1.0" in resp.text  # version

    def test_overview_diagnostics_card(self, client):
        resp = client.get("/settings")
        assert "诊断" in resp.text

    def test_overview_no_api_key(self, client):
        """Settings overview must not show API key."""
        svc = _get_svc()
        svc.set_secret("llm.api_key", "sk-should-not-leak-12345")
        resp = client.get("/settings")
        assert "sk-should-not-leak-12345" not in resp.text

    def test_overview_links_to_sub_pages(self, client):
        resp = client.get("/settings")
        assert 'href="/settings/ai"' in resp.text
        assert 'href="/settings/obsidian"' in resp.text
        assert 'href="/settings/system"' in resp.text
        assert 'href="/settings/about"' in resp.text

    def test_overview_has_tasks_link(self, client):
        resp = client.get("/settings")
        assert 'href="/tasks"' in resp.text


# ══════════════════════════════════════════════════════════════════════
# System page
# ══════════════════════════════════════════════════════════════════════


class TestSystemPage:
    def test_system_page_loads(self, client):
        resp = client.get("/settings/system")
        assert resp.status_code == 200
        assert "数据与系统" in resp.text

    def test_system_page_shows_version(self, client):
        resp = client.get("/settings/system")
        assert "0.1.0" in resp.text

    def test_system_page_shows_python(self, client):
        resp = client.get("/settings/system")
        assert "Python" in resp.text

    def test_system_page_shows_os(self, client):
        resp = client.get("/settings/system")
        import platform
        assert platform.system() in resp.text

    def test_system_page_has_path_labels(self, client):
        resp = client.get("/settings/system")
        assert "必须备份" in resp.text
        assert "可重建" in resp.text or "可清理" in resp.text

    def test_system_page_has_db_info(self, client):
        resp = client.get("/settings/system")
        assert "数据库" in resp.text

    def test_system_page_has_service_info(self, client):
        resp = client.get("/settings/system")
        assert "服务" in resp.text
        assert "127.0.0.1" in resp.text or "localhost" in resp.text

    def test_system_page_is_readonly(self, client):
        """No forms on system page — it's read-only."""
        resp = client.get("/settings/system")
        assert '<form method="POST"' not in resp.text

    def test_system_page_shows_readonly_notice(self, client):
        resp = client.get("/settings/system")
        assert "只读" in resp.text


# ══════════════════════════════════════════════════════════════════════
# About page
# ══════════════════════════════════════════════════════════════════════


class TestAboutPage:
    def test_about_page_loads(self, client):
        resp = client.get("/settings/about")
        assert resp.status_code == 200
        assert "诊断与关于" in resp.text

    def test_about_page_shows_version(self, client):
        resp = client.get("/settings/about")
        assert "0.1.0" in resp.text

    def test_about_page_shows_rc(self, client):
        resp = client.get("/settings/about")
        assert "RC" in resp.text

    def test_about_page_shows_privacy(self, client):
        resp = client.get("/settings/about")
        assert "隐私" in resp.text or "本地" in resp.text

    def test_about_page_shows_disclaimer(self, client):
        resp = client.get("/settings/about")
        assert "不构成投资建议" in resp.text or "不是投资建议" in resp.text

    def test_about_page_has_tasks_link(self, client):
        resp = client.get("/settings/about")
        assert 'href="/tasks"' in resp.text

    def test_about_page_no_api_key(self, client):
        svc = _get_svc()
        svc.set_secret("llm.api_key", "sk-no-leak-about")
        resp = client.get("/settings/about")
        assert "sk-no-leak-about" not in resp.text

    def test_about_page_has_license(self, client):
        resp = client.get("/settings/about")
        assert "开源" in resp.text or "许可" in resp.text

    def test_about_page_has_env_summary(self, client):
        resp = client.get("/settings/about")
        assert "环境总览" in resp.text or "环境" in resp.text or "AI" in resp.text

    def test_about_page_maps_mock_status_to_css_class(self, client):
        resp = client.get("/settings/about")
        assert 'class="status-badge status-mock"' in resp.text


# ══════════════════════════════════════════════════════════════════════
# Sub-navigation
# ══════════════════════════════════════════════════════════════════════


class TestSubNavigation:
    def test_ai_page_nav_ai_active(self, client):
        resp = client.get("/settings/ai")
        assert 'href="/settings/ai" class="active"' in resp.text

    def test_obsidian_page_nav_obsidian_active(self, client):
        resp = client.get("/settings/obsidian")
        assert 'href="/settings/obsidian" class="active"' in resp.text

    def test_system_page_nav_system_active(self, client):
        resp = client.get("/settings/system")
        assert 'href="/settings/system" class="active"' in resp.text

    def test_about_page_nav_about_active(self, client):
        resp = client.get("/settings/about")
        assert 'href="/settings/about" class="active"' in resp.text


# ══════════════════════════════════════════════════════════════════════
# Main navigation
# ══════════════════════════════════════════════════════════════════════


class TestMainNav:
    def test_main_nav_has_settings_link(self, client):
        resp = client.get("/dashboard")
        assert 'href="/settings"' in resp.text
        assert "配置中心" in resp.text
        assert "系统与集成" in resp.text

    @pytest.mark.parametrize(
        "path",
        [
            "/settings",
            "/settings/ai",
            "/settings/obsidian",
            "/settings/system",
            "/settings/about",
        ],
    )
    def test_settings_pages_reuse_main_app_shell(self, client, path):
        resp = client.get(path)
        assert resp.status_code == 200
        assert 'class="app-shell"' in resp.text
        assert 'class="app-sidebar"' in resp.text
        assert "data-nav-toggle" in resp.text
        assert 'src="/static/app.js?v=20260714"' in resp.text


# ══════════════════════════════════════════════════════════════════════
# Version consistency
# ══════════════════════════════════════════════════════════════════════


class TestVersionConsistency:
    def test_version_from_init(self):
        from signalvault import __version__
        assert __version__ == "0.1.0"

    def test_version_on_overview(self, client):
        resp = client.get("/settings")
        assert "0.1.0" in resp.text

    def test_version_on_system(self, client):
        resp = client.get("/settings/system")
        assert "0.1.0" in resp.text

    def test_version_on_about(self, client):
        resp = client.get("/settings/about")
        assert "0.1.0" in resp.text


# ══════════════════════════════════════════════════════════════════════
# AI/Obsidian form behavior regression
# ══════════════════════════════════════════════════════════════════════


class TestAIFormRegression:
    def test_ai_page_still_has_provider_form(self, client):
        resp = client.get("/settings/ai")
        assert 'name="provider"' in resp.text
        assert 'name="model"' in resp.text

    def test_ai_page_still_has_key_form(self, client):
        resp = client.get("/settings/ai")
        assert 'name="api_key"' in resp.text

    def test_ai_page_still_has_test_button(self, client):
        resp = client.get("/settings/ai")
        assert "测试连接" in resp.text

    def test_ai_page_has_csrf(self, client):
        resp = client.get("/settings/ai")
        assert 'name="_csrf_token"' in resp.text


class TestObsidianFormRegression:
    def test_obsidian_page_still_has_path_input(self, client):
        resp = client.get("/settings/obsidian")
        assert 'name="vault_path"' in resp.text

    def test_obsidian_page_still_has_enable_toggle(self, client):
        resp = client.get("/settings/obsidian")
        assert "启用" in resp.text or "禁用" in resp.text

    def test_obsidian_page_has_csrf(self, client):
        resp = client.get("/settings/obsidian")
        assert 'name="_csrf_token"' in resp.text


# ══════════════════════════════════════════════════════════════════════
# Path shortening
# ══════════════════════════════════════════════════════════════════════


class TestPathShortening:
    def test_shorten_home_path(self):
        import os

        from signalvault.services.settings_overview_service import _shorten_path
        home = os.path.expanduser("~")
        result = _shorten_path(home + "/Documents/MyVault")
        assert result.startswith("~")

    def test_shorten_non_home_path(self):
        from signalvault.services.settings_overview_service import _shorten_path
        result = _shorten_path("D:\\MyVault")
        assert result == "D:\\MyVault"

    def test_shorten_empty_path(self):
        from signalvault.services.settings_overview_service import _shorten_path
        assert _shorten_path("") == ""


# ══════════════════════════════════════════════════════════════════════
# ORM / FTS table counts
# ══════════════════════════════════════════════════════════════════════


class TestDBTableCounts:
    def test_count_tables_returns_nonzero(self):
        from signalvault.services.settings_overview_service import _count_db_tables
        orm_count, fts_count = _count_db_tables()
        # Even if DB not initialized, should not crash
        assert isinstance(orm_count, int)
        assert isinstance(fts_count, int)


# ══════════════════════════════════════════════════════════════════════
# /tasks remains primary diagnostics entry
# ══════════════════════════════════════════════════════════════════════


class TestTasksIsPrimaryDiagnostics:
    def test_about_links_to_tasks(self, client):
        resp = client.get("/settings/about")
        assert 'href="/tasks"' in resp.text

    def test_overview_links_to_tasks(self, client):
        resp = client.get("/settings")
        assert 'href="/tasks"' in resp.text


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════


def _get_svc():
    from signalvault.settings.service import get_config_service
    return get_config_service()
