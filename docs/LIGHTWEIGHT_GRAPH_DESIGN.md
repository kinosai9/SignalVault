# P5-B: Lightweight Knowledge Graph Design

> 状态：Implemented ✅ | P5-B | 2026-07-02
> 前置阅读：`docs/P5_SEARCH_GRAPH_PLAN.md`

## 零、As-Implemented 摘要

**模块：** `db/knowledge_graph.py`（~420 行）
**模型：** `KnowledgeNode`（10 列）+ `KnowledgeEdge`（16 列），位于 `db/models.py`

**Node Builders（6 类）：** reports → sources → entities → views → signals → evidence
**Edge Builders（4 类）：** mentioned_in → derived_from → tracks → cites_page/cites_timestamp

**已实现的 Node Types：** report, source, company, topic, person, investment_view, tracking_signal, evidence
**已实现的 Edge Types：** mentioned_in, derived_from, supports, related_to, tracks, cites_page, cites_timestamp

**核心 API：**
```python
rebuild_knowledge_graph(session) → {nodes, edges, node_types, edge_types}  # 幂等
get_entity_neighborhood(session, entity_name, depth=1) → {center, neighbors, edges, summary}
get_evidence_trail(session, view_id=1) → {target, evidence[], report, source}
list_graph_edges(session, edge_type="derived_from") → [edge_dict, ...]
export_graph_json(session) → JSON string with nodes, edges, metadata
```

**CLI：** `graph rebuild` / `graph neighborhood` / `graph evidence-trail` / `graph export`
**MCP：** `get_entity_neighborhood`, `list_graph_edges`, `get_evidence_trail`

**复杂算法（仅预留，未实现）：**
```python
compute_community_detection() → NotImplementedError
compute_similarity() → NotImplementedError
find_central_entities() → NotImplementedError
```

---

## 一、设计原则

- **纯 SQLite，不引入 Neo4j / NetworkX 等外部依赖。**
- **两张表：`knowledge_nodes` + `knowledge_edges`。**
- **从现有 DB 可完全重建（`graph rebuild`），支持增量更新（`graph update`）。**
- **不做复杂图算法**，只为后续（P6+）预留接口。
- **图是只读的查询加速层**，不是新的主数据源。

## 二、数据模型

### 2.1 knowledge_nodes

```python
# db/models.py

class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_key: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
        # Globally unique: "report:{id}" | "entity:{normalized_name}" |
        # "view:{id}" | "signal:{id}" | "source:{source_hash}" |
        # "evidence:{report_id}:{page_or_timestamp}"
    node_type: Mapped[str] = mapped_column(String(40), nullable=False)
        # "report" | "source" | "company" | "topic" | "person" |
        # "technology" | "investment_view" | "tracking_signal" | "evidence"
    label: Mapped[str] = mapped_column(String(500), default="")
        # Human-readable display name
    properties_json: Mapped[str] = mapped_column(Text, default="{}")
        # Type-specific metadata (report_id, source_type, page_number, etc.)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
```

**properties_json 示例：**

```json
// node_type="report"
{"report_id": 15, "title": "...", "source_type": "youtube", "created_at": "..."}

// node_type="entity"  (company/topic/person/technology)
{"name": "NVIDIA", "entity_type": "company", "report_count": 12, "view_count": 34}

// node_type="evidence"
{"report_id": 15, "page_number": 12, "source_quote": "Q4 revenue grew 35%...",
 "source_type": "pdf_upload", "source_path": "report.pdf", "content_hash": "abc123"}
```

### 2.2 knowledge_edges

```python
class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    edge_key: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
        # "mentioned_in:{source_node_key}->{target_node_key}"
        # "derived_from:{view_node_key}->{report_node_key}"
    source_node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    edge_type: Mapped[str] = mapped_column(String(40), nullable=False)
        # See edge type catalog below
    weight: Mapped[float] = mapped_column(Float, default=1.0)
        # 1.0 = default, >1.0 = strong connection, <1.0 = weak
    properties_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
```

### 2.3 Edge Type Catalog

| edge_type | from (node_type) | to (node_type) | 含义 | weight |
|-----------|------------------|-----------------|------|--------|
| `mentioned_in` | entity | report | 实体在报告中被提及 | entity_count |
| `derived_from` | investment_view | report | 观点来源于某报告 | 1.0 |
| `derived_from` | tracking_signal | report | 信号来源于某报告 | 1.0 |
| `supports` | investment_view | investment_view | 观点 A 支持观点 B | 1.0 |
| `contradicts` | investment_view | investment_view | 观点 A 与观点 B 矛盾 | 1.0 |
| `related_to` | entity | entity | 两个实体相关（同报告中出现） | co-occurrence |
| `tracks` | tracking_signal | entity | 信号跟踪某实体 | 1.0 |
| `cites_page` | evidence | report | 证据引用 PDF 页码 | 1.0 |
| `cites_timestamp` | evidence | report | 证据引用视频时间戳 | 1.0 |
| `has_evidence` | investment_view | evidence | 观点有证据支持 | 1.0 |
| `has_signal` | entity | tracking_signal | 实体被某信号跟踪 | 1.0 |

## 三、图谱构建

### 3.1 全量重建

```python
# db/graph.py

def rebuild_graph(session: Session) -> dict:
    """从现有 DB 表全量重建知识图谱。

    Steps:
      1. DELETE all nodes and edges
      2. INSERT report nodes (from reports + episodes)
      3. INSERT source nodes (from channels + pdf source_paths)
      4. INSERT entity nodes (from entities + investment_views.target_name)
      5. INSERT view nodes (from investment_views)
      6. INSERT signal nodes (from tracking_signals)
      7. INSERT evidence nodes (from investment_views with timestamp/page)
      8. INSERT edges: mentioned_in, derived_from, tracks, cites_page, ...
      9. INSERT edges: related_to (entity co-occurrence)
      10. INSERT edges: has_evidence, has_signal

    Returns:
        {"nodes": 1234, "edges": 5678, "node_types": {...}, "edge_types": {...}}
    """
```

### 3.2 增量更新

```python
def update_graph(session: Session, report_id: int) -> dict:
    """当新增报告后，增量追加该报告相关的节点和边。

    Does NOT rebuild the entire graph.
    Only adds nodes/edges related to the given report_id.
    Uses edge_key dedup to avoid duplicates.
    """
```

### 3.3 实体归一化

同一实体可能以不同名称出现在不同报告中（如 "NVIDIA" / "Nvidia" / "英伟达"）。
使用 `entities.normalized_name` 作为规范名，`aliases` 处理同义词。

```python
def _normalize_entity_key(name: str, session: Session) -> str:
    """Map entity name to canonical node_key via entities table."""
    entity = session.query(EntityRecord).filter(
        func.lower(EntityRecord.normalized_name) == name.lower().strip()
    ).first()
    if entity:
        return f"entity:{entity.normalized_name.lower()}"
    return f"entity:{name.lower().strip()}"
```

## 四、查询 API

### 4.1 Entity Neighborhood

```python
def get_entity_neighborhood(
    session: Session,
    entity_name: str,
    depth: int = 1,
    edge_types: list[str] | None = None,
    limit: int = 50,
) -> dict:
    """Query the subgraph around an entity.

    Returns:
        {
            "entity": {node dict},
            "neighbors": [
                {
                    "node": {neighbor node dict},
                    "edges": [{edge dict}, ...],  # edges connecting them
                    "depth": 1
                },
                ...
            ],
            "total_connections": 42
        }
    """
```

### 4.2 Graph Export

```python
def export_graph(session: Session, format: str = "json") -> str:
    """Export the full graph in JSON format.

    Returns a JSON string compatible with:
      - vis.js / D3.js (visualization)
      - Gephi (import)
      - NetworkX (read_node_link_data)

    Schema:
    {
        "nodes": [{"id": "entity:nvidia", "type": "company", "label": "NVIDIA", ...}],
        "edges": [{"source": "view:123", "target": "report:15", "type": "derived_from", ...}]
    }
    """
```

### 4.3 Evidence Trail

```python
def get_evidence_trail(
    session: Session,
    view_id: int | None = None,
    signal_id: int | None = None,
    report_id: int | None = None,
) -> dict:
    """Trace the evidence chain for a view, signal, or report.

    Returns:
        {
            "target": {view/signal/report dict},
            "evidence_nodes": [
                {
                    "type": "page_citation" | "timestamp_citation" | "quote",
                    "page_number": 12,
                    "timestamp": "p.12" | "00:15:30",
                    "source_quote": "...",
                    "source": {
                        "report_id": 15,
                        "source_type": "pdf_upload",
                        "source_path": "report.pdf",
                        "channel_name": ""  # for YouTube
                    }
                }
            ],
            "derived_views": [view dicts from the same report],
            "related_signals": [signal dicts for the same target]
        }
    """
```

## 五、CLI 入口

```bash
# 图谱管理
python -m signalvault graph build                     # 全量重建
python -m signalvault graph update --report-id 15     # 增量更新
python -m signalvault graph stats                     # 节点/边统计

# 图谱查询
python -m signalvault graph neighborhood "NVIDIA"     # 实体邻域
python -m signalvault graph neighborhood "NVIDIA" --depth 2
python -m signalvault graph evidence-trail --view 123 # 证据链

# 图谱导出
python -m signalvault graph export --output graph.json
```

## 六、MCP Tools

### 6.1 `get_entity_neighborhood`

```json
{
    "name": "get_entity_neighborhood",
    "description": "查询实体的知识图谱邻域：关联的公司、话题、报告、观点、信号。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "entity_name": {"type": "string", "description": "实体名称"},
            "depth": {"type": "integer", "default": 1, "minimum": 1, "maximum": 3},
            "edge_types": {"type": "array", "items": {"type": "string"}},
            "limit": {"type": "integer", "default": 30, "maximum": 100}
        },
        "required": ["entity_name"]
    }
}
```

### 6.2 `list_graph_edges`

```json
{
    "name": "list_graph_edges",
    "description": "列出知识图谱边，支持按类型和实体过滤。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "edge_type": {"type": "string", "description": "边类型过滤"},
            "entity_name": {"type": "string", "description": "按实体名过滤关联边"},
            "limit": {"type": "integer", "default": 30, "maximum": 100}
        }
    }
}
```

### 6.3 `get_evidence_trail`

```json
{
    "name": "get_evidence_trail",
    "description": "获取证据链：观点→原文引用→来源→时间戳/页码→PDF/视频。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "view_id": {"type": "integer", "description": "投资观点 ID"},
            "signal_id": {"type": "integer", "description": "跟踪信号 ID"},
            "report_id": {"type": "integer", "description": "报告 ID"}
        }
    }
}
```

## 七、模块结构

```
src/signalvault/db/
    models.py            ← 扩展：KnowledgeNode + KnowledgeEdge ORM
    session.py           ← 扩展：_migrate_knowledge_graph_tables
    graph.py             ← NEW: rebuild/update/query/export
    graph_serializers.py ← NEW: node/edge → JSON-safe dict

src/signalvault/mcp_server/
    tools.py             ← 扩展：3 个新 tool
    serializers.py       ← 扩展：serialize_graph_node / serialize_graph_edge

tests/
    test_knowledge_graph.py ← NEW: ~25 tests
```

## 八、边界与未来预留

### 当前不做

| 项目 | 说明 |
|------|------|
| 复杂图算法 | Louvain/Adamic-Adar/PageRank 仅预留方法签名 |
| 图可视化 | 只做 JSON export，可视化由外部工具完成 |
| 实时边更新 | 图谱为 batch rebuild + 手动增量更新 |
| 边权重自动学习 | 当前 weight 为启发式规则，不做 ML |

### 预留接口

```python
# db/graph.py — P6+ 候选接口

def compute_community_detection(session, method="louvain") -> dict:
    """社区发现（预留）"""
    raise NotImplementedError

def compute_similarity(session, entity_a: str, entity_b: str, method="adamic_adar") -> float:
    """实体相似度（预留）"""
    raise NotImplementedError

def find_central_entities(session, top_n: int = 10, method="pagerank") -> list[dict]:
    """中心实体发现（预留）"""
    raise NotImplementedError
```

## 九、图谱重建性能估算

基于当前项目数据规模（~100 reports, ~500 views, ~200 entities, ~200 signals）：

| 操作 | 预计耗时 |
|------|----------|
| 全量重建 | < 1 秒（纯内存组装 + batch INSERT） |
| 增量更新（1 report） | < 100ms |
| entity neighborhood (depth=1) | < 50ms |
| graph export JSON | < 200ms |

如果未来数据量增长到 1000+ reports，FTS5 替代 LIKE 即可，图结构本身不需要变更。
