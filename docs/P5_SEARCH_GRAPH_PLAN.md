# P5 Plan: Search Enhancement + Lightweight Knowledge Graph

> 状态：P5-A ✅ | P5-B ✅ | P5-C ✅ | P5-S 收口 | 2026-07-02
> 前置：P3-A/B/C/D 全部完成 | P4-A/B 全部完成

## 一、定位

P3 解决了"知识库变成可恢复、可审计、可被 Agent 查询的后端"。
P4 解决了"PDF 材料怎么进入这个后端"。
P5 解决"如何在海量已入库数据中快速找到相关性最高的信息，并理解信息之间的关联"。

当前搜索（FTS5 + LIKE）只覆盖报告粒度，不支持跨报告、跨实体、跨证据的统一检索。
知识之间的关联（同一实体出现在哪些报告、哪些观点互相支持或矛盾）完全依赖人工记忆。

**P5 不改变分析引擎，不新增外部搜索引擎，不引入复杂图算法。**
P5 只做两件事：**统一搜索** + **轻量知识图谱**，全部基于 SQLite 实现。

## 二、分阶段计划

### P5-A：统一搜索增强

**目标：** 一次查询可以搜索报告、投资观点、跟踪信号、实体、PDF 证据、视频时间戳证据。

**策略：**
- SQLite FTS5（已有）→ 扩展索引列，覆盖 views/signals/entities/evidence
- LIKE fallback（已有）→ 扩展到多表联合搜索
- metadata filter（新增）：source_type、date range、entity_type、view_direction
- 结果统一排序 + 去重 + relevance 评分

**交付：**
- 新增 `db/unified_search.py` — 统一搜索入口
- 扩展 `db/fts.py` — FTS5 索引包含 evidence/page_number、entities 等
- CLI: `search <query>` 或 `reports search <query> --unified`
- MCP: 新增 `unified_search` tool

**验收标准：**
- [x] 搜索返回 reports + views + signals + entities 混合结果
- [x] 每条结果带 result_type、snippet、relevance_score、report_id、source_type
- [x] FTS5 + LIKE + metadata filter 组合
- [x] 35 专项测试
- [x] MCP `unified_search` tool（第 9 个只读 tool）
- [x] CLI `search` 命令
- [x] ruff clean

### P5-B：轻量知识图谱

**目标：** 从现有 DB 表自动构建知识节点和边，支持实体邻域查询和图导出。

**策略：**
- 两张新表：`knowledge_nodes` + `knowledge_edges`（纯 SQLite）
- 从 reports / entities / investment_views / tracking_signals 重建
- 支持增量更新（新增报告后增量追加节点和边）
- 不做复杂图算法（Louvain、Adamic-Adar 等只预留接口）

**交付：**
- 新增 `db/graph.py` — graph build/query/export
- 新增 `db/models.py` — KnowledgeNode / KnowledgeEdge ORM
- 新增 `db/session.py` — migration
- CLI: `graph build` / `graph export` / `graph neighborhood <entity>`
- MCP: 新增 `get_entity_neighborhood` / `list_graph_edges` / `get_evidence_trail`

**验收标准：**
- [x] 从 seeded_db 可重建完整图谱
- [x] rebuild 幂等（重复运行不产生重复节点/边）
- [x] entity neighborhood 查询返回关联报告、观点、信号
- [x] graph export JSON 可被外部工具导入
- [x] evidence trail 支持 view → evidence → report 链路
- [x] 27 专项测试
- [x] MCP: get_entity_neighborhood / list_graph_edges / get_evidence_trail
- [x] CLI: graph rebuild / neighborhood / evidence-trail / export
- [x] ruff clean

### P5-C：MCP 集成 ✅ 已完成（随 P5-A/B）

4 个 MCP tool 已在 P5-A 和 P5-B 中全部实现，无需单独阶段。

| Tool | 实现阶段 | 状态 |
|------|----------|------|
| `unified_search` | P5-A | ✅ |
| `get_entity_neighborhood` | P5-B | ✅ |
| `list_graph_edges` | P5-B | ✅ |
| `get_evidence_trail` | P5-B | ✅ |

MCP tools 总数：**12 个**（P3-D 8 个 + P5-A 1 个 + P5-B 3 个），全部只读。

### P5-S：收口封板 ✅ 已完成（2026-07-02）

**交付：**
- `docs/P5_ACCEPTANCE_REPORT.md` — 完整验收报告
- 本文档更新 — P5-A/B/C 完成状态
- `docs/SEARCH_ENHANCEMENT_DESIGN.md` — As-Implemented 摘要
- `docs/LIGHTWEIGHT_GRAPH_DESIGN.md` — As-Implemented 摘要
- `README.md` — Search & Graph 小节
- `CHANGELOG.md` — P5-S closeout 条目

- docs/P5_ACCEPTANCE_REPORT.md
- 文档一致性
- ruff + pytest 验证

## 三、与 P3/P4 的关系

```
P3-A ingest_jobs     ← P5 独立：不影响摄入流程
P3-B vault_lint      ← P5 独立：不影响 lint
P3-C review_items    ← P5 可选关联：review items 可出现在图谱中
P3-D mcp_server      ← P5 扩展：新增 4 个 MCP tool
P4-A pdf_extraction  ← P5 受益：PDF evidence 出现在搜索结果和图谱中
P4-B pdf_analysis    ← P5 受益：evidence_page 出现在证据链中
```

P5 不破坏 P3/P4 任何现有功能，仅新增搜索层和图谱层。

## 四、测试策略

```
tests/test_unified_search.py   — 搜索报告/views/signals/entities/evidence、filters、空结果
tests/test_knowledge_graph.py  — 图谱构建/增量更新/neighborhood/export/空图谱
tests/test_mcp_search_graph.py — MCP tool dispatch、返回结构、只读验证
```

预计 ≥70 专项测试。复用现有 fixtures（`seeded_db`, `db_session`）。

## 五、不做事项（P5 明确排除）

| 排除项 | 原因 |
|--------|------|
| **外部向量数据库（LanceDB/Pinecone/Weaviate）** | 保持 SQLite 自包含 |
| **Neo4j / 图数据库** | 两张 SQLite 表足够 |
| **Web UI 搜索/图谱可视化** | 非当前优先 |
| **Deep Research** | 多轮 LLM 编排 |
| **真实 OCR Provider** | P4-D 候选 |
| **写入型 MCP tool** | 安全边界 |
| **自动投资建议** | 项目定位明确排除 |
| **复杂图算法（PageRank/Community Detection）** | 预留接口，不做实现 |
| **实时搜索索引** | FTS5 重建为 batch 操作 |
| **语义搜索 / Embedding** | 不引入向量模型 |
| **跨语言搜索** | 当前只做 CJK + ASCII tokenize |

## 六、依赖

```
不新增任何 pyproject.toml 依赖。
全部基于已有 SQLite + SQLAlchemy + FTS5 实现。
```
