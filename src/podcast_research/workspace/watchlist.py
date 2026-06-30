"""P2-J.2: Watchlist Brief generator.

Reads 99_System/Watchlist.yaml, generates per-item brief from WorkspaceSnapshot.
No LLM, no external APIs. Pure deterministic rules.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from podcast_research.utils.file_io import read_text_safe
from podcast_research.workspace.scanner import WorkspaceSnapshot

logger = logging.getLogger(__name__)

WATCHLIST_YAML = "Watchlist.yaml"

# ── Alias / fuzzy maps ────────────────────────────────────────────

COMPANY_ALIAS_MAP: dict[str, str] = {
    # 中英文常见别名 → 官方名称
    "open ai": "OpenAI", "英伟达": "NVIDIA", "nividia": "NVIDIA",
    "nivdia": "NVIDIA", "nvidia corporation": "NVIDIA",
    "google": "Alphabet", "谷歌": "Alphabet", "google inc": "Alphabet",
    "meta ai": "Meta", "facebook": "Meta", "微软": "Microsoft",
    "台积电": "TSMC", "tsm": "TSMC",
    "core weave": "CoreWeave", "coreweave": "CoreWeave",
    "vercel ai": "Vercel", "anthropic ai": "Anthropic",
    "mistral ai": "Mistral", "shopify commerce": "Shopify",
    "salesforce crm": "Salesforce", "zendesk support": "Zendesk",
    "blackrock investment": "BlackRock", "vanguard group": "Vanguard",
    "perplexity ai": "Perplexity",
    "amazon web services": "Amazon", "aws": "Amazon",
    "deep seek": "DeepSeek", "deepseek ai": "DeepSeek",
    "apple inc": "Apple", "intel corporation": "Intel",
    "amd inc": "AMD", "advanced micro devices": "AMD",
    "tesla inc": "Tesla", "spacex exploration": "SpaceX",
    "oracle corporation": "Oracle", "palantir technologies": "Palantir",
    "cloudflare inc": "Cloudflare", "databricks inc": "Databricks",
    "anthropic ai safety": "Anthropic",
}

THEME_TOPIC_MAP: dict[str, list[str]] = {
    "Agent 工具链": ["AI Agents", "Developer Tools", "Model Context Protocol"],
    "企业级 AI 应用": ["Enterprise AI", "AI Applications", "AI Safety & Security"],
    "算力基础设施": ["AI Infrastructure", "Semiconductor", "Data Center", "Cloud"],
    "AI 应用层": ["AI Applications", "Enterprise AI", "Business Model"],
    "AI 模型与算法": ["AI Models", "AI for Science", "AI Safety & Security"],
    "投资与资本市场": ["Public Markets", "Valuation", "Investment Framework"],
}


def _normalize(text: str) -> str:
    """Normalize for fuzzy matching: lowercase, remove spaces/hyphens/slashes/punctuation."""
    import re
    t = text.lower().strip()
    t = re.sub(r'[\s\-/_.]', '', t)
    return t


def resolve_watchlist_name(
    name: str,
    item_type: str,
    known_companies: set[str],
    known_topics: set[str],
) -> dict:
    """Resolve a watchlist entry name to canonical form.

    Returns dict with: canonical_name, match_status, card_path, related_topics, message
    """
    result = {
        "canonical_name": name,
        "match_status": "missing",
        "card_path": "",
        "related_topics": [],
        "message": "",
    }

    candidates = known_companies if item_type == "company" else known_topics
    cand_label = "公司" if item_type == "company" else "主题"

    # 1. Exact match
    if name in candidates:
        result["match_status"] = "linked"
        result["canonical_name"] = name
        result["message"] = f"已关联知识卡「{name}」"
        return result

    # 2. Alias match (company or topic)
    alias_map = COMPANY_ALIAS_MAP if item_type == "company" else {}
    from podcast_research.llm_wiki.taxonomy import TOPIC_CANONICAL_MAP
    if item_type == "topic":
        alias_map = {k: v for k, v in TOPIC_CANONICAL_MAP.items()}

    name_lower = name.lower().strip()
    if name_lower in alias_map:
        canonical = alias_map[name_lower]
        if canonical in candidates:
            result["match_status"] = "alias"
            result["canonical_name"] = canonical
            result["message"] = f"已将「{name}」识别为「{canonical}」"
            return result

    # 3. Fuzzy match
    norm_input = _normalize(name)
    for cand in candidates:
        if _normalize(cand) == norm_input:
            result["match_status"] = "fuzzy"
            result["canonical_name"] = cand
            result["message"] = f"已将「{name}」匹配到「{cand}」"
            return result

    # Also fuzzy-check alias map keys
    for alias_key, canonical in alias_map.items():
        if _normalize(alias_key) == norm_input and canonical in candidates:
            result["match_status"] = "alias"
            result["canonical_name"] = canonical
            result["message"] = f"已将「{name}」识别为「{canonical}」"
            return result

    # 4. Theme resolution
    if item_type == "theme":
        if name in THEME_TOPIC_MAP:
            result["related_topics"] = THEME_TOPIC_MAP[name]
            result["message"] = f"已关联 {len(result['related_topics'])} 个相关主题"
        else:
            result["message"] = "已作为自定义关注方向保留"
        result["match_status"] = "custom"
        return result

    # 5. Missing
    result["message"] = f"未找到对应{cand_label}知识卡，将保留为弱关注对象"
    return result


def get_suggested_companies(snapshot) -> list[str]:
    """Suggest companies for watchlist from filtered core companies.

    Uses the same _NOT_A_COMPANY + entity_type filtering as core_companies()
    to avoid suggesting non-company entities like products, models, concepts.
    """
    from podcast_research.llm_wiki.context_builder import HIGH_VALUE_COMPANIES
    suggestions = []
    # P2-N.4.4.1: Use filtered core_companies() instead of raw snapshot.companies
    for c in snapshot.core_companies():
        claims_n = snapshot.claims_count_for(c.name)
        signals_n = snapshot.signals_count_for(c.name)
        score = claims_n * 2 + signals_n * 3 + len(c.source_reports)
        if score > 0 or c.name in HIGH_VALUE_COMPANIES:
            suggestions.append((c.name, score))
    suggestions.sort(key=lambda x: x[1], reverse=True)
    return [name for name, _ in suggestions[:10]]


def get_suggested_topics(snapshot) -> list[str]:
    """Suggest topics for watchlist from filtered core topics only.

    Excludes generic/non-topic names already filtered by core_topics().
    """
    scored = []
    # P2-N.4.4.1: Only suggest from core_topics(), not raw snapshot.topics
    for t in snapshot.core_topics():
        score = snapshot.claims_count_for(t.name) * 2 + snapshot.signals_count_for(t.name) * 1.5
        if score > 0 or t.status == "core":
            scored.append((t.name, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [name for name, _ in scored[:10]]
DEFAULT_WATCHLIST = """# 关注对象配置 — 填写你关注的公司、主题、方向
# 修改后运行"更新知识库"即可在首页和 /watchlist 看到更新

companies:
  - OpenAI
  - NVIDIA

topics:
  - AI Agents
  - Enterprise AI

themes:
  - Agent 工具链
  - 企业级 AI 应用
"""


@dataclass
class WatchlistConfig:
    companies: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)


@dataclass
class WatchlistItemBrief:
    name: str
    item_type: str  # company / topic / theme
    direct_count: int = 0
    indirect_count: int = 0
    observation_count: int = 0
    reinforced_count: int = 0
    direct_items: list[str] = field(default_factory=list)
    indirect_items: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    reinforced: list[str] = field(default_factory=list)
    status: str = "no_new_evidence"  # direct / indirect / no_new_evidence
    summary: str = ""
    card_exists: bool = True
    context_topics: list[str] = field(default_factory=list)  # P2-N.4.3.2: topics discussed for companies


def load_watchlist(vault_path: Path) -> WatchlistConfig:
    """Load watchlist from 99_System/Watchlist.yaml. Auto-corrects known aliases.

    Returns empty config if missing.
    """
    path = vault_path / "99_System" / WATCHLIST_YAML
    if not path.exists():
        return WatchlistConfig()
    try:
        content = read_text_safe(path)
        config = _parse_watchlist_yaml(content)
        # Auto-correct known company aliases
        corrected = False
        for i, name in enumerate(config.companies):
            name_lower = name.lower()
            if name_lower in COMPANY_ALIAS_MAP:
                canonical = COMPANY_ALIAS_MAP[name_lower]
                if canonical != name:
                    config.companies[i] = canonical
                    corrected = True
                    logger.info("Watchlist: auto-corrected '%s' → '%s'", name, canonical)
        if corrected:
            # Deduplicate after correction
            seen = set()
            unique = []
            for c in config.companies:
                if c not in seen:
                    seen.add(c)
                    unique.append(c)
            config.companies = unique
            save_watchlist(vault_path, config)
        return config
    except Exception:
        logger.warning("Failed to parse Watchlist.yaml, using empty config")
        return WatchlistConfig()


def ensure_watchlist_template(vault_path: Path) -> Path:
    """Create Watchlist.yaml template if it doesn't exist."""
    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    path = system_dir / WATCHLIST_YAML
    if not path.exists():
        path.write_text(DEFAULT_WATCHLIST, encoding="utf-8")
    return path


def _parse_watchlist_yaml(content: str) -> WatchlistConfig:
    """Simple YAML parser for watchlist config — flat lists only."""
    config = WatchlistConfig()
    current_key = ""
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if stripped.endswith(":"):
            current_key = stripped[:-1].strip()
            continue
        if stripped.startswith("- ") and current_key:
            value = stripped[2:].strip().strip('"').strip("'")
            if current_key == "companies":
                config.companies.append(value)
            elif current_key == "topics":
                config.topics.append(value)
            elif current_key == "themes":
                config.themes.append(value)
    return config


def generate_watchlist_brief(
    snapshot: WorkspaceSnapshot,
    vault_path: Path,
) -> list[WatchlistItemBrief]:
    """Generate per-item watchlist brief from vault snapshot."""
    from podcast_research.workspace.canonical_view import (
        build_canonical_claim_views,
        build_canonical_signal_views,
    )

    config = load_watchlist(vault_path)
    items: list[WatchlistItemBrief] = []

    # Build lookup maps
    topic_names = {t.name for t in snapshot.topics}
    company_names = {c.name for c in snapshot.companies}
    core_topic_names = {t.name for t in snapshot.core_topics()}
    active_topic_names = _get_active_topic_names(snapshot)

    # Pre-compute canonical views once (expensive, ~0.4s each)
    # Formerly called per-item inside _build_item_brief and
    # build_watchlist_evidence (9 items × 2 views = ~7s wasted)
    canonical_views = build_canonical_claim_views(snapshot)
    signal_views = build_canonical_signal_views(snapshot)

    # Process companies
    for name in config.companies:
        resolved = resolve_watchlist_name(name, "company", company_names, topic_names)
        search_name = resolved["canonical_name"]
        item = _build_item_brief(
            search_name, "company", snapshot, topic_names, company_names,
            core_topic_names, active_topic_names, canonical_views, signal_views,
        )
        item.name = name  # Show original user input
        if resolved["match_status"] == "missing":
            item.card_exists = False
        items.append(item)

    # Process topics
    for name in config.topics:
        resolved = resolve_watchlist_name(name, "topic", company_names, topic_names)
        search_name = resolved["canonical_name"]
        item = _build_item_brief(
            search_name, "topic", snapshot, topic_names, company_names,
            core_topic_names, active_topic_names, canonical_views, signal_views,
        )
        item.name = name
        if resolved["match_status"] == "missing":
            item.card_exists = False
        items.append(item)

    # Process themes (use related_topics for indirect matching)
    for name in config.themes:
        resolved = resolve_watchlist_name(name, "theme", company_names, topic_names)
        item = WatchlistItemBrief(name=name, item_type="theme")
        if resolved["related_topics"]:
            # Check indirect relevance through related topics
            active_related = [t for t in resolved["related_topics"] if t in active_topic_names]
            if active_related:
                item.status = "indirect"
                item.summary = f"方向「{name}」关联的 {len(active_related)} 个主题近期活跃"
                item.indirect_count = len(active_related)
                item.indirect_items = [f"关联升温主题: {t}" for t in active_related[:3]]
            else:
                item.status = "no_new_evidence"
                item.summary = f"方向「{name}」关联的主题暂无新增内容。"
        else:
            item.status = "no_new_evidence"
            item.summary = f"方向「{name}」已作为自定义关注方向保留。"
        items.append(item)

    return items


def _build_item_brief(
    name: str,
    item_type: str,
    snapshot: WorkspaceSnapshot,
    topic_names: set[str],
    company_names: set[str],
    core_topic_names: set[str],
    active_topic_names: set[str],
    canonical_views: list | None = None,
    signal_views: list | None = None,
) -> WatchlistItemBrief:
    """Build brief for a single watchlist item.

    P2-N.4.4.2: Uses canonical_view.build_watchlist_evidence() for unified
    dedup across all sections (direct/indirect/reinforced/observations).

    canonical_views / signal_views: Pre-computed from
        build_canonical_claim_views() and build_canonical_signal_views().
        Pass from generate_watchlist_brief() to avoid recomputing per-item.
    """
    from podcast_research.workspace.canonical_view import build_watchlist_evidence

    item = WatchlistItemBrief(name=name, item_type=item_type)

    # Check card exists
    if item_type == "company":
        item.card_exists = name in company_names
    elif item_type == "topic":
        item.card_exists = name in topic_names

    # Build unified evidence view (all sections share one dedup set)
    ev = build_watchlist_evidence(
        snapshot, name, item_type,
        claim_views=canonical_views,
        signal_views=signal_views,
    )

    # Populate item from evidence view
    item.direct_items = ev.direct_claims[:3] + ev.direct_signals[:3]
    item.direct_count = ev.direct_count
    item.indirect_items = ev.indirect_items[:3]
    item.indirect_count = ev.indirect_count
    item.reinforced = ev.reinforced[:3]
    item.reinforced_count = ev.reinforced_count
    item.observations = ev.observations[:5]
    item.observation_count = ev.observation_count

    # P2-N.4.3.2: Extract context topics for company items
    if item_type == "company" and canonical_views is not None:
        context_topics_set: set[str] = set()
        for cv in canonical_views:
            if name in cv.related_companies:
                for t in cv.related_topics:
                    context_topics_set.add(t)
        item.context_topics = sorted(context_topics_set)[:5]

    # Status
    if item.direct_count > 0:
        item.status = "direct"
    elif item.indirect_count > 0:
        item.status = "indirect"
    else:
        item.status = "no_new_evidence"

    # Summary
    item.summary = _build_item_summary(item)

    return item


def _get_active_topic_names(snapshot: WorkspaceSnapshot) -> set[str]:
    """Topics with claims or signals."""
    names = set()
    for t in snapshot.topics:
        if snapshot.claims_count_for(t.name) > 0 or snapshot.signals_count_for(t.name) > 0:
            names.add(t.name)
    return names


def _build_item_summary(item: WatchlistItemBrief) -> str:
    """Build natural language summary for a watchlist item.

    P2-N.4.3.2: Adds topic context to company items — what subjects
    are driving the discussion around this company.
    """
    if not item.card_exists:
        return "未找到对应知识卡片，建议先分析相关报告。"

    if item.status == "direct":
        parts = []
        # P2-N.4.3.2: Topic context for companies
        if item.item_type == "company" and item.context_topics:
            topics_str = "、".join(item.context_topics[:3])
            if topics_str:
                parts.append(f"围绕 {topics_str} 等方向")
        if item.direct_count > 0:
            parts.append(f"本轮有 {item.direct_count} 条相关更新")
        if item.reinforced_count > 0:
            parts.append(f"{item.reinforced_count} 条被多份报告交叉验证")
        if item.observation_count > 0:
            parts.append(f"{item.observation_count} 个观察点需继续跟踪")
        return "，".join(parts) + "。" if parts else "有直接相关更新。"

    elif item.status == "indirect":
        return (
            "本轮未直接提到，但通过相关主题/公司存在间接关联。"
            "建议继续关注相关方向的变化。"
        )

    else:
        return (
            "本轮暂无新证据。当前判断仍主要依赖既有报告，"
            "建议等待新的相关信息后再更新判断。"
        )


# ── Markdown / Obsidian output ────────────────────────────────────

def render_watchlist_markdown(brief: list[WatchlistItemBrief]) -> str:
    """Render watchlist brief as markdown for Obsidian.

    P2-N.2: Structured per-item output with sections:
        - 本轮新增 (new evidence)
        - 已被多报告强化 (reinforced by multiple reports)
        - 需要继续观察 (open observations)
        - 暂无新证据 (no new evidence)
    """
    from podcast_research.utils.display import clean_display_text

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = ["# Watchlist Brief", "", f"*Generated: {now}*", ""]

    companies = [b for b in brief if b.item_type == "company"]
    topics = [b for b in brief if b.item_type == "topic"]
    themes = [b for b in brief if b.item_type == "theme"]

    for section_title, items in [("关注公司", companies), ("关注主题", topics), ("关注方向", themes)]:
        if not items:
            continue
        lines.append(f"## {section_title}")
        lines.append("")
        for item in items:
            status_icon = {"direct": "🟢", "indirect": "🟡", "no_new_evidence": "⚪"}.get(item.status, "⚪")
            lines.append(f"### {status_icon} {item.name}")
            lines.append("")

            # Summary line
            lines.append(item.summary)
            lines.append("")

            # ── P2-N.2: Structured sections ──

            # 本轮新增 (direct items = new evidence this round)
            if item.direct_count > 0:
                lines.append("**本轮新增：**")
                for d in item.direct_items[:3]:
                    lines.append(f"- {clean_display_text(d, 100)}")
                lines.append("")

            # 已被多报告强化 (reinforced claims)
            if item.reinforced_count > 0:
                lines.append("**已被多报告强化：**")
                for r in item.reinforced[:2]:
                    lines.append(f"- {clean_display_text(r, 100)}")
                lines.append("")

            # 需要继续观察 (open observations / watching signals)
            if item.observation_count > 0:
                lines.append("**需要继续观察：**")
                for o in item.observations[:3]:
                    lines.append(f"- {clean_display_text(o, 100)}")
                lines.append("")

            # 暂无新证据
            if item.status == "no_new_evidence" and item.card_exists:
                lines.append("*本轮暂无新证据，当前判断主要依赖既有报告。*")
                lines.append("")

            # Indirect connections (if any, as supplementary)
            if item.indirect_items and item.status != "no_new_evidence":
                lines.append("*间接关联：*")
                for d in item.indirect_items[:2]:
                    lines.append(f"- {clean_display_text(d, 100)}")
                lines.append("")

    # No new evidence section — consolidated
    no_evidence = [b for b in brief if b.status == "no_new_evidence" and b.card_exists]
    if no_evidence:
        lines.append("## 暂无新证据")
        lines.append("")
        for item in no_evidence:
            lines.append(f"- **{item.name}** ({item.item_type}): {item.summary}")
        lines.append("")

    return "\n".join(lines)


def save_watchlist(vault_path: Path, config: WatchlistConfig) -> Path:
    """Write WatchlistConfig back to Watchlist.yaml."""
    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    path = system_dir / WATCHLIST_YAML

    lines = ["# 关注对象配置 — 填写你关注的公司、主题、方向", ""]
    for section, items in [("companies", config.companies), ("topics", config.topics), ("themes", config.themes)]:
        lines.append(f"{section}:")
        if items:
            for item in items:
                lines.append(f"  - {item}")
        else:
            lines.append("  []")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def add_watchlist_item(vault_path: Path, item_type: str, name: str) -> tuple[WatchlistConfig, str]:
    """Add an item to watchlist. Auto-corrects known aliases. Returns (config, message)."""
    name = name.strip()
    if not name:
        return WatchlistConfig(), "名称不能为空"

    if item_type not in ("company", "topic", "theme"):
        return WatchlistConfig(), "无效类型"

    config = load_watchlist(vault_path)
    target = {"company": config.companies, "topic": config.topics, "theme": config.themes}[item_type]

    # Resolve known aliases before adding
    resolved_name = name
    alias_msg = ""
    if item_type == "company":
        name_lower = name.lower()
        if name_lower in COMPANY_ALIAS_MAP:
            resolved_name = COMPANY_ALIAS_MAP[name_lower]
            alias_msg = f"已将「{name}」自动纠正为「{resolved_name}」— "
        elif name_lower in {k.lower(): k for k in COMPANY_ALIAS_MAP}:
            # Already canonical, no correction needed
            pass

    # Check if canonical name already exists
    if resolved_name in target:
        if alias_msg:
            return config, f"{alias_msg}「{resolved_name}」已在关注列表中"
        return config, f"「{name}」已在关注列表中"

    # Check if original name was already added under a different alias
    if name != resolved_name and name in target:
        target.remove(name)
        if resolved_name in target:
            return config, f"{alias_msg}「{resolved_name}」已在关注列表中"

    target.append(resolved_name)
    save_watchlist(vault_path, config)
    if alias_msg:
        return config, f"{alias_msg}已添加至关注列表"
    return config, f"已添加「{name}」"


def remove_watchlist_item(vault_path: Path, item_type: str, name: str) -> tuple[WatchlistConfig, str]:
    """Remove an item from watchlist. Returns (config, message)."""
    name = name.strip()
    if not name:
        return WatchlistConfig(), "名称不能为空"

    if item_type not in ("company", "topic", "theme"):
        return WatchlistConfig(), "无效类型"

    config = load_watchlist(vault_path)
    target = {"company": config.companies, "topic": config.topics, "theme": config.themes}[item_type]

    if name not in target:
        return config, f"「{name}」不在关注列表中"

    target.remove(name)
    save_watchlist(vault_path, config)
    return config, f"已移除「{name}」"


def write_watchlist_brief(vault_path: Path, brief_md: str) -> Path:
    """Write Watchlist Brief to 99_System/ using managed block."""
    from podcast_research.workspace.managed_block import _upsert_managed_block

    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    path = system_dir / "Watchlist Brief.md"
    _upsert_managed_block(path, "watchlist-brief", brief_md)
    return path
