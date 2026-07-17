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
    """True only until the user completes or globally skips onboarding."""
    return not get_onboarding_state().completed


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
