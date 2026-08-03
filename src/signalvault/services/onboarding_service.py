"""C3: First-run onboarding state and safe completion summary.

Onboarding completion records a user decision, not system health.  This
service is the only writer for onboarding metadata and persists exclusively
through ConfigService.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

CURRENT_ONBOARDING_VERSION = 1


@dataclass(frozen=True)
class OnboardingState:
    version: int = 0
    completed: bool = False
    completed_at: str = ""
    skipped_ai: bool = False
    skipped_obsidian: bool = False


def _get_svc():
    from signalvault.settings.service import get_config_service

    return get_config_service()


def get_onboarding_state() -> OnboardingState:
    """Return persisted onboarding decisions without evaluating health."""
    svc = _get_svc()
    return OnboardingState(
        version=int(svc.get("_internal.onboarding.version")),
        completed=bool(svc.get("_internal.onboarding.completed")),
        completed_at=str(svc.get("_internal.onboarding.completed_at")),
        skipped_ai=bool(svc.get("_internal.onboarding.skipped_ai")),
        skipped_obsidian=bool(svc.get("_internal.onboarding.skipped_obsidian")),
    )


def should_enter_onboarding() -> bool:
    """True only until the user completes or globally skips onboarding.

    M3-C-1: 自动检测配置完成状态。如果用户已在 Settings 完成所有必要配置
    （非 mock 的真实 AI 配置 + Obsidian 初始化），自动标记为已完成。

    注意：mock 模式不算"已完成"，必须显式配置真实 provider 或跳过向导。
    """
    state = get_onboarding_state()

    # 1. 显式已完成（走完向导或点击跳过）→ 不进入向导
    if state.completed:
        return False

    # 2. 检测是否有**用户主动配置**（非默认 mock）
    from signalvault.services.ai_settings_service import get_ai_settings_view
    from signalvault.services.obsidian_settings_service import (
        get_obsidian_settings_view,
    )

    ai_view = get_ai_settings_view()
    obs_view = get_obsidian_settings_view()

    # 用户已主动配置真实 AI provider（非 mock）且验证通过
    has_real_ai_config = (
        ai_view.provider != "mock"
        and ai_view.api_key_configured
        and ai_view.last_validation_ok
        and not ai_view.validation_stale
    )

    # 用户已初始化 Obsidian vault
    has_obsidian_config = (
        obs_view.enabled
        and obs_view.path_valid
        and obs_view.is_signalvault_initialized
        and obs_view.writable
    )

    # 3. 两者都配置完成 → 自动标记（用户已自行配置，不必强制走向导）
    if has_real_ai_config and has_obsidian_config:
        complete_onboarding()
        return False

    # 4. 否则进入向导（包括默认 mock 模式）
    return True


def set_ai_skipped(skipped: bool) -> OnboardingState:
    _get_svc().set_user_value("_internal.onboarding.skipped_ai", bool(skipped))
    return get_onboarding_state()


def set_obsidian_skipped(skipped: bool) -> OnboardingState:
    _get_svc().set_user_value(
        "_internal.onboarding.skipped_obsidian", bool(skipped)
    )
    return get_onboarding_state()


def complete_onboarding() -> OnboardingState:
    """Persist completion independently from AI/Obsidian health."""
    svc = _get_svc()
    svc.set_user_value("_internal.onboarding.version", CURRENT_ONBOARDING_VERSION)
    svc.set_user_value("_internal.onboarding.completed_at", _utcnow_iso())
    svc.set_user_value("_internal.onboarding.completed", True)
    return get_onboarding_state()


def skip_onboarding() -> OnboardingState:
    """Record an explicit global skip so the wizard is not forced again."""
    set_ai_skipped(True)
    set_obsidian_skipped(True)
    return complete_onboarding()


def get_completion_summary() -> dict[str, Any]:
    """Build a safe summary by delegating status calculation to C2 services."""
    from signalvault.services.ai_settings_service import get_ai_settings_view
    from signalvault.services.obsidian_settings_service import (
        get_obsidian_settings_view,
    )

    return {
        "onboarding": get_onboarding_state(),
        "ai": get_ai_settings_view(),
        "obsidian": get_obsidian_settings_view(),
    }


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
