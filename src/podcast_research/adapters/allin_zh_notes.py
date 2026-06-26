"""All-In Podcast 中文可视化笔记 Adapter。

抓取 https://chirs-ma.github.io/allin-podcast-zh-notes/ 站点内容：
- 首页 → episode 列表（title / url / date / slug）
- 单集页面 → 完整结构化内容（核心要点、时间线、人物观点、双语引语）

Site: https://github.com/chirs-ma/allin-podcast-zh-notes (CC0/public implied, no LICENSE file)
Provider: allin-podcast-zh-notes
Source type: external_static_notes / derived / secondary
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from podcast_research.adapters.external_html_notes import (
    ExternalEpisodeEntry,
    ExternalHTMLNotesAdapter,
    FetchErrorResult,
    NormalizedEpisodeSegment,
    NormalizedQuote,
    NormalizedSourceDocument,
    NormalizedSpeakerTurn,
    NormalizedSpeakerViewpoint,
)

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# Site base URL
SITE_BASE = "https://chirs-ma.github.io/allin-podcast-zh-notes/"
RAW_BASE = "https://raw.githubusercontent.com/chirs-ma/allin-podcast-zh-notes/main/"


class AllInZHNotesAdapter(ExternalHTMLNotesAdapter):
    """All-In Podcast 中文可视化笔记 Adapter。

    用法:
        adapter = AllInZHNotesAdapter()
        episodes = adapter.fetch_homepage(SITE_BASE)
        doc = adapter.fetch_episode(f"{SITE_BASE}episodes/slug/notes.visual.html")
    """

    provider_name = "allin-podcast-zh-notes"

    # ── Homepage parsing ───────────────────────────────────────────────────

    def _parse_homepage(self, html: str, base_url: str = "") -> list[ExternalEpisodeEntry]:
        """Parse index.html → list of episode entries.

        Each episode is an <a class="episode-card"> inside <div class="episode-list">.
        """
        soup = self._parse_html(html)
        container = soup.find("div", class_="episode-list")
        if not container:
            logger.warning("No episode-list div found in homepage HTML")
            return []

        entries: list[ExternalEpisodeEntry] = []
        for card in container.find_all("a", class_="episode-card"):
            entry = self._parse_homepage_card(card, base_url)
            if entry and entry.url:
                entries.append(entry)

        logger.info("Homepage parsed: %d episodes", len(entries))
        return entries

    def _parse_homepage_card(self, card: "Tag", base_url: str = "") -> ExternalEpisodeEntry | None:
        """Parse a single <a class="episode-card"> into ExternalEpisodeEntry."""
        href = card.get("href", "")
        if isinstance(href, list):
            href = href[0] if href else ""
        href = str(href).strip()

        title_el = card.find("h2", class_="episode-title")
        date_el = card.find("span", class_="episode-date")

        title = self._clean_text(title_el.get_text(strip=True) if title_el else "")
        date = self._clean_text(date_el.get_text(strip=True) if date_el else "")
        date = self._parse_date(date)

        # Resolve relative URL
        full_url = urljoin(base_url, href) if base_url else href
        slug = self._slug_from_url(href)

        return ExternalEpisodeEntry(
            title=title,
            url=full_url,
            date=date,
            slug=slug,
            video_id="",  # not on homepage
        )

    # ── Episode parsing ───────────────────────────────────────────────────

    def _parse_episode(self, html: str, url: str) -> NormalizedSourceDocument:
        """Parse a single episode page → NormalizedSourceDocument."""
        soup = self._parse_html(html)

        # ── Hero / metadata ──────────────────────────────────────────────
        hero = soup.find("header", class_="hero")
        title = ""
        generated_at = ""
        youtube_url = ""
        reading_time = ""
        summary = ""

        if hero:
            h1 = hero.find("h1")
            title = self._clean_text(h1.get_text(strip=True)) if h1 else ""

            # Meta: 生成时间 + YouTube 链接
            meta_div = hero.find("div", class_="meta")
            if meta_div:
                for span in meta_div.find_all("span"):
                    text = span.get_text(strip=True)
                    if "生成时间" in text:
                        generated_at = text.replace("生成时间：", "").replace("生成时间:", "").strip()
                    elif "来源" in text:
                        a_tag = span.find("a")
                        if a_tag and a_tag.get("href"):
                            youtube_url = str(a_tag["href"]).strip()

                # Also check for YouTube link outside span
                source_link = meta_div.find("a", href=re.compile(r"youtube\.com|youtu\.be"))
                if source_link and not youtube_url:
                    youtube_url = str(source_link["href"]).strip()

            # Meta strip: reading time, etc.
            meta_strip = hero.find("div", class_="meta-strip")
            if meta_strip:
                for pill in meta_strip.find_all("span", class_="meta-pill"):
                    text = pill.get_text(strip=True)
                    if "分钟" in text or "阅读" in text:
                        b_tag = pill.find("b")
                        if b_tag:
                            minutes = b_tag.get_text(strip=True)
                            # Avoid double "分钟": if the <b> already contains it, use as-is
                            if "分钟" in minutes:
                                reading_time = minutes
                            else:
                                reading_time = f"{minutes} 分钟"
                        else:
                            reading_time = text

            # Summary
            summary_div = hero.find("div", class_="summary")
            if summary_div:
                p_tag = summary_div.find("p")
                if p_tag:
                    summary = self._clean_text(p_tag.get_text(strip=True))

        # ── Key points (#takeaways) ──────────────────────────────────────
        key_points = self._parse_key_points(soup)

        # ── Timeline (#timeline) ─────────────────────────────────────────
        timeline = self._parse_timeline(soup)

        # ── Speaker viewpoints (#speakers) ───────────────────────────────
        speaker_viewpoints = self._parse_speakers(soup)

        # ── Bilingual quotes (#quotes) ───────────────────────────────────
        bilingual_quotes = self._parse_quotes(soup)

        # ── Video ID extraction ──────────────────────────────────────────
        video_id = self._extract_video_id_from_url(youtube_url)

        slug = self._slug_from_url(url)

        # ── Build document ───────────────────────────────────────────────
        doc = NormalizedSourceDocument(
            provider=self.provider_name,
            source_type="derived",
            source_confidence="secondary",
            source_url=url,
            original_source_url=youtube_url,
            slug=slug,
            title=title,
            generated_at=generated_at,
            reading_time=reading_time,
            summary=summary,
            youtube_video_id=video_id,
            key_points=key_points,
            timeline=timeline,
            speaker_viewpoints=speaker_viewpoints,
            bilingual_quotes=bilingual_quotes,
        )
        return doc

    # ── Section parsers ────────────────────────────────────────────────────

    def _parse_key_points(self, soup: "BeautifulSoup") -> list[str]:
        """Parse <section id="takeaways"> → list of key point strings (1-indexed)."""
        section = soup.find("section", id="takeaways")
        if not section:
            return []

        points: list[str] = []
        for li in section.find_all("li", class_="takeaway"):
            p_tag = li.find("p")
            if p_tag:
                text = self._clean_text(p_tag.get_text(strip=True))
                if text:
                    points.append(text)

        return points

    def _parse_timeline(self, soup: "BeautifulSoup") -> list[NormalizedEpisodeSegment]:
        """Parse <section id="timeline"> → list of NormalizedEpisodeSegment."""
        section = soup.find("section", id="timeline")
        if not section:
            return []

        segments: list[NormalizedEpisodeSegment] = []
        for card in section.find_all("article", class_="timeline-card"):
            seg = self._parse_timeline_card(card)
            if seg:
                segments.append(seg)

        return segments

    def _parse_timeline_card(self, card: "Tag") -> NormalizedEpisodeSegment | None:
        """Parse a single <article class="timeline-card">."""
        # Index
        index_el = card.find("span", class_="timeline-index")
        index = int(index_el.get_text(strip=True)) if index_el else 0

        # Time range
        meta_el = card.find("span", class_="timeline-meta")
        time_range = self._clean_text(meta_el.get_text(strip=True)) if meta_el else ""

        # Section title
        body = card.find("div", class_="timeline-body")
        title = ""
        if body:
            h3 = body.find("h3")
            title = self._clean_text(h3.get_text(strip=True)) if h3 else ""

        # Content sections
        content_div = card.find("div", class_="section-content")
        core_points: list[str] = []
        background_terms: list[dict] = []
        speaker_turns: list[NormalizedSpeakerTurn] = []

        if content_div:
            # Iterate through children in order
            current_section = ""
            for child in content_div.children:
                if not hasattr(child, "name"):
                    continue

                tag_name = child.name
                text = self._clean_text(child.get_text(strip=True)) if hasattr(child, "get_text") else ""

                if tag_name == "h4":
                    text_lower = text.lower() if text else ""
                    if "核心内容" in text_lower or "core" in text_lower:
                        current_section = "core"
                    elif "背景" in text_lower or "术语" in text_lower or "term" in text_lower:
                        current_section = "terms"
                    elif "详细" in text_lower or "整理" in text_lower or "detail" in text_lower:
                        current_section = "transcript"
                    else:
                        current_section = ""

                elif tag_name == "ul" and current_section == "core":
                    for li in child.find_all("li"):
                        pt = self._clean_text(li.get_text(strip=True))
                        if pt:
                            core_points.append(pt)

                elif tag_name == "ul" and current_section == "terms":
                    for li in child.find_all("li"):
                        full_text = self._clean_text(li.get_text(strip=True))
                        if full_text:
                            # Try to split term: definition (common format)
                            parts = full_text.split("：", 1) if "：" in full_text else full_text.split(":", 1)
                            if len(parts) == 2:
                                background_terms.append({"term": parts[0].strip(), "definition": parts[1].strip()})
                            else:
                                background_terms.append({"term": full_text, "definition": ""})

                elif tag_name == "p" and current_section == "transcript":
                    # Speaker turns: <p><strong>Speaker:</strong> text</p>
                    strong = child.find("strong")
                    if strong:
                        speaker = self._clean_text(strong.get_text(strip=True)).rstrip("：:")
                        turn_text = self._clean_text(child.get_text(strip=True))
                        # Remove speaker prefix if duplicated
                        prefix = strong.get_text(strip=True)
                        if turn_text.startswith(prefix):
                            turn_text = turn_text[len(prefix):].lstrip("：: ")
                        speaker_turns.append(NormalizedSpeakerTurn(
                            speaker_name=speaker,
                            text=turn_text,
                        ))
                    else:
                        # Plain paragraph — might be narration
                        pt = self._clean_text(child.get_text(strip=True))
                        if pt:
                            speaker_turns.append(NormalizedSpeakerTurn(
                                speaker_name="(旁白)",
                                text=pt,
                            ))

        return NormalizedEpisodeSegment(
            index=index,
            title=title,
            time_range=time_range,
            core_points=core_points,
            background_terms=background_terms,
            speaker_turns=speaker_turns,
        )

    def _parse_speakers(self, soup: "BeautifulSoup") -> list[NormalizedSpeakerViewpoint]:
        """Parse <section id="speakers"> → list of NormalizedSpeakerViewpoint."""
        section = soup.find("section", id="speakers")
        if not section:
            return []

        viewpoints: list[NormalizedSpeakerViewpoint] = []
        for card in section.find_all("article", class_="speaker-card"):
            kicker = card.find("p", class_="speaker-kicker")
            role = self._clean_text(kicker.get_text(strip=True)) if kicker else ""

            h3 = card.find("h3")
            name = self._clean_text(h3.get_text(strip=True)) if h3 else ""

            # Viewpoint paragraph — inside the div after h3
            vp_div = card.find("div")
            vp_text = ""
            if vp_div:
                p_tag = vp_div.find("p")
                if p_tag:
                    vp_text = self._clean_text(p_tag.get_text(strip=True))

            if name:
                viewpoints.append(NormalizedSpeakerViewpoint(
                    name=name,
                    role=role,
                    viewpoint=vp_text,
                ))

        return viewpoints

    def _parse_quotes(self, soup: "BeautifulSoup") -> list[NormalizedQuote]:
        """Parse <section id="quotes"> → list of NormalizedQuote."""
        section = soup.find("section", id="quotes")
        if not section:
            return []

        panel = section.find("div", class_="panel")
        if not panel:
            return []

        quotes: list[NormalizedQuote] = []
        for ol in panel.find_all("ol"):
            li = ol.find("li")
            if not li:
                continue
            strong = li.find("strong")
            text_en = self._clean_text(strong.get_text(strip=True)) if strong else self._clean_text(li.get_text(strip=True))

            # The <p> with Chinese translation is a sibling of <ol>, not a child.
            # Structure: <ol>...</ol> <p>中文：... 说明：...</p>
            next_p = ol.find_next_sibling("p")
            text_zh = ""
            context_note = ""
            if next_p:
                full = self._clean_text(next_p.get_text(strip=True))
                # Split: "中文：xxx 说明：yyy"
                zh_match = re.search(r"中文[：:](.*?)(?:说明[：:]|$)", full)
                if zh_match:
                    text_zh = zh_match.group(1).strip()
                note_match = re.search(r"说明[：:](.*)", full)
                if note_match:
                    context_note = note_match.group(1).strip()

            if text_en:
                quotes.append(NormalizedQuote(
                    text_en=text_en,
                    text_zh=text_zh,
                    context_note=context_note,
                ))

        return quotes

    # ── Convenience method ──────────────────────────────────────────────────

    def fetch_all(
        self, base_url: str = SITE_BASE,
    ) -> tuple[list[ExternalEpisodeEntry], list[NormalizedSourceDocument], list[FetchErrorResult]]:
        """Fetch homepage + all episode pages. Use sparingly (rate limit aware).

        Single episode failures do NOT abort the batch — they are recorded
        in the errors list and the remaining episodes continue.

        Returns:
            (episode_entries, successful_documents, fetch_errors)
        """
        entries = self.fetch_homepage(base_url)
        docs: list[NormalizedSourceDocument] = []
        errors: list[FetchErrorResult] = []

        for entry in entries:
            try:
                doc = self.fetch_episode(entry.url)
                docs.append(doc)
                logger.info("Fetched episode: %s", entry.title[:50])
            except Exception as e:
                error_category = self._classify_error(e)
                error_result = FetchErrorResult(
                    url=entry.url,
                    error_category=error_category,
                    error_message=str(e)[:200],
                    slug=entry.slug,
                    title=entry.title,
                )
                errors.append(error_result)
                logger.warning(
                    "Failed to fetch episode '%s': [%s] %s",
                    entry.title[:50], error_category, e,
                )

        return entries, docs, errors
