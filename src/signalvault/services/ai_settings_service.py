"""C2-A: AI Settings Service — unified backend for HTML pages and JSON API.

Both the HTML templates and the /api/settings/* JSON endpoints call the
same functions here.  No template context ever contains an API key.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════════
# Validation state persistence
# ═══════════════════════════════════════════════════════════════════════════════

_VALIDATION_STATE_KEY = "llm.validation_state"


@dataclass
class LLMValidationState:
    """Persisted LLM validation result (non-sensitive)."""

    last_ok: bool = False
    last_checked_at: str = ""           # ISO 8601 UTC
    last_error_type: str = ""           # ValidationErrorType value
    config_fingerprint: str = ""        # hash of non-sensitive config fields


def _get_svc():
    from signalvault.settings.service import get_config_service
    return get_config_service()


# ═══════════════════════════════════════════════════════════════════════════════
# Config fingerprint — detects changes that invalidate old validation
# ═══════════════════════════════════════════════════════════════════════════════


def _compute_config_fingerprint(svc) -> str:
    """Hash of non-sensitive LLM config fields.

    Changing provider, base_url, model, or API key revision invalidates
    old validation.  Does NOT include the API key value itself.

    secret_revision is a monotonic counter that increments on every
    key set/delete, so replacing Key A with Key B (both key:yes)
    still invalidates the old validation.
    """
    # Normalize base_url: strip trailing slash for consistent fingerprint
    base_url = str(svc.get("llm.base_url")).rstrip("/")

    parts = [
        str(svc.get("llm.provider")),
        base_url,
        str(svc.get("llm.model")),
        "key:yes" if svc.is_secret_set("llm.api_key") else "key:no",
        f"secret_rev:{svc.get('_internal.llm_secret_revision')}",
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _get_validation_state(svc) -> LLMValidationState:
    """Read the persisted validation state."""
    try:
        raw = svc.get("_internal.llm_validation")
        if raw and isinstance(raw, str):
            data = json.loads(raw)
            return LLMValidationState(
                last_ok=data.get("last_ok", False),
                last_checked_at=data.get("last_checked_at", ""),
                last_error_type=data.get("last_error_type", ""),
                config_fingerprint=data.get("config_fingerprint", ""),
            )
    except (json.JSONDecodeError, KeyError):
        pass
    return LLMValidationState()


def _save_validation_state(svc, state: LLMValidationState) -> None:
    """Persist validation state via config.toml (non-sensitive only)."""
    payload = json.dumps({
        "last_ok": state.last_ok,
        "last_checked_at": state.last_checked_at,
        "last_error_type": state.last_error_type,
        "config_fingerprint": state.config_fingerprint,
    }, ensure_ascii=False)
    # Store as a regular config value (not a secret)
    svc.set_user_value("_internal.llm_validation", payload)


def is_validation_stale(svc) -> bool:
    """Check if the last validation is stale (config changed since)."""
    state = _get_validation_state(svc)
    current_fp = _compute_config_fingerprint(svc)
    return state.config_fingerprint != current_fp


# ═══════════════════════════════════════════════════════════════════════════════
# Settings view model (safe for templates — NO API KEY)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class AISettingsView:
    """All AI settings data safe for template rendering."""

    # Provider
    provider: str = "mock"
    provider_source: str = "default"       # runtime_override / cli / env / user_config / default
    model: str = "mock-v1"
    model_source: str = "default"
    base_url: str = ""
    base_url_source: str = "default"

    # API Key (status only, never the value)
    api_key_configured: bool = False
    api_key_source: str = ""               # secret_store / env / ""

    # Advanced
    timeout: float = 120.0
    timeout_source: str = "default"
    max_retries: int = 2
    max_retries_source: str = "default"
    temperature: float = 0.1
    temperature_source: str = "default"

    # Validation
    last_validation_ok: bool = False
    last_validation_at: str = ""
    last_validation_error: str = ""
    validation_stale: bool = True

    # Override info
    overridden_by_env: bool = False
    overridden_by_env_fields: list[str] = field(default_factory=list)

    # Status label for display
    status_label: str = "Mock 模式"
    status_class: str = "status-mock"


def get_ai_settings_view() -> AISettingsView:
    """Build the AI settings view model from ConfigService.

    Safe for templates — never includes api_key value.
    """
    svc = _get_svc()
    view = AISettingsView()

    # Provider
    pv = svc.get_with_source("llm.provider")
    view.provider = str(pv.value)
    view.provider_source = pv.source

    # Model
    mv = svc.get_with_source("llm.model")
    view.model = str(mv.value)
    view.model_source = mv.source

    # Base URL
    bv = svc.get_with_source("llm.base_url")
    view.base_url = str(bv.value)
    view.base_url_source = bv.source

    # API Key status
    secret_info = svc.get_secret_with_source("llm.api_key")
    view.api_key_configured = secret_info["configured"] == "true"
    view.api_key_source = secret_info["source"]

    # Advanced
    tv = svc.get_with_source("llm.timeout")
    view.timeout = float(tv.value)
    view.timeout_source = tv.source
    rv = svc.get_with_source("llm.max_retries")
    view.max_retries = int(rv.value)
    view.max_retries_source = rv.source
    tempv = svc.get_with_source("llm.temperature")
    view.temperature = float(tempv.value)
    view.temperature_source = tempv.source

    # Validation state
    state = _get_validation_state(svc)
    view.last_validation_ok = state.last_ok
    view.last_validation_at = state.last_checked_at
    view.last_validation_error = state.last_error_type
    view.validation_stale = is_validation_stale(svc)

    # Env override detection
    user_fields = ["llm.provider", "llm.model", "llm.base_url"]
    for key in user_fields:
        cv = svc.get_with_source(key)
        if cv.source == "env" and cv.is_overridden:
            view.overridden_by_env = True
            view.overridden_by_env_fields.append(key)

    # Status label
    view.status_label, view.status_class = _compute_status_label(view)

    return view


def _compute_status_label(view: AISettingsView) -> tuple[str, str]:
    """Compute a user-facing status label and CSS class."""
    if view.provider == "mock":
        return "Mock 模式", "status-mock"

    if view.overridden_by_env:
        return "配置被环境变量覆盖", "status-overridden"

    if not view.api_key_configured:
        return "配置不完整", "status-incomplete"

    if view.validation_stale or not view.last_validation_at:
        return "已配置，尚未验证", "status-unvalidated"

    if view.last_validation_ok:
        return "连接正常", "status-ok"

    return "连接失败", "status-error"


# ═══════════════════════════════════════════════════════════════════════════════
# Write operations
# ═══════════════════════════════════════════════════════════════════════════════


def update_ai_settings(fields: dict[str, Any]) -> dict[str, Any]:
    """Update LLM configuration from a dict of field values.

    Args:
        fields: Dict with any of: provider, model, base_url, timeout,
                max_retries, temperature.  api_key is handled separately.

    Returns:
        {"ok": true, "updated": [...]} or {"ok": false, "error": "..."}
    """
    svc = _get_svc()
    updated: list[str] = []

    llm_fields = {
        "provider": "llm.provider",
        "model": "llm.model",
        "base_url": "llm.base_url",
        "timeout": "llm.timeout",
        "max_retries": "llm.max_retries",
        "temperature": "llm.temperature",
    }

    for fname, key in llm_fields.items():
        if fname in fields:
            try:
                svc.set_user_value(key, fields[fname])
                updated.append(key)
            except (ValueError, KeyError) as e:
                return {"ok": False, "error": f"Invalid value for {field}: {e}"}

    # Invalidate old validation if config changed
    if updated:
        _invalidate_validation(svc)

    return {"ok": True, "updated": updated}


def _increment_secret_revision(svc) -> int:
    """Increment the secret revision counter and return the new value."""
    current = int(svc.get("_internal.llm_secret_revision"))
    new_rev = current + 1
    svc.set_user_value("_internal.llm_secret_revision", new_rev)
    return new_rev


def replace_llm_secret(api_key: str) -> dict[str, Any]:
    """Replace the stored API key.

    Empty string deletes the key.  Invalidates old validation.
    Increments secret_revision so that old validation is invalidated
    even when replacing one configured key with another.
    """
    svc = _get_svc()
    if not api_key or not api_key.strip():
        svc.delete_secret("llm.api_key")
    else:
        svc.set_secret("llm.api_key", api_key.strip())

    # Increment secret revision — key presence alone is not enough
    _increment_secret_revision(svc)
    _invalidate_validation(svc)

    return {"ok": True}


def delete_llm_secret() -> dict[str, Any]:
    """Delete the stored API key.  Invalidates old validation."""
    svc = _get_svc()
    svc.delete_secret("llm.api_key")
    _increment_secret_revision(svc)
    _invalidate_validation(svc)
    return {"ok": True}


def test_llm_connection(
    provider: str = "",
    base_url: str = "",
    model: str = "",
    api_key: str = "",
) -> dict[str, Any]:
    """Test LLM connectivity and persist the result.

    Uses provided values if given, otherwise reads from ConfigService.
    Does NOT save the API key — only tests with it.
    """
    svc = _get_svc()

    # Resolve values
    provider = provider or str(svc.get("llm.provider"))
    base_url = base_url or str(svc.get("llm.base_url"))
    model = model or str(svc.get("llm.model"))
    # api_key: use provided temp key, or stored, or env
    if not api_key:
        api_key = svc.get_secret("llm.api_key") or ""

    # Mock is always "connected"
    if provider == "mock":
        state = LLMValidationState(
            last_ok=True,
            last_checked_at=_utcnow_iso(),
            last_error_type="",
            config_fingerprint=_compute_config_fingerprint(svc),
        )
        _save_validation_state(svc, state)
        return {
            "ok": True,
            "message": "Mock 模式 — 无需连接测试",
            "latency_ms": 0,
            "error_type": "",
        }

    if not base_url:
        return {"ok": False, "error": "base_url 未配置", "error_type": ""}
    if not api_key:
        return {"ok": False, "error": "API Key 未配置", "error_type": ""}

    # Real validation
    import asyncio

    from signalvault.settings.llm_validator import validate_llm_config

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're in an async context — create task
            import nest_asyncio
            nest_asyncio.apply()
        result = asyncio.run(validate_llm_config(base_url, api_key, model))
    except RuntimeError:
        # No event loop — create one
        result = asyncio.run(validate_llm_config(base_url, api_key, model))
    except Exception as e:
        return {"ok": False, "error": f"测试失败: {e}", "error_type": "unknown"}

    # Persist validation state
    state = LLMValidationState(
        last_ok=result.ok,
        last_checked_at=result.checked_at,
        last_error_type=result.error_type if not result.ok else "",
        config_fingerprint=_compute_config_fingerprint(svc),
    )
    _save_validation_state(svc, state)

    return {
        "ok": result.ok,
        "error_type": result.error_type,
        "user_message": result.user_message if not result.ok else "",
        "latency_ms": result.latency_ms,
        "model_reported": result.model_reported,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Internal
# ═══════════════════════════════════════════════════════════════════════════════


def _invalidate_validation(svc) -> None:
    """Clear validation state when config changes."""
    state = LLMValidationState()  # all defaults = invalid
    _save_validation_state(svc, state)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
