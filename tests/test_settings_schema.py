"""C1-B: ConfigSchema tests."""

from signalvault.settings.schema import (
    RUNTIME_SCHEMA,
    ConfigCategory,
    get_defaults,
    get_schema_keys,
    get_sensitive_keys,
)


class TestSchemaCoverage:
    def test_all_required_categories_present(self):
        categories = {item.category for item in RUNTIME_SCHEMA.values()}
        assert ConfigCategory.LLM in categories
        assert ConfigCategory.OBSIDIAN in categories
        assert ConfigCategory.WEB in categories
        assert ConfigCategory.LOGGING in categories
        assert ConfigCategory.ANALYSIS in categories
        assert ConfigCategory.INTEGRATIONS in categories

    def test_no_duplicate_keys(self):
        keys = list(RUNTIME_SCHEMA.keys())
        assert len(keys) == len(set(keys))

    def test_every_item_has_key_and_default(self):
        for key, item in RUNTIME_SCHEMA.items():
            assert item.key == key
            assert item.default is not None or item.type in (str,)

    def test_sensitive_keys_excludes_api_key_from_normal_storage(self):
        sensitive = get_sensitive_keys()
        assert "llm.api_key" in sensitive
        # No non-sensitive key should have sensitive=True
        for key, item in RUNTIME_SCHEMA.items():
            if not item.sensitive:
                assert key not in sensitive

    def test_defaults_include_all_keys(self):
        defaults = get_defaults()
        assert set(defaults.keys()) == set(RUNTIME_SCHEMA.keys())

    def test_schema_keys_sorted(self):
        keys = get_schema_keys()
        assert keys == sorted(keys)


class TestLLMSchema:
    def test_llm_provider_validator(self):
        item = RUNTIME_SCHEMA["llm.provider"]
        assert item.validator("mock") is True
        assert item.validator("openai-compatible") is True
        assert item.validator("invalid") is False

    def test_llm_api_key_is_sensitive(self):
        item = RUNTIME_SCHEMA["llm.api_key"]
        assert item.sensitive is True

    def test_llm_defaults(self):
        assert RUNTIME_SCHEMA["llm.provider"].default == "mock"
        assert RUNTIME_SCHEMA["llm.model"].default == "mock-v1"
        assert RUNTIME_SCHEMA["llm.timeout"].default == 120.0
        assert RUNTIME_SCHEMA["llm.max_retries"].default == 2


class TestObsidianSchema:
    def test_vault_path_default_empty(self):
        assert RUNTIME_SCHEMA["obsidian.vault_path"].default == ""

    def test_export_enabled_has_env_var(self):
        assert RUNTIME_SCHEMA["obsidian.export_enabled"].env_var == "OBSIDIAN_EXPORT_ENABLED"
