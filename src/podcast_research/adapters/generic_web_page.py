"""P2-S.3.1: GenericWebPageAdapter — parse arbitrary web pages.

Reuses the P2-S.2.2 retry engine from ExternalHTMLNotesAdapter.
Never crashes on malformed HTML — always returns a degraded ParsedWebPage.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from podcast_research.adapters.external_html_notes import ExternalHTMLNotesAdapter

if TYPE_CHECKING:
    from bs4 import Tag

logger = logging.getLogger(__name__)


@dataclass
class ParsedWebPage:
    """Output of GenericWebPageAdapter.fetch_page()."""
    title: str = ""
    meta_description: str = ""
    canonical_url: str = ""
    h1_texts: list[str] = field(default_factory=list)
    h2_texts: list[str] = field(default_factory=list)
    h3_texts: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    detected_youtube_urls: list[str] = field(default_factory=list)
    content_hash: str = ""
    summary: str = ""
    parse_quality: str = "good"     # "good", "degraded", "minimal"
    raw_text_length: int = 0
    content_blocks_count: int = 0
    error: str = ""


class GenericWebPageAdapter(ExternalHTMLNotesAdapter):
    """Adapter for parsing arbitrary web pages into ParsedWebPage.

    Inherits retry engine, error classification, HTML parsing, and utility
    methods from ExternalHTMLNotesAdapter. Adds fetch_page() → ParsedWebPage.
    """

    provider_name = "generic_web_page"

    # ── Public API ───────────────────────────────────────────────────────

    def fetch_page(self, url: str) -> ParsedWebPage:
        """Fetch and parse a generic web page. Never raises on parse errors.

        Returns a ParsedWebPage even if fetch/parse completely fails —
        parse_quality will be "minimal" with error details.
        """
        try:
            html = self._fetch_html(url)
        except Exception as e:
            return ParsedWebPage(
                title=url,
                parse_quality="minimal",
                error=str(e)[:200],
            )
        return self._parse_page(html, url)

    # ── Parsing ──────────────────────────────────────────────────────────

    def _parse_page(self, html: str, url: str) -> ParsedWebPage:
        """Parse HTML into ParsedWebPage. All exceptions caught internally."""
        try:
            soup = self._parse_html(html)
        except Exception:
            return ParsedWebPage(
                title=url,
                parse_quality="minimal",
                raw_text_length=len(html),
                error="HTML parse failed",
            )

        content_hash = hashlib.sha256(
            html.encode("utf-8", errors="replace")
        ).hexdigest()

        result = ParsedWebPage(
            content_hash=content_hash,
            raw_text_length=len(html),
        )
        populated = 0

        try:
            # ── Title ─────────────────────────────────────────────────
            if soup.title and soup.title.string:
                result.title = self._clean_text(str(soup.title.string))
                populated += 1

            # ── Canonical URL ─────────────────────────────────────────
            canon = soup.find("link", rel="canonical")
            if canon and canon.get("href"):
                result.canonical_url = str(canon["href"])

            # ── Meta description ──────────────────────────────────────
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                result.meta_description = self._clean_text(
                    str(meta_desc["content"])
                )
                populated += 1

            # ── Headings ──────────────────────────────────────────────
            for tag_name, _attr in [
                ("h1", "h1_texts"), ("h2", "h2_texts"), ("h3", "h3_texts"),
            ]:
                for el in soup.find_all(tag_name):
                    if self._is_content_element(el):
                        text = self._clean_text(el.get_text())
                        if text and len(text) > 1:
                            getattr(result, _attr).append(text)

            # ── Paragraphs ────────────────────────────────────────────
            for p in soup.find_all("p"):
                if self._is_content_element(p):
                    text = self._clean_text(p.get_text())
                    if text and len(text) > 10:
                        result.paragraphs.append(text)

            # ── YouTube URLs ──────────────────────────────────────────
            yt_re = re.compile(
                r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)"
                r"([a-zA-Z0-9_-]{11})"
            )
            for a in soup.find_all("a", href=True):
                href = str(a["href"])
                if yt_re.search(href) and href not in result.detected_youtube_urls:
                    result.detected_youtube_urls.append(href)

            # ── Summary ───────────────────────────────────────────────
            result.summary = result.meta_description or (
                result.paragraphs[0] if result.paragraphs else ""
            )

            # ── Parse quality ─────────────────────────────────────────
            total_blocks = (
                len(result.h1_texts) + len(result.h2_texts)
                + len(result.h3_texts) + len(result.paragraphs)
            )
            result.content_blocks_count = total_blocks

            if populated == 0 and total_blocks == 0:
                result.parse_quality = "minimal"
            elif total_blocks < 3:
                result.parse_quality = "degraded"
            else:
                result.parse_quality = "good"

        except Exception as e:
            result.parse_quality = "minimal"
            if not result.error:
                result.error = str(e)[:200]

        return result

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _is_content_element(el: "Tag") -> bool:
        """Exclude elements inside nav, footer, header, script, style."""
        excluded = {"nav", "footer", "header", "script", "style", "noscript"}
        parent = el.parent
        while parent is not None:
            if hasattr(parent, "name") and parent.name in excluded:
                return False
            parent = parent.parent if hasattr(parent, "parent") else None
        return True
