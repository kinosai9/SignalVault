"""P2-S.3.2.1: Rule-based Source Profiler.

Determines whether a URL is eligible for tracked source creation
and recommends discovery / identity / change-detection strategies.

Profiling is read-only: it must never write Reports, Deep Notes,
Source Archives, Claims, or Signals.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from signalvault.sources.models import (
    SourceKind,
    SourceProfile,
    SuggestedAction,
    TrackingEligibility,
)

logger = logging.getLogger(__name__)

# ── Adapter allowlist ───────────────────────────────────────────────────────
# Only adapters in this set can be automatically selected during profiling.
# LLM profilers MUST respect this allowlist and cannot promote an adapter
# that is not listed here.
TRACKABLE_ADAPTER_ALLOWLIST: set[str] = {
    "allin_zh_notes",
}

# ── Rule-based profiler ─────────────────────────────────────────────────────


def profile_source_url(url: str) -> SourceProfile:
    """Profile a URL to determine its tracking eligibility.

    Uses rule-based heuristics (no LLM). Fetches the URL if needed
    for HTML-level detection (RSS link, article structure, list patterns).

    Returns a SourceProfile — no side effects, no writes.
    """
    if not url or not url.strip():
        return _make_unknown_profile(url, "Empty URL")

    url = url.strip()
    normalized = _normalize_url(url)
    domain = urlparse(url).netloc or "unknown"

    # ── Rule 1: AllIn Podcast ZH notes ──────────────────────────────────
    if _is_allin_url(url):
        return SourceProfile(
            url=url,
            normalized_url=normalized,
            provider="allin-podcast-zh-notes",
            domain=domain,
            source_kind=SourceKind.allin_notes_index,
            tracking_supported=True,
            tracking_eligibility=TrackingEligibility.supported,
            confidence=0.95,
            recommended_adapter="allin_zh_notes",
            discovery_strategy="allin_homepage",
            identity_strategy="video_id_or_slug",
            change_detection_strategy="content_hash",
            detected_title="All-In Podcast Chinese Notes",
            suggested_action=SuggestedAction.create_tracked_source,
        )

    # ── Rule 2: RSS/Atom direct URL ─────────────────────────────────────
    if _is_feed_url(url):
        kind = SourceKind.atom_feed if "atom" in url.lower() else SourceKind.rss_feed
        return SourceProfile(
            url=url,
            normalized_url=normalized,
            domain=domain,
            source_kind=kind,
            tracking_supported=False,
            tracking_eligibility=TrackingEligibility.needs_adapter,
            confidence=0.8,
            suggested_action=SuggestedAction.create_adapter_first,
            unsupported_reason="RSS/Atom feeds require a dedicated adapter (not implemented yet).",
            risk_warnings=["本轮不做 RSS 跟踪。可改用单网页导入处理单篇文章。"],
        )

    # ── Rules 3-6 require HTML fetch ────────────────────────────────────
    html = _try_fetch(url)

    if html is None:
        return SourceProfile(
            url=url,
            normalized_url=normalized,
            domain=domain,
            source_kind=SourceKind.unknown,
            tracking_supported=False,
            tracking_eligibility=TrackingEligibility.low_confidence,
            confidence=0.0,
            suggested_action=SuggestedAction.use_single_url_import,
            unsupported_reason="无法访问该 URL，请检查链接是否有效。",
            risk_warnings=["网络请求失败，无法完成页面识别。"],
        )

    # ── Rule 3: HTML feed detection ─────────────────────────────────────
    feed_url = _detect_feed_link(html, url)
    if feed_url:
        return SourceProfile(
            url=url,
            normalized_url=normalized,
            domain=domain,
            source_kind=SourceKind.rss_feed,
            tracking_supported=False,
            tracking_eligibility=TrackingEligibility.needs_adapter,
            confidence=0.75,
            detected_feed_url=feed_url,
            suggested_action=SuggestedAction.create_adapter_first,
            unsupported_reason="页面包含 RSS/Atom feed 链接，但 RSS 跟踪尚未实现。",
            risk_warnings=["本轮不做 RSS 跟踪。"],
        )

    # ── Rule 4: Single article detection ────────────────────────────────
    if _is_single_article(html):
        title = _extract_title(html)
        return SourceProfile(
            url=url,
            normalized_url=normalized,
            domain=domain,
            source_kind=SourceKind.single_article,
            tracking_supported=False,
            tracking_eligibility=TrackingEligibility.unsupported,
            confidence=0.85,
            detected_title=title,
            suggested_action=SuggestedAction.use_single_url_import,
            unsupported_reason="This looks like a single article, not a trackable index page.",
        )

    # ── Rule 5: Generic list page detection ─────────────────────────────
    if _has_list_page_pattern(html):
        title = _extract_title(html)
        return SourceProfile(
            url=url,
            normalized_url=normalized,
            domain=domain,
            source_kind=SourceKind.generic_list_page,
            tracking_supported=False,
            tracking_eligibility=TrackingEligibility.needs_adapter,
            confidence=0.6,
            detected_title=title,
            detected_entry_candidates_count=_count_entry_candidates(html),
            suggested_action=SuggestedAction.create_adapter_first,
            unsupported_reason="页面包含候选条目列表，但没有专用 adapter，无法持续跟踪。",
            risk_warnings=["Generic list pages need a site-specific adapter before tracking."],
        )

    # ── Rule 6: Unknown ─────────────────────────────────────────────────
    return _make_unknown_profile(url, "Could not confidently identify a trackable source structure.")


# ── Helpers ─────────────────────────────────────────────────────────────────


def _is_allin_url(url: str) -> bool:
    url_lower = url.lower()
    return (
        "allin-podcast-zh-notes" in url_lower
        and "chirs-ma.github.io" in url_lower
    )


def _is_feed_url(url: str) -> bool:
    url_lower = url.lower()
    return (
        url_lower.endswith((".xml", ".rss", ".atom"))
        or "/feed" in url_lower
        or "/rss" in url_lower
    )


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}" if parsed.scheme else url.strip()


def _try_fetch(url: str) -> str | None:
    """Fetch HTML from a URL using the adapter's retry engine. Returns None on failure."""
    try:
        from signalvault.adapters.external_html_notes import (
            ExternalHTMLNotesAdapter,
        )
        adapter = ExternalHTMLNotesAdapter(timeout=15, max_retries=1)
        return adapter._fetch_html(url)  # noqa: SLF001
    except Exception:
        logger.warning("Failed to fetch URL for profiling: %s", url, exc_info=True)
        return None


def _detect_feed_link(html: str, base_url: str) -> str | None:
    """Detect RSS/Atom feed link in HTML <head>."""
    import re
    from urllib.parse import urljoin

    pattern = re.compile(
        r'<link\s+[^>]*rel=["\'](?:alternate|feed)["\']'
        r'[^>]*type=["\']application/(?:rss\+xml|atom\+xml)["\']'
        r'[^>]*href=["\']([^"\']+)["\']',
        re.IGNORECASE,
    )
    m = pattern.search(html)
    if not m:
        # Try reversed order (href before type)
        pattern2 = re.compile(
            r'<link\s+[^>]*href=["\']([^"\']+)["\']'
            r'[^>]*type=["\']application/(?:rss\+xml|atom\+xml)["\']',
            re.IGNORECASE,
        )
        m = pattern2.search(html)
    if m:
        return urljoin(base_url, m.group(1))
    return None


def _is_single_article(html: str) -> bool:
    """Heuristic: detects single-article pages."""
    html_lower = html.lower()
    # Strong article signals
    has_article_tag = "<article" in html_lower
    has_og_article = 'og:type" content="article"' in html_lower or \
        "og:type 'content='article'" in html_lower or \
        'property="og:type" content="article"' in html_lower
    has_paragraphs = html_lower.count("<p") >= 3

    # List page counters
    has_article_list = html_lower.count("<article") >= 3
    has_many_h2_links = _count_entry_candidates(html) >= 3

    if has_article_list or has_many_h2_links:
        return False  # likely a list page, not single article

    return (has_article_tag or has_og_article) and has_paragraphs


def _has_list_page_pattern(html: str) -> bool:
    """Heuristic: detects pages with multiple entry candidates."""
    return _count_entry_candidates(html) >= 3


def _count_entry_candidates(html: str) -> int:
    """Count likely entry/article cards on a page."""
    import re
    count = 0
    html_lower = html.lower()
    # Count <article> tags
    count += len(re.findall(r'<article\b', html_lower))
    if count >= 3:
        return count
    # Count <li> with nested <a> + <h2>/<h3> (common list pattern)
    count += len(re.findall(r'<li[^>]*>.*?<a[^>]*>.*?<h[23]', html_lower, re.DOTALL))
    if count >= 3:
        return count
    # Count card-like divs with title+link (class contains "card" or "item")
    count += len(re.findall(r'class=["\'][^"\']*(?:card|item|entry|post)[^"\']*["\']', html_lower))
    return count


def _extract_title(html: str) -> str | None:
    """Extract the <title> from HTML."""
    import re
    m = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    if m:
        title = m.group(1).strip()
        return title[:200] if title else None
    return None


def _make_unknown_profile(url: str, reason: str) -> SourceProfile:
    return SourceProfile(
        url=url or "",
        source_kind=SourceKind.unknown,
        tracking_supported=False,
        tracking_eligibility=TrackingEligibility.low_confidence,
        confidence=0.0,
        suggested_action=SuggestedAction.use_single_url_import,
        unsupported_reason=reason,
    )
