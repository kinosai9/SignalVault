"""C1-C: LLM Runtime Config — unified provider configuration and factory.

LLMRuntimeConfig is the single source of truth for LLM provider settings.
All creation sites must use ``create_llm_provider()`` instead of reading
config.py directly or instantiating providers by hand.

Provider name normalization: input ``openai_compatible`` is normalized to
``openai-compatible`` internally.  The canonical names are:

    mock
    openai-compatible
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from signalvault.llm.base import LLMProvider

if TYPE_CHECKING:
    from signalvault.settings.service import ConfigService


# ═══════════════════════════════════════════════════════════════════════════════
# LLMRuntimeConfig
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class LLMRuntimeConfig:
    """Frozen snapshot of LLM provider settings resolved at call time.

    Use ``from_config_service()`` to build from ConfigService, or construct
    directly with ``replace()`` for overrides.
    """

    provider: str = "mock"       # canonical: "mock" | "openai-compatible"
    model: str = "mock-v1"
    base_url: str = ""
    api_key: str | None = None   # None = not configured
    timeout: float = 120.0
    max_retries: int = 2
    temperature: float = 0.1

    @staticmethod
    def from_config_service(svc: ConfigService) -> "LLMRuntimeConfig":
        """Build an LLMRuntimeConfig from a ConfigService instance.

        Reads all llm.* keys at call time — NOT at import time.
        """
        provider_raw = str(svc.get("llm.provider"))
        return LLMRuntimeConfig(
            provider=_normalize_provider(provider_raw),
            model=str(svc.get("llm.model")),
            base_url=str(svc.get("llm.base_url")),
            api_key=svc.get_secret("llm.api_key"),
            timeout=float(svc.get("llm.timeout")),
            max_retries=int(svc.get("llm.max_retries")),
            temperature=float(svc.get("llm.temperature")),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Provider factory
# ═══════════════════════════════════════════════════════════════════════════════


def create_llm_provider(config: LLMRuntimeConfig) -> LLMProvider:
    """Create an LLMProvider from an LLMRuntimeConfig.

    This is the SINGLE factory function.  All call sites — pipeline,
    LLM-WIKI, CLI, web — must use this instead of direct instantiation.
    """
    provider = _normalize_provider(config.provider)

    if provider == "mock":
        from signalvault.llm.mock_provider import MockLLMProvider
        return MockLLMProvider()

    if provider == "openai-compatible":
        from signalvault.llm.openai_compatible_provider import (
            OpenAICompatibleProvider,
        )
        if not config.api_key:
            raise ValueError(
                "openai-compatible provider 需要配置 LLM_API_KEY"
            )
        return OpenAICompatibleProvider(
            base_url=config.base_url,
            api_key=config.api_key,
            model=config.model,
            max_retries=config.max_retries,
            timeout=config.timeout,
            temperature=config.temperature,
        )

    raise ValueError(
        f"不支持的 LLM provider: {config.provider!r}，"
        f"可选: mock, openai-compatible"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _normalize_provider(name: str) -> str:
    """Normalize provider name to canonical form.

    >>> _normalize_provider("openai_compatible")
    'openai-compatible'
    >>> _normalize_provider("openai-compatible")
    'openai-compatible'
    >>> _normalize_provider("mock")
    'mock'
    """
    name = str(name).strip().lower()
    if name in ("openai_compatible", "openai-compatible"):
        return "openai-compatible"
    if name == "mock":
        return "mock"
    # Unknown providers: return as-is (will fail with clear error in factory)
    return name
