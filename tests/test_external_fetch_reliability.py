"""P2-S.2.2: External Fetch Reliability tests.

Tests:
1. SSL EOF retry — fails first, succeeds second
2. timeout retry — succeeds after retry
3. 3 failures → fetch_failed
4. fetch_all partial failure — single failure doesn't abort batch
5. validation report records failed_urls
6. HTTP 404 — no infinite retry
7. malformed html → degraded, not crash
8. existing tests pass
9. ruff clean
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from podcast_research.adapters.allin_zh_notes import AllInZHNotesAdapter
from podcast_research.adapters.external_html_notes import (
    DEFAULT_MAX_RETRIES,
    ERROR_CONNECTION,
    ERROR_HTTP_4XX,
    ERROR_HTTP_5XX,
    ERROR_SSL,
    ERROR_TIMEOUT,
    ERROR_UNKNOWN,
    FetchErrorResult,
    NormalizedSourceDocument,
)

# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def adapter() -> AllInZHNotesAdapter:
    """Adapter with fast retries for testing (no real backoff wait)."""
    return AllInZHNotesAdapter(timeout=10, max_retries=3, backoffs=[0.01, 0.02, 0.03])


# ═════════════════════════════════════════════════════════════════════════════
# Error classification tests
# ═════════════════════════════════════════════════════════════════════════════


class TestErrorClassification:
    """Test that errors are correctly classified into categories."""

    def test_classify_timeout(self, adapter: AllInZHNotesAdapter) -> None:
        err = httpx.TimeoutException("timed out")
        assert adapter._classify_error(err) == ERROR_TIMEOUT

    def test_classify_connect_error(self, adapter: AllInZHNotesAdapter) -> None:
        err = httpx.ConnectError("connection refused")
        assert adapter._classify_error(err) == ERROR_CONNECTION

    def test_classify_read_error(self, adapter: AllInZHNotesAdapter) -> None:
        err = httpx.ReadError("connection reset")
        assert adapter._classify_error(err) == ERROR_CONNECTION

    def test_classify_ssl_error(self, adapter: AllInZHNotesAdapter) -> None:
        # Simulate an SSL error (ssl module error wrapped or string-based)
        try:
            import ssl
            err = ssl.SSLEOFError("EOF occurred in violation of protocol")
        except ImportError:
            err = Exception("ssl EOF occurred in violation of protocol")
        category = adapter._classify_error(err)
        assert category == ERROR_SSL

    def test_classify_ssl_from_string(self, adapter: AllInZHNotesAdapter) -> None:
        """SSL errors from httpx may carry 'ssl' in their string representation."""
        err = Exception("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred")
        category = adapter._classify_error(err)
        assert category in (ERROR_SSL, ERROR_CONNECTION)

    def test_classify_http_404(self, adapter: AllInZHNotesAdapter) -> None:
        category = adapter._classify_error(Exception("not found"), status_code=404)
        assert category == ERROR_HTTP_4XX

    def test_classify_http_500(self, adapter: AllInZHNotesAdapter) -> None:
        category = adapter._classify_error(Exception("server error"), status_code=500)
        assert category == ERROR_HTTP_5XX

    def test_classify_unknown(self, adapter: AllInZHNotesAdapter) -> None:
        err = ValueError("some random error")
        category = adapter._classify_error(err)
        assert category == ERROR_UNKNOWN


class TestRetryable:
    """Test the _is_retryable decision logic."""

    def test_ssl_is_retryable(self, adapter: AllInZHNotesAdapter) -> None:
        assert adapter._is_retryable(ERROR_SSL) is True

    def test_timeout_is_retryable(self, adapter: AllInZHNotesAdapter) -> None:
        assert adapter._is_retryable(ERROR_TIMEOUT) is True

    def test_connection_is_retryable(self, adapter: AllInZHNotesAdapter) -> None:
        assert adapter._is_retryable(ERROR_CONNECTION) is True

    def test_http_5xx_is_retryable(self, adapter: AllInZHNotesAdapter) -> None:
        assert adapter._is_retryable(ERROR_HTTP_5XX) is True

    def test_http_404_not_retryable(self, adapter: AllInZHNotesAdapter) -> None:
        assert adapter._is_retryable(ERROR_HTTP_4XX, status_code=404) is False

    def test_http_403_not_retryable(self, adapter: AllInZHNotesAdapter) -> None:
        assert adapter._is_retryable(ERROR_HTTP_4XX, status_code=403) is False

    def test_unknown_not_retryable(self, adapter: AllInZHNotesAdapter) -> None:
        assert adapter._is_retryable(ERROR_UNKNOWN) is False


# ═════════════════════════════════════════════════════════════════════════════
# Test 1: SSL EOF — fails first, succeeds on retry
# ═════════════════════════════════════════════════════════════════════════════


class TestSSLRetry:
    """Test 1: SSL EOF retry behavior."""

    def test_ssl_fails_once_then_succeeds(self, adapter: AllInZHNotesAdapter) -> None:
        """First attempt SSL error, second attempt returns HTML."""
        html = "<html><body><h1>OK</h1></body></html>"
        mock_resp = MagicMock()
        mock_resp.text = html

        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise httpx.ReadError("[SSL: UNEXPECTED_EOF_WHILE_READING]")
            return mock_resp

        with patch("httpx.get", side_effect=mock_get):
            result = adapter._fetch_html("https://example.com/ep1")
            assert result == html
            assert call_count[0] == 2  # failed once, succeeded on retry


# ═════════════════════════════════════════════════════════════════════════════
# Test 2: timeout retry — succeeds after retry
# ═════════════════════════════════════════════════════════════════════════════


class TestTimeoutRetry:
    """Test 2: timeout is retryable and can succeed on retry."""

    def test_timeout_then_success(self, adapter: AllInZHNotesAdapter) -> None:
        html = "<html><body><h1>OK</h1></body></html>"
        mock_resp = MagicMock()
        mock_resp.text = html

        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise httpx.TimeoutException("timed out")
            return mock_resp

        with patch("httpx.get", side_effect=mock_get):
            result = adapter._fetch_html("https://example.com/ep1")
            assert result == html
            assert call_count[0] == 3  # two timeouts, third succeeds


# ═════════════════════════════════════════════════════════════════════════════
# Test 3: 3 failures → fetch_failed
# ═════════════════════════════════════════════════════════════════════════════


class TestExhaustedRetries:
    """Test 3: after max_retries exhausted, raises RuntimeError."""

    def test_all_retries_exhausted(self, adapter: AllInZHNotesAdapter) -> None:
        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            raise httpx.ReadError("SSL EOF")

        with patch("httpx.get", side_effect=mock_get):
            with pytest.raises(RuntimeError, match="Failed to fetch"):
                adapter._fetch_html("https://example.com/ep1")

        # 3 retries + 1 initial attempt = 4 total
        assert call_count[0] == 4

    def test_three_failures_sets_fetch_failed(self, adapter: AllInZHNotesAdapter) -> None:
        """After exhausting retries, the caller gets RuntimeError."""
        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            raise httpx.TimeoutException("timeout")

        with patch("httpx.get", side_effect=mock_get):
            with pytest.raises(RuntimeError):
                adapter._fetch_html("https://example.com/ep2")

        assert call_count[0] == 4  # 3 retries exhausted


# ═════════════════════════════════════════════════════════════════════════════
# Test 4: fetch_all partial failure doesn't abort batch
# ═════════════════════════════════════════════════════════════════════════════


# Minimal test homepage HTML
MOCK_HOMEPAGE = """<!doctype html><html><body>
<div class="page"><div class="episode-list">
<a class="episode-card" href="./episodes/ep-ok-1/notes.visual.html"><h2 class="episode-title">OK Episode 1</h2><span class="episode-date">2026-06-23</span></a>
<a class="episode-card" href="./episodes/ep-bad/notes.visual.html"><h2 class="episode-title">Bad Episode</h2><span class="episode-date">2026-06-15</span></a>
<a class="episode-card" href="./episodes/ep-ok-2/notes.visual.html"><h2 class="episode-title">OK Episode 2</h2><span class="episode-date">2026-05-31</span></a>
</div></div>
</body></html>"""

# A minimal valid episode HTML
MOCK_OK_EPISODE = """<!doctype html><html><body>
<div class="page"><main class="article"><header class="hero">
<h1>OK Episode</h1>
<div class="meta"><span>生成时间：2026-06-23 15:00</span><span>来源：<a href="https://www.youtube.com/watch?v=test0000001">YouTube</a></span></div>
</header></main></div>
</body></html>"""


class TestPartialFailureFetchAll:
    """Test 4: fetch_all continues on single episode failure."""

    def test_fetch_all_continues_after_failure(self, adapter: AllInZHNotesAdapter) -> None:
        """fetch_all should return successes for episodes that work, errors for ones that fail."""

        def mock_fetch_html(url):
            if "ep-bad" in url:
                raise RuntimeError("Failed to fetch after 4 attempts: [ssl_error]")
            if "ep-ok" in url:
                return MOCK_OK_EPISODE
            # Base/homepage URL → return homepage HTML
            return MOCK_HOMEPAGE

        with patch.object(adapter, "_fetch_html", side_effect=mock_fetch_html):
            entries, docs, errors = adapter.fetch_all(base_url="https://example.com")

        assert len(entries) == 3  # homepage parsed
        assert len(docs) == 2      # 2 successes
        assert len(errors) == 1    # 1 failure
        assert "ep-bad" in errors[0].url

    def test_fetch_all_errors_have_category(self, adapter: AllInZHNotesAdapter) -> None:
        """Each FetchErrorResult should have an error category."""
        def mock_fetch_html(url):
            if "ep-bad" in url:
                raise httpx.TimeoutException("timeout")
            if "ep-ok" in url:
                return MOCK_OK_EPISODE
            return MOCK_HOMEPAGE

        with patch.object(adapter, "_fetch_html", side_effect=mock_fetch_html):
            entries, docs, errors = adapter.fetch_all(base_url="https://example.com")

        assert len(errors) == 1
        assert errors[0].error_category == ERROR_TIMEOUT
        assert errors[0].url != ""
        assert errors[0].slug != ""


# ═════════════════════════════════════════════════════════════════════════════
# Test 5: validation report records failed_urls
# ═════════════════════════════════════════════════════════════════════════════


class TestFetchErrorResult:
    """Test 5: FetchErrorResult dataclass."""

    def test_fetch_error_result_fields(self) -> None:
        err = FetchErrorResult(
            url="https://example.com/ep1",
            error_category=ERROR_SSL,
            error_message="SSL EOF",
            http_status=None,
            attempts=4,
            slug="ep-1",
            title="Test Episode",
        )
        assert err.url == "https://example.com/ep1"
        assert err.error_category == ERROR_SSL
        assert err.attempts == 4
        assert err.slug == "ep-1"

    def test_fetch_error_result_defaults(self) -> None:
        err = FetchErrorResult()
        assert err.error_category == ERROR_UNKNOWN
        assert err.url == ""


# ═════════════════════════════════════════════════════════════════════════════
# Test 6: HTTP 404 — no infinite retry
# ═════════════════════════════════════════════════════════════════════════════


class TestHTTP404NoRetry:
    """Test 6: HTTP 404 should NOT be retried."""

    def test_http_404_raises_immediately(self, adapter: AllInZHNotesAdapter) -> None:
        """404 should raise on first attempt without retrying."""
        call_count = [0]
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=mock_resp,
        )

        def mock_get(url, **kwargs):
            call_count[0] += 1
            return mock_resp

        with patch("httpx.get", side_effect=mock_get):
            with pytest.raises(httpx.HTTPStatusError):
                adapter._fetch_html("https://example.com/nonexistent")

        assert call_count[0] == 1  # no retries for 404

    def test_http_403_raises_immediately(self, adapter: AllInZHNotesAdapter) -> None:
        """403 should raise without retrying."""
        call_count = [0]
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Forbidden", request=MagicMock(), response=mock_resp,
        )

        def mock_get(url, **kwargs):
            call_count[0] += 1
            return mock_resp

        with patch("httpx.get", side_effect=mock_get):
            with pytest.raises(httpx.HTTPStatusError):
                adapter._fetch_html("https://example.com/forbidden")

        assert call_count[0] == 1

    def test_http_500_is_retried(self, adapter: AllInZHNotesAdapter) -> None:
        """500 should trigger retry."""
        call_count = [0]
        html = "<html><body>OK</body></html>"

        def mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] < 2:
                mock_resp = MagicMock()
                mock_resp.status_code = 500
                mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "Server Error", request=MagicMock(), response=mock_resp,
                )
                return mock_resp
            else:
                mock_resp = MagicMock()
                mock_resp.text = html
                return mock_resp

        with patch("httpx.get", side_effect=mock_get):
            result = adapter._fetch_html("https://example.com/flaky")
            assert result == html
            assert call_count[0] == 2  # 500 → retried → success


# ═════════════════════════════════════════════════════════════════════════════
# Test 7: malformed html → degraded, not crash
# ═════════════════════════════════════════════════════════════════════════════


class TestMalformedHTMLGraceful:
    """Test 7: malformed HTML produces degraded document, not a crash."""

    def test_malformed_html_returns_document(self, adapter: AllInZHNotesAdapter) -> None:
        """Malformed HTML with no sections should return a doc with empty fields."""
        html = "<html><body><p>Just garbage, no real structure here.</p></body></html>"
        doc = adapter._parse_episode(html, url="https://example.com/broken")
        assert isinstance(doc, NormalizedSourceDocument)
        assert doc.key_points == []
        assert doc.timeline == []
        assert doc.speaker_viewpoints == []
        assert doc.bilingual_quotes == []

    def test_empty_body_does_not_crash(self, adapter: AllInZHNotesAdapter) -> None:
        """Empty body is parsed as an empty document."""
        doc = adapter._parse_episode("<html><body></body></html>", url="https://example.com/empty")
        assert isinstance(doc, NormalizedSourceDocument)
        assert doc.title == ""

    def test_partial_html_preserves_what_it_can(self, adapter: AllInZHNotesAdapter) -> None:
        """HTML with only a hero section preserves what's available."""
        html = """<!doctype html><html><body>
        <header class="hero">
        <h1>Partial Episode</h1>
        <div class="meta">
        <span>生成时间：2026-01-15 10:00</span>
        </div>
        </header>
        </body></html>"""
        doc = adapter._parse_episode(html, url="https://example.com/partial")
        assert doc.title == "Partial Episode"
        assert doc.generated_at == "2026-01-15 10:00"


# ═════════════════════════════════════════════════════════════════════════════
# Additional: max_retries config and backoff
# ═════════════════════════════════════════════════════════════════════════════


class TestRetryConfig:
    """Test retry configuration options."""

    def test_default_max_retries(self) -> None:
        adapter = AllInZHNotesAdapter()
        assert adapter._max_retries == DEFAULT_MAX_RETRIES

    def test_custom_max_retries(self) -> None:
        adapter = AllInZHNotesAdapter(max_retries=1)
        assert adapter._max_retries == 1

    def test_custom_backoffs(self) -> None:
        adapter = AllInZHNotesAdapter(max_retries=2, backoffs=[0.1, 0.5])
        assert adapter._backoffs == [0.1, 0.5]

    def test_zero_max_retries(self, adapter: AllInZHNotesAdapter) -> None:
        """With max_retries=0, no retries happen."""
        adapter_no_retry = AllInZHNotesAdapter(max_retries=0, backoffs=[])
        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            raise httpx.TimeoutException("timeout")

        with patch("httpx.get", side_effect=mock_get):
            with pytest.raises(RuntimeError):
                adapter_no_retry._fetch_html("https://example.com/ep1")

        assert call_count[0] == 1  # only initial attempt, no retries

    def test_connection_error_retry(self, adapter: AllInZHNotesAdapter) -> None:
        """Connection reset is retryable."""
        html = "<html><body>OK</body></html>"
        mock_resp = MagicMock()
        mock_resp.text = html
        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] < 2:
                raise httpx.ConnectError("connection reset")
            return mock_resp

        with patch("httpx.get", side_effect=mock_get):
            result = adapter._fetch_html("https://example.com/ep1")
            assert result == html
            assert call_count[0] == 2


# ═════════════════════════════════════════════════════════════════════════════
# Test: error message in RuntimeError after exhaustion
# ═════════════════════════════════════════════════════════════════════════════


class TestExhaustedErrorMessage:
    """Test that the final RuntimeError message is informative."""

    def test_error_message_includes_url(self, adapter: AllInZHNotesAdapter) -> None:
        def mock_get(url, **kwargs):
            raise httpx.TimeoutException("timeout")

        with patch("httpx.get", side_effect=mock_get):
            with pytest.raises(RuntimeError, match="https://example.com/specific-ep"):
                adapter._fetch_html("https://example.com/specific-ep")

    def test_error_message_includes_category(self, adapter: AllInZHNotesAdapter) -> None:
        def mock_get(url, **kwargs):
            raise httpx.TimeoutException("timeout")

        with patch("httpx.get", side_effect=mock_get):
            with pytest.raises(RuntimeError, match="timeout"):
                adapter._fetch_html("https://example.com/x")
