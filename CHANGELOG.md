# Changelog

## Unreleased

### P7-D — Diagnostic Bundle Export (2026-07-03)

**Implemented:**
- `diagnostics/bundle.py` — `DiagnosticBundleBuilder` producing timestamped zip with 9 files
- `DiagnosticBundleConfig` / `DiagnosticBundleResult` dataclasses
- `redact_value()` / `redact_dict()` / `redact_list()` — recursive redaction with 3-tier policy:
  - REDACT_KEYS (12 keys): api_key, token, password, secret, cookie, etc. → `[REDACTED]`
  - TRUNCATE_KEYS (8 keys): content_text, source_quote, report_markdown, etc. → `[N chars redacted]`
  - EXISTENCE_KEYS (3 keys): vault_path, db_path, data_dir → true/false
- 9 bundle files: manifest.json, diagnostics_summary.json, operation_logs.json, review_items_summary.json, ingest_jobs_summary.json, config_summary.json, system_info.json, search_graph_summary.json, README.txt
- CLI: `podcast-research diagnostics bundle --output <path> --limit-logs <n> --json`
- Bundle export records `system.diagnostics` operation log
- All using stdlib `zipfile` — no external dependencies
- `export_diagnostic_bundle()` convenience function

**Tests:** 34 new in `tests/test_diagnostic_bundle.py` (11 redaction + 13 creation + 5 redaction-in-bundle + 4 CLI + 1 convenience)
**Ruff:** Clean

### P7-C — Diagnostics Center Backend (2026-07-03)

**Implemented:**
- `diagnostics/summary.py` — `DiagnosticsCenter.get_summary()` aggregating 9 subsystems
- `SubsystemStatus` dataclass: name, label, status (ok/attention/blocked/unknown), summary, counts, issues, suggested_actions
- `DiagnosticsSummary` dataclass: overall_status, 9 subsystems, recent_failures, open_review_count, blocked_count, attention_count, suggested_actions
- `RecoveryAction` dataclass + 9 registered actions (install zsxq-cli, login zsxq, refresh groups, retry ingest, review items, vault lint, rebuild graph, configure LLM, handle PDF OCR)
- 9 subsystem checks: ingest, review, operations, zsxq, pdf, vault, search, graph, config
- Overall status computation: blocked > attention (=any open review) > ok
- CLI: `podcast-research diagnostics summary` (--json)
- CLI: `podcast-research doctor` (alias for diagnostics summary)
- Operation logging: diagnostics summary records `system.diagnostics` operation
- All checks work with mock/fresh DB, no real zsxq-cli/API key required

**Tests:** 28 new in `tests/test_diagnostics_summary.py` (all mock)
**Ruff:** Clean
**Full suite:** 1847 passed

### P7-A/B — Error Taxonomy + Operation Log (2026-07-03)

**Implemented:**

P7-A: Error Taxonomy (`diagnostics/errors.py`)
- `ErrorSeverity` enum: info / warning / error / blocker
- `ErrorCategory` enum: 11 categories (source / auth / permission / extraction / analysis / llm / database / vault / search_graph / mcp / config)
- `ErrorRecord` dataclass: 18 fields (error_code, category, severity, user_message, technical_detail, suggested_actions, related_command, source_type, entity_ref, create_review_item, review_item_type, metadata, etc.)
- `ErrorCodeRegistry`: register, get, list_all, list_by_category, list_by_severity, list_by_source_type, count
- 30 built-in error codes covering P3-P6 scenarios
- `create_error_record()` — factory with template + runtime context
- `map_exception_to_error()` — 7 Python exception types → error_code mapping
- `review_item_to_error_record()` — 13 review item_types → error_code mapping
- All user_messages in Chinese, all codes have suggested_actions

P7-B: Operation Log (`diagnostics/operation_log.py`)
- `OperationLog` ORM in `db/models.py` — 16 columns + 4 indexes
- `_migrate_operation_logs_table()` in `db/session.py` — auto-creates on init_db
- `OperationLogManager`: start, succeed, fail, get, list_operations, count_by_status, recent_failures
- 24 VALID_OPERATION_TYPES (zsxq/pdf/ingest/vault/review/search/graph/mcp/system)
- `_sanitize_metadata()` — redacts api_key/token/password/secret + trims content_text/source_quote
- duration_ms auto-computed on succeed/fail
- CLI: `logs list` (--status, --type, --limit, --json) + `logs show <id>` (prefix matching)

Operation log wiring (key CLI paths):
- `graph rebuild` — wired with success/failure logging
- `zsxq doctor` — wired with success/failure + error_code
- `zsxq analyze` — wired with success/failure + error_code

**Tests:** 48 new (28 error taxonomy + 20 operation log), all mock
**Ruff:** Clean

### P7 Planning — User-facing Reliability & Diagnostics (2026-07-03)

**规划文档（本轮只更新文档，不写业务代码）：**
- `docs/P7_RELIABILITY_DIAGNOSTICS_PLAN.md` — P7 整体计划：定位、现状评估、设计原则、6 阶段交付范围、分阶段计划、模块结构、DB 变更、测试策略、边界、与 Codex 对接点
- `docs/ERROR_TAXONOMY_DESIGN.md` — P7-A 统一错误分类体系：ErrorRecord 数据结构、11 大类别 40+ error_code、ErrorCodeRegistry、与 review_items 映射、现有 error_type 迁移表
- `docs/OPERATION_LOG_DESIGN.md` — P7-B 操作日志：OperationLog 数据模型、22+ operation types、OperationLogManager CRUD、生命周期示例
- `docs/DIAGNOSTIC_BUNDLE_DESIGN.md` — P7-C/D 诊断中心 + 诊断包：DiagnosticsSummary 9 子系统、overall_status 判定、Bundle 10 文件结构、Redaction 规则、Recovery Actions 注册表、CLI 命令设计、Web/API 对接

**设计亮点：**
- 统一 error_code 格式：`CATEGORY_SUBCATEGORY_NNN`（如 `AUTH_ZSXQ_001`）
- Operation Log 覆盖 22+ 操作类型，独立于 JobEvent
- 诊断包脱敏规则：绝对不包含密钥/原文/隐私字段
- CLI + Web 共用数据结构，Codex 前端可直接消费
- Recovery Actions：8 个常见问题的标准恢复动作

**P7 边界：**
- 不做前端 UI 实现（属 Codex 侧）
- 不做自动修复、远程上报、性能 profiling
- 不改 analysis prompt、不新增信息源

### P6-S — Closeout: Acceptance Report & Documentation (2026-07-03)

**Delivered:**
- `docs/P6_ACCEPTANCE_REPORT.md` — 完整验收报告：目标、交付清单、CLI 命令、数据模型、review items、pipeline 链路、auto-benefits、测试结果、未做事项、P6-B 候选
- `docs/P6_ZSXQ_CONNECTOR_PLAN.md` — 更新：P6-A1/A2 标记完成，P6-S Closeout，P6-B 候选明确边界
- `docs/ZSXQ_CONNECTOR_DESIGN.md` — 新增 §11 As-Implemented 摘要（模块结构、evidence 传递、只读边界）
- `README.md` — 整理 ZSXQ 使用工作流（7 步）、分析链路、数据追溯、安全边界表
- 命名一致性检查通过：`source_type=zsxq_topic` 统一贯穿所有模块
- 1771 tests passed，ruff clean

### P6-A2 — ZSXQ Topic Analysis Pipeline (2026-07-03)

**Implemented:**
- `sources/zsxq_analysis.py`: ZSXQ topic → LLM analysis pipeline — `analyze_zsxq_topic()`, `build_zsxq_analysis_source()`, `_check_zsxq_analysis_eligibility()`, `_topic_to_segments()`, `import_and_analyze()`
- Reuses existing `_run_pipeline()` from `analysis/pipeline.py` — no new LLM pipeline
- Eligibility checks: empty/short content, inactive group, attachment-only, minimal quality, missing key fields
- 3 new review item types: `zsxq_analysis_skipped`, `zsxq_content_too_short`, `zsxq_evidence_missing`
- Evidence design: source_type=zsxq_topic, source_url, group_id, topic_id via source_info; page_number=None, timestamp=None
- Report metadata: group_id, group_name, topic_id, topic_title, author_name, create_time, source_url, content_hash in source_info
- `_infer_source_type()` extended in `repository.py` and `unified_search.py` to recognize `zsxq_topic`
- `_build_source_nodes()` extended in `knowledge_graph.py` to include ZSXQ source nodes
- CLI: `zsxq analyze --group-id <id> --topic-id <id> --mock --focus --output --depth`
- Tests: 39 new in `tests/test_zsxq_analysis.py` (all mock, no real CLI/network/LLM)
- Coverage: topic→segments, eligibility, mock pipeline, report metadata, evidence traceability, review items, CLI smoke, unified_search, knowledge_graph rebuild

**Boundary (still read-only):**
- No search-groups / api raw/call
- No posting/commenting/liking/deleting
- No attachment download/OCR
- No Web UI / new MCP tool / new external dependency
- No scheduled scanning

### P6-A1 — ZSXQ Read-only Subscription Import (2026-07-02)

**Implemented:**
- `sources/zsxq_models.py`: ZsxqGroup, ZsxqTopic, ZsxqSourceProfile dataclasses + compute_content_hash
- `sources/zsxq_cli.py`: zsxq-cli wrapper (subprocess) — check_cli(), list_groups(), fetch_topic(), fetch_topics() + 4 exception types
- `sources/zsxq_registry.py`: JSON-file group registry — list_registry(), get_group(), refresh_registry() (added/reactivated/deactivated/unchanged)
- `sources/zsxq_import.py`: topic import — build_zsxq_source_profile() + import_topic_to_ingest() + sync_group_to_ingest() with error→review mapping
- `ingest_jobs.py`: source_type="zsxq_topic"
- `review_items.py`: 5 new item_types (zsxq_cli_missing, zsxq_auth_required, zsxq_permission_denied, zsxq_parse_failed, zsxq_attachment_unsupported)
- CLI: zsxq doctor / groups (--refresh) / import-topic / sync
- Tests: 29 new in `tests/test_zsxq_import.py` (all mock, no real CLI/network)
- Registry: JSON file at data/zsxq_groups.json, access_status tracking, historical data preserved

**Not yet:**
- LLM analysis pipeline integration (topic → _run_pipeline)
- Attachment download/OCR

### P6 Planning — ZSXQ Read-only Subscription Import (2026-07-02)

P6 路线明确：P6-A 定位为知识星球只读订阅导入，不是 ZSXQ 客户端。

**规划文档：**
- `docs/P6_ZSXQ_CONNECTOR_PLAN.md` — 高层计划：定位、复用 P3/P4/P5、CLI 范围（允许/禁止）、数据边界、接入方式、入库策略、内容使用边界、排除项
- `docs/ZSXQ_CONNECTOR_DESIGN.md` — 详细设计：ZsxqTopic/ZsxqSourceProfile 数据模型、zsxq-cli wrapper、source profile、ingest_jobs 复用、analysis pipeline 接入、review items、CLI 命令设计

**核心约束：**
- 唯一接入方式：官方 `zsxq-cli`，不使用社区逆向工具、不抓 cookie、不反编译 API
- 只读导入用户已订阅内容；不做订阅/发布/评论/运营
- 订阅/取消订阅只在官方客户端完成；本项目提供手动刷新授权范围
- Group registry：本地 `zsxq_groups` 表，`access_status` 标记 active/inaccessible
- 权限消失的星球不删除历史数据；重新订阅后可恢复 active
- 不做定时扫描 — 刷新由用户手动触发
- 不保存成员列表、手机号、私信等用户隐私字段
- source_type = "zsxq_topic"，content_hash 去重
- 5 种新 review item_type：cli_missing / auth_required / permission_denied / parse_failed / attachment_unsupported
- CLI: zsxq doctor / groups (--refresh) / import-topic / sync / analyze
- 不规划：search-groups / subscribe / topic create-edit-delete / comment-reply-like / member search / admin
- unified_search 和 knowledge_graph 自动受益，无需修改

### P5-S — Closeout & Documentation Consolidation (2026-07-02)

**Done:**
- `docs/P5_ACCEPTANCE_REPORT.md`: comprehensive acceptance report — P5-A/B/C deliverables, data model changes, CLI/MCP inventories, graph data flow, evidence trail example, test results (1703 passed), exclusion list
- `docs/P5_SEARCH_GRAPH_PLAN.md`: P5-C marked complete (delivered within P5-A/B), P5-S closeout section added
- `docs/SEARCH_ENHANCEMENT_DESIGN.md`: as-implemented summary (FTS5 + LIKE + metadata filter + CLI/MCP)
- `docs/LIGHTWEIGHT_GRAPH_DESIGN.md`: as-implemented summary (6 node builders, 4 edge builders, 7 node types, 7 edge types, reserved algorithm stubs)
- `README.md`: consolidated "Search & Graph" section with CLI examples and full 12-tool MCP inventory
- `CHANGELOG.md`: this entry

**P5 Final State:**
```
P5-A  Unified Search             — FTS5+LIKE, UnifiedSearchResult, CLI search, MCP unified_search
P5-B  Lightweight Knowledge Graph — knowledge_nodes/edges, rebuild, neighborhood, evidence trail, export
P5-C  MCP Integration            — delivered within P5-A/B; 12 total read-only MCP tools
P5-S  Closeout                   — acceptance report, documentation consolidation
```

**Naming unified:**
- P5-A: Unified Search Enhancement
- P5-B: Lightweight Knowledge Graph
- P5-C: MCP Integration (completed as part of P5-A/B)
- P5-S: Closeout

### P5-B — Lightweight Knowledge Graph (2026-07-02)

**Implemented:**
- `db/models.py`: `KnowledgeNode` (10 columns) + `KnowledgeEdge` (16 columns) SQLAlchemy models
- `db/session.py`: `_migrate_knowledge_graph_tables` + 5 indexes
- `db/knowledge_graph.py` (~420 lines): `rebuild_knowledge_graph()` (6 node builders, 4 edge builders) + `get_entity_neighborhood()` + `get_evidence_trail()` + `list_graph_edges()` + `export_graph_json()`
- 7 node types: report, source, company, topic, person, investment_view, tracking_signal, evidence
- 7 edge types: mentioned_in, derived_from, supports, related_to, tracks, cites_page, cites_timestamp
- Rebuild is idempotent (node_key/edge_key dedup)
- CLI: `graph rebuild` / `graph neighborhood <entity>` / `graph evidence-trail --view <id>` / `graph export`
- MCP: `get_entity_neighborhood` / `list_graph_edges` / `get_evidence_trail` (12 total MCP tools)
- Tests: 27 new in `tests/test_knowledge_graph.py`

**Not yet:**
- Complex graph algorithms (Louvain, Adamic-Adar, PageRank) — interfaces reserved
- Graph visualization UI
- Obsidian vault scan for graph construction

### P5-A — Unified Search Enhancement (2026-07-02)

**Implemented:**
- `db/unified_search.py`: `UnifiedSearchResult` dataclass (22 fields) + `unified_search()` entry point + `_unified_search_like()` (4-table fallback) + `_unified_search_fts()` (FTS5 path) + `serialize_unified_result()`
- Search across reports, investment_views, tracking_signals, entities with a single query
- Metadata filters: result_type, source_type, entity_type, view_direction, signal_status
- Lightweight relevance scoring via matched field heuristics
- `_clean_snippet()` context extraction
- CLI: `search <query>` command (--type/--source-type/--entity-type/--direction/--signal-status/--json/--limit)
- MCP: `unified_search` tool (9th read-only MCP tool)
- Tests: 35 new in `tests/test_unified_search.py`

**Architecture:**
```
search "NVIDIA GPU"
  → unified_search()
    → FTS5 (Fast) → LIKE fallback (Always available)
    → Metadata filters on top
    → UnifiedSearchResult[] sorted by relevance_score
```

**Not yet:**
- Vector search / embedding
- knowledge_nodes / knowledge_edges (P5-B)
- entity_neighborhood / graph_edges / evidence_trail MCP tools

### P5 Planning — Search Enhancement + Lightweight Knowledge Graph (2026-07-02)

P5 规划启动：在已入库的报告/观点/信号/实体/PDF 证据基础上，构建统一搜索层和轻量知识图谱。

**规划文档：**
- `docs/P5_SEARCH_GRAPH_PLAN.md` — 高层计划：P5-A 搜索增强 / P5-B 轻量图谱 / P5-C MCP 集成 / P5-S 收口
- `docs/SEARCH_ENHANCEMENT_DESIGN.md` — 统一搜索设计：FTS5+LIKE+Metadata Filter 三层架构、UnifiedSearchResult schema、跨类型 relevance 评分、MCP unified_search tool
- `docs/LIGHTWEIGHT_GRAPH_DESIGN.md` — 轻量图谱设计：knowledge_nodes + knowledge_edges 两张 SQLite 表、8 种节点类型、11 种边类型、entity neighborhood 查询、evidence trail、graph export JSON

**核心设计决策：**
- 纯 SQLite：不引入向量数据库、Neo4j、外部搜索引擎
- 图可重建 + 增量更新：从现有 DB 表 batch rebuild，按 report 增量追加
- 不做复杂图算法：Louvain、Adamic-Adar、PageRank 仅预留接口
- 4 个新 MCP tool（全部只读）：unified_search / get_entity_neighborhood / list_graph_edges / get_evidence_trail
- 复用现有 FTS5 + CJK tokenize，扩展 view/signal/entity 三级 FTS 表
- 不新增 pyproject.toml 依赖

### P4-S — Closeout & Documentation Consolidation (2026-07-02)

**Done:**
- `docs/P4_ACCEPTANCE_REPORT.md`: comprehensive acceptance report — P4-A/B deliverables, CLI command list, data model changes, page-level evidence trace, quality gate behavior, OCR boundary, MCP auto-benefit, test results (1641 passed)
- `docs/P4_PDF_INGESTION_PLAN.md`: P4-S closeout section; phased naming unified (P4-A Extraction / P4-B Analysis / P4-S Closeout); future P4-C/D candidates noted
- `docs/PDF_EXTRACTION_DESIGN.md`: as-implemented summary section added covering both phases, evidence flow, quality gate table
- `README.md`: "PDF 入库工作流" section replacing single-phase description — covers preview→extract→analyze→review→MCP query
- `CHANGELOG.md`: this entry

**P4 Final State:**
```
P4-A  PDF Extraction       — pdfplumber text extraction, quality grading, ingest_jobs, review_items
P4-B  PDF Analysis + Page  — analysis pipeline, page-level evidence, quality gate, MCP serializers
P4-S  Closeout             — acceptance report, documentation consolidation
```

**Naming unified:**
- P4-A: PDF Extraction
- P4-B: PDF Analysis + Page-level Evidence
- P4-S: Closeout

**Future candidates (not in current scope):**
- P4-C: Web upload + non-technical user entry
- P4-D: OCR Provider implementation

### P4-B — PDF Analysis Pipeline + Page-level Evidence (2026-07-02)

**Implemented:**
- `sources/pdf_analysis.py`: `analyze_pdf()` entry point + `build_pdf_source_profile()` + `_pages_to_segments()` + `_check_analysis_eligibility()`
- Page-to-segment conversion: each PDF page → SubtitleSegment with `segment_id="page_N"`, `start_time="p.{N}"` carrying page numbers through the pipeline
- Quality gating: minimal/failed PDFs skip analysis → review_items (pdf_analysis_skipped)
- `analysis/models.py`: Evidence.page_number: int | None
- `db/models.py`: InvestmentViewRecord.evidence_page: int | None (nullable)
- `db/session.py`: migration for evidence_page column
- `db/repository.py`: save_investment_views stores evidence_page; get_report_detail returns it
- `sources/review_items.py`: 2 new item_types — pdf_analysis_skipped, pdf_evidence_missing
- `mcp_server/serializers.py`: serialize_investment_view returns evidence_page; serialize_report_detail returns source_file/source_hash/page_count
- CLI: `pdf analyze <path>` (--mock/--no-mock, --focus, --write-review, --output, --db-path)
- Tests: 31 new in `tests/test_pdf_analysis.py`

**Architecture:**
```
PDF → extract_pdf() → build_pdf_source_profile() → _check_analysis_eligibility()
  → quality gate → _pages_to_segments() → _run_pipeline() (existing)
  → report + views + signals (with evidence_page)
```

### P4-A — PDF Text Extraction & Source Profile (2026-07-02)

**Implemented:**
- `sources/pdf_extraction.py`: PdfPage, PdfMetadata, PdfExtractionResult dataclasses + `extract_pdf()` (pdfplumber-based, page-level) + `try_ocr_pdf()` (OCR skeleton, graceful degrade) + `build_pdf_review_findings()` (review integration)
- `ingest_jobs` extended: `source_type="pdf_upload"`, job_key `pdf_upload:{content_hash}`
- `review_items` extended: 3 new item_types — `pdf_needs_ocr`, `pdf_quality_issue`, `pdf_extraction_failed`
- CLI: `pdf preview <path>` / `pdf extract <path>` (--json, --write-review, --output, --db-path)
- Dependency: `pdfplumber>=0.11`
- Tests: 47 new in `tests/test_pdf_extraction.py`

**OCR Strategy Clarified (2026-07-02 documentation update):**
- P4 defaults to text-based PDF; scanned/low-text PDFs are not in P4-A mandatory scope
- Scanned PDFs are marked `needs_ocr=True` and enter Review Queue — no automatic OCR call
- No local heavy OCR (tesseract/PaddleOCR) required by default
- Future OCR will use pluggable provider architecture with user-supplied API keys
- OCR providers (Tencent/Aliyun/Azure/Google/Mistral/OpenAI Vision) are candidates only
- No API key is built-in; no external request is made unless user explicitly configures a provider
- P4-A does NOT: full OCR, table extraction, chart understanding, Deep Research, external API integration, file upload to external services

**Not yet:**
- Full LLM analysis pipeline integration
- Table/chart structured extraction
- OCR provider implementation (skeleton only)

### P4 Planning — PDF Document Ingestion Expansion (2026-07-02)

P4 路线调整：原"多期观点对比"推迟到 P5，P4 改为 **PDF 文档入库优先**。

**规划文档：**
- `docs/P4_PDF_INGESTION_PLAN.md` — 高层计划：定位、分阶段、复用 P3 基础设施、测试策略、排除项
- `docs/PDF_EXTRACTION_DESIGN.md` — 详细设计：双路径提取、数据模型、OCR 后备、页码 evidence、Review Queue 集成

**核心设计决策：**
- PDF 适配在 `sources/` 层完成，不侵入 `analysis/`、`llm/`、`db/` 核心
- 文本提取主路径（pdfplumber）+ OCR 后备（pytesseract），自动降级
- 复用 P3 ingest_jobs（`source_type="pdf_upload"`）、review_items（`pdf_quality_issue` / `pdf_needs_ocr`）
- 页码级 evidence：`InvestmentViewRecord.evidence_page`，`Evidence.page_number`
- OCR 为 optional dependency，无 Tesseract 环境 graceful degrade
- 不做：表格结构化、图表理解、Deep Research、写入型 MCP

**分阶段：**
- P4-A：文本型 PDF 提取
- P4-B：OCR 后备路径
- P4-C：PDF Source Profile + 元数据
- P4-D：Page-level Evidence + Review Queue
- P4-E：文档 + 收口

## P3-A — Persistent Ingest Job Queue (2026-07-01)

P3 定位：把 podcast_research 从"可运行的数据处理流水线"升级为"可恢复、可审计、可被 Agent 查询的投资知识库后端"。

### P3-A Done
- **IngestJob model**: 22-column SQLAlchemy model (`db/models.py`) — identity, status, preview JSON, action, result, references, timestamps
- **Migration**: `_migrate_ingest_jobs_table` with partial UNIQUE index on `(job_key, status) WHERE pending_preview` for dedup
- **IngestJobManager**: 14 methods in `sources/ingest_jobs.py` — create, find, list, confirm, mark_failed, retry, resume, expire, count
- **Dual-write (Phase 1)**: All four ingest entry points write to both memory stores and `ingest_jobs`:
  - URL import preview/confirm
  - File upload preview/confirm  
  - Tracked source profile/create
  - Tracked source entry refresh/import
- **Dashboard**: falls back to `ingest_jobs` counts when memory stores are empty (restart recovery)
- **CLI**: `ingest list/show/retry/resume` commands
- **Tests**: 54 new tests in `tests/test_ingest_jobs.py` — CRUD, dedup, status transitions, retry, expiry, restart recovery, dual-write, CLI smoke
- **Result**: 1439 tests (1438 passed, 1 pre-existing flaky), ruff clean

## P3-B/C — Vault Lint + Review Queue (2026-07-01)

### P3-B Vault Lint Done
- **5 lint rules** in `workspace/vault_lint.py`: frontmatter_invalid, frontmatter_missing, dead_wikilink, duplicate_report, orphan_card
- **CLI**: `vault-lint --vault <path>` with `--rules`, `--exclude`, `--json`, `--write-review` flags
- **Runner**: `run_vault_lint()` returns structured findings dict; `write_lint_to_review()` batch-creates review items
- **Integration**: `--write-review` auto-creates review_items with dedup (same source_path + item_type + open)

### P3-C Review Queue Done
- **ReviewItem model**: 12-column SQLAlchemy model (`db/models.py`) — item_type, severity, status, title, description, source_ref, source_path, suggested_action_json, resolution_note, timestamps
- **Migration**: `_migrate_review_items_table` with indexes on status, item_type, severity
- **ReviewItemManager** (`sources/review_items.py`): create_item, create_from_lint_findings, list_items, get_item, count_by_status, accept/skip/resolve
- **Status machine**: `open → accepted | skipped | resolved`; `accepted → resolved`
- **8 item_types**: lint_frontmatter_invalid, lint_frontmatter_missing, lint_dead_wikilink, lint_duplicate_report, lint_orphan_card, entity_duplicate_candidate, patch_review, manual
- **Dedup**: Same source_path + item_type + open → skip creation on re-lint
- **CLI**: `review list/show/accept/skip/resolve`
- **Patch Review compat**: `patch_review` item_type reserved; existing Patch Review system untouched

### Test Results
- **53 new tests** in `tests/test_vault_lint_review.py`
- **1492 total tests**, all pass
- **2 warnings** — known harmless: uvicorn websockets deprecation (pre-existing since P2-O), no action needed
- ruff clean

## P3-D — MCP Server (2026-07-02)

### Done
- **mcp_server package** (`src/podcast_research/mcp_server/`): 4 modules — `__init__.py`, `server.py`, `tools.py`, `serializers.py`
- **8 read-only MCP tools**: `search_reports`, `get_report`, `list_channels`, `search_entities`, `get_entity_profile`, `list_investment_views`, `list_tracking_signals`, `list_review_items`
- **Architecture**: Query functions (`_query_*()`) decoupled from MCP adapter layer (`handle_call_tool()`), enabling full unit testing without MCP dependency
- **Transport**: stdio (JSON-RPC), compatible with Claude Code / Codex / Claude Desktop
- **CLI**: `python -m podcast_research mcp-serve [--db-path path/to/db]`
- **Dependency**: `mcp>=1.0` added to `pyproject.toml`
- **Security**: All tools read-only; no write operations exposed; local stdio only; max limits on all queries (50-100)
- **81 new tests** in `tests/test_mcp_server.py` — server smoke, all 8 tool query functions, tool handler dispatch, empty DB stability, read-only verification
- **Documentation**: `docs/MCP_SERVER_DESIGN.md` rewritten from design to as-implemented; README, P3_PLAN, CHANGELOG updated

### Not in scope
- No Vault file-system tools (vault_status, get_lint_issues, search_claims) — deferred to future iteration
- No write tools (accept/skip/resolve review, retry ingest, trigger analysis)
- No streaming/SSE transport
- No OAuth/API Key authentication

### Test Results
- **71 new tests** in `tests/test_mcp_server.py`
- **1563 total tests**, all pass
- ruff clean

## P3-S — Closeout & Documentation Consolidation (2026-07-02)

### Done
- **P3_PLAN.md**: Added P3-S closeout section with quartet summary, CLI command list, data table list, exclusions, residual risks
- **P3_ACCEPTANCE_REPORT.md**: New comprehensive acceptance report — sub-phase deliverables, CLI/MCP tool/data table inventories, test results, known warnings, residual risks
- **README.md**: Added "P3: Agent-ready knowledge backend" consolidated section with MCP tool table; updated roadmap table to mark P3 complete; updated project structure and metrics
- **MCP_SERVER_DESIGN.md**: Expanded integration guide with Claude Code/Codex/Cursor/Claude Desktop examples; strengthened security section with explicit remote-exposure prohibition
- **CHANGELOG.md**: This entry — P3-S closeout documentation

### P3 Final State

```
P3 deliverables:
  ingest_jobs   — persistent ingest queue (22-column table, 14-method manager)
  vault_lint    — 5 lint rules scanning Obsidian vaults
  review_items  — unified human-triage queue (12-column table, 4-state machine)
  mcp_server    — 8 read-only MCP tools via stdio transport
  
CLI:     13 new commands across 4 command groups
Tests:   178 new (54 + 53 + 71), 1563 total, all pass
Ruff:    clean
Docs:    6 design/plan/report documents updated
```

### P3 Explicitly Excluded
- Write-capable MCP tools (security boundary)
- Deep Research (multi-turn LLM orchestration)
- Complex knowledge graph (entity relationships, causal chains)
- Desktop UI (React/Tauri/Electron)
- Automatic scheduled tasks
- Vector database (LanceDB etc.)
- New LLM provider
- Chrome extension / PDF/Office parsing

## P2-S.3.5 — Source Ingestion Consistency & Release Hardening (2026-07-01)

### Status & Action Label Unification
- Added `SOURCE_STATUS_LABELS`, `ACTION_LABELS`, `SUGGESTED_ACTION_LABELS`, `TRACKING_ELIGIBILITY_LABELS` to `sources/models.py`
- Unified 12 status labels: `preview_ready`→"待确认", `imported`→"已入库", `existing`→"已发现", `failed`→"失败", `degraded`→"解析退化"
- Unified 11 action labels for buttons: `confirm_archive`→"确认归档", `batch_import`→"导入选中项", etc.
- `ACTION_DESCRIPTIONS` keys changed from `ActionEnum` to `str` for simpler template usage
- Updated 5 templates to use template variables instead of hardcoded text

### Dashboard Statistics Consistency
- Verified YouTube channel count ↔ active channels, tracked source count ↔ enabled sources, pending entries, URL/file previews, SourceArchive count all consistent with sub-pages

### Skipped Test Recovery
- `test_full_flow_preview_then_confirm` unskipped — root cause was Windows MAX_PATH (pytest temp dir + archive subdirs > 260 chars)
- Fixed by using `tempfile.mkdtemp(prefix="v_")` for short vault path instead of `tmp_path / "v"`

### Documentation
- New `docs/SOURCE_INGESTION.md` — four entry points, unified processing pipeline, status/action labels, boundaries & limitations
- Updated CLAUDE.md, ROADMAP.md, README.md, CHANGELOG.md, TODO.md, ARCHITECTURE.md, DEV_GUIDE.md

### Naming & Boundary Audit
- Confirmed `confirm_archive` only used for SourceArchive, `existing` only for tracked source entries
- Verified Report not misused by web/file import, Deep Notes boundaries correct, LLM profiler stub safe
- Unsupported tracked URLs correctly redirect to single URL import

### Result
- 1385 tests, ruff clean, 80 Python modules, 1 skipped test recovered

## P2-S.3.3 + P2-S.3.4 — File Upload & Unified Sources Dashboard (2026-06-30)

### P2-S.3.3: User Text File Upload Preview & Archive
- New modules: `sources/file_profile.py`, `sources/file_content_extractor.py`, `sources/file_import_preview.py`
- Supports `.md` / `.txt` / `.html` / `.htm` upload with encoding detection (UTF-8 / UTF-8-SIG / GB18030)
- `UploadedFileProfile` → `ExtractedFileContent` → `FileImportPreview` pipeline
- Content extraction: Markdown H1 as title, HTML script/style/nav stripping via BeautifulSoup
- Import eligibility gate: text ≥ 200 chars, parse_quality ≠ minimal, content_hash required
- Conflict detection: same_content_hash (blocker), same_filename (warning), same_title (info)
- Scan dirs: SourceArchive, ReportMaterial, DeepNotes
- Web routes: GET `/sources/files/import`, POST `/sources/files/preview`, POST `/sources/files/confirm`
- File size limit: 5MB. Temp file cleanup on confirm. Filename sanitization.
- 46 tests (45 passed, 1 skipped due to config_store fixture interaction)

### P2-S.3.4: Source Ingestion Dashboard & Unified Navigation
- New `/sources` dashboard page with four entry cards + stats bar + pending summary + quick-add
- `_build_sources_dashboard_context()` gathers counts from DB, vault, and in-memory preview stores
- Navigation: main nav → `/sources`, sub-nav adds "📋 总览", dashboard button updated
- 19 tests

### Code Consolidation (P2-S.3.x refactor)
- **ActionEnum unified**: added `confirm_archive`, `FileImportPreview` now uses `ActionEnum` instead of bare `str`
- **ConflictDetector unified**: added `detect_for_file()`, removed standalone `detect_file_conflicts()` from `file_import_preview.py`
- **Performance fix**: `generate_watchlist_brief` — pre-compute canonical views outside per-item loop (7.3s → 0.69s, dashboard 10.4s → 2.8s)
- 1384 tests, ruff clean

## P2-S — External Sources & Deep Notes Export (2026-06-26)
- **P2-S.1**: External Derived Source Adapter (`external_html_notes`, `allin_zh_notes`) with retry engine
- **P2-S.2**: Deep Notes markdown export, health check, report linking, episode linking
- **P2-S.2.2**: External fetch reliability — retry with backoff (0.5/1.5/3.0s), error classification
- **P2-S.3.1**: Generic Web URL Import Preview — `GenericWebPageAdapter`, `ImportPreview`, `ConflictDetector`
- Web routes: GET `/sources/import`, POST preview/confirm; Source archive output
- 1261 tests, ruff clean

## P2-O — Engineering Stabilization (2026-06-05)
- GitHub Actions CI (push/PR auto pytest + ruff)
- ruff lint config (76 per-file-ignores)
- CSS cache busting (content hash)
- 7 Playwright UI smoke tests
- docs/ARCHITECTURE.md, docs/RELEASE_CHECKLIST.md
- Runtime observability & task failure UX (P2-O.2/O.2.1)
- 930 tests

## P2-N — Research Brief Quality Tuning (2026-06-05)
- Dashboard markdown artifact cleanup
- Entity/topic classification noise fix
- Research Brief: statistical → explanatory style
- Watchlist Brief: four-section evidence categorization
- 904 tests

## P2-M — Channel Filters & Source Pages (2026-06-05)
- 8 pill-button channel filters (watchlist-matched, by status, by tag)
- Source pages: card-based DOM restructure + CSS hard-fix
- 904 tests

## P2-L — First-run Vault Setup (2026-06-01)
- `/setup/vault` initialization wizard
- Dashboard Vault health detection + one-click repair
- Non-empty directory safety (no overwrite)

## P2-K — Watchlist + Task Queue (2026-06-01)
- Watchlist matching engine + brief generation
- Background task queue (analyze/sync jobs)
- Task failure diagnostics (5-level classification)
- Rerun with archive workflow

## P2-H — Obsidian Workspace Hardening (2026-05-31)
- Home Dashboard + Knowledge Map + Review Queue
- Curation status: raw/indexed/reviewed/enhanced/archived
- Relation backfill (related_topics/related_companies)
- Long-tail topic normalization
- 664 tests

## P2-F — Claim & Signal System (2026-05-30)
- Deterministic extraction from reports and patches
- Card generation with frontmatter + source reports
- Status management, similarity detection, tracking updates
- CLI: claims list/show/update-status/update-meta/find-similar/backlog
- CLI: signals list/show/update-status/update-meta/find-similar/backlog/update-tracking/add-update/tracking-backlog

## P2-E — LLM-WIKI Dynamic Maintenance (2026-05-30)
- Patch Review lifecycle: generate → validate → apply → rollback → reject
- LLM generates patch proposals from source reports
- YAML frontmatter + 9-item Review Checklist per patch
- LLM-WIKI:BEGIN/END markers for safe apply
- Topic + Company card patch generation
- Validation gate: frontmatter, target card, source reports, sections

## P2-D — Topic/Company Card Ecosystem (2026-05-30)
- Deterministic card generation from reports
- Card cleanup: company→topic migration, alias merge
- Topic taxonomy: 25 core topics, 50+ alias map
- Status: core/emerging/long_tail/manual_review
- Generic topic guard + canonical casing

## P2-C — Obsidian Vault Export (2026-05-30)
- Export YouTube reports to Obsidian Vault
- YAML frontmatter + structured Markdown
- Channel cards + system index + export log
- UnknownChannel cleanup with DB backfill
- Channel card reconciliation

## P2-B — Long Video Chunking (2026-05-30)
- Map-Reduce: segment-boundary split → per-chunk extraction → dedup + compaction → single report
- Auto-detect (>50K chars or >1000 segments)
- Manual: --chunked / --no-chunking / --chunk-size / --chunk-overlap

## P2-A — Prompt v2 + Cross-Channel Eval (2026-05-29)
- Tech/AI Investing Prompt v2: 10 evidence types, AI value chain, entity normalization
- target_name blacklist, investment_relevance strict grading
- Cross-channel eval: reports/export/summary, 10 generic target detection

## P1-F — Channel Tags (2026-05-28)
- channels: tags/priority/default_focus/notes fields
- seed-tech-ai: 5 core channels, idempotent + self-healing
- CLI: channels tag --add/--remove/--set, list --tag/--priority

## P1-E — YouTube Channel Management (2026-05-28)
- Channel subscription + yt-dlp video list fetch
- Video dedup (channel_id + video_id), status tracking
- CLI: channels add/list/refresh/videos/analyze-video

## P1-D — FTS5 Search (2026-05-28)
- SQLite FTS5 virtual table, CJK whitespace tokenization
- Search: FTS5 first → LIKE fallback

## P1-C — HTML Web Console (2026-05-27)
- Jinja2 templates, minimal CSS, no frontend framework
- Routes: /reports, /reports/{id}, /search

## P1-B — FastAPI API (2026-05-27)
- Read-only JSON API, 9 endpoints
- create_app() factory, serve command

## P1-A — CLI Report Library (2026-05-27)
- reports list/show/search/targets/sources subcommands
- Rich table output, LIKE search

## P0-B — YouTube Adapter (2026-05-27)
- youtube-transcript-api integration
- Transcript cache, language fallback
- YouTube URL validation

## P0-A — Local Subtitle Analysis (2026-05-27)
- SRT/VTT/TXT parsing + cleaning
- Mock LLM pipeline (keyword rule engine)
- Markdown report + SQLite storage
- CLI: --subtitle-file, --focus, --depth
