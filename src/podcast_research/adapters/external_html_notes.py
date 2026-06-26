"""External HTML Notes Adapter — 外部衍生信息源适配器。

抓取已经加工好的静态 HTML 精读页面，输出统一的 NormalizedSourceDocument。
不作为 source of truth，而是作为 YouTube 原始来源的补充（derived/secondary）。

Design:
- Base adapter: ExternalHTMLNotesAdapter — fetches HTML, parses with BeautifulSoup
- Specific adapters inherit and implement site-specific selectors
- All output flows through NormalizedSourceDocument + related types
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# Error types
# ═════════════════════════════════════════════════════════════════════════════

# Error categories for classification
ERROR_SSL = "ssl_error"
ERROR_TIMEOUT = "timeout"
ERROR_CONNECTION = "connection_error"
ERROR_HTTP_4XX = "http_4xx"
ERROR_HTTP_5XX = "http_5xx"
ERROR_MALFORMED = "malformed_html"
ERROR_PARSE = "parse_error"
ERROR_UNKNOWN = "unknown_error"

# Errors that are worth retrying (transient)
_RETRYABLE_ERRORS = {ERROR_SSL, ERROR_TIMEOUT, ERROR_CONNECTION, ERROR_HTTP_5XX}

# HTTP status codes that should NOT be retried (client errors)
_NON_RETRYABLE_STATUSES = {400, 401, 403, 404, 405, 410}


@dataclass
class FetchErrorResult:
    """Structured error record for a failed fetch attempt."""
    url: str = ""
    error_category: str = ERROR_UNKNOWN
    error_message: str = ""
    http_status: int | None = None
    attempts: int = 0
    slug: str = ""
    title: str = ""  # from homepage entry, if available


# Default retry config
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFFS = [0.5, 1.5, 3.0]  # seconds between retries


# ═════════════════════════════════════════════════════════════════════════════
# Normalized data types
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class NormalizedQuote:
    """双语引语 — 英文原话 + 中文翻译 + 上下文说明。"""
    text_en: str = ""
    text_zh: str = ""
    context_note: str = ""


@dataclass
class NormalizedSpeakerTurn:
    """单次发言 — 说话人 + 内容 + 可选时间戳。"""
    speaker_name: str
    text: str
    timestamp: str = ""


@dataclass
class NormalizedEpisodeSegment:
    """单段时间线分段 — 时间范围 + 核心内容 + 背景术语 + 逐段发言。"""
    index: int
    title: str = ""
    time_range: str = ""
    core_points: list[str] = field(default_factory=list)
    background_terms: list[dict] = field(default_factory=list)  # [{term: str, definition: str}]
    speaker_turns: list[NormalizedSpeakerTurn] = field(default_factory=list)


@dataclass
class NormalizedSpeakerViewpoint:
    """嘉宾观点总结。"""
    name: str = ""
    role: str = ""
    viewpoint: str = ""


@dataclass
class NormalizedSourceDocument:
    """外部衍生信息源统一中间结构。

    所有 external_static_notes adapter 的输出格式。
    """
    # ── Source identity ──
    provider: str = ""                # e.g. "allin-podcast-zh-notes"
    source_type: str = "derived"      # always "derived" for external notes
    source_confidence: str = "secondary"  # always "secondary"
    source_url: str = ""              # the external page URL
    original_source_url: str = ""     # YouTube URL (the primary source)
    slug: str = ""                    # external site slug / directory name

    # ── Content metadata ──
    title: str = ""
    generated_at: str = ""
    reading_time: str = ""
    summary: str = ""
    youtube_video_id: str = ""

    # ── Structured content ──
    key_points: list[str] = field(default_factory=list)
    timeline: list[NormalizedEpisodeSegment] = field(default_factory=list)
    speaker_viewpoints: list[NormalizedSpeakerViewpoint] = field(default_factory=list)
    bilingual_quotes: list[NormalizedQuote] = field(default_factory=list)

    # ── Provenance (required per spec) ──
    provenance: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provenance:
            self.provenance = {
                "provider": self.provider,
                "source_url": self.source_url,
                "source_type": self.source_type,
                "source_confidence": self.source_confidence,
                "original_source_url": self.original_source_url,
            }


@dataclass
class ExternalEpisodeEntry:
    """首页 episode 列表条目（轻量，仅含导航信息）。"""
    title: str = ""
    url: str = ""           # relative or absolute URL to episode page
    date: str = ""          # YYYY-MM-DD
    slug: str = ""          # extracted from URL
    video_id: str = ""      # if available from homepage (usually not)


# ═════════════════════════════════════════════════════════════════════════════
# Base adapter
# ═════════════════════════════════════════════════════════════════════════════


class ExternalHTMLNotesAdapter:
    """外部 HTML 精读页面 Adapter 基类。

    子类实现：
    - _parse_homepage(html) → list[ExternalEpisodeEntry]
    - _parse_episode(html, url) → NormalizedSourceDocument
    - provider_name: str (class attribute)

    子类可覆盖：
    - _fetch_html(url) → str (默认 httpx with retry)
    - _extract_video_id(doc) → str
    """

    provider_name: str = "unknown"

    def __init__(
        self,
        timeout: int = 30,
        user_agent: str | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoffs: list[float] | None = None,
    ) -> None:
        self._timeout = timeout
        self._user_agent = user_agent or (
            "Mozilla/5.0 (compatible; podcast-research-bot/1.0; +https://github.com/kinosai9/podcast_research)"
        )
        self._max_retries = max_retries
        self._backoffs = backoffs or DEFAULT_BACKOFFS[:max_retries]

    # ── Error classification ──────────────────────────────────────────────

    @staticmethod
    def _classify_error(exception: Exception, status_code: int | None = None) -> str:
        """Classify an exception into an error category string."""
        import httpx

        # HTTP status codes
        if status_code is not None:
            if 400 <= status_code < 500:
                return ERROR_HTTP_4XX
            if 500 <= status_code < 600:
                return ERROR_HTTP_5XX

        # httpx-specific exceptions
        if isinstance(exception, httpx.TimeoutException):
            return ERROR_TIMEOUT
        if isinstance(exception, httpx.ConnectError):
            return ERROR_CONNECTION
        if isinstance(exception, httpx.ReadError):
            return ERROR_CONNECTION

        # SSL errors
        error_str = str(exception).lower()
        if "ssl" in error_str or "ssl" in type(exception).__name__.lower():
            return ERROR_SSL
        if "eof" in error_str and "ssl" in error_str:
            return ERROR_SSL

        # Connection reset / broken pipe
        if any(kw in error_str for kw in ["connection reset", "broken pipe", "connectionrefused", "connection refused", "eof"]):
            return ERROR_CONNECTION

        # Timeout
        if any(kw in error_str for kw in ["timeout", "timed out"]):
            return ERROR_TIMEOUT

        return ERROR_UNKNOWN

    @staticmethod
    def _is_retryable(error_category: str, status_code: int | None = None) -> bool:
        """Determine if an error is worth retrying.

        Args:
            error_category: One of the ERROR_* constants.
            status_code: HTTP status code, if applicable.

        Returns:
            True if retry is likely to succeed.
        """
        # Never retry 4xx client errors (except 429 Too Many Requests)
        if status_code is not None and status_code in _NON_RETRYABLE_STATUSES:
            return False

        return error_category in _RETRYABLE_ERRORS

    # ── HTML fetching with retry ──────────────────────────────────────────

    def _fetch_html(self, url: str) -> str:
        """Fetch HTML from URL with retry on transient errors.

        Retries on: SSL errors, timeouts, connection errors, HTTP 5xx.
        Does NOT retry on: HTTP 4xx (except 429), malformed HTML, parse errors.

        Raises:
            httpx.HTTPStatusError: on non-retryable HTTP errors.
            RuntimeError: after exhausting all retries.
        """
        import httpx

        last_error: Exception | None = None
        last_category: str = ERROR_UNKNOWN
        last_status: int | None = None

        for attempt in range(self._max_retries + 1):
            try:
                if attempt > 0:
                    backoff = self._backoffs[min(attempt - 1, len(self._backoffs) - 1)]
                    logger.info(
                        "Retry %d/%d for %s after %.1fs",
                        attempt, self._max_retries, url, backoff,
                    )
                    time.sleep(backoff)

                logger.info("Fetching %s (attempt %d/%d)", url, attempt + 1, self._max_retries + 1)
                resp = httpx.get(
                    url,
                    follow_redirects=True,
                    timeout=self._timeout,
                    headers={"User-Agent": self._user_agent},
                )
                resp.raise_for_status()
                return resp.text

            except httpx.HTTPStatusError as e:
                last_error = e
                last_status = e.response.status_code
                last_category = self._classify_error(e, status_code=last_status)

                if not self._is_retryable(last_category, status_code=last_status):
                    logger.warning(
                        "Non-retryable HTTP %d for %s, not retrying",
                        last_status, url,
                    )
                    raise

                logger.warning(
                    "HTTP %d for %s (attempt %d/%d): %s",
                    last_status, url, attempt + 1, self._max_retries + 1, e,
                )

            except Exception as e:
                last_error = e
                last_category = self._classify_error(e)

                if not self._is_retryable(last_category):
                    logger.warning(
                        "Non-retryable error '%s' for %s, not retrying",
                        last_category, url,
                    )
                    raise

                logger.warning(
                    "Fetch error '%s' for %s (attempt %d/%d): %s",
                    last_category, url, attempt + 1, self._max_retries + 1, e,
                )

        # Exhausted all retries
        raise RuntimeError(
            f"Failed to fetch {url} after {self._max_retries + 1} attempts: "
            f"[{last_category}] {last_error}"
        )

    def _parse_html(self, html: str) -> "BeautifulSoup":
        """Parse HTML string into BeautifulSoup object."""
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "lxml")

    # ── Public API ─────────────────────────────────────────────────────────

    def fetch_homepage(self, url: str) -> list[ExternalEpisodeEntry]:
        """Fetch and parse the homepage, returning episode list."""
        html = self._fetch_html(url)
        return self._parse_homepage(html, url)

    def fetch_episode(self, url: str) -> NormalizedSourceDocument:
        """Fetch and parse a single episode page.

        Raises:
            RuntimeError: if fetch fails after all retries.
            ValueError: if HTML is malformed beyond parsing.
        """
        html = self._fetch_html(url)
        return self._parse_episode(html, url)

    # ── Subclass interface ─────────────────────────────────────────────────

    def _parse_homepage(self, html: str, base_url: str = "") -> list[ExternalEpisodeEntry]:
        raise NotImplementedError

    def _parse_episode(self, html: str, url: str) -> NormalizedSourceDocument:
        raise NotImplementedError

    # ── Shared utilities ───────────────────────────────────────────────────

    @staticmethod
    def _extract_video_id_from_url(youtube_url: str) -> str:
        """Extract YouTube video ID from various URL formats."""
        if not youtube_url:
            return ""
        patterns = [
            r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([a-zA-Z0-9_-]{11})",
            r"^([a-zA-Z0-9_-]{11})$",
        ]
        for pat in patterns:
            m = re.search(pat, youtube_url)
            if m:
                return m.group(1)
        return ""

    @staticmethod
    def _slug_from_url(url: str) -> str:
        """Extract slug/directory name from an episode URL path."""
        # e.g. "./episodes/my-slug/notes.visual.html" → "my-slug"
        # e.g. "https://.../episodes/my-slug/notes.visual.html" → "my-slug"
        m = re.search(r"/episodes/([^/]+)/", url)
        if m:
            return m.group(1)
        # fallback: last path segment before filename
        parts = url.rstrip("/").split("/")
        if len(parts) >= 2:
            return parts[-2]
        return ""

    @staticmethod
    def _clean_text(text: str) -> str:
        """Clean extracted text: strip whitespace, normalize."""
        if not text:
            return ""
        return " ".join(text.split())

    @staticmethod
    def _parse_date(text: str) -> str:
        """Try to parse a date string to YYYY-MM-DD format."""
        if not text:
            return ""
        # Already YYYY-MM-DD
        if re.match(r"^\d{4}-\d{2}-\d{2}$", text.strip()):
            return text.strip()
        # Chinese format: "2026年4月10日"
        m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
        if m:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return text.strip()
