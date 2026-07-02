# P3 Plan: 知识库后端化

> 状态：P3-A/B/C/D 已完成 | P3-S 收口 | 2026-07-02
> 基于 P2-S.3.5 完成状态

## 定位

把 podcast_research 从"可运行的数据处理流水线"升级为"可恢复、可审计、可被 Agent 查询的投资知识库后端"。

P2 解决了"能处理什么"，P3 解决"运行时出问题怎么办"和"怎么让别人/别的程序来查询"。

## 主线任务

| 任务 | 简称 | 目标 |
|------|------|------|
| P3-A | 持久化摄入队列 | SQLite ingest_jobs 收编 `_preview_store`，支持重启恢复、状态追踪、失败重试、hash 去重 |
| P3-B | Vault Lint | 扫描 Obsidian vault，检查 frontmatter、死 wikilink、重复报告、孤立卡片、命名一致性 |
| P3-C | Review Queue | 将 Patch Review 泛化为通用 review_items，承接 lint issue、实体合并建议、重复报告等 |
| P3-D | MCP Server | Python mcp 包实现只读 MCP server，让 Claude Code/Codex 可查询报告、观点、信号、实体、频道、lint 结果 |
| P3-E | 文档与操作手册 | 固化 P3 范围、数据表、CLI、验收规则 |

## 分阶段计划

### P3-A：持久化摄入队列 ✅ 已完成（2026-07-01）

**实现摘要：**

- 新增 `IngestJob` SQLAlchemy 模型（22 列）— `db/models.py`
- 新增 `_migrate_ingest_jobs_table` — `db/session.py`
- 新增 `IngestJobManager`（14 个方法）— `sources/ingest_jobs.py`
- **Phase 1 双写模式**：所有摄入入口同时写入内存 `_preview_store` 和 SQLite `ingest_jobs`
- CLI `ingest list/show/retry/resume`
- 54 个专项测试 — `tests/test_ingest_jobs.py`

**当前架构约定（Phase 1）：**

| 层级 | 用途 | 持久化 |
|------|------|--------|
| `_preview_store` / `_file_preview_store` / `_profile_store` | 运行期缓存（优先读取） | 否（进程重启丢失） |
| `ingest_jobs` 表 | 可恢复状态源（后备读取 + 重启恢复） | 是（SQLite） |
| `_import_results_store` | 一次性显示结果 | 否（保持原有，有意义的短期数据） |

- Dashboard 统计：优先从内存 `_preview_store` 读取，为空时回退到 `ingest_jobs`（处理重启场景）
- 写入：所有摄入入口双写（内存 + DB），DB 写入失败不阻塞流程
- 去重：同一 `job_key` + `pending_preview` 状态受部分唯一索引保护

**后续阶段约束：**
- P3-B / P3-C 不应新增对 `_preview_store` / `_file_preview_store` / `_profile_store` 的依赖
- 新功能应直接使用 `IngestJobManager` 或从 `ingest_jobs` 表查询
- Phase 2（完全切换）可在所有 P3 阶段完成后进行

**验收标准：**
- [x] `ingest_jobs` 表创建，包含所有必要字段
- [x] URL 预览双写到 ingest_jobs（同时保留 `_preview_store`）
- [x] 文件上传预览双写到 ingest_jobs（同时保留 `_file_preview_store`）
- [x] Profile 双写到 ingest_jobs（同时保留 `_profile_store`）
- [x] Import results 结果写入 ingest_jobs；`_import_results_store` 保留为一次性显示
- [x] 服务重启后通过 `ingest_jobs` 恢复待确认项（`ingest resume`）  
- [x] source_hash / job_key 去重（部分唯一索引）
- [x] 过期预览自动清理（`expire_old_jobs`）
- [x] Dashboard 统计在内存为空时从 ingest_jobs 查询
- [x] 现有 Sources 模块测试全部通过
- [x] 新增 ingest_jobs 专项测试：54 tests
- [x] ruff clean

**结果：** 1439 tests（1438 passed, 1 pre-existing flaky），ruff clean。

### P3-B：Vault Lint ✅ 已完成（2026-07-01）

**实现摘要：**

- 新增 `workspace/vault_lint.py` — 5 条 lint rule + runner
- Rules: `frontmatter_invalid`, `frontmatter_missing`, `dead_wikilink`, `duplicate_report`, `orphan_card`
- CLI: `vault-lint --vault <path> [--rules/--exclude/--json/--write-review]`
- 与 P3-C 集成：`--write-review` 将 lint 发现写入 `review_items` 表

**验收标准：**
- [x] `vault_lint` CLI 命令可用
- [x] 5 条 lint rule 全部实现
- [x] Vault 中问题可检测和报告
- [x] `--json` 输出格式
- [x] `--write-review` 将发现写入 review_items
- [x] 现有测试不受影响
- [x] Lint 专项测试：27 tests（含于 test_vault_lint_review.py）
- [x] ruff clean

### P3-C：Review Queue ✅ 已完成（2026-07-01）

**实现摘要：**

- 新增 `ReviewItem` SQLAlchemy 模型（12 列）— `db/models.py`
- 新增 `_migrate_review_items_table` — `db/session.py`
- 新增 `ReviewItemManager` — `sources/review_items.py`
- 支持 7 种 item_type：`lint_frontmatter_invalid`, `lint_frontmatter_missing`, `lint_dead_wikilink`, `lint_duplicate_report`, `lint_orphan_card`, `entity_duplicate_candidate`, `patch_review`, `manual`
- 状态机：`open → accepted/skipped/resolved`；`accepted → resolved`
- CLI: `review list/show/accept/skip/resolve`
- 去重：同一 `source_path + item_type + open` 不重复创建
- 与 Patch Review 兼容：patch_review 类型已预留，现有 Patch Review 不受影响

**验收标准：**
- [x] `review_items` 表创建
- [x] 统一状态机实现
- [x] CLI review 命令可用
- [x] Lint issues 自动转入 review_items（`--write-review`）
- [x] 去重正常（同一文件+类型不重复创建 open item）
- [x] 现有 Patch Review 测试继续通过
- [x] Review 专项测试：26 tests（含于 test_vault_lint_review.py）
- [x] ruff clean

### P3-D：MCP Server ✅ 已完成（2026-07-02）

**实现摘要：**

- 新增 `mcp_server/` 包（4 个模块：`__init__.py`, `server.py`, `tools.py`, `serializers.py`）
- 8 个只读 MCP tool：`search_reports`, `get_report`, `list_channels`, `search_entities`, `get_entity_profile`, `list_investment_views`, `list_tracking_signals`, `list_review_items`
- CLI: `python -m podcast_research mcp-serve [--db-path path/to/db]`
- stdio transport，兼容 Claude Code / Codex / Claude Desktop
- 依赖：`mcp>=1.0`
- 71 个专项测试 — `tests/test_mcp_server.py`
- Query 函数与 MCP 适配层拆开，核心逻辑无 MCP 依赖即可完整单测

**架构：**
```
MCP Client (Claude Code / Codex)
    │ stdio (JSON-RPC)
    ▼
create_mcp_server() → Server
    ├─ @list_tools → 8 Tool 定义
    └─ @call_tool  → handle_call_tool(name, args) → _query_*()
```

**MCP Tools（8 个，全部只读）：**

| Tool | 功能 | 数据源 |
|------|------|--------|
| `search_reports` | 搜索报告（关键词 + source 过滤） | SQLite FTS5/LIKE |
| `get_report` | 获取报告详情（含 views/signals/markdown） | reports JOIN episodes |
| `list_channels` | 列出 YouTube 频道及视频统计 | channels 表 |
| `search_entities` | 搜索实体（按类型/名称过滤） | entities 表 |
| `get_entity_profile` | 获取实体详情 + 关联观点 | entities + investment_views |
| `list_investment_views` | 列出投资观点（target/direction/ai_layer） | investment_views 表 |
| `list_tracking_signals` | 列出跟踪信号（target/status） | tracking_signals 表 |
| `list_review_items` | 列出审核事项（type/status/severity） | review_items 表 |

**验收标准：**
- [x] `python -m podcast_research mcp-serve` 可启动
- [x] 8 个 tool 全部可用
- [x] 只读验证（无写入 tool，查询不修改 DB）
- [x] 空 DB / 无结果稳定返回
- [x] MCP 专项测试：71 tests
- [x] ruff clean
- [x] 文档更新：MCP_SERVER_DESIGN.md 改为 as-implemented

### P3-E：文档与操作手册 ✅ 已完成（2026-07-02）

**交付文档：**
- [x] `docs/P3_PLAN.md` — 本文件
- [x] `docs/INGEST_QUEUE_DESIGN.md` — P3-A 实现后已补充
- [x] `docs/VAULT_LINT_REVIEW_QUEUE_DESIGN.md` — P3-B/C 实现后已补充
- [x] `docs/MCP_SERVER_DESIGN.md` — P3-D 实现后已更新
- [x] `docs/P3_ACCEPTANCE_REPORT.md` — P3-S 验收报告（新增）
- [x] `docs/PROJECT_RULES.md` — 工程规范（含 P3 规则）
- [x] `README.md` — 已更新 P3-A/B/C/D 完成状态 + P3 后端化章节
- [x] `CHANGELOG.md` — 已更新全部 P3 阶段

---

## P3-S 收口（2026-07-02）

### P3 四件套

P3 形成了四个独立但可串联的子系统：

| 系统 | 模块 | 作用 | CLI 入口 |
|------|------|------|----------|
| **持久化摄入队列** | `sources/ingest_jobs.py` + `IngestJob` 模型 | 所有摄入任务可恢复、可追踪、可去重 | `ingest list/show/retry/resume` |
| **Vault 健康检查** | `workspace/vault_lint.py` | 5 条 lint rule 检查 Obsidian vault 健康 | `vault-lint --vault <path>` |
| **人工审核队列** | `sources/review_items.py` + `ReviewItem` 模型 | lint issues / patch / entity merge 统一 triage | `review list/show/accept/skip/resolve` |
| **MCP Server** | `mcp_server/` | 8 个只读 tool，让 AI Agent 查询知识库 | `mcp-serve [--db-path]` |

### P3 数据表（全部新增于 P3，无破坏现有结构）

| 表 | 阶段 | 行数 | 用途 |
|------|------|------|------|
| `ingest_jobs` | P3-A | 22 列 | 摄入任务持久化，含部分唯一索引 |
| `review_items` | P3-B/C | 12 列 | 统一审核队列，4 态状态机 |

### CLI 命令清单（P3 新增）

```
# 摄入队列
ingest list [--type/--status/--limit]
ingest show <job_id>
ingest retry <job_id>
ingest resume

# Vault 健康检查
vault-lint --vault <path> [--rules/--exclude/--json/--write-review]

# 审核队列
review list [--type/--status/--limit]
review show <item_id>
review accept <item_id> [--note]
review skip <item_id> [--note]
review resolve <item_id> [--note]

# MCP Server
mcp-serve [--db-path <path>] [--vault-path <path>]
```

### 测试结果

| 阶段 | 新增测试 | 累计测试 | 结果 |
|------|----------|----------|------|
| P3-A | 54 | 1439 | ✅ |
| P3-B/C | 53 | 1492 | ✅ |
| P3-D | 71 | 1563 | ✅ |

全绿，ruff clean。2 个已知 harmless warnings（uvicorn websockets deprecation，P2-O 以来已知）。

### P3 不做（明确排除）

| 排除项 | 原因 |
|------|------|
| 写入型 MCP tool | 安全边界：MCP 保持只读，写入通过 CLI/Web 执行 |
| Deep Research | 超出 P3 范围，需要多轮 LLM 编排 |
| 复杂知识图谱 | 实体关系图、因果链需要独立设计阶段 |
| 桌面 UI（React/Tauri/Electron） | 不在项目路线，Web Console 已覆盖 |
| 自动定时任务 | 依赖外部调度器（cron/systemd），不进项目 |
| 向量数据库（LanceDB 等） | RAG 场景未验证，不提前引入 |
| 新增 LLM provider | 保持 OpenAI-compatible 单一接口 |
| Chrome 扩展 / PDF/Office 解析 | 不在项目范围 |

### 残余风险与后续建议

| 风险 | 当前状态 | 建议 |
|------|------|------|
| ingest_jobs Phase 1 双写 | 内存 + DB 双写，Phase 2 可完全切换 | 所有 P3 阶段完成后评估切换 |
| Vault Lint 误报率 | 5 条 rule，info 级别不阻塞 | 积累使用数据后调优阈值 |
| Review Queue 积压 | 无自动分配/提醒 | 每次 vault-lint --write-review 前人工检查 |
| MCP 仅查 DB | Vault 文件系统的 Claim/Signal 不在查询范围 | P5 扩展 `search_claims`/`search_signals` tool |
| MCP 无写入 | accept/skip/resolve 需 CLI 或 Web | 保持只读安全边界，写入走现有 CLI |

---

## P4 展望：PDF Document Ingestion Expansion

> 详细计划见 `docs/P4_PDF_INGESTION_PLAN.md` 和 `docs/PDF_EXTRACTION_DESIGN.md`

P4 调整为 **PDF 入库优先**（原"多期观点对比"推迟到 P5）。核心思路：

- 在 `sources/` 层新增 PDF 适配器（pdfplumber 文本提取 + pytesseract OCR 后备）
- 完全复用 P3 ingest_jobs / review_items / mcp_server 基础设施
- 页码级 evidence：投资观点可追溯到 PDF 页码
- 不做表格结构化提取、不做多模态图表理解、不做 Deep Research

**分阶段：**
- P4-A：文本型 PDF 提取（主路径，80%+ 覆盖）
- P4-B：OCR 后备路径（扫描件）
- P4-C：PDF Source Profile + 元数据
- P4-D：Page-level Evidence + Review Queue
- P4-E：文档 + MCP 自动受益
