"""Shared taxonomy data for LLM-WIKI patch apply hardening.

Contains:
- Section ordering for Topic Cards
- Topic canonical name mapping
- Entity classification (company vs product/framework)
"""

from __future__ import annotations

# Standard section order for Topic Cards.
# New sections created during apply are inserted at their canonical position.
SECTION_ORDER = [
    "## Current Understanding",
    "## Key Claims",
    "## Related Companies",
    "## Related Topics",
    "## Open Questions",
    "## Timeline",
    "## Source Reports",
]

# Topic alias → canonical name map.
# Extracted from P2-D.2 taxonomy consolidation.
TOPIC_CANONICAL_MAP: dict[str, str] = {
    # AI Agents
    "ai agent": "AI Agents",
    "ai agents": "AI Agents",
    "agentic ai": "AI Agents",
    "agents": "AI Agents",
    "agent workflow": "AI Agents",
    "agent orchestration": "AI Agents",
    "agent tools": "AI Agents",
    "agentic workflow": "AI Agents",
    "agent infrastructure": "AI Agents",
    "coding agents": "AI Agents",
    "agentic infrastructure": "AI Agents",
    "agent": "AI Agents",  # P2-N.1: lone "Agent" → AI Agents
    # AI Infrastructure
    "ai infra": "AI Infrastructure",
    "ai infrastructure": "AI Infrastructure",
    "ai compute": "AI Infrastructure",
    "compute infrastructure": "AI Infrastructure",
    "gpu cluster": "AI Infrastructure",
    "training infrastructure": "AI Infrastructure",
    "infrastructure": "AI Infrastructure",  # P2-N.1
    # AI Capex
    "ai capex": "AI Capex",
    "cloud capex": "AI Capex",
    "infrastructure capex": "AI Capex",
    "capital expenditure": "AI Capex",
    # Enterprise AI
    "enterprise saas": "Enterprise AI",
    "enterprise software": "Enterprise AI",
    "enterprise ai adoption": "Enterprise AI",
    "enterprise deployment": "Enterprise AI",
    "b2b ai": "Enterprise AI",
    "enterprise": "Enterprise AI",  # P2-N.1
    # AI Models
    "llm": "AI Models",
    "language model": "AI Models",
    "foundation model": "AI Models",
    "model training": "AI Models",
    "model architecture": "AI Models",
    "reasoning model": "AI Models",
    "model": "AI Models",  # P2-N.1
    # Open Source AI
    "open models": "Open Source AI",
    "open source models": "Open Source AI",
    "open-source ai": "Open Source AI",
    "open weights": "Open Source AI",
    # AI Safety & Security
    "ai safety": "AI Safety & Security",
    "ai security": "AI Safety & Security",
    "enterprise ai security": "AI Safety & Security",
    "alignment": "AI Safety & Security",
    "ai governance": "AI Safety & Security",
    "compliance": "AI Safety & Security",
    # China AI
    "china models": "China AI",
    "chinese ai": "China AI",
    # Business Model
    "business model": "Business Model",
    "monetization": "Business Model",
    "pricing": "Business Model",
    "saas pricing": "Business Model",
    "outcome based": "Business Model",
    "usage based": "Business Model",
    "gtm strategy": "Business Model",
    # Moat & Strategy
    "moat": "Moat & Strategy",
    "competitive advantage": "Moat & Strategy",
    "seven powers": "Moat & Strategy",
    # Valuation
    "valuation multiple": "Valuation",
    "re-rating": "Valuation",
    "ipo valuation": "Valuation",
    # Venture Market
    "vc": "Venture Market",
    "venture": "Venture Market",
    "private market": "Venture Market",
    "startup funding": "Venture Market",
    "venture capital": "Venture Market",
    # Investment Framework
    "long-term investing": "Investment Framework",
    "investment thesis": "Investment Framework",
    "portfolio strategy": "Investment Framework",
    # AI for Science
    "ai for science": "AI for Science",
    "ai-for-science": "AI for Science",
    "ai science": "AI for Science",
    "scientific ai": "AI for Science",
    "scientific discovery": "AI for Science",
    "research workflow": "AI for Science",
    # AI Applications
    "application": "AI Applications",
    "applications": "AI Applications",
    "ai application": "AI Applications",
    "ai applications": "AI Applications",
    "consumer tech": "AI Applications",
    "consumer ai": "AI Applications",
    "conversational ui": "AI Applications",
    "conversational commerce": "AI Applications",
    "interactive ai": "AI Applications",
    # Developer Tools
    "developer tool": "Developer Tools",
    "developer tools": "Developer Tools",
    "ci/cd": "Developer Tools",
    "cicd": "Developer Tools",
    "ai coding": "Developer Tools",
    "ai engineering": "Developer Tools",
    # Cloud
    "cloud": "Cloud",
    "cloud computing": "Cloud",
    "cloud infrastructure": "Cloud",
    # Semiconductor
    "semiconductor": "Semiconductor",
    "cpu supply": "Semiconductor",
    "cpu bottleneck": "Semiconductor",
    # Customer Service
    "customer service": "Customer Service",
    "resolution rate": "Customer Service",
    # Data Center
    "data center": "Data Center",
    "data centres": "Data Center",
    # Public Markets
    "public market": "Public Markets",
    "market": "Public Markets",  # P2-N.1
    "capital market": "Public Markets",  # P2-N.1
    "tech stock": "Public Markets",
    "index fund": "Public Markets",
    "passive": "Public Markets",
    # Robotics
    "robotics": "Robotics",
    # Academic Publishing
    "academic publishing": "Academic Publishing",
    # Model Context Protocol
    "model context protocol": "Model Context Protocol",
    "mcp": "Model Context Protocol",
    # Licensing
    "licensing": "Licensing",
    # AI Safety & Compliance (subsumed under AI Safety & Security)
    "ai safety & compliance": "AI Safety & Security",
    "enterprise security": "AI Safety & Security",
    # Distribution
    "distribution": "Distribution",
}

# Known non-company entities: products, frameworks, tools, protocols.
# These should be annotated with their entity type when appearing in Related Companies.
KNOWN_NON_COMPANY: dict[str, str] = {
    # Products / Models
    "chatgpt": "product",
    "gpt-4": "model",
    "gpt-5": "model",
    "gpt": "model",
    "claude": "model",
    "gemini": "model",
    "sonnet": "model",
    "opus": "model",
    "haiku": "model",
    "sora": "product",
    "qwen": "model",
    "deepseek": "model",
    "llama": "model",
    "codex": "product",
    "github copilot": "product",
    # Tools / IDEs
    "claude code": "tool",
    "cursor": "IDE",
    "windsurf": "IDE",
    "copilot": "tool",
    # Frameworks
    "langchain": "framework",
    "llamaindex": "framework",
    "crewai": "framework",
    "autogen": "framework",
    # Protocols
    "model context protocol": "protocol",
    "mcp": "protocol",
    # Platforms
    "github": "platform",
    "hugging face": "platform",
    "arxiv": "platform",
    "shopify": "platform",
    # Mac/OS
    "mac os": "OS",
    "windows": "OS",
    "linux": "OS",
    # Hardware
    "apple silicon": "hardware",
    "macbook": "hardware",
    "m5 max": "hardware",
    "gpu": "hardware",
    # Concepts (not entities at all)
    "plg": "concept",
    "egc": "concept",
    "sso": "concept",
    "scim": "concept",
    "reinforcement learning": "concept",
    "rl": "concept",
    "inner loop": "concept",
    "ai slop": "concept",
    # P2-N.4.3: Additional non-company entities
    "sam altman": "person",
    "satya nadella": "person",
    "donald trump": "person",
    "ai regulation": "policy_or_regulation",
    "ai compute infrastructure": "industry_theme",
    "ai semiconductors": "industry_theme",
    "agentic ai": "technology",
    "enterprise ai": "technology",
    "venture capital": "industry_theme",
    "vibe coding": "concept",
    "api": "technology",
    "sdk": "technology",
    "edge computing": "technology",
    "robotics": "technology",
    "quantum computing": "technology",
    "saas": "technology",
    "platform": "technology",
    "data center": "industry_theme",
    # P2-N.4.3.2: Additional leaking non-company entities
    "artificial intelligence": "technology",
    "deep research": "product",
    "enterprise ai adoption": "industry_theme",
    "grok": "model",
    "mai models": "model",
    "microsoft 365": "product",
    "microsoft azure": "product",
    "reasoning models": "technology",
    "ai-washing companies": "concept",
    "cod ex": "product",
    "ai数据中心电力基础设施": "industry_theme",
    "美国科技公司": "concept",
}


def normalize_topic_name(name: str) -> str:
    """Normalize a topic name to its canonical form.

    Args:
        name: Raw topic name (e.g. "ai agents", "enterprise saas")

    Returns:
        Canonical topic name if found, otherwise the original name
    """
    name_lower = name.strip().lower()
    # Direct match
    if name_lower in TOPIC_CANONICAL_MAP:
        return TOPIC_CANONICAL_MAP[name_lower]
    # Normalize hyphens/underscores to spaces and try again
    normalized = name_lower.replace("-", " ").replace("_", " ")
    if normalized != name_lower and normalized in TOPIC_CANONICAL_MAP:
        return TOPIC_CANONICAL_MAP[normalized]
    return name.strip()


def classify_entity(name: str) -> str | None:
    """Classify an entity name as company, product, framework, etc.

    Args:
        name: Entity name (from [[Entity]] link)

    Returns:
        Type label if known non-company, None if company or unknown
    """
    name_lower = name.strip().lower()
    if name_lower in KNOWN_NON_COMPANY:
        return KNOWN_NON_COMPANY[name_lower]
    return None


def get_section_position(section_name: str) -> int:
    """Get the canonical position of a section in topic card ordering.

    Args:
        section_name: Section header (e.g. "## Current Understanding")

    Returns:
        Position index (0-based), or len(SECTION_ORDER) if unknown
    """
    try:
        return SECTION_ORDER.index(section_name)
    except ValueError:
        return len(SECTION_ORDER)
