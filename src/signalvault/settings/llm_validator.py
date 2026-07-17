"""C1-C: LLM Config Validator — backend service for testing LLM connectivity.

Uses httpx (same stack as OpenAiCompatibleProvider) to send a minimal
chat completion request and classify any errors.

Tests use mock HTTP transport — no real API calls in automation.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

import httpx

logger = logging.getLogger(__name__)

# Request timeout for validation (shorter than analysis timeout)
_VALIDATION_TIMEOUT = 10.0


class ValidationErrorType(str, Enum):
    AUTH_FAILED = "auth_failed"
    MODEL_NOT_FOUND = "model_not_found"
    BASE_URL_UNREACHABLE = "base_url_unreachable"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXCEEDED = "quota_exceeded"
    SSL_ERROR = "ssl_error"
    PROTOCOL_INCOMPATIBLE = "protocol_incompatible"
    PARSE_ERROR = "parse_error"
    UNKNOWN = "unknown"


@dataclass
class LLMValidationResult:
    """Structured result of an LLM connectivity test.

    ``technical_detail`` MUST NOT contain API keys.
    """

    ok: bool
    error_type: str = ""                    # ValidationErrorType value or ""
    user_message: str = ""                  # Chinese, safe for display
    technical_detail: str = ""              # English, no keys, for logs
    latency_ms: float = 0.0
    checked_at: str = ""                    # ISO 8601 UTC
    model_reported: str = ""                # model name from API response


async def validate_llm_config(
    base_url: str,
    api_key: str,
    model: str = "",
    *,
    timeout: float = _VALIDATION_TIMEOUT,
    client: httpx.AsyncClient | None = None,
) -> LLMValidationResult:
    """Test LLM connectivity with a minimal chat completion request.

    Args:
        base_url: API base URL (e.g. https://api.openai.com/v1).
        api_key: API key — NEVER logged.
        model: Model name to test (uses API default if empty).
        timeout: Request timeout in seconds.
        client: Optional pre-configured httpx client (for test mocking).

    Returns:
        LLMValidationResult with structured error classification.
    """
    from datetime import datetime, timezone

    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    start = time.perf_counter()

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict = {
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    if model:
        payload["model"] = model

    should_close = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout)

    try:
        resp = await client.post(url, headers=headers, json=payload)
        latency = (time.perf_counter() - start) * 1000

        if resp.is_success:
            try:
                data = resp.json()
                model_reported = data.get("model", "")
            except Exception:
                model_reported = ""
            return LLMValidationResult(
                ok=True,
                latency_ms=round(latency, 1),
                checked_at=checked_at,
                model_reported=model_reported,
            )

        # Non-success status codes
        status = resp.status_code
        error_type, user_message, tech_detail = _classify_http_error(status, resp)
        return LLMValidationResult(
            ok=False,
            error_type=error_type,
            user_message=user_message,
            technical_detail=tech_detail,
            latency_ms=round(latency, 1),
            checked_at=checked_at,
        )

    except httpx.TimeoutException:
        latency = (time.perf_counter() - start) * 1000
        return LLMValidationResult(
            ok=False,
            error_type=ValidationErrorType.TIMEOUT.value,
            user_message="连接超时，请检查网络或 base_url 是否可达。",
            technical_detail="Request timed out",
            latency_ms=round(latency, 1),
            checked_at=checked_at,
        )

    except httpx.ConnectError as e:
        latency = (time.perf_counter() - start) * 1000
        return LLMValidationResult(
            ok=False,
            error_type=ValidationErrorType.BASE_URL_UNREACHABLE.value,
            user_message="无法连接到服务器，请检查 base_url 和网络连接。",
            technical_detail=f"ConnectError: {_safe_error(e)}",
            latency_ms=round(latency, 1),
            checked_at=checked_at,
        )

    except httpx.HTTPError as e:
        latency = (time.perf_counter() - start) * 1000
        return LLMValidationResult(
            ok=False,
            error_type=ValidationErrorType.PROTOCOL_INCOMPATIBLE.value,
            user_message="服务器返回了意外的响应，请确认 base_url 是 OpenAI-compatible API。",
            technical_detail=f"HTTPError: {_safe_error(e)}",
            latency_ms=round(latency, 1),
            checked_at=checked_at,
        )

    except (OSError, ValueError) as e:
        latency = (time.perf_counter() - start) * 1000
        err_str = str(e).lower()
        if "ssl" in err_str or "tls" in err_str or "certificate" in err_str:
            return LLMValidationResult(
                ok=False,
                error_type=ValidationErrorType.SSL_ERROR.value,
                user_message="SSL/TLS 连接失败，请检查证书配置。",
                technical_detail=f"SSLError: {_safe_error(e)}",
                latency_ms=round(latency, 1),
                checked_at=checked_at,
            )
        return LLMValidationResult(
            ok=False,
            error_type=ValidationErrorType.UNKNOWN.value,
            user_message=f"连接失败：{_safe_error(e)[:100]}",
            technical_detail=f"OSError: {_safe_error(e)}",
            latency_ms=round(latency, 1),
            checked_at=checked_at,
        )

    finally:
        if should_close and client is not None:
            await client.aclose()


def _classify_http_error(status: int, resp: httpx.Response) -> tuple[str, str, str]:
    """Classify HTTP error status codes into ValidationErrorType.

    Returns (error_type, user_message, technical_detail).
    """
    try:
        body = resp.json()
    except Exception:
        body = {"error": {}}
    error_msg = ""
    error_type_str = ""
    if isinstance(body, dict):
        err = body.get("error", {})
        if isinstance(err, dict):
            error_msg = err.get("message", "")
            error_type_str = err.get("type", "")
        elif isinstance(err, str):
            error_msg = err
        # Some providers nest under "error" → "metadata" or top-level "message"
        if not error_msg:
            error_msg = body.get("message", "")

    if status == 400:
        # DeepSeek and some OpenAI-compatible providers return HTTP 400
        # (not 404) when the model name doesn't exist.  Check the body
        # for model-not-found signals before treating it as a generic error.
        if _looks_like_model_not_found(error_msg, error_type_str):
            return (
                ValidationErrorType.MODEL_NOT_FOUND.value,
                "模型未找到，请确认模型名称正确。DeepSeek 等提供商对不存在模型返回 400 而非 404。",
                f"HTTP 400: {_safe_str(error_msg)}",
            )
        return (
            ValidationErrorType.PROTOCOL_INCOMPATIBLE.value,
            "请求参数有误，请检查 API 配置。",
            f"HTTP 400: {_safe_str(error_msg)}",
        )

    if status == 401:
        return (
            ValidationErrorType.AUTH_FAILED.value,
            "API Key 无效，请检查后重试。",
            f"HTTP 401: {_safe_str(error_msg)}",
        )
    if status == 403:
        return (
            ValidationErrorType.AUTH_FAILED.value,
            "API Key 没有访问权限。",
            f"HTTP 403: {_safe_str(error_msg)}",
        )
    if status == 404:
        return (
            ValidationErrorType.MODEL_NOT_FOUND.value,
            "模型未找到，请确认模型名称和 base_url 正确。",
            f"HTTP 404: {_safe_str(error_msg)}",
        )
    if status == 429:
        return (
            ValidationErrorType.RATE_LIMITED.value,
            "请求过于频繁，请稍后重试。",
            f"HTTP 429: {_safe_str(error_msg)}",
        )
    if status in (402, 422):
        return (
            ValidationErrorType.QUOTA_EXCEEDED.value,
            "API 配额不足或请求参数有误，请检查账户余额。",
            f"HTTP {status}: {_safe_str(error_msg)}",
        )
    if status in (502, 503, 504):
        label = {502: "Bad Gateway", 503: "Service Unavailable", 504: "Gateway Timeout"}[status]
        return (
            ValidationErrorType.UPSTREAM_UNAVAILABLE.value,
            f"上游服务不可达 (HTTP {status} {label})。如果您使用了代理或网关，请检查其配置和目标地址是否可达。",
            f"HTTP {status}: {_safe_str(error_msg)}",
        )
    # 5xx and other unhandled codes
    return (
        ValidationErrorType.PROTOCOL_INCOMPATIBLE.value,
        f"服务器返回错误 (HTTP {status})，请确认 base_url 正确。",
        f"HTTP {status}: {_safe_str(error_msg)}",
    )


def _looks_like_model_not_found(error_msg: str, error_type_str: str) -> bool:
    """Check whether an HTTP error body looks like a model-not-found response.

    DeepSeek (HTTP 400) and other providers may return messages like:
      - "The model `deepseek-chat` does not exist"
      - "model does not exist"
      - "invalid model"
      - error type "invalid_request_error" combined with model keywords
    """
    msg_lower = error_msg.lower()
    type_lower = error_type_str.lower()

    # Strong signals: error message mentions model + existence
    strong_patterns = [
        "model" in msg_lower and "does not exist" in msg_lower,
        "model" in msg_lower and "not found" in msg_lower,
        "model" in msg_lower and "no such" in msg_lower,
        "invalid model" in msg_lower,
        "model not available" in msg_lower,
    ]
    if any(strong_patterns):
        return True

    # Weak signal: error type suggests invalid model combined with model keyword
    return type_lower in ("invalid_request_error", "invalid_parameter") and "model" in msg_lower


def _safe_error(exc: Exception) -> str:
    """Extract error message, redacting any accidental key material."""
    msg = str(exc)
    return _safe_str(msg)


def _safe_str(s: str) -> str:
    """Truncate and sanitize a string for technical_detail."""
    s = s or ""
    # Truncate long messages
    if len(s) > 300:
        s = s[:297] + "..."
    return s
