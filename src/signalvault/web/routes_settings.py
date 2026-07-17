"""C2-A: Settings & integration JSON API routes.

Local-only (127.0.0.1).  Never returns API keys in responses.
CSRF-protected on write endpoints.  Uses ai_settings_service as the
single backend — HTML forms and JSON API share the same logic.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_svc():
    from signalvault.settings.service import get_config_service
    return get_config_service()


def _ok(data: dict) -> JSONResponse:
    return JSONResponse({"ok": True, "data": data})


def _err(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def _check_csrf(request: Request) -> bool:
    """CSRF check for JSON API write endpoints.

    Returns True if the request is safe (GET) or has a valid CSRF token.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True
    from signalvault.web.csrf import check_origin, validate_csrf
    if not check_origin(request):
        return False
    # Try header first, then JSON body field
    submitted = request.headers.get("x-csrf-token", "")
    if not submitted:
        return False
    return validate_csrf(request, submitted)


def _csrf_guard(request: Request):
    """Raise 403 if CSRF check fails."""
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return
    from signalvault.web.csrf import check_origin, validate_csrf
    if not check_origin(request):
        return JSONResponse(
            {"ok": False, "error": "非本地来源的请求被拒绝", "error_type": "csrf"},
            status_code=403,
        )
    submitted = request.headers.get("x-csrf-token", "")
    if not submitted:
        return JSONResponse(
            {"ok": False, "error": "缺少 CSRF token (X-CSRF-Token header)", "error_type": "csrf"},
            status_code=403,
        )
    if not validate_csrf(request, submitted):
        return JSONResponse(
            {"ok": False, "error": "CSRF token 无效", "error_type": "csrf"},
            status_code=403,
        )
    return None  # OK


# ═══════════════════════════════════════════════════════════════════════════════
# Settings status (read-only — no CSRF needed)
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/settings/status")
async def get_public_settings_status(request: Request):
    """Return non-sensitive configuration status."""
    from signalvault.services.ai_settings_service import get_ai_settings_view
    svc = _get_svc()
    snapshot = svc.get_public_snapshot()

    # Add AI settings view
    view = get_ai_settings_view()
    snapshot["_ai"] = {
        "provider": view.provider,
        "model": view.model,
        "base_url": view.base_url,
        "api_key_configured": view.api_key_configured,
        "api_key_source": view.api_key_source,
        "status_label": view.status_label,
        "last_validation_ok": view.last_validation_ok,
        "last_validation_at": view.last_validation_at,
        "validation_stale": view.validation_stale,
        "overridden_by_env": view.overridden_by_env,
    }

    # Add SetupStatus
    try:
        from signalvault.settings.setup_status import SetupStatus
        vault_path = str(svc.get("obsidian.vault_path"))
        status = SetupStatus.evaluate(vault_path=vault_path)
        status.llm_provider = view.provider
        status.llm_configured = view.api_key_configured or view.provider == "mock"
        status.llm_validated = view.last_validation_ok and not view.validation_stale
        snapshot["_status"] = {
            "core_ready": status.core_ready,
            "llm_ready": status.llm_ready,
            "obsidian_ready": status.obsidian_ready,
            "needs_onboarding": status.needs_onboarding,
        }
    except Exception:
        pass

    return _ok(snapshot)


# ═══════════════════════════════════════════════════════════════════════════════
# LLM settings (write — CSRF protected)
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/api/settings/llm")
async def update_llm_settings(request: Request):
    """Update LLM configuration.  Uses ai_settings_service."""
    csrf_err = _csrf_guard(request)
    if csrf_err is not None:
        return csrf_err

    try:
        body = await request.json()
    except Exception:
        return _err("Invalid JSON body")

    # api_key goes through the secret path
    if "api_key" in body:
        api_key = body.pop("api_key")
        from signalvault.services.ai_settings_service import replace_llm_secret
        replace_llm_secret(str(api_key) if api_key else "")

    from signalvault.services.ai_settings_service import update_ai_settings
    result = update_ai_settings(body)
    if result.get("ok"):
        return _ok(result)
    return _err(result.get("error", "更新失败"))


@router.post("/api/settings/llm/test")
async def test_llm_settings(request: Request):
    """Test LLM connectivity.  Uses ai_settings_service."""
    csrf_err = _csrf_guard(request)
    if csrf_err is not None:
        return csrf_err

    try:
        body = await request.json()
    except Exception:
        body = {}

    from signalvault.services.ai_settings_service import test_llm_connection
    result = await test_llm_connection(
        provider=body.get("provider", ""),
        base_url=body.get("base_url", ""),
        model=body.get("model", ""),
        api_key=body.get("api_key", ""),
    )
    if result.get("ok"):
        return _ok(result)
    return _err(result.get("user_message") or result.get("error", "测试连接失败"))


@router.post("/api/settings/llm/secret")
async def update_llm_secret(request: Request):
    """Update API key."""
    csrf_err = _csrf_guard(request)
    if csrf_err is not None:
        return csrf_err

    try:
        body = await request.json()
    except Exception:
        return _err("Invalid JSON body")

    api_key = body.get("api_key", "")
    from signalvault.services.ai_settings_service import replace_llm_secret
    result = replace_llm_secret(str(api_key) if api_key else "")
    return _ok(result)


@router.delete("/api/settings/llm/secret")
async def delete_llm_secret_endpoint(request: Request):
    """Delete stored API key."""
    csrf_err = _csrf_guard(request)
    if csrf_err is not None:
        return csrf_err

    from signalvault.services.ai_settings_service import delete_llm_secret
    result = delete_llm_secret()
    return _ok(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Obsidian settings — delegates to obsidian_settings_service
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/obsidian/status")
async def get_obsidian_status(request: Request):
    """Return Obsidian vault status via service layer."""
    from signalvault.services.obsidian_settings_service import (
        get_obsidian_settings_view,
    )

    view = get_obsidian_settings_view()

    return _ok({
        "enabled": view.enabled,
        "state": view.state,
        "state_label": view.state_label,
        "vault_path": view.vault_path,
        "vault_path_source": view.vault_path_source,
        "path_valid": view.path_valid,
        "exists": view.exists,
        "is_directory": view.is_directory,
        "is_absolute": view.is_absolute,
        "readable": view.readable,
        "writable": view.writable,
        "has_obsidian_metadata": view.has_obsidian_metadata,
        "is_signalvault_initialized": view.is_signalvault_initialized,
        "missing_dirs": view.missing_directories,
        "missing_files": view.missing_files,
        "manifest_exists": view.manifest_exists,
        "manifest_conflict": view.manifest_conflict,
        "vault_schema_version": view.vault_schema_version,
        "initialized_at": view.initialized_at,
        "last_repaired_at": view.last_repaired_at,
        "preview_will_create_dirs": view.preview_will_create_dirs,
        "preview_will_create_files": view.preview_will_create_files,
        "error_message": view.error_message,
    })


@router.post("/api/obsidian/validate")
async def api_validate_obsidian_path(request: Request):
    """Validate a candidate vault path without saving. Delegates to service."""
    from signalvault.services.obsidian_settings_service import validate_obsidian_path

    try:
        body = await request.json()
    except Exception:
        return _err("Invalid JSON body")

    vault_path = body.get("vault_path", "")
    if not vault_path:
        return _err("vault_path 不能为空")

    result = validate_obsidian_path(str(vault_path))
    return _ok(result)


@router.post("/api/obsidian/preview")
async def api_preview_vault_init(request: Request):
    """Preview vault initialization without modifying filesystem."""
    from signalvault.services.obsidian_settings_service import (
        preview_vault_initialization,
    )

    try:
        body = await request.json()
    except Exception:
        return _err("Invalid JSON body")

    vault_path = body.get("vault_path", "")
    if not vault_path:
        return _err("vault_path 不能为空")

    result = preview_vault_initialization(str(vault_path))
    return _ok(result)


@router.post("/api/obsidian/initialize")
async def api_initialize_obsidian_vault(request: Request):
    """Initialize an Obsidian vault. CSRF-protected. Delegates to service."""
    csrf_err = _csrf_guard(request)
    if csrf_err is not None:
        return csrf_err

    from signalvault.services.obsidian_settings_service import initialize_obsidian_vault

    try:
        body = await request.json()
    except Exception:
        return _err("Invalid JSON body")

    vault_path = body.get("vault_path", "")
    if not vault_path:
        return _err("vault_path 不能为空")

    result = initialize_obsidian_vault(str(vault_path))
    if result.get("ok"):
        return _ok(result)
    return _err(result.get("error", "初始化失败"))


@router.post("/api/obsidian/repair")
async def api_repair_obsidian_vault(request: Request):
    """Repair an Obsidian vault. CSRF-protected. Delegates to service."""
    csrf_err = _csrf_guard(request)
    if csrf_err is not None:
        return csrf_err

    from signalvault.services.obsidian_settings_service import repair_obsidian_vault

    try:
        body = await request.json()
    except Exception:
        return _err("Invalid JSON body")

    vault_path = body.get("vault_path", "")
    if not vault_path:
        return _err("vault_path 不能为空")

    result = repair_obsidian_vault(str(vault_path))
    if result.get("ok"):
        return _ok(result)
    return _err(result.get("error", "修复失败"))


@router.post("/api/obsidian/test-write")
async def api_test_obsidian_write(request: Request):
    """Test write to vault. CSRF-protected. Delegates to service."""
    csrf_err = _csrf_guard(request)
    if csrf_err is not None:
        return csrf_err

    from signalvault.services.obsidian_settings_service import test_obsidian_write

    try:
        body = await request.json()
    except Exception:
        return _err("Invalid JSON body")

    vault_path = body.get("vault_path", "")
    if not vault_path:
        return _err("vault_path 不能为空")

    result = test_obsidian_write(str(vault_path))
    if result.get("ok"):
        return _ok(result)
    return _err(result.get("error", "写入测试失败"))


@router.post("/api/obsidian/disable")
async def api_disable_obsidian(request: Request):
    """Disable Obsidian integration. CSRF-protected. Delegates to service."""
    csrf_err = _csrf_guard(request)
    if csrf_err is not None:
        return csrf_err

    from signalvault.services.obsidian_settings_service import (
        disable_obsidian_integration,
    )
    result = disable_obsidian_integration()
    return _ok(result)


@router.post("/api/obsidian/clear-path")
async def api_clear_vault_path(request: Request):
    """Clear saved vault path. CSRF-protected. Delegates to service."""
    csrf_err = _csrf_guard(request)
    if csrf_err is not None:
        return csrf_err

    from signalvault.services.obsidian_settings_service import clear_vault_path
    result = clear_vault_path()
    return _ok(result)


@router.post("/api/obsidian/settings")
async def api_update_obsidian_settings(request: Request):
    """Update Obsidian settings. CSRF-protected. Delegates to service."""
    csrf_err = _csrf_guard(request)
    if csrf_err is not None:
        return csrf_err

    from signalvault.services.obsidian_settings_service import update_obsidian_settings

    try:
        body = await request.json()
    except Exception:
        return _err("Invalid JSON body")

    result = update_obsidian_settings(body)
    if result.get("ok"):
        return _ok(result)
    return _err(result.get("error", "保存失败"))
