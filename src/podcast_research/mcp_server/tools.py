"""MCP tool definitions and handler for podcast_research read-only queries.

All 8 tools are read-only — they query the SQLite DB and return
JSON-serializable dicts/lists. No writes, no vault modification.
"""

from __future__ import annotations

import logging

from mcp.types import TextContent, Tool

from podcast_research.db.session import get_session, init_db
from podcast_research.mcp_server.serializers import (
    serialize_channel,
    serialize_entity,
    serialize_investment_view,
    serialize_report_detail,
    serialize_report_summary,
    serialize_review_item,
    serialize_tracking_signal,
)

logger = logging.getLogger(__name__)

# ── Tool definitions ─────────────────────────────────────────────────────────

TOOLS: list[Tool] = [
    Tool(
        name="search_reports",
        description="搜索已入库的投资分析报告。支持关键词搜索和按来源/频道过滤。返回报告摘要列表。",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词（在报告正文、观点标的、逻辑链中搜索）",
                },
                "source": {
                    "type": "string",
                    "enum": ["youtube", "local", "all"],
                    "default": "all",
                    "description": "按来源过滤",
                },
                "channel": {
                    "type": "string",
                    "description": "频道名称过滤（模糊匹配）",
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "maximum": 50,
                    "description": "最大返回数量",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="get_report",
        description="获取指定报告的完整内容，包括投资观点、跟踪信号和 Markdown 正文。",
        inputSchema={
            "type": "object",
            "properties": {
                "report_id": {
                    "type": "integer",
                    "description": "报告 ID",
                },
            },
            "required": ["report_id"],
        },
    ),
    Tool(
        name="list_channels",
        description="列出所有已关注的 YouTube 频道及视频统计。",
        inputSchema={
            "type": "object",
            "properties": {
                "active_only": {
                    "type": "boolean",
                    "default": False,
                    "description": "只返回活跃频道",
                },
            },
        },
    ),
    Tool(
        name="search_entities",
        description="搜索知识库中的实体（公司/产品/技术/人物等），支持按类型和名称过滤。",
        inputSchema={
            "type": "object",
            "properties": {
                "entity_type": {
                    "type": "string",
                    "description": "实体类型: company / product / technology / person / theme / stock",
                },
                "name_filter": {
                    "type": "string",
                    "description": "名称过滤（模糊匹配）",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "maximum": 100,
                    "description": "最大返回数量",
                },
            },
        },
    ),
    Tool(
        name="get_entity_profile",
        description="获取指定实体的详细信息，包括关联的投资观点和最近出现时间。",
        inputSchema={
            "type": "object",
            "properties": {
                "entity_name": {
                    "type": "string",
                    "description": "实体名称（精确匹配 normalized_name）",
                },
            },
            "required": ["entity_name"],
        },
    ),
    Tool(
        name="list_investment_views",
        description="列出投资观点，支持按标的名称、方向、AI 价值链层级过滤。",
        inputSchema={
            "type": "object",
            "properties": {
                "target_name": {
                    "type": "string",
                    "description": "投资标的名称过滤（模糊匹配）",
                },
                "view_direction": {
                    "type": "string",
                    "enum": ["bullish", "bearish", "neutral", "all"],
                    "default": "all",
                    "description": "观点方向",
                },
                "ai_value_chain_layer": {
                    "type": "string",
                    "description": "AI 价值链层级: infrastructure / platform / application / security / other",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "maximum": 100,
                    "description": "最大返回数量",
                },
            },
        },
    ),
    Tool(
        name="list_tracking_signals",
        description="列出跟踪信号，支持按标的名称和状态过滤。",
        inputSchema={
            "type": "object",
            "properties": {
                "target_name": {
                    "type": "string",
                    "description": "投资标的名称过滤（模糊匹配）",
                },
                "status": {
                    "type": "string",
                    "enum": ["open", "triggered", "resolved", "all"],
                    "default": "open",
                    "description": "信号状态",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "maximum": 100,
                    "description": "最大返回数量",
                },
            },
        },
    ),
    Tool(
        name="list_review_items",
        description="获取待处理的人工审核事项列表（来自 Vault Lint / 实体合并建议等）。",
        inputSchema={
            "type": "object",
            "properties": {
                "item_type": {
                    "type": "string",
                    "description": "事项类型: lint_frontmatter_invalid / lint_dead_wikilink / entity_duplicate_candidate / patch_review 等",
                },
                "status": {
                    "type": "string",
                    "enum": ["open", "accepted", "skipped", "resolved", "all"],
                    "default": "open",
                    "description": "事项状态",
                },
                "severity": {
                    "type": "string",
                    "enum": ["error", "warning", "info", "all"],
                    "default": "all",
                    "description": "严重程度",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "maximum": 100,
                    "description": "最大返回数量",
                },
            },
        },
    ),
    Tool(
        name="unified_search",
        description="统一搜索知识库：报告、投资观点、跟踪信号、实体。支持类型过滤和来源过滤。",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词",
                },
                "result_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["report", "investment_view", "tracking_signal", "entity"],
                    },
                    "description": "限定结果类型，不传则搜索全部",
                },
                "source_type": {
                    "type": "string",
                    "enum": ["youtube", "pdf_upload", "local", "all"],
                    "default": "all",
                    "description": "按来源过滤",
                },
                "entity_type": {
                    "type": "string",
                    "description": "实体类型过滤: company / topic / technology / person / stock",
                },
                "view_direction": {
                    "type": "string",
                    "enum": ["bullish", "bearish", "neutral", "all"],
                    "default": "all",
                    "description": "观点方向过滤",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "maximum": 100,
                    "description": "最大返回数量",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="get_entity_neighborhood",
        description="查询实体的知识图谱邻域：关联的公司、话题、报告、观点、信号。",
        inputSchema={
            "type": "object",
            "properties": {
                "entity_name": {
                    "type": "string",
                    "description": "实体名称（模糊匹配）",
                },
                "entity_type": {
                    "type": "string",
                    "description": "实体类型: company / topic / person",
                },
                "depth": {
                    "type": "integer",
                    "default": 1,
                    "minimum": 1,
                    "maximum": 1,
                    "description": "邻域深度（当前仅支持 1）",
                },
                "limit": {
                    "type": "integer",
                    "default": 30,
                    "maximum": 100,
                    "description": "最大返回邻居数",
                },
            },
            "required": ["entity_name"],
        },
    ),
    Tool(
        name="list_graph_edges",
        description="列出知识图谱边，支持按类型和实体过滤。",
        inputSchema={
            "type": "object",
            "properties": {
                "edge_type": {
                    "type": "string",
                    "description": "边类型: mentioned_in / derived_from / supports / related_to / tracks / cites_page / cites_timestamp",
                },
                "entity_name": {
                    "type": "string",
                    "description": "按实体名过滤关联边",
                },
                "limit": {
                    "type": "integer",
                    "default": 30,
                    "maximum": 100,
                    "description": "最大返回数量",
                },
            },
        },
    ),
    Tool(
        name="get_evidence_trail",
        description="获取证据链：观点/信号→原文引用→来源→时间戳/页码→报告。",
        inputSchema={
            "type": "object",
            "properties": {
                "view_id": {
                    "type": "integer",
                    "description": "投资观点 ID",
                },
                "signal_id": {
                    "type": "integer",
                    "description": "跟踪信号 ID",
                },
            },
        },
    ),
]

# ── Query helpers (DB-backed, read-only) ────────────────────────────────────


def _ensure_db(db_path: str | None = None) -> None:
    """Lazily initialize the DB engine if needed."""
    from podcast_research.db.session import _engine
    if _engine is None:
        init_db(db_path)


def _query_search_reports(
    query: str,
    source: str = "all",
    channel: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search reports by keyword."""
    from podcast_research.db.repository import search_reports

    session = get_session()
    try:
        results = search_reports(session, query, limit=limit)
        summaries: list[dict] = []
        for r in results:
            item = serialize_report_summary(r)
            # Source filter
            if source != "all" and item["source_type"] != source:
                continue
            # Channel filter (fuzzy match on title)
            if channel and channel.lower() not in (item.get("title") or "").lower():
                continue
            summaries.append(item)
        return summaries[:limit]
    finally:
        session.close()


def _query_get_report(report_id: int) -> dict | None:
    """Get full report detail by ID."""
    from podcast_research.db.repository import get_report_detail

    session = get_session()
    try:
        detail = get_report_detail(session, report_id)
        if detail is None:
            return None
        return serialize_report_detail(detail)
    finally:
        session.close()


def _query_list_channels(active_only: bool = False) -> list[dict]:
    """List all channels."""
    from podcast_research.db.repository import list_channels

    session = get_session()
    try:
        channels = list_channels(session, active_only=active_only)
        return [serialize_channel(ch) for ch in channels]
    finally:
        session.close()


def _query_search_entities(
    entity_type: str | None = None,
    name_filter: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search entities with optional type and name filters."""
    from podcast_research.db.repository import list_entities

    session = get_session()
    try:
        entities = list_entities(session, entity_type=entity_type, limit=limit * 2)
        results = [serialize_entity(e) for e in entities]
        # Name filter (fuzzy match)
        if name_filter:
            nf = name_filter.lower()
            results = [
                e for e in results
                if nf in (e.get("name") or "").lower()
                or nf in (e.get("normalized_name") or "").lower()
                or any(nf in (a or "").lower() for a in e.get("aliases", []))
            ]
        return results[:limit]
    finally:
        session.close()


def _query_get_entity_profile(entity_name: str) -> dict | None:
    """Get entity profile: entity info + related investment views."""
    from sqlalchemy import func

    from podcast_research.db.models import EntityRecord, InvestmentViewRecord

    session = get_session()
    try:
        # Find entity by normalized_name (exact match)
        entity = (
            session.query(EntityRecord)
            .filter(
                func.lower(EntityRecord.normalized_name) == entity_name.lower().strip()
            )
            .first()
        )
        if entity is None:
            # Try exact name match
            entity = (
                session.query(EntityRecord)
                .filter(
                    func.lower(EntityRecord.name) == entity_name.lower().strip()
                )
                .first()
            )
        if entity is None:
            return None

        # Get related investment views — match on normalized_target_name
        # or target_name (fallback for records without normalized names)
        normalized = (entity.normalized_name or entity.name).lower()
        views = (
            session.query(InvestmentViewRecord)
            .filter(
                func.lower(InvestmentViewRecord.normalized_target_name) == normalized
            )
            .order_by(InvestmentViewRecord.created_at.desc())
            .limit(50)
            .all()
        )
        if not views:
            # Fallback: match on target_name for records without normalized names
            views = (
                session.query(InvestmentViewRecord)
                .filter(
                    func.lower(InvestmentViewRecord.target_name) == normalized
                )
                .order_by(InvestmentViewRecord.created_at.desc())
                .limit(50)
                .all()
            )

        # Count distinct reports mentioning this entity
        report_ids = {v.report_id for v in views}
        report_count = len(report_ids)

        # Get last seen date
        last_seen = max((v.created_at for v in views), default=None)

        return {
            "name": entity.name,
            "normalized_name": entity.normalized_name or entity.name,
            "entity_type": entity.entity_type,
            "aliases": _parse_aliases(entity.aliases),
            "report_count": report_count,
            "view_count": len(views),
            "last_seen": last_seen.isoformat() if last_seen else None,
            "recent_views": [
                {
                    "report_id": v.report_id,
                    "target_name": v.target_name,
                    "view_direction": v.view_direction,
                    "logic_chain": v.logic_chain,
                    "confidence": v.confidence,
                    "source_quote": v.source_quote,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                }
                for v in views[:10]
            ],
        }
    finally:
        session.close()


def _parse_aliases(raw: str) -> list[str]:
    """Parse entity aliases JSON string."""
    import json as _json
    if not raw:
        return []
    try:
        return _json.loads(raw)
    except (_json.JSONDecodeError, TypeError):
        return []


def _query_list_investment_views(
    target_name: str | None = None,
    view_direction: str = "all",
    ai_value_chain_layer: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List investment views with optional filters."""
    from podcast_research.db.models import InvestmentViewRecord

    session = get_session()
    try:
        q = session.query(InvestmentViewRecord)
        if target_name:
            q = q.filter(
                InvestmentViewRecord.target_name.like(f"%{target_name}%")
            )
        if view_direction != "all":
            q = q.filter_by(view_direction=view_direction)
        if ai_value_chain_layer:
            q = q.filter_by(ai_value_chain_layer=ai_value_chain_layer)
        q = q.order_by(InvestmentViewRecord.created_at.desc()).limit(limit)
        views = q.all()
        return [
            {
                **serialize_investment_view({
                    "target_name": v.target_name,
                    "normalized_target_name": v.normalized_target_name,
                    "target_type": v.target_type,
                    "view_direction": v.view_direction,
                    "confidence": v.confidence,
                    "time_horizon": v.time_horizon,
                    "logic_chain": v.logic_chain,
                    "evidence_type": v.evidence_type,
                    "evidence_detail": v.evidence_detail,
                    "evidence_strength": v.evidence_strength,
                    "risk_warning": v.risk_warning,
                    "source_quote": v.source_quote,
                    "timestamp_start": v.timestamp_start,
                    "timestamp_end": v.timestamp_end,
                    "speaker_label": v.speaker_label,
                    "ai_value_chain_layer": v.ai_value_chain_layer,
                    "business_impact": v.business_impact,
                    "investment_relevance": v.investment_relevance,
                }),
                "report_id": v.report_id,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in views
        ]
    finally:
        session.close()


def _query_list_tracking_signals(
    target_name: str | None = None,
    status: str = "open",
    limit: int = 20,
) -> list[dict]:
    """List tracking signals with optional filters."""
    from podcast_research.db.models import TrackingSignalRecord

    session = get_session()
    try:
        q = session.query(TrackingSignalRecord)
        if target_name:
            q = q.filter(
                TrackingSignalRecord.target_name.like(f"%{target_name}%")
            )
        if status != "all":
            q = q.filter_by(status=status)
        q = q.order_by(TrackingSignalRecord.created_at.desc()).limit(limit)
        signals = q.all()
        return [
            {
                **serialize_tracking_signal({
                    "target_name": s.target_name,
                    "signal": s.signal,
                    "trigger_condition": s.trigger_condition,
                    "expected_date": s.expected_date,
                    "status": s.status,
                    "source_quote": s.source_quote,
                    "timestamp": s.timestamp,
                }),
                "id": s.id,
                "report_id": s.report_id,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in signals
        ]
    finally:
        session.close()


def _query_list_review_items(
    item_type: str | None = None,
    status: str = "open",
    severity: str = "all",
    limit: int = 20,
) -> list[dict]:
    """List review items with optional filters."""
    from podcast_research.sources.review_items import ReviewItemManager

    items = ReviewItemManager.list_items(
        item_type=item_type if item_type else None,
        status=status if status != "all" else None,
        severity=severity if severity != "all" else None,
        limit=limit,
    )
    return [serialize_review_item(item) for item in items]


# ── Tool dispatcher ──────────────────────────────────────────────────────────


async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Dispatch MCP tool calls to the appropriate query function.

    All functions return dict/list — serialized as JSON text content.
    """
    import json as _json

    try:
        if name == "search_reports":
            result = _query_search_reports(
                query=arguments.get("query", ""),
                source=arguments.get("source", "all"),
                channel=arguments.get("channel"),
                limit=min(int(arguments.get("limit", 10)), 50),
            )
            return [TextContent(type="text", text=_json.dumps(result, ensure_ascii=False, default=str))]

        elif name == "get_report":
            report_id = int(arguments.get("report_id", 0))
            if report_id <= 0:
                return [TextContent(
                    type="text",
                    text=_json.dumps({"error": "report_id must be a positive integer"}, ensure_ascii=False),
                )]
            result = _query_get_report(report_id)
            if result is None:
                return [TextContent(
                    type="text",
                    text=_json.dumps({"error": f"Report not found: id={report_id}"}, ensure_ascii=False),
                )]
            return [TextContent(type="text", text=_json.dumps(result, ensure_ascii=False, default=str))]

        elif name == "list_channels":
            result = _query_list_channels(
                active_only=bool(arguments.get("active_only", False)),
            )
            return [TextContent(type="text", text=_json.dumps(result, ensure_ascii=False, default=str))]

        elif name == "search_entities":
            result = _query_search_entities(
                entity_type=arguments.get("entity_type"),
                name_filter=arguments.get("name_filter"),
                limit=min(int(arguments.get("limit", 20)), 100),
            )
            return [TextContent(type="text", text=_json.dumps(result, ensure_ascii=False, default=str))]

        elif name == "get_entity_profile":
            entity_name = arguments.get("entity_name", "")
            if not entity_name:
                return [TextContent(
                    type="text",
                    text=_json.dumps({"error": "entity_name is required"}, ensure_ascii=False),
                )]
            result = _query_get_entity_profile(entity_name)
            if result is None:
                return [TextContent(
                    type="text",
                    text=_json.dumps({"error": f"Entity not found: {entity_name}"}, ensure_ascii=False),
                )]
            return [TextContent(type="text", text=_json.dumps(result, ensure_ascii=False, default=str))]

        elif name == "list_investment_views":
            result = _query_list_investment_views(
                target_name=arguments.get("target_name"),
                view_direction=arguments.get("view_direction", "all"),
                ai_value_chain_layer=arguments.get("ai_value_chain_layer"),
                limit=min(int(arguments.get("limit", 20)), 100),
            )
            return [TextContent(type="text", text=_json.dumps(result, ensure_ascii=False, default=str))]

        elif name == "list_tracking_signals":
            result = _query_list_tracking_signals(
                target_name=arguments.get("target_name"),
                status=arguments.get("status", "open"),
                limit=min(int(arguments.get("limit", 20)), 100),
            )
            return [TextContent(type="text", text=_json.dumps(result, ensure_ascii=False, default=str))]

        elif name == "list_review_items":
            result = _query_list_review_items(
                item_type=arguments.get("item_type"),
                status=arguments.get("status", "open"),
                severity=arguments.get("severity", "all"),
                limit=min(int(arguments.get("limit", 20)), 100),
            )
            return [TextContent(type="text", text=_json.dumps(result, ensure_ascii=False, default=str))]

        elif name == "unified_search":
            from podcast_research.db.unified_search import (
                serialize_unified_result,
                unified_search,
            )
            session = get_session()
            try:
                rtypes = arguments.get("result_types")
                results = unified_search(
                    session,
                    arguments.get("query", ""),
                    result_types=list(rtypes) if rtypes else None,
                    source_type=arguments.get("source_type", "all"),
                    entity_type=arguments.get("entity_type"),
                    view_direction=arguments.get("view_direction", "all"),
                    limit=min(int(arguments.get("limit", 20)), 100),
                )
                output = [serialize_unified_result(r) for r in results]
            finally:
                session.close()
            return [TextContent(type="text", text=_json.dumps(output, ensure_ascii=False, default=str))]

        elif name == "get_entity_neighborhood":
            from podcast_research.db.knowledge_graph import get_entity_neighborhood
            session = get_session()
            try:
                result = get_entity_neighborhood(
                    session,
                    arguments.get("entity_name", ""),
                    entity_type=arguments.get("entity_type"),
                    depth=min(int(arguments.get("depth", 1)), 1),
                    limit=min(int(arguments.get("limit", 30)), 100),
                )
            finally:
                session.close()
            return [TextContent(type="text", text=_json.dumps(result, ensure_ascii=False, default=str))]

        elif name == "list_graph_edges":
            from podcast_research.db.knowledge_graph import list_graph_edges
            session = get_session()
            try:
                result = list_graph_edges(
                    session,
                    edge_type=arguments.get("edge_type"),
                    entity_name=arguments.get("entity_name"),
                    limit=min(int(arguments.get("limit", 30)), 100),
                )
            finally:
                session.close()
            return [TextContent(type="text", text=_json.dumps(result, ensure_ascii=False, default=str))]

        elif name == "get_evidence_trail":
            from podcast_research.db.knowledge_graph import get_evidence_trail
            session = get_session()
            try:
                result = get_evidence_trail(
                    session,
                    view_id=arguments.get("view_id"),
                    signal_id=arguments.get("signal_id"),
                )
            finally:
                session.close()
            return [TextContent(type="text", text=_json.dumps(result, ensure_ascii=False, default=str))]

        else:
            return [TextContent(
                type="text",
                text=_json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False),
            )]

    except Exception as e:
        logger.exception("Tool call failed: %s", name)
        return [TextContent(
            type="text",
            text=_json.dumps({"error": f"Tool execution error: {str(e)}"}, ensure_ascii=False),
        )]
