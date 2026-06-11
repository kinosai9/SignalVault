"""P2-M.4: Watchlist Matcher — deterministic video-to-watchlist matching.

No LLM, no external APIs. Pure substring / normalized string matching against
the user's Watchlist.yaml (companies, topics, themes).

Used by the video list page to surface "推荐整理" badges.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from podcast_research.workspace.watchlist import (
    COMPANY_ALIAS_MAP,
    THEME_TOPIC_MAP,
    WatchlistConfig,
)


def _normalize(text: str) -> str:
    """Normalize for fuzzy matching: lowercase, remove punctuation/spaces."""
    t = text.lower().strip()
    t = re.sub(r"[\s\-/_.（）()【】\[\]「」『』]", "", t)
    return t


@dataclass
class MatchResult:
    """Result of matching a video against the watchlist."""

    matched: bool = False
    matched_terms: list[str] = field(default_factory=list)
    matched_type: str = ""  # company / topic / theme
    reason: str = ""


def match_video_to_watchlist(
    title: str,
    watchlist: WatchlistConfig,
    description: str = "",
) -> MatchResult:
    """Match a video title/description against the user's watchlist.

    Matching strategy (deterministic, no LLM):
        1. Company: exact name → alias map lookup → normalized substring match
        2. Topic: exact name → normalized substring match
        3. Theme: exact name → check if any related_topic appears in title

    Returns MatchResult with matched=True if any watchlist item matches.
    """
    search_text = title
    if description:
        search_text = f"{title} {description}"

    # ── 1. Check companies ──
    for company in watchlist.companies:
        if _match_company(company, search_text):
            return MatchResult(
                matched=True,
                matched_terms=[company],
                matched_type="company",
                reason=f"视频标题命中关注公司「{company}」",
            )

    # ── 2. Check topics ──
    for topic in watchlist.topics:
        if _match_topic(topic, search_text):
            return MatchResult(
                matched=True,
                matched_terms=[topic],
                matched_type="topic",
                reason=f"视频标题命中关注主题「{topic}」",
            )

    # ── 3. Check themes — match if any related_topic appears ──
    for theme in watchlist.themes:
        match_result = _match_theme(theme, search_text)
        if match_result:
            return match_result

    return MatchResult()


def _match_company(name: str, text: str) -> bool:
    """Check if a company name appears in the text.

    Steps:
        1. Exact case-insensitive match
        2. Alias map lookup + match (e.g. "英伟达" → "NVIDIA")
        3. Normalized substring (strip punctuation, spaces)
    """
    # Exact match
    if name.lower() in text.lower():
        return True

    # Alias match
    normalized_name = _normalize(name)
    aliases_to_try = {name, normalized_name}

    # Add known aliases
    for alias, canonical in COMPANY_ALIAS_MAP.items():
        if _normalize(canonical) == normalized_name:
            aliases_to_try.add(alias)
            aliases_to_try.add(_normalize(alias))

    normalized_text = _normalize(text)

    for alias in aliases_to_try:
        if alias in text.lower() or alias in normalized_text:
            return True

    return False


def _match_topic(name: str, text: str) -> bool:
    """Check if a topic name appears in the text.

    Uses case-insensitive substring and normalized matching.
    Also checks topic alias map from taxonomy.
    """
    # Exact match
    if name.lower() in text.lower():
        return True

    # Normalized match
    norm_name = _normalize(name)
    norm_text = _normalize(text)
    if norm_name in norm_text:
        return True

    # Check taxonomy alias map
    try:
        from podcast_research.llm_wiki.taxonomy import TOPIC_CANONICAL_MAP
        # Check if any alias of this canonical topic matches
        for alias, canonical in TOPIC_CANONICAL_MAP.items():
            if _normalize(canonical) == norm_name:
                norm_alias = _normalize(alias)
                if norm_alias in norm_text:
                    return True
    except ImportError:
        pass

    return False


def _match_theme(name: str, text: str) -> MatchResult | None:
    """Check if a theme matches via its related_topics.

    A theme matches if any of its related topics appear in the title.
    """
    if name not in THEME_TOPIC_MAP:
        return None

    related = THEME_TOPIC_MAP[name]
    matched_topics = []

    for topic in related:
        if _match_topic(topic, text):
            matched_topics.append(topic)

    if matched_topics:
        return MatchResult(
            matched=True,
            matched_terms=matched_topics,
            matched_type="theme",
            reason=f"视频命中关注方向「{name}」(关联主题: {', '.join(matched_topics[:3])})",
        )

    return None


def compute_recommendation(
    import_status: str,
    watchlist_match: MatchResult | None,
    duration_seconds: int = 0,
) -> list[str]:
    """Compute recommendation badges for a video.

    Returns a list of badge strings to display.
    """
    badges: list[str] = []

    # Recommendation badge: new + watchlist match
    if import_status == "new" and watchlist_match and watchlist_match.matched:
        badges.append("recommended")  # 推荐整理

    # Long video badge: > 90 minutes
    if duration_seconds > 90 * 60:
        badges.append("long_video")  # 长视频，预计耗时较长

    return badges
