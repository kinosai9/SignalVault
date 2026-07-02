# P3 验收报告

> 日期：2026-07-02 | 状态：P3-S 收口完成

## 一、P3 目标回顾

把 podcast_research 从"可运行的数据处理流水线"升级为"可恢复、可审计、可被 Agent 查询的投资知识库后端"。

P2 解决了"能处理什么"，P3 解决：
- 运行时出问题怎么办（ingest_jobs 持久化）
- 知识库质量怎么保证（vault_lint）
- 发现问题怎么跟踪处理（review_items）
- 怎么让 AI Agent 来查询（mcp_server）

## 二、子阶段交付清单

### P3-A：持久化摄入队列 ✅

| 维度 | 内容 |
|------|------|
| **新增文件** | `sources/ingest_jobs.py`（~500 行，14 个方法） |
| **新增模型** | `IngestJob`（22 列）：身份、状态、预览 JSON、操作、结果、引用、时间戳 |
| **迁移** | `_migrate_ingest_jobs_table` + 部分唯一索引 `(job_key, status) WHERE pending_preview` |
| **架构** | Phase 1 双写：内存 `_preview_store` + SQLite `ingest_jobs`；Dashboard 内存优先、DB 后备 |
| **CLI** | `ingest list/show/retry/resume` |
| **测试** | 54 tests（CRUD、去重、状态迁移、重试、过期、重启恢复、双写、CLI smoke） |

### P3-B：Vault Lint ✅

| 维度 | 内容 |
|------|------|
| **新增文件** | `workspace/vault_lint.py` |
| **Lint Rules** | 5 条：`frontmatter_invalid`, `frontmatter_missing`, `dead_wikilink`, `duplicate_report`, `orphan_card` |
| **CLI** | `vault-lint --vault <path> [--rules/--exclude/--json/--write-review]` |
| **集成** | `--write-review` 自动将 lint 发现写入 `review_items`（去重） |
| **测试** | 27 tests（含于 `test_vault_lint_review.py`） |

### P3-C：Review Queue ✅

| 维度 | 内容 |
|------|------|
| **新增文件** | `sources/review_items.py`（~280 行） |
| **新增模型** | `ReviewItem`（12 列）：类型、严重度、状态、标题、描述、来源、建议操作、处理备注 |
| **状态机** | `open → accepted/skipped/resolved`；`accepted → resolved` |
| **item_type** | 8 种：`lint_*`(5)、`entity_duplicate_candidate`、`patch_review`、`manual` |
| **去重** | 同一 `source_path + item_type + open` 不重复创建 |
| **CLI** | `review list/show/accept/skip/resolve` |
| **测试** | 26 tests（含于 `test_vault_lint_review.py`） |

### P3-D：MCP Server ✅

| 维度 | 内容 |
|------|------|
| **新增文件** | `mcp_server/__init__.py`, `server.py`, `tools.py`, `serializers.py` |
| **MCP Tools** | 8 个只读 tool（见下方） |
| **Transport** | stdio（JSON-RPC） |
| **依赖** | `mcp>=1.0` |
| **CLI** | `mcp-serve [--db-path <path>]` |
| **架构** | Query 函数与 MCP 适配层拆开；核心逻辑无 MCP 依赖可独立单测 |
| **测试** | 71 tests（server smoke、8 tool 查询、handler dispatch、空 DB、只读验证） |

## 三、CLI 命令清单（P3 新增 13 条）

```
# 摄入队列（4 条）
python -m podcast_research ingest list [--type/--status/--limit]
python -m podcast_research ingest show <job_id>
python -m podcast_research ingest retry <job_id>
python -m podcast_research ingest resume

# Vault 健康检查（1 条）
python -m podcast_research vault-lint --vault <path> [--rules/--exclude/--json/--write-review]

# 审核队列（5 条）
python -m podcast_research review list [--type/--status/--limit]
python -m podcast_research review show <item_id>
python -m podcast_research review accept <item_id> [--note]
python -m podcast_research review skip <item_id> [--note]
python -m podcast_research review resolve <item_id> [--note]

# MCP Server（1 条）
python -m podcast_research mcp-serve [--db-path <path>]

# 已有命令（2 条，P3 修改）
python -m podcast_research serve          # 原有，无变更
python -m podcast_research reports *      # 原有，无变更
```

## 四、MCP Tools 清单（8 个，全部只读）

| # | Tool | 功能 | 数据源 |
|---|------|------|--------|
| 1 | `search_reports` | 搜索报告（关键词 + source 过滤） | SQLite FTS5/LIKE |
| 2 | `get_report` | 获取报告详情（含 views/signals/markdown） | reports JOIN episodes |
| 3 | `list_channels` | 列出 YouTube 频道及视频统计 | channels 表 |
| 4 | `search_entities` | 搜索实体（按类型/名称过滤） | entities 表 |
| 5 | `get_entity_profile` | 获取实体详情 + 关联投资观点 | entities + investment_views |
| 6 | `list_investment_views` | 列出投资观点（target/direction/ai_layer） | investment_views 表 |
| 7 | `list_tracking_signals` | 列出跟踪信号（target/status） | tracking_signals 表 |
| 8 | `list_review_items` | 列出审核事项（type/status/severity） | review_items 表 |

所有 tool 返回 JSON-serializable dict/list，含追溯字段（`report_id`, `source_path`, `video_id`, `channel_name`）。默认 limit 10-20，最大 50-100。不存在数据返回结构化 error 而非异常。

## 五、数据表清单

### P3 新增表

| 表 | 阶段 | 列数 | 索引 | 用途 |
|------|------|------|------|------|
| `ingest_jobs` | P3-A | 22 | `uq_ingest_jobs_key_status` (partial), `idx_ingest_jobs_status`, `idx_ingest_jobs_source_type`, `idx_ingest_jobs_expires` | 摄入任务持久化 |
| `review_items` | P3-B/C | 12 | `idx_review_status`, `idx_review_type`, `idx_review_severity` | 统一审核队列 |

### 已有表（P3 未修改结构）

`episodes`, `reports`, `investment_views`, `tracking_signals`, `entities`, `channels`, `channel_videos`, `jobs`, `job_events`, `tracked_sources`, `tracked_source_entries` — 11 张表，P3 未 ALTER。

## 六、测试结果

| 指标 | 数值 |
|------|------|
| **总测试数** | 1563 |
| **P3 新增测试** | 178（54 + 53 + 71） |
| **通过率** | 100%（1563/1563） |
| **ruff** | clean（0 errors） |
| **已知 Warnings** | 2（uvicorn websockets deprecation，P2-O 以来已知，harmless） |

```
tests/test_ingest_jobs.py         — 54 tests (P3-A)
tests/test_vault_lint_review.py   — 53 tests (P3-B/C)
tests/test_mcp_server.py          — 71 tests (P3-D)
其余 1385 tests                   — P0-P2 存量
─────────────────────────────────────────
总计                              1563 tests
```

## 七、残余风险与后续建议

| # | 风险 | 严重度 | 建议 |
|---|------|--------|------|
| 1 | ingest_jobs Phase 1 双写模式，内存+DB 两套状态 | 低 | Phase 2 可完全切换到 DB，移除内存 store |
| 2 | Vault Lint 误报率未在生产环境验证 | 低 | 积累使用数据后调优各 rule 阈值 |
| 3 | Review Queue 无自动分配/提醒 | 低 | 每次 `vault-lint --write-review` 前人工检查已有 open items |
| 4 | MCP 仅查 DB，Vault 文件系统的 Claim/Signal 不在范围 | 中 | P4 可扩展 `search_claims`/`search_signals`（需扫描 Vault 文件） |
| 5 | MCP 无写入 tool，accept/skip/resolve 需 CLI 或 Web | 设计决策 | 保持只读安全边界，写入走现有 CLI 通道 |
| 6 | 无 Deep Research（多轮 LLM 编排） | 范围外 | P4 或独立项目考虑 |

## 八、P3 不做（设计决策记录）

| 排除项 | 决策原因 |
|------|----------|
| 写入型 MCP tool | 安全边界：MCP 保持只读，写入通过 CLI/Web 执行 |
| Deep Research | 需要多轮 LLM 编排 + 外部搜索，超出 P3 范围 |
| 复杂知识图谱（实体关系图、因果链） | 需要独立设计阶段 |
| 桌面 UI（React/Tauri/Electron） | Web Console 已覆盖所有交互 |
| 自动定时任务（cron/scheduler） | 依赖外部调度器，不进项目代码 |
| 向量数据库（LanceDB 等） | RAG 场景未验证 |
| 新增 LLM provider | 保持 OpenAI-compatible 单一接口 |
| Vault 文件系统 MCP tool | 当前 8 个 tool 覆盖 DB 全部核心表，文件扫描留给后续 |

## 九、验收结论

**P3-A/B/C/D 全部验收通过。P3-S 收口完成。**

P3 交付了四项可独立运行、可串联协作的子系统，将 podcast_research 从纯流水线升级为具备持久化恢复、质量审计、人工审核队列和 Agent 可查询能力的知识库后端。

1563 tests 全绿，ruff clean，所有 CLI 命令可用，所有 MCP tool 可被 Claude Code/Codex 发现和调用。
