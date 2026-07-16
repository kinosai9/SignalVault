"""C2-A / C2-B: CSRF protection for local settings write endpoints.

Design for single-user local app (no login/session):
- Session token stored in a signed cookie
- Every POST form includes a hidden CSRF field
- JSON API clients include X-CSRF-Token header
- Origin/Referer checked for browser requests
- No CORS headers on write endpoints

Security model: double-submit cookie pattern with HMAC signing.
The token is set as a cookie AND must be submitted in the request body/header.
An attacker on a different origin cannot read the cookie, so they cannot
forge the token.

C2-B: Origin check uses URL host comparison (not string contains) to prevent
      bypasses like ``http://127.0.0.1.attacker.com``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Callable
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse, Response

# ═══════════════════════════════════════════════════════════════════════════════
# Token generation
# ═══════════════════════════════════════════════════════════════════════════════

CSRF_COOKIE_NAME = "signalvault_csrf"
CSRF_HEADER_NAME = "x-csrf-token"
CSRF_FORM_FIELD = "_csrf_token"
CSRF_COOKIE_MAX_AGE = 86400  # 24 hours
CSRF_TOKEN_BYTES = 32

# Change this per installation? For local single-user, a static secret is
# acceptable — the cookie is HttpOnly and SameSite=Strict.
_CSRF_SECRET = secrets.token_bytes(32)

# Hosts allowed for Origin/Referer checks (port is validated separately)
_ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def generate_csrf_token() -> str:
    """Generate a new CSRF token (random + HMAC timestamp)."""
    raw = secrets.token_bytes(CSRF_TOKEN_BYTES)
    return raw.hex()


def _sign_token(token: str) -> str:
    """HMAC-sign a token so we can verify it wasn't tampered."""
    mac = hmac.new(_CSRF_SECRET, token.encode(), hashlib.sha256)
    return mac.hexdigest()


def set_csrf_cookie(response: Response, token: str | None = None) -> str:
    """Set the CSRF cookie and return the token for embedding in forms.

    If *token* is provided, that token is used (caller must embed the same
    token in the form).  Otherwise a new random token is generated.
    """
    if token is None:
        token = generate_csrf_token()
    # Cookie value is token:signature
    signed = f"{token}:{_sign_token(token)}"
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=signed,
        max_age=CSRF_COOKIE_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=False,  # localhost, no HTTPS
        path="/",
    )
    return token


# ═══════════════════════════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════════════════════════


def validate_csrf(request: Request, submitted_token: str) -> bool:
    """Validate a submitted CSRF token against the cookie.

    Uses double-submit cookie pattern: the cookie contains token:signature.
    The submitted token must match the cookie's token.
    """
    cookie_value = request.cookies.get(CSRF_COOKIE_NAME, "")
    if not cookie_value:
        return False
    if ":" not in cookie_value:
        return False

    cookie_token, signature = cookie_value.rsplit(":", 1)
    expected_sig = _sign_token(cookie_token)

    # Constant-time comparison
    return hmac.compare_digest(signature, expected_sig) and hmac.compare_digest(
        submitted_token, cookie_token
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Origin / Referer check
# ═══════════════════════════════════════════════════════════════════════════════


def _is_local_origin(origin_or_url: str) -> bool:
    """Check if an Origin/Referer URL resolves to a local loopback host.

    Uses urlparse for correct host extraction — NOT string matching.
    Rejects ``http://127.0.0.1.attacker.com`` because the parsed hostname
    is ``127.0.0.1.attacker.com``, not ``127.0.0.1``.

    Allowed:  http://127.0.0.1, http://127.0.0.1:<any-port>,
              http://localhost, http://localhost:<any-port>,
              http://[::1], http://[::1]:<any-port>
    """
    if not origin_or_url:
        return False

    try:
        parsed = urlparse(origin_or_url)
    except Exception:
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    # Scheme must be http (local dev server)
    if parsed.scheme not in ("http", ""):
        return False

    return hostname in _ALLOWED_HOSTS


def check_origin(request: Request) -> bool:
    """Verify the request origin is local.

    Checks Origin header first, then Referer as fallback.
    Returns True if the origin is allowed or undetermined (non-browser clients).

    C2-B: Uses URL host comparison — ``127.0.0.1.attacker.com`` is rejected
          because urlparse extracts the FQDN, not a substring.
    """
    origin = request.headers.get("origin", "")
    if origin:
        # Reject "null" origin (sandboxed iframes, file://, data:)
        if origin.lower() == "null":
            return False
        return _is_local_origin(origin)

    # Fallback: check Referer for browser form submissions
    referer = request.headers.get("referer", "")
    if referer:
        return _is_local_origin(referer)

    # No Origin/Referer — likely a non-browser client (CLI, API tool)
    # Allow if CSRF token is present (JSON API clients)
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# Middleware helpers
# ═══════════════════════════════════════════════════════════════════════════════


def csrf_protected(handler: Callable):
    """Decorator for routes that need CSRF protection on POST.

    Checks:
    1. Origin/Referer is local (or absent for API clients)
    2. CSRF token matches cookie

    Extracts token from JSON body (_csrf_token field) or form data.
    Returns 403 JSON on failure.
    """
    import functools

    @functools.wraps(handler)
    async def wrapper(request: Request):
        # Only enforce on POST/PUT/DELETE
        if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
            return await handler(request)

        # 1. Origin check
        if not check_origin(request):
            return _forbidden("非本地来源的请求被拒绝")

        # 2. CSRF token check
        token = await _extract_csrf_token(request)
        if not token:
            return _forbidden("缺少 CSRF token")

        if not validate_csrf(request, token):
            return _forbidden("CSRF token 无效")

        return await handler(request)

    return wrapper


async def _extract_csrf_token(request: Request) -> str | None:
    """Extract CSRF token from JSON body or form data."""
    content_type = request.headers.get("content-type", "")

    # Try JSON body
    if "application/json" in content_type:
        try:
            body = await request.json()
            return body.get(CSRF_FORM_FIELD, "")
        except Exception:
            return None

    # Try form data
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        try:
            form = await request.form()
            return form.get(CSRF_FORM_FIELD, "")
        except Exception:
            return None

    # Try header (for API clients)
    header_token = request.headers.get(CSRF_HEADER_NAME, "")
    if header_token:
        return header_token

    return None


def _forbidden(message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": message, "error_type": "csrf"},
        status_code=403,
    )
