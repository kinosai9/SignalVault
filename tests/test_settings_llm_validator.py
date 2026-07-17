"""C1-C tests: LLM Config Validator.

All tests use mock HTTP — no real API calls.
"""

from __future__ import annotations

import httpx
import pytest

from signalvault.settings.llm_validator import (
    ValidationErrorType,
    validate_llm_config,
)

# ── Mock transport builder ────────────────────────────────────────────────────


def _mock_transport(status: int = 200, json_body: dict | None = None,
                    exc: type[Exception] | None = None):
    """Build an httpx.MockTransport that returns a given response or raises."""
    if exc is not None:
        async def handler(request):
            raise exc("mock error")
    else:
        body = json_body or {"model": "test-model"}
        async def handler(request):
            return httpx.Response(status, json=body)
    return httpx.MockTransport(handler)


def _make_client(transport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport, base_url="https://test.api")


# ── Success ───────────────────────────────────────────────────────────────────


class TestValidationSuccess:
    @pytest.mark.anyio
    async def test_successful_validation(self):
        client = _make_client(_mock_transport(200, {"model": "gpt-4o"}))
        result = await validate_llm_config(
            "https://api.example.com", "sk-test", "gpt-4o",
            client=client,
        )
        assert result.ok is True
        assert result.error_type == ""
        assert result.model_reported == "gpt-4o"
        assert result.latency_ms >= 0
        assert result.checked_at != ""


# ── Error classification ──────────────────────────────────────────────────────


class TestErrorClassification:
    @pytest.mark.anyio
    async def test_auth_failed_401(self):
        client = _make_client(_mock_transport(401, {"error": {"message": "Bad key"}}))
        result = await validate_llm_config(
            "https://api.example.com", "sk-bad", client=client,
        )
        assert result.ok is False
        assert result.error_type == ValidationErrorType.AUTH_FAILED.value

    @pytest.mark.anyio
    async def test_auth_failed_403(self):
        client = _make_client(_mock_transport(403))
        result = await validate_llm_config(
            "https://api.example.com", "sk-bad", client=client,
        )
        assert result.ok is False
        assert result.error_type == ValidationErrorType.AUTH_FAILED.value

    @pytest.mark.anyio
    async def test_model_not_found_404(self):
        client = _make_client(_mock_transport(404))
        result = await validate_llm_config(
            "https://api.example.com", "sk-test", client=client,
        )
        assert result.ok is False
        assert result.error_type == ValidationErrorType.MODEL_NOT_FOUND.value

    @pytest.mark.anyio
    async def test_model_not_found_400_deepseek_style(self):
        """DeepSeek returns HTTP 400 when model doesn't exist."""
        client = _make_client(_mock_transport(400, {
            "error": {"message": "The model `deepseek-chat` does not exist",
                       "type": "invalid_request_error"}
        }))
        result = await validate_llm_config(
            "https://api.example.com", "sk-test", model="deepseek-chat",
            client=client,
        )
        assert result.ok is False
        assert result.error_type == ValidationErrorType.MODEL_NOT_FOUND.value

    @pytest.mark.anyio
    async def test_model_not_found_400_message_match(self):
        """Various model-not-found message patterns on HTTP 400."""
        patterns = [
            {"error": {"message": "model not found"}},
            {"error": {"message": "invalid model"}},
            {"error": {"message": "no such model"}},
            {"error": {"message": "model not available"}},
        ]
        for body in patterns:
            client = _make_client(_mock_transport(400, body))
            result = await validate_llm_config(
                "https://api.example.com", "sk-test", client=client,
            )
            assert result.error_type == ValidationErrorType.MODEL_NOT_FOUND.value, (
                f"Pattern not matched: {body}"
            )

    @pytest.mark.anyio
    async def test_http_400_not_model_related(self):
        """HTTP 400 without model-not-found signal should be generic error."""
        client = _make_client(_mock_transport(400, {
            "error": {"message": "invalid request body"}
        }))
        result = await validate_llm_config(
            "https://api.example.com", "sk-test", client=client,
        )
        assert result.ok is False
        assert result.error_type != ValidationErrorType.MODEL_NOT_FOUND.value
        assert result.error_type == ValidationErrorType.PROTOCOL_INCOMPATIBLE.value

    @pytest.mark.anyio
    async def test_rate_limited(self):
        client = _make_client(_mock_transport(429))
        result = await validate_llm_config(
            "https://api.example.com", "sk-test", client=client,
        )
        assert result.ok is False
        assert result.error_type == ValidationErrorType.RATE_LIMITED.value

    @pytest.mark.anyio
    async def test_quota_exceeded_402(self):
        client = _make_client(_mock_transport(402))
        result = await validate_llm_config(
            "https://api.example.com", "sk-test", client=client,
        )
        assert result.ok is False
        assert result.error_type == ValidationErrorType.QUOTA_EXCEEDED.value

    @pytest.mark.anyio
    async def test_upstream_unavailable_502(self):
        client = _make_client(_mock_transport(502))
        result = await validate_llm_config(
            "https://api.example.com", "sk-test", client=client,
        )
        assert result.ok is False
        assert result.error_type == ValidationErrorType.UPSTREAM_UNAVAILABLE.value
        assert "代理" in result.user_message or "网关" in result.user_message

    @pytest.mark.anyio
    async def test_upstream_unavailable_503(self):
        client = _make_client(_mock_transport(503))
        result = await validate_llm_config(
            "https://api.example.com", "sk-test", client=client,
        )
        assert result.ok is False
        assert result.error_type == ValidationErrorType.UPSTREAM_UNAVAILABLE.value

    @pytest.mark.anyio
    async def test_upstream_unavailable_504(self):
        client = _make_client(_mock_transport(504))
        result = await validate_llm_config(
            "https://api.example.com", "sk-test", client=client,
        )
        assert result.ok is False
        assert result.error_type == ValidationErrorType.UPSTREAM_UNAVAILABLE.value

    @pytest.mark.anyio
    async def test_timeout(self):
        client = _make_client(_mock_transport(exc=httpx.TimeoutException))
        result = await validate_llm_config(
            "https://api.example.com", "sk-test", client=client,
        )
        assert result.ok is False
        assert result.error_type == ValidationErrorType.TIMEOUT.value

    @pytest.mark.anyio
    async def test_base_url_unreachable(self):
        client = _make_client(_mock_transport(exc=httpx.ConnectError))
        result = await validate_llm_config(
            "https://api.example.com", "sk-test", client=client,
        )
        assert result.ok is False
        assert result.error_type == ValidationErrorType.BASE_URL_UNREACHABLE.value

    @pytest.mark.anyio
    async def test_ssl_error(self):
        client = _make_client(_mock_transport(
            exc=lambda msg: OSError("ssl certificate verify failed")
        ))
        result = await validate_llm_config(
            "https://api.example.com", "sk-test", client=client,
        )
        assert result.ok is False
        assert result.error_type == ValidationErrorType.SSL_ERROR.value


# ── API key not in technical_detail ───────────────────────────────────────────


class TestNoKeyLeakage:
    @pytest.mark.anyio
    async def test_api_key_not_in_error_message(self):
        """API key must never appear in technical_detail."""
        client = _make_client(_mock_transport(401))
        result = await validate_llm_config(
            "https://api.example.com", "sk-super-secret-key-12345", client=client,
        )
        assert "sk-super-secret-key-12345" not in result.technical_detail
        assert "sk-super-secret-key-12345" not in result.user_message

    @pytest.mark.anyio
    async def test_api_key_not_in_timeout_error(self):
        client = _make_client(_mock_transport(exc=httpx.TimeoutException))
        result = await validate_llm_config(
            "https://api.example.com", "sk-another-key", client=client,
        )
        assert "sk-another-key" not in result.technical_detail
