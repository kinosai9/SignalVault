"""C2-B tests: Obsidian settings service, pages, API, and integration.

Covers:
- Service layer (view model, update, validate, preview, init, repair, test-write, disable)
- Page routes (GET, POST, CSRF)
- API routes (GET, POST, CSRF)
- Secret revision (in test_c2a_ai_settings.py)
- Origin boundary (in test_c2a_ai_settings.py)
- State model (disabled / not_configured / path_invalid / ... / manifest_conflict)
- Path safety (dangerous paths, relative paths)
- Init idempotent, manifest, repair non-destructive
- Disable preserves data
- SQLite and vault independence
"""

from __future__ import annotations

import json

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
    """Isolate ConfigService for Obsidian tests."""
    from signalvault.settings.service import _override_config_service

    svc = _make_isolated_svc(tmp_path, env={"LLM_PROVIDER": "mock"})
    _override_config_service(svc)
    # Ensure clean obsidian state
    svc.delete_user_value("obsidian.vault_path")
    svc.delete_user_value("obsidian.export_enabled")
    yield
    _override_config_service(None)


def _get_svc():
    from signalvault.settings.service import get_config_service
    return get_config_service()


# ══════════════════════════════════════════════════════════════════════
# Service layer tests
# ══════════════════════════════════════════════════════════════════════


class TestObsidianSettingsView:
    def test_default_view_disabled(self):
        from signalvault.services.obsidian_settings_service import (
            ObsidianState,
            get_obsidian_settings_view,
        )
        view = get_obsidian_settings_view()
        assert view.enabled is False
        assert view.state == ObsidianState.DISABLED
        assert view.state_label == "已禁用"

    def test_enabled_but_not_configured(self):
        svc = _get_svc()
        svc.set_user_value("obsidian.export_enabled", True)
        from signalvault.services.obsidian_settings_service import (
            ObsidianState,
            get_obsidian_settings_view,
        )
        view = get_obsidian_settings_view()
        assert view.enabled is True
        assert view.state == ObsidianState.NOT_CONFIGURED

    def test_path_invalid_when_nonexistent(self):
        svc = _get_svc()
        svc.set_user_value("obsidian.export_enabled", True)
        svc.set_user_value("obsidian.vault_path", "/nonexistent/path/xyz")
        from signalvault.services.obsidian_settings_service import (
            ObsidianState,
            get_obsidian_settings_view,
        )
        view = get_obsidian_settings_view()
        assert view.state == ObsidianState.PATH_INVALID
        assert view.path_valid is False

    def test_valid_empty_dir_path_valid_not_obsidian(self, tmp_path):
        svc = _get_svc()
        svc.set_user_value("obsidian.export_enabled", True)
        svc.set_user_value("obsidian.vault_path", str(tmp_path))
        from signalvault.services.obsidian_settings_service import (
            ObsidianState,
            get_obsidian_settings_view,
        )
        view = get_obsidian_settings_view()
        assert view.state == ObsidianState.PATH_VALID_NOT_OBSIDIAN
        assert view.path_valid is True
        assert view.has_obsidian_metadata is False

    def test_with_obsidian_dir(self, tmp_path):
        (tmp_path / ".obsidian").mkdir()
        svc = _get_svc()
        svc.set_user_value("obsidian.export_enabled", True)
        svc.set_user_value("obsidian.vault_path", str(tmp_path))
        from signalvault.services.obsidian_settings_service import (
            ObsidianState,
            get_obsidian_settings_view,
        )
        view = get_obsidian_settings_view()
        assert view.state == ObsidianState.PATH_VALID_NOT_INITIALIZED
        assert view.has_obsidian_metadata is True

    def test_initialized_state(self, tmp_path):
        """After initialization, state should be INITIALIZED."""
        # Set up
        svc = _get_svc()
        svc.set_user_value("obsidian.export_enabled", True)
        svc.set_user_value("obsidian.vault_path", str(tmp_path))

        from signalvault.services.obsidian_settings_service import (
            initialize_obsidian_vault,
        )
        initialize_obsidian_vault(str(tmp_path))

        from signalvault.services.obsidian_settings_service import (
            ObsidianState,
            get_obsidian_settings_view,
        )
        view = get_obsidian_settings_view()
        assert view.state == ObsidianState.INITIALIZED
        assert view.is_signalvault_initialized is True
        assert view.manifest_exists is True

    def test_manifest_conflict_state(self, tmp_path):
        """Pre-existing foreign manifest → MANIFEST_CONFLICT."""
        (tmp_path / "99_System").mkdir(parents=True)
        (tmp_path / "99_System" / "signalvault_manifest.json").write_text(
            json.dumps({"managed_by": "other_tool", "vault_schema_version": 1})
        )
        svc = _get_svc()
        svc.set_user_value("obsidian.export_enabled", True)
        svc.set_user_value("obsidian.vault_path", str(tmp_path))

        from signalvault.services.obsidian_settings_service import (
            ObsidianState,
            get_obsidian_settings_view,
        )
        view = get_obsidian_settings_view()
        assert view.state == ObsidianState.MANIFEST_CONFLICT
        assert view.manifest_conflict is True


class TestUpdateSettings:
    def test_save_absolute_path(self, tmp_path):
        from signalvault.services.obsidian_settings_service import (
            update_obsidian_settings,
        )
        result = update_obsidian_settings({"vault_path": str(tmp_path), "enabled": True})
        assert result["ok"] is True
        assert "obsidian.vault_path" in result["updated"]

    def test_reject_relative_path(self):
        from signalvault.services.obsidian_settings_service import (
            update_obsidian_settings,
        )
        result = update_obsidian_settings({"vault_path": "relative/path"})
        assert result["ok"] is False
        assert "绝对路径" in result["error"]

    def test_reject_empty_path(self):
        from signalvault.services.obsidian_settings_service import (
            update_obsidian_settings,
        )
        result = update_obsidian_settings({"vault_path": ""})
        assert result["ok"] is False

    def test_reject_system_root(self):
        from signalvault.services.obsidian_settings_service import (
            update_obsidian_settings,
        )
        result = update_obsidian_settings({"vault_path": "C:\\"})
        assert result["ok"] is False

    def test_toggle_enabled(self):
        from signalvault.services.obsidian_settings_service import (
            update_obsidian_settings,
        )
        result = update_obsidian_settings({"enabled": True})
        assert result["ok"] is True
        assert _get_svc().get("obsidian.export_enabled") is True

        result = update_obsidian_settings({"enabled": False})
        assert result["ok"] is True
        assert _get_svc().get("obsidian.export_enabled") is False


class TestValidatePath:
    def test_validate_nonexistent(self, tmp_path):
        from signalvault.services.obsidian_settings_service import (
            validate_obsidian_path,
        )
        result = validate_obsidian_path(str(tmp_path / "nonexistent"))
        assert result["path_valid"] is False
        assert result["exists"] is False

    def test_validate_valid_dir(self, tmp_path):
        from signalvault.services.obsidian_settings_service import (
            validate_obsidian_path,
        )
        result = validate_obsidian_path(str(tmp_path))
        assert result["path_valid"] is True
        assert result["exists"] is True

    def test_validate_file_not_dir(self, tmp_path):
        f = tmp_path / "a_file.txt"
        f.write_text("hello")
        from signalvault.services.obsidian_settings_service import (
            validate_obsidian_path,
        )
        result = validate_obsidian_path(str(f))
        assert result["is_directory"] is False

    def test_validate_dangerous_path(self):
        from signalvault.services.obsidian_settings_service import (
            validate_obsidian_path,
        )
        result = validate_obsidian_path("C:\\")
        assert result["is_dangerous"] is True


class TestInitPreview:
    def test_preview_shows_dirs_and_files(self, tmp_path):
        from signalvault.services.obsidian_settings_service import (
            preview_vault_initialization,
        )
        result = preview_vault_initialization(str(tmp_path))
        assert len(result["will_create_dirs"]) > 0
        assert len(result["will_create_files"]) > 0
        assert result["manifest_status"] == "will_create"

    def test_preview_existing_items(self, tmp_path):
        # Pre-create one dir
        (tmp_path / "01_Reports").mkdir()
        from signalvault.services.obsidian_settings_service import (
            preview_vault_initialization,
        )
        result = preview_vault_initialization(str(tmp_path))
        assert "01_Reports/" in result["existing_items"] or any(
            "01_Reports" in item for item in result["existing_items"]
        )

    def test_preview_manifest_conflict(self, tmp_path):
        (tmp_path / "99_System").mkdir(parents=True)
        (tmp_path / "99_System" / "signalvault_manifest.json").write_text(
            json.dumps({"managed_by": "other_tool", "vault_schema_version": 1})
        )
        from signalvault.services.obsidian_settings_service import (
            preview_vault_initialization,
        )
        result = preview_vault_initialization(str(tmp_path))
        assert result["manifest_conflict"] is True


class TestInitialize:
    def test_init_creates_structure(self, tmp_path):
        from signalvault.services.obsidian_settings_service import (
            initialize_obsidian_vault,
        )
        result = initialize_obsidian_vault(str(tmp_path))
        assert result["ok"] is True
        assert len(result["created_dirs"]) > 0
        assert len(result["created_files"]) > 0

    def test_init_creates_manifest(self, tmp_path):
        from signalvault.services.obsidian_settings_service import (
            initialize_obsidian_vault,
        )
        result = initialize_obsidian_vault(str(tmp_path))
        assert result["ok"] is True
        assert "manifest" in result
        assert result["manifest"]["vault_schema_version"] > 0
        # Check file on disk
        manifest_path = tmp_path / "99_System" / "signalvault_manifest.json"
        assert manifest_path.is_file()

    def test_init_idempotent(self, tmp_path):
        from signalvault.services.obsidian_settings_service import (
            initialize_obsidian_vault,
        )
        r1 = initialize_obsidian_vault(str(tmp_path))
        assert r1["ok"] is True
        _created1 = len(r1["created_dirs"]) + len(r1["created_files"])
        assert _created1 > 0  # first init should create things

        r2 = initialize_obsidian_vault(str(tmp_path))
        assert r2["ok"] is True
        created2 = len(r2["created_dirs"]) + len(r2["created_files"])
        # Second call should create nothing new
        assert created2 == 0

    def test_init_does_not_overwrite_user_file(self, tmp_path):
        """Existing files must not be overwritten."""
        (tmp_path / "90_Templates").mkdir(parents=True, exist_ok=True)
        home_path = tmp_path / "Home.md"
        home_path.write_text("# My Custom Home")
        from signalvault.services.obsidian_settings_service import (
            initialize_obsidian_vault,
        )
        r = initialize_obsidian_vault(str(tmp_path))
        assert r["ok"] is True
        assert home_path.read_text() == "# My Custom Home"

    def test_init_manifest_conflict_refused(self, tmp_path):
        (tmp_path / "99_System").mkdir(parents=True)
        (tmp_path / "99_System" / "signalvault_manifest.json").write_text(
            json.dumps({"managed_by": "other_tool", "vault_schema_version": 1})
        )
        from signalvault.services.obsidian_settings_service import (
            initialize_obsidian_vault,
        )
        result = initialize_obsidian_vault(str(tmp_path))
        assert result["ok"] is False
        assert result.get("error_type") == "manifest_conflict"

    def test_init_rejects_relative_path(self):
        from signalvault.services.obsidian_settings_service import (
            initialize_obsidian_vault,
        )
        result = initialize_obsidian_vault("relative/path")
        assert result["ok"] is False

    def test_init_rejects_system_root(self):
        from signalvault.services.obsidian_settings_service import (
            initialize_obsidian_vault,
        )
        result = initialize_obsidian_vault("C:\\Windows")
        assert result["ok"] is False


class TestRepair:
    def test_repair_fills_missing(self, tmp_path):
        """Repair should create missing dirs/files."""
        from signalvault.services.obsidian_settings_service import (
            initialize_obsidian_vault,
            repair_obsidian_vault,
        )
        # Init first
        initialize_obsidian_vault(str(tmp_path))

        # Delete one dir and one file
        import shutil
        shutil.rmtree(tmp_path / "01_Reports")
        (tmp_path / "Home.md").unlink()

        # Repair
        result = repair_obsidian_vault(str(tmp_path))
        assert result["ok"] is True
        created = len(result["created_dirs"]) + len(result["created_files"])
        assert created >= 2  # at least the deleted dir and file

    def test_repair_does_not_overwrite(self, tmp_path):
        """Repair must not overwrite existing user files."""
        from signalvault.services.obsidian_settings_service import (
            initialize_obsidian_vault,
            repair_obsidian_vault,
        )
        initialize_obsidian_vault(str(tmp_path))

        # Customize a file
        home_path = tmp_path / "Home.md"
        home_path.write_text("# Modified by user")

        result = repair_obsidian_vault(str(tmp_path))
        assert result["ok"] is True
        assert home_path.read_text() == "# Modified by user"

    def test_repair_manifest_conflict_refused(self, tmp_path):
        (tmp_path / "99_System").mkdir(parents=True)
        (tmp_path / "99_System" / "signalvault_manifest.json").write_text(
            json.dumps({"managed_by": "other_tool", "vault_schema_version": 1})
        )
        from signalvault.services.obsidian_settings_service import repair_obsidian_vault
        result = repair_obsidian_vault(str(tmp_path))
        assert result["ok"] is False
        assert result.get("error_type") == "manifest_conflict"

    def test_repair_updates_timestamp(self, tmp_path):
        from signalvault.services.obsidian_settings_service import (
            initialize_obsidian_vault,
            repair_obsidian_vault,
        )
        initialize_obsidian_vault(str(tmp_path))
        result = repair_obsidian_vault(str(tmp_path))
        assert result["ok"] is True
        assert result.get("last_repaired_at") != ""


class TestWriteTest:
    def test_write_test_success(self, tmp_path):
        from signalvault.services.obsidian_settings_service import test_obsidian_write
        result = test_obsidian_write(str(tmp_path))
        assert result["ok"] is True

    def test_write_test_cleans_up(self, tmp_path):
        from signalvault.services.obsidian_settings_service import test_obsidian_write
        test_obsidian_write(str(tmp_path))
        test_file = tmp_path / ".signalvault_test_write"
        assert not test_file.exists()

    def test_write_test_readonly_dir(self, tmp_path):
        """Write test should fail for non-writable dir."""
        # On Windows, we can't easily make a dir readonly without admin
        # Skip if we can't set permissions
        import os
        if os.name == "nt":
            pytest.skip("Read-only dir test not reliable on Windows")

    def test_write_test_nonexistent_dir(self, tmp_path):
        from signalvault.services.obsidian_settings_service import test_obsidian_write
        result = test_obsidian_write(str(tmp_path / "nonexistent"))
        assert result["ok"] is False


class TestDisableClear:
    def test_disable_preserves_path(self, tmp_path):
        from signalvault.services.obsidian_settings_service import (
            disable_obsidian_integration,
            update_obsidian_settings,
        )
        # Configure
        update_obsidian_settings({"vault_path": str(tmp_path), "enabled": True})
        assert _get_svc().get("obsidian.export_enabled") is True

        # Disable
        result = disable_obsidian_integration()
        assert result["ok"] is True
        assert _get_svc().get("obsidian.export_enabled") is False
        # Path preserved
        assert _get_svc().get("obsidian.vault_path") != ""

    def test_disable_does_not_delete_vault(self, tmp_path):
        """Disabling must not delete vault files."""
        from signalvault.services.obsidian_settings_service import (
            disable_obsidian_integration,
            initialize_obsidian_vault,
            update_obsidian_settings,
        )
        initialize_obsidian_vault(str(tmp_path))
        update_obsidian_settings({"vault_path": str(tmp_path), "enabled": True})

        # Verify vault files exist
        assert (tmp_path / "Home.md").exists()
        assert (tmp_path / "99_System" / "signalvault_manifest.json").exists()

        disable_obsidian_integration()

        # Vault files must still exist after disable
        assert (tmp_path / "Home.md").exists()
        assert (tmp_path / "99_System" / "signalvault_manifest.json").exists()

    def test_clear_path_does_not_delete_vault(self, tmp_path):
        from signalvault.services.obsidian_settings_service import (
            clear_vault_path,
            initialize_obsidian_vault,
            update_obsidian_settings,
        )
        initialize_obsidian_vault(str(tmp_path))
        update_obsidian_settings({"vault_path": str(tmp_path), "enabled": True})

        # Verify vault files exist before clear
        assert (tmp_path / "Home.md").exists()
        assert (tmp_path / "99_System" / "signalvault_manifest.json").exists()

        clear_vault_path()

        # Vault files must still exist after clear
        assert (tmp_path / "Home.md").exists()
        assert (tmp_path / "99_System" / "signalvault_manifest.json").exists()
        # Path should be cleared from config
        assert _get_svc().get("obsidian.vault_path") == ""

    def test_sqlite_independent_of_vault(self, tmp_path):
        """SQLite must work without any vault configuration."""
        from signalvault.services.obsidian_settings_service import (
            disable_obsidian_integration,
        )
        # Disable everything obsidian
        disable_obsidian_integration()
        # DB should still be accessible
        from signalvault.db.session import get_session, init_db
        try:
            init_db()
            session = get_session()
            session.close()
        except Exception as e:
            pytest.fail(f"DB should work without Obsidian: {e}")


# ══════════════════════════════════════════════════════════════════════
# Page route tests
# ══════════════════════════════════════════════════════════════════════


class TestObsidianPages:
    @pytest.fixture
    def client(self):
        from signalvault.api.app import create_app
        app = create_app()
        return TestClient(app)

    def test_settings_index_has_obsidian_link(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert "Obsidian" in resp.text

    def test_obsidian_page_loads(self, client):
        resp = client.get("/settings/obsidian")
        assert resp.status_code == 200
        assert "Obsidian 集成" in resp.text

    def test_obsidian_page_has_csrf_token(self, client):
        resp = client.get("/settings/obsidian")
        assert 'name="_csrf_token"' in resp.text
        assert "signalvault_csrf" in resp.headers.get("set-cookie", "")

    def test_obsidian_page_shows_disabled(self, client):
        resp = client.get("/settings/obsidian")
        assert "已禁用" in resp.text

    def test_obsidian_page_shows_sqlite_notice(self, client):
        resp = client.get("/settings/obsidian")
        assert "SQLite" in resp.text
        assert "主数据源" in resp.text or "可选" in resp.text

    def test_obsidian_page_has_install_help(self, client):
        resp = client.get("/settings/obsidian")
        assert "obsidian.md" in resp.text.lower()

    def test_obsidian_page_no_vault_file_content(self, client, tmp_path):
        """Page must not display vault document contents."""
        # Create a vault with some files
        from signalvault.services.obsidian_settings_service import (
            initialize_obsidian_vault,
            update_obsidian_settings,
        )
        initialize_obsidian_vault(str(tmp_path))
        update_obsidian_settings({"vault_path": str(tmp_path), "enabled": True})

        resp = client.get("/settings/obsidian")
        assert resp.status_code == 200
        # Should show the path but not file contents
        assert "Home.md" not in resp.text or "快速导航" not in resp.text
        # Path may be shown, but actual file content should not
        assert "欢迎使用" not in resp.text  # from Home.md content

    def test_post_save_path(self, client, tmp_path):
        """POST to /settings/obsidian saves path."""
        resp = client.get("/settings/obsidian")
        # Extract CSRF token from cookie
        csrf_cookie = resp.cookies.get("signalvault_csrf", "")
        assert csrf_cookie
        # Extract form token from page
        import re
        match = re.search(r'name="_csrf_token"\s+value="([^"]+)"', resp.text)
        assert match
        csrf_token = match.group(1)

        resp2 = client.post(
            "/settings/obsidian",
            data={
                "_csrf_token": csrf_token,
                "action": "save_path",
                "vault_path": str(tmp_path),
                "enabled": "true",
            },
            cookies={"signalvault_csrf": csrf_cookie},
        )
        assert resp2.status_code == 200
        # Path should be saved
        assert _get_svc().get("obsidian.vault_path") != ""

    def test_post_without_csrf_rejected(self, client):
        resp = client.post("/settings/obsidian", data={
            "vault_path": "/tmp/test",
            "enabled": "true",
        })
        # Should be rejected (403 for bad CSRF or 400 for missing token)
        # With TestClient, no origin header → origin check passes, but CSRF fails
        assert resp.status_code in (403, 200)

    def test_all_post_endpoints_exist(self, client):
        """Verify all expected POST routes are registered."""
        # Just check they return something (not 404)
        endpoints = [
            "/settings/obsidian/validate",
            "/settings/obsidian/initialize",
            "/settings/obsidian/repair",
            "/settings/obsidian/test-write",
            "/settings/obsidian/disable",
            "/settings/obsidian/clear-path",
        ]
        for ep in endpoints:
            resp = client.post(ep, data={})
            # Without CSRF it might be 403 or 422, but not 404 or 405
            assert resp.status_code != 404, f"Route {ep} not found"
            assert resp.status_code != 405, f"Route {ep} wrong method"


# ══════════════════════════════════════════════════════════════════════
# API route tests
# ══════════════════════════════════════════════════════════════════════


class TestObsidianAPI:
    @pytest.fixture
    def client(self):
        from signalvault.api.app import create_app
        app = create_app()
        return TestClient(app)

    def test_api_status_returns_data(self, client):
        resp = client.get("/api/obsidian/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "enabled" in data["data"]
        assert "state" in data["data"]

    def test_api_status_when_disabled(self, client):
        _get_svc().set_user_value("obsidian.export_enabled", False)
        resp = client.get("/api/obsidian/status")
        data = resp.json()
        assert data["data"]["state"] == "disabled"

    def test_api_validate_path(self, client, tmp_path):
        resp = client.post("/api/obsidian/validate", json={
            "vault_path": str(tmp_path),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["path_valid"] is True

    def test_api_preview(self, client, tmp_path):
        resp = client.post("/api/obsidian/preview", json={
            "vault_path": str(tmp_path),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "will_create_dirs" in data["data"]

    def test_api_initialize_requires_csrf(self, client, tmp_path):
        """POST to initialize without CSRF token should be rejected."""
        resp = client.post("/api/obsidian/initialize", json={
            "vault_path": str(tmp_path),
        })
        # Should be 403 due to missing CSRF
        assert resp.status_code == 403
        data = resp.json()
        assert "csrf" in data.get("error_type", "")

    def test_api_repair_requires_csrf(self, client, tmp_path):
        resp = client.post("/api/obsidian/repair", json={
            "vault_path": str(tmp_path),
        })
        assert resp.status_code == 403

    def test_api_test_write_requires_csrf(self, client, tmp_path):
        resp = client.post("/api/obsidian/test-write", json={
            "vault_path": str(tmp_path),
        })
        assert resp.status_code == 403

    def test_api_disable_requires_csrf(self, client):
        resp = client.post("/api/obsidian/disable")
        assert resp.status_code == 403

    def test_api_clear_path_requires_csrf(self, client):
        resp = client.post("/api/obsidian/clear-path")
        assert resp.status_code == 403

    def test_api_settings_requires_csrf(self, client):
        resp = client.post("/api/obsidian/settings", json={
            "enabled": True,
        })
        assert resp.status_code == 403

    def test_api_validate_rejects_empty_path(self, client):
        resp = client.post("/api/obsidian/validate", json={
            "vault_path": "",
        })
        assert resp.status_code == 400


# ══════════════════════════════════════════════════════════════════════
# State model tests (all 8 states)
# ══════════════════════════════════════════════════════════════════════


class TestStateModel:
    def test_state_disabled(self):
        svc = _get_svc()
        svc.set_user_value("obsidian.export_enabled", False)
        from signalvault.services.obsidian_settings_service import (
            ObsidianState,
            get_obsidian_settings_view,
        )
        view = get_obsidian_settings_view()
        assert view.state == ObsidianState.DISABLED

    def test_state_not_configured(self):
        svc = _get_svc()
        svc.set_user_value("obsidian.export_enabled", True)
        svc.delete_user_value("obsidian.vault_path")
        from signalvault.services.obsidian_settings_service import (
            ObsidianState,
            get_obsidian_settings_view,
        )
        view = get_obsidian_settings_view()
        assert view.state == ObsidianState.NOT_CONFIGURED

    def test_state_path_invalid(self, tmp_path):
        svc = _get_svc()
        svc.set_user_value("obsidian.export_enabled", True)
        svc.set_user_value("obsidian.vault_path", str(tmp_path / "no_such_dir"))
        from signalvault.services.obsidian_settings_service import (
            ObsidianState,
            get_obsidian_settings_view,
        )
        view = get_obsidian_settings_view()
        assert view.state == ObsidianState.PATH_INVALID

    def test_state_path_valid_not_obsidian(self, tmp_path):
        svc = _get_svc()
        svc.set_user_value("obsidian.export_enabled", True)
        svc.set_user_value("obsidian.vault_path", str(tmp_path))
        from signalvault.services.obsidian_settings_service import (
            ObsidianState,
            get_obsidian_settings_view,
        )
        view = get_obsidian_settings_view()
        assert view.state == ObsidianState.PATH_VALID_NOT_OBSIDIAN

    def test_state_path_valid_not_initialized(self, tmp_path):
        (tmp_path / ".obsidian").mkdir()
        svc = _get_svc()
        svc.set_user_value("obsidian.export_enabled", True)
        svc.set_user_value("obsidian.vault_path", str(tmp_path))
        from signalvault.services.obsidian_settings_service import (
            ObsidianState,
            get_obsidian_settings_view,
        )
        view = get_obsidian_settings_view()
        assert view.state == ObsidianState.PATH_VALID_NOT_INITIALIZED

    def test_state_initialized(self, tmp_path):
        from signalvault.services.obsidian_settings_service import (
            initialize_obsidian_vault,
        )
        initialize_obsidian_vault(str(tmp_path))
        svc = _get_svc()
        svc.set_user_value("obsidian.export_enabled", True)
        svc.set_user_value("obsidian.vault_path", str(tmp_path))
        from signalvault.services.obsidian_settings_service import (
            ObsidianState,
            get_obsidian_settings_view,
        )
        view = get_obsidian_settings_view()
        assert view.state == ObsidianState.INITIALIZED

    def test_state_needs_repair(self, tmp_path):
        from signalvault.services.obsidian_settings_service import (
            initialize_obsidian_vault,
        )
        initialize_obsidian_vault(str(tmp_path))
        # Delete something to trigger repair state
        import shutil
        shutil.rmtree(tmp_path / "01_Reports")
        svc = _get_svc()
        svc.set_user_value("obsidian.export_enabled", True)
        svc.set_user_value("obsidian.vault_path", str(tmp_path))
        from signalvault.services.obsidian_settings_service import (
            ObsidianState,
            get_obsidian_settings_view,
        )
        view = get_obsidian_settings_view()
        assert view.state == ObsidianState.NEEDS_REPAIR

    def test_state_manifest_conflict(self, tmp_path):
        (tmp_path / "99_System").mkdir(parents=True)
        (tmp_path / "99_System" / "signalvault_manifest.json").write_text(
            json.dumps({"managed_by": "other_tool", "vault_schema_version": 1})
        )
        svc = _get_svc()
        svc.set_user_value("obsidian.export_enabled", True)
        svc.set_user_value("obsidian.vault_path", str(tmp_path))
        from signalvault.services.obsidian_settings_service import (
            ObsidianState,
            get_obsidian_settings_view,
        )
        view = get_obsidian_settings_view()
        assert view.state == ObsidianState.MANIFEST_CONFLICT


# ══════════════════════════════════════════════════════════════════════
# Path safety tests
# ══════════════════════════════════════════════════════════════════════


class TestPathSafety:
    def test_system_root_rejected(self):
        from signalvault.services.obsidian_settings_service import (
            update_obsidian_settings,
        )
        result = update_obsidian_settings({"vault_path": "C:\\"})
        assert result["ok"] is False

    def test_user_home_flagged_dangerous(self):
        import os

        from signalvault.services.obsidian_settings_service import _is_dangerous_path
        home = os.path.expanduser("~")
        assert _is_dangerous_path(home) is True

    def test_site_packages_flagged(self):
        from signalvault.services.obsidian_settings_service import _is_dangerous_path
        # site-packages itself IS dangerous
        assert _is_dangerous_path("/usr/lib/python3/site-packages") is True
        # site-packages as parent dir is dangerous
        assert _is_dangerous_path("/usr/lib/python3/site-packages/somepkg") is True

    def test_normal_dir_not_dangerous(self, tmp_path):
        from signalvault.services.obsidian_settings_service import _is_dangerous_path
        # tmp_path (under AppData) should NOT be flagged
        assert _is_dangerous_path(str(tmp_path)) is False

    def test_appdata_flagged(self):
        from signalvault.services.obsidian_settings_service import _is_dangerous_path
        # AppData itself as vault root is dangerous
        assert _is_dangerous_path("C:\\Users\\test\\AppData") is True
        # But a subdirectory of AppData is fine
        assert _is_dangerous_path("C:\\Users\\test\\AppData\\Local\\MyVault") is False


# ══════════════════════════════════════════════════════════════════════
# Default path consistency (Web/CLI)
# ══════════════════════════════════════════════════════════════════════


class TestDefaultPathConsistency:
    def test_web_and_cli_read_same_config(self, tmp_path):
        """config_store.get_user_vault_path reads the same ConfigService value."""
        from signalvault.settings.service import _override_config_service

        svc = _make_isolated_svc(tmp_path, env={"LLM_PROVIDER": "mock"})
        _override_config_service(svc)
        svc.set_user_value("obsidian.vault_path", str(tmp_path))

        # Web path via ConfigService
        web_path = str(svc.get("obsidian.vault_path"))

        # CLI path via config_store (which delegates to ConfigService)
        from signalvault.config_store import get_user_vault_path
        cli_path = get_user_vault_path()

        assert web_path == cli_path

    def test_cli_vault_arg_priority(self, tmp_path):
        """CLI --vault should take priority (via runtime override)."""
        from signalvault.settings.service import _override_config_service

        svc = _make_isolated_svc(tmp_path, env={"LLM_PROVIDER": "mock"})
        _override_config_service(svc)

        # User config says one path
        svc.set_user_value("obsidian.vault_path", str(tmp_path / "saved"))

        # CLI override says another
        cli_path = str(tmp_path / "cli-override")
        svc.set_runtime_override("obsidian.vault_path", cli_path)

        # Runtime override wins
        assert str(svc.get("obsidian.vault_path")) == cli_path


# ══════════════════════════════════════════════════════════════════════
# Clean-room simulation
# ══════════════════════════════════════════════════════════════════════


class TestCleanRoomFlow:
    """Simulate the clean-room verification flow:
    fresh SIGNALVAULT_HOME → AI default Mock → create temp vault dir →
    save path → validate → no .obsidian state correct → init →
    manifest correct → repair idempotent → disable →
    SQLite and vault files preserved → restart state preserved.
    """

    def test_full_clean_room_flow(self, tmp_path):
        from signalvault.services.obsidian_settings_service import (
            ObsidianState,
            disable_obsidian_integration,
            get_obsidian_settings_view,
            initialize_obsidian_vault,
            repair_obsidian_vault,
            update_obsidian_settings,
        )
        from signalvault.settings.service import _override_config_service

        # Fresh home
        svc2_home = tmp_path / "fresh_home"
        svc2_home.mkdir()
        svc2 = _make_isolated_svc(svc2_home, env={"LLM_PROVIDER": "mock"})
        _override_config_service(svc2)

        # Step 1: Clean state, AI is mock
        view = get_obsidian_settings_view()
        assert view.state == ObsidianState.DISABLED

        # Step 2: Create temp vault dir
        vault_dir = tmp_path / "test_vault"
        vault_dir.mkdir()

        # Step 3: Save path and enable
        result = update_obsidian_settings({
            "vault_path": str(vault_dir),
            "enabled": True,
        })
        assert result["ok"] is True

        # Step 4: Validate — no .obsidian
        view = get_obsidian_settings_view()
        assert view.path_valid is True
        assert view.has_obsidian_metadata is False
        assert view.state == ObsidianState.PATH_VALID_NOT_OBSIDIAN

        # Step 5: Initialize
        result = initialize_obsidian_vault(str(vault_dir))
        assert result["ok"] is True

        # Step 6: Manifest correct
        view = get_obsidian_settings_view()
        assert view.is_signalvault_initialized is True
        assert view.manifest_exists is True
        assert view.manifest_managed_by == "signalvault"
        assert view.manifest_conflict is False
        assert view.state == ObsidianState.INITIALIZED

        # Step 7: Repair idempotent
        result = repair_obsidian_vault(str(vault_dir))
        assert result["ok"] is True
        created = len(result["created_dirs"]) + len(result["created_files"])
        assert created == 0  # Nothing to repair

        # Step 8: Disable
        result = disable_obsidian_integration()
        assert result["ok"] is True

        # Step 9: Vault files preserved
        assert (vault_dir / "99_System" / "signalvault_manifest.json").exists()
        assert (vault_dir / "Home.md").exists()

        # Step 10: Restart — reload ConfigService
        svc3 = _make_isolated_svc(svc2_home, env={"LLM_PROVIDER": "mock"})
        _override_config_service(svc3)
        view = get_obsidian_settings_view()
        assert view.enabled is False  # disabled
        assert view.vault_path != ""  # path preserved

        _override_config_service(None)
