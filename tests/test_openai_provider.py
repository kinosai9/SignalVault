"""Tests for OpenAICompatibleProvider — mock HTTP layer, no real API calls."""

import json

import pytest


class TestStripMarkdownWrapper:
    def test_plain_json(self):
        from signalvault.llm.openai_compatible_provider import OpenAICompatibleProvider
        p = OpenAICompatibleProvider("http://x", "k", "m")
        result = p._strip_markdown_wrapper('{"key": "value"}')
        assert result == '{"key": "value"}'

    def test_json_fence(self):
        from signalvault.llm.openai_compatible_provider import OpenAICompatibleProvider
        p = OpenAICompatibleProvider("http://x", "k", "m")
        result = p._strip_markdown_wrapper('```json\n{"key": "value"}\n```')
        assert result == '{"key": "value"}'

    def test_fence_no_lang(self):
        from signalvault.llm.openai_compatible_provider import OpenAICompatibleProvider
        p = OpenAICompatibleProvider("http://x", "k", "m")
        result = p._strip_markdown_wrapper('```\n{"a":1}\n```')
        assert result == '{"a":1}'

    def test_empty_string(self):
        from signalvault.llm.openai_compatible_provider import OpenAICompatibleProvider
        p = OpenAICompatibleProvider("http://x", "k", "m")
        assert p._strip_markdown_wrapper("") == ""

    def test_whitespace_only(self):
        from signalvault.llm.openai_compatible_provider import OpenAICompatibleProvider
        p = OpenAICompatibleProvider("http://x", "k", "m")
        # Whitespace-only gets stripped by _strip_markdown_wrapper
        result = p._strip_markdown_wrapper("   \n  ")
        assert result.strip() == ""


class TestTryRepairJson:
    def test_truncated_json_last_brace(self):
        from signalvault.llm.openai_compatible_provider import OpenAICompatibleProvider
        p = OpenAICompatibleProvider("http://x", "k", "m")
        # JSON cut off after the last complete } — repair should slice there
        result = p._try_repair_json('{"a": 1}\n{"b": 2')
        assert result == {"a": 1}

    def test_valid_json(self):
        from signalvault.llm.openai_compatible_provider import OpenAICompatibleProvider
        p = OpenAICompatibleProvider("http://x", "k", "m")
        result = p._try_repair_json('{"x": "y"}')
        assert result == {"x": "y"}

    def test_unrepairable(self):
        from signalvault.llm.openai_compatible_provider import OpenAICompatibleProvider
        p = OpenAICompatibleProvider("http://x", "k", "m")
        with pytest.raises(ValueError, match="无法解析"):
            p._try_repair_json("not json at all {{{")


class TestConstructor:
    def test_defaults(self):
        from signalvault.llm.openai_compatible_provider import OpenAICompatibleProvider
        p = OpenAICompatibleProvider("https://api.example.com", "sk-test", "gpt-4")
        assert p.base_url == "https://api.example.com"
        assert p.api_key == "sk-test"
        assert p.model == "gpt-4"
        assert p.max_retries == 2
        assert p.timeout == 120.0

    def test_custom_retries(self):
        from signalvault.llm.openai_compatible_provider import OpenAICompatibleProvider
        p = OpenAICompatibleProvider("http://x", "k", "m", max_retries=5, timeout=60.0)
        assert p.max_retries == 5
        assert p.timeout == 60.0

    def test_strips_trailing_slash(self):
        from signalvault.llm.openai_compatible_provider import OpenAICompatibleProvider
        p = OpenAICompatibleProvider("https://api.example.com/", "k", "m")
        assert p.base_url == "https://api.example.com"


class TestTranslateText:
    def test_mock_has_translate(self):
        from signalvault.llm.mock_provider import MockLLMProvider
        p = MockLLMProvider()
        result = p.translate_text("Hello world")
        assert "[MOCK" in result
        assert "Hello world" in result

    def test_mock_empty_text(self):
        from signalvault.llm.mock_provider import MockLLMProvider
        p = MockLLMProvider()
        assert p.translate_text("") == ""
        assert p.translate_text("   ") == "   "

    def test_openai_has_translate_method(self):
        from signalvault.llm.openai_compatible_provider import OpenAICompatibleProvider
        p = OpenAICompatibleProvider("http://x", "k", "m")
        assert hasattr(p, "translate_text")
        assert callable(p.translate_text)
