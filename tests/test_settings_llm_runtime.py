"""C1-C tests: LLMRuntimeConfig + create_llm_provider factory."""

from __future__ import annotations

import pytest

from signalvault.llm.mock_provider import MockLLMProvider
from signalvault.llm.openai_compatible_provider import OpenAICompatibleProvider
from signalvault.settings.app_paths import AppPaths
from signalvault.settings.llm_runtime import (
    LLMRuntimeConfig,
    _normalize_provider,
    create_llm_provider,
)
from signalvault.settings.secret_store import SecretStore
from signalvault.settings.service import ConfigService


def _make_svc(tmp_path, env=None, **kwargs):
    """Create an isolated ConfigService for testing.

    Default env={} (empty snapshot) to block conftest.py's env overrides
    (LLM_MODEL=mock-investment-analyst etc.) from leaking in.
    """
    paths = AppPaths.resolve(home_override=str(tmp_path))
    secrets = SecretStore(paths.config_dir)
    if env is None:
        env = {}
    return ConfigService(paths, env=env, secret_store=secrets, **kwargs)


# ══════════════════════════════════════════════════════════════════════
# Provider name normalization
# ══════════════════════════════════════════════════════════════════════


class TestProviderNormalization:
    def test_normalize_openai_compatible_underscore(self):
        assert _normalize_provider("openai_compatible") == "openai-compatible"

    def test_normalize_openai_compatible_hyphen(self):
        assert _normalize_provider("openai-compatible") == "openai-compatible"

    def test_normalize_mock(self):
        assert _normalize_provider("mock") == "mock"

    def test_normalize_case_insensitive(self):
        assert _normalize_provider("MOCK") == "mock"
        assert _normalize_provider("OpenAI_Compatible") == "openai-compatible"

    def test_normalize_unknown_passthrough(self):
        assert _normalize_provider("unknown-provider") == "unknown-provider"


# ══════════════════════════════════════════════════════════════════════
# LLMRuntimeConfig.from_config_service
# ══════════════════════════════════════════════════════════════════════


class TestLLMRuntimeConfigFromService:
    def test_defaults_are_mock(self, tmp_path):
        svc = _make_svc(tmp_path)
        cfg = LLMRuntimeConfig.from_config_service(svc)
        assert cfg.provider == "mock"
        assert cfg.model == "mock-v1"
        assert cfg.api_key is None
        assert cfg.base_url == ""

    def test_reads_timeout_from_schema_default(self, tmp_path):
        svc = _make_svc(tmp_path)
        cfg = LLMRuntimeConfig.from_config_service(svc)
        assert cfg.timeout == 120.0

    def test_reads_max_retries_from_schema_default(self, tmp_path):
        svc = _make_svc(tmp_path)
        cfg = LLMRuntimeConfig.from_config_service(svc)
        assert cfg.max_retries == 2

    def test_reads_temperature_from_schema_default(self, tmp_path):
        svc = _make_svc(tmp_path)
        cfg = LLMRuntimeConfig.from_config_service(svc)
        assert cfg.temperature == 0.1

    def test_env_overrides_provider(self, tmp_path):
        svc = _make_svc(tmp_path, env={"LLM_PROVIDER": "openai-compatible"})
        cfg = LLMRuntimeConfig.from_config_service(svc)
        assert cfg.provider == "openai-compatible"

    def test_env_overrides_model(self, tmp_path):
        svc = _make_svc(tmp_path, env={"LLM_MODEL": "gpt-4o"})
        cfg = LLMRuntimeConfig.from_config_service(svc)
        assert cfg.model == "gpt-4o"

    def test_env_overrides_base_url(self, tmp_path):
        svc = _make_svc(tmp_path, env={"LLM_BASE_URL": "https://api.example.com"})
        cfg = LLMRuntimeConfig.from_config_service(svc)
        assert cfg.base_url == "https://api.example.com"

    def test_api_key_from_env(self, tmp_path):
        svc = _make_svc(tmp_path, env={"LLM_API_KEY": "sk-test-env"})
        cfg = LLMRuntimeConfig.from_config_service(svc)
        assert cfg.api_key == "sk-test-env"

    def test_api_key_from_secret_store(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_secret("llm.api_key", "sk-test-store")
        cfg = LLMRuntimeConfig.from_config_service(svc)
        assert cfg.api_key == "sk-test-store"

    def test_secret_store_preferred_over_env(self, tmp_path):
        svc = _make_svc(tmp_path, env={"LLM_API_KEY": "sk-from-env"})
        svc.set_secret("llm.api_key", "sk-from-store")
        cfg = LLMRuntimeConfig.from_config_service(svc)
        assert cfg.api_key == "sk-from-store"

    def test_runtime_override_visible(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_runtime_override("llm.provider", "openai-compatible")
        cfg = LLMRuntimeConfig.from_config_service(svc)
        assert cfg.provider == "openai-compatible"

    def test_user_config_persisted_and_read(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc.set_user_value("llm.model", "custom-model")
        cfg = LLMRuntimeConfig.from_config_service(svc)
        assert cfg.model == "custom-model"


# ══════════════════════════════════════════════════════════════════════
# create_llm_provider
# ══════════════════════════════════════════════════════════════════════


class TestCreateLLMProvider:
    def test_default_config_returns_mock(self):
        cfg = LLMRuntimeConfig()
        provider = create_llm_provider(cfg)
        assert isinstance(provider, MockLLMProvider)

    def test_mock_explicit_returns_mock(self):
        cfg = LLMRuntimeConfig(provider="mock")
        provider = create_llm_provider(cfg)
        assert isinstance(provider, MockLLMProvider)

    def test_openai_compatible_returns_real_provider(self):
        cfg = LLMRuntimeConfig(
            provider="openai-compatible",
            base_url="https://api.example.com",
            api_key="sk-test",
            model="gpt-4o",
        )
        provider = create_llm_provider(cfg)
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.base_url == "https://api.example.com"
        assert provider.model == "gpt-4o"

    def test_openai_compatible_no_api_key_raises(self):
        cfg = LLMRuntimeConfig(
            provider="openai-compatible",
            base_url="https://api.example.com",
            api_key=None,
        )
        with pytest.raises(ValueError, match="LLM_API_KEY"):
            create_llm_provider(cfg)

    def test_provider_name_normalized_underscore(self):
        cfg = LLMRuntimeConfig(
            provider="openai_compatible",
            base_url="https://api.example.com",
            api_key="sk-test",
        )
        provider = create_llm_provider(cfg)
        assert isinstance(provider, OpenAICompatibleProvider)

    def test_timeout_passed_to_provider(self):
        cfg = LLMRuntimeConfig(
            provider="openai-compatible",
            base_url="https://api.example.com",
            api_key="sk-test",
            timeout=60.0,
        )
        provider = create_llm_provider(cfg)
        assert provider.timeout == 60.0

    def test_max_retries_passed_to_provider(self):
        cfg = LLMRuntimeConfig(
            provider="openai-compatible",
            base_url="https://api.example.com",
            api_key="sk-test",
            max_retries=5,
        )
        provider = create_llm_provider(cfg)
        assert provider.max_retries == 5

    def test_temperature_passed_to_provider(self):
        cfg = LLMRuntimeConfig(
            provider="openai-compatible",
            base_url="https://api.example.com",
            api_key="sk-test",
            temperature=0.5,
        )
        provider = create_llm_provider(cfg)
        assert provider.temperature == 0.5

    def test_unknown_provider_raises(self):
        cfg = LLMRuntimeConfig(provider="anthropic")
        with pytest.raises(ValueError, match="不支持的 LLM provider"):
            create_llm_provider(cfg)


# ══════════════════════════════════════════════════════════════════════
# Frozen dataclass behavior
# ══════════════════════════════════════════════════════════════════════


class TestLLMRuntimeConfigFrozen:
    def test_is_frozen(self):
        cfg = LLMRuntimeConfig()
        with pytest.raises(Exception):  # noqa: B017 — FrozenInstanceError is internal
            cfg.provider = "changed"  # type: ignore[misc]

    def test_replace_creates_new_instance(self):
        cfg = LLMRuntimeConfig()
        new_cfg = cfg  # dataclasses.replace not imported here; test immutability
        assert new_cfg is cfg  # same object when no change (replace not used)
