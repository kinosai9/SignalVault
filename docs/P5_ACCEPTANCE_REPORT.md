# P5 验收报告

> 日期：2026-07-02 | 状态：P5-S 收口完成

## 一、P5 目标与定位

P3 解决了"知识库变成可恢复、可审计、可被 Agent 查询的后端"。
P4 解决了"PDF 材料怎么进入这个后端"。
P5 解决"如何在海量已入库数据中快速找到相关性最高的信息，并理解信息之间的关联"。

P5 不改变分析引擎，不新增外部搜索引擎，不引入复杂图算法。
P5 只做两件事：**统一搜索** + **轻量知识图谱**，全部基于 SQLite 实现。

## 二、子阶段交付

### P5-A：统一搜索增强 ✅

| 维度 | 内容 |
|------|------|
| **新增文件** | `db/unified_search.py`（~440 行） |
| **核心结构** | `UnifiedSearchResult`（22 字段） |
| **搜索引擎** | `unified_search()` — FTS5 优先 + LIKE fallback（4 表联合） |
| **Metadata Filters** | result_type, source_type, entity_type, view_direction, signal_status |
| **Relevance** | 轻量启发式评分（entity match > source_quote > logic_chain > title） |
| **CLI** | `search <query>`（--type/--source-type/--entity-type/--direction/--json） |
| **MCP** | `unified_search` tool（第 9 个） |
| **测试** | 35 tests |

### P5-B：轻量知识图谱 ✅

| 维度 | 内容 |
|------|------|
| **新增文件** | `db/knowledge_graph.py`（~420 行） |
| **新增模型** | `KnowledgeNode`（10 列）+ `KnowledgeEdge`（16 列） |
| **Node Types** | report, source, company, topic, person, investment_view, tracking_signal, evidence |
| **Edge Types** | mentioned_in, derived_from, supports, related_to, tracks, cites_page, cites_timestamp |
| **核心函数** | `rebuild_knowledge_graph()` (幂等), `get_entity_neighborhood()`, `get_evidence_trail()`, `list_graph_edges()`, `export_graph_json()` |
| **CLI** | `graph rebuild` / `graph neighborhood <entity>` / `graph evidence-trail` / `graph export` |
| **MCP** | `get_entity_neighborhood`, `list_graph_edges`, `get_evidence_trail`（第 10-12 个） |
| **测试** | 27 tests |

### P5-C：MCP 集成 ✅（随 P5-A/B 一并完成）

原计划 P5-C 单独实现 4 个 MCP tool，实际在 P5-A 和 P5-B 中已全部完成：

| Tool | 阶段 | 功能 |
|------|------|------|
| `unified_search` | P5-A | 统一搜索报告/观点/信号/实体 |
| `get_entity_neighborhood` | P5-B | 实体图谱邻域查询 |
| `list_graph_edges` | P5-B | 图谱边列表 |
| `get_evidence_trail` | P5-B | 证据链追溯 |

P5-C 无需单独实现阶段。

## 三、数据模型变化

### UnifiedSearchResult

```python
@dataclass
class UnifiedSearchResult:
    result_type: str        # report | investment_view | tracking_signal | entity
    title, snippet, relevance_score, matched_fields
    report_id, source_type, source_path, source_title, video_url, channel_name
    timestamp, page_number, source_quote
    entity_name, entity_type, view_direction, signal_status
    metadata: dict
```

### KnowledgeNode (10 columns)

| 列 | 用途 |
|----|------|
| node_key | 全局唯一标识（`report:15`, `entity:nvidia`, `investment_view:3`） |
| node_type | report / source / company / topic / person / investment_view / tracking_signal / evidence |
| label / normalized_label | 显示名 + 小写归一化 |
| source_ref | 来源引用 |
| metadata_json | 类型特定元数据 |

### KnowledgeEdge (16 columns)

| 列 | 用途 |
|----|------|
| edge_key | 全局唯一（`derived_from:view:3>report:15`） |
| source_node_key / target_node_key | 有向边端点 |
| edge_type | mentioned_in / derived_from / supports / related_to / tracks / cites_page / cites_timestamp |
| weight / evidence_ref / report_id / source_type / source_path | 边元数据 |
| page_number / timestamp | 证据定位 |

## 四、CLI 命令清单（P5 新增 6 条）

```bash
# 统一搜索
python -m signalvault search "NVIDIA"
python -m signalvault search "GPU" --type investment_view --source-type pdf_upload

# 知识图谱
python -m signalvault graph rebuild
python -m signalvault graph neighborhood "NVIDIA"
python -m signalvault graph evidence-trail --view 1
python -m signalvault graph export -o graph.json
```

## 五、MCP Tools 清单（12 个，全部只读）

| # | Tool | 阶段 | 功能 |
|---|------|------|------|
| 1 | `search_reports` | P3-D | 搜索报告 |
| 2 | `get_report` | P3-D | 报告详情 |
| 3 | `list_channels` | P3-D | 频道列表 |
| 4 | `search_entities` | P3-D | 实体搜索 |
| 5 | `get_entity_profile` | P3-D | 实体详情 |
| 6 | `list_investment_views` | P3-D | 投资观点 |
| 7 | `list_tracking_signals` | P3-D | 跟踪信号 |
| 8 | `list_review_items` | P3-D | 审核队列 |
| 9 | `unified_search` | P5-A | 统一搜索 |
| 10 | `get_entity_neighborhood` | P5-B | 实体邻域 |
| 11 | `list_graph_edges` | P5-B | 图谱边 |
| 12 | `get_evidence_trail` | P5-B | 证据链 |

## 六、图谱数据流

```
seeded_db ──→ rebuild_knowledge_graph()
  ├─ Node builders: reports → sources → entities → views → signals → evidence
  └─ Edge builders: mentioned_in → derived_from → tracks → cites_page/timestamp
       │
       ├─→ get_entity_neighborhood("NVIDIA")
       │     → center + neighbors + edges + summary
       │
       ├─→ get_evidence_trail(view_id=1)
       │     → target view → evidence {page/timestamp, source_quote} → report → source
       │
       ├─→ list_graph_edges(edge_type="derived_from")
       │     → filtered edge list with metadata
       │
       └─→ export_graph_json()
             → {nodes: [...], edges: [...], metadata: {generated_at, node_count, edge_count}}
```

## 七、Evidence Trail 示例

```
输入: get_evidence_trail(view_id=1)

输出:
  target: {node_type: "investment_view", label: "宁德时代", ...}
  evidence:
    - type: citation
      page_number: 12          ← PDF 页码
      timestamp: ""            ← 视频场景为空
      source_quote: "Q4 revenue grew 35% YoY driven by..."
  report:
    {node_type: "report", label: "2025 Q4 AI Report", ...}
  source:
    null  ← 如果频道/P元数据已在 report metadata 中
```

## 八、测试结果

| 指标 | 数值 |
|------|------|
| **总测试数** | 1703 |
| **P5 新增测试** | 62（35 + 27） |
| **通过率** | 100%（1703/1703） |
| **ruff** | clean（0 errors） |
| **已知 Warnings** | 2（uvicorn websockets deprecation，P2-O 以来已知） |

```
tests/test_unified_search.py   — 35 tests (P5-A)
tests/test_knowledge_graph.py  — 27 tests (P5-B)
其余 1641 tests                 — P0-P4 存量
─────────────────────────────────────
总计                             1703 tests
```

## 九、未做事项（P5 明确排除）

| 排除项 | 原因 |
|--------|------|
| 向量数据库（LanceDB/Pinecone/Weaviate） | 保持 SQLite 自包含 |
| Neo4j / 图数据库 | 两张 SQLite 表足够 |
| Web UI 搜索/图谱可视化 | 非当前优先 |
| Deep Research | 多轮 LLM 编排 |
| 真实 OCR Provider | P4-D 候选 |
| 写入型 MCP tool | 安全边界（12 个全部只读） |
| 自动投资建议 | 项目定位明确排除 |
| 复杂图算法（PageRank/Community Detection） | 预留接口，不做实现 |
| 语义搜索 / Embedding | 不引入向量模型 |
| 跨语言搜索 | 当前只做 CJK + ASCII tokenize |

## 十、验收结论

**P5-A/P5-B/P5-C 全部验收通过。P5-S 收口完成。**

P5 交付了统一搜索层和轻量知识图谱两项能力：
- 一次搜索覆盖报告、观点、信号、实体四种类型；
- SQLite 图谱可从现有 DB 重建，支持实体邻域、证据链、JSON 导出；
- 12 个只读 MCP tool 覆盖查询 → 搜索 → 图谱 → 证据链全链路。

62 个 P5 专项测试，1703 个全量测试，ruff clean。
