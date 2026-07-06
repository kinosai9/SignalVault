# P7 Plan: User-facing Reliability & Diagnostics

> 状态：P7-A/B ✅ | P7-C ✅ | P7-D ✅ | P7-E ✅ | CLI 对接 ✅ | Web/API 页面承接进入 SignalVault 前端体验改造 | 2026-07-06
> 前置：P3/P4/P5/P6 全部完成
> 角色：文档规划阶段，不写业务代码

## 一、P7 定位

当前系统已具备完整的数据摄入→分析→搜索→图谱链路（P3–P6），但**错误提示、操作审计、远程诊断**三个横向能力分散在 48 个 logger、4 个异常类、若干 ad-hoc `console.print("[red]...")` 中。

P7 不新增信息源、不扩展分析能力、不改 prompt。**P7 只做一件事：让非 IT 用户在使用中遇到问题时，能看懂发生了什么、知道下一步该做什么、并能把诊断信息导出给技术支持。**

P7 与 Codex 前端原型设计并行推进：P7 已提供后端错误模型、操作日志、诊断数据结构、恢复动作和 CLI；Web/API 页面承接进入 `docs/FRONTEND_EXPERIENCE_EXECUTION_PLAN.md`。

## 二、当前状态评估

### 2.1 已有能力

| 能力 | 位置 | 成熟度 |
|------|------|--------|
| 异常类 | `zsxq_cli.py` 4 个 + `adapters/` 1 个 + `services/` analyze error_type | 分散 |
| 错误记录 | `Job.error` / `IngestJob.error_message` / `ChannelVideo.failure_reason` / `TrackedSource.last_error` | 表级不一致 |
| Review Queue | `review_items` 表（17 item_types，open/accepted/skipped/resolved） | 成熟 |
| 任务事件 | `JobEvent`（job_id, level, stage, message, detail） | 仅 Job 级别 |
| CLI 检查 | `zsxq doctor` | 仅 ZSXQ |
| 日志 | 48 个 `logging.getLogger(__name__)` | 文件级，无结构 |

### 2.2 缺失能力

| 缺失 | 影响 |
|------|------|
| 统一错误码 | 用户无法搜索/对照错误含义 |
| 操作审计日志 | 无法追溯"谁在什么时候做了什么" |
| 诊断聚合 | 无法一眼看到系统健康状态 |
| 建议动作 | 用户看到错误但不知道该做什么 |
| 诊断导出 | 远程排查靠截图+手动描述 |
| 全系统 doctor | 配置/DB/依赖一键检查 |
| 降级状态通知 | 某个子系统挂了用户不知道 |

## 三、设计原则

1. **面向非 IT 用户**：错误信息中文、易懂、带下一步指引。技术细节折叠在 `technical_detail` 中。
2. **最小侵入**：新增表/模块通过现有 `db/sources/` 模式接入，不改 `analysis/`、`llm/` 核心。
3. **复用现有基础设施**：`error_code` 可映射到 `review_items.item_type`；`operation_log` 可复用 `JobEvent` 结构。
4. **安全第一**：诊断导出不含密钥、不含完整原文、不含用户隐私字段。
5. **CLI + Web 共用**：所有诊断数据结构返回 dict/JSON，CLI 渲染为表格，Web 渲染为卡片。

## 四、交付范围

### 4.1 P7-A：Error Taxonomy（错误分类体系）

**文档：** `docs/ERROR_TAXONOMY_DESIGN.md`

统一 11 大类错误，每个错误包含结构化字段：

```
error_code      — 唯一错误码，如 "ZSXQ_AUTH_001"
severity        — info / warning / error / blocker
user_message    — 面向用户的中文说明
technical_detail— 技术细节（可选，折叠）
suggested_actions — 建议操作列表（CLI 命令或操作指引）
related_command — 关联 CLI 命令
source_type     — 数据来源类型
entity_ref      — 关联实体引用
```

11 大类别：

1. `source_error` — 信息源获取失败
2. `auth_error` — 认证/授权失败
3. `permission_error` — 权限不足
4. `extraction_error` — 内容提取失败
5. `analysis_error` — 分析 pipeline 失败
6. `llm_error` — LLM 调用失败
7. `database_error` — 数据库异常
8. `vault_error` — Obsidian Vault 异常
9. `search_graph_error` — 搜索/图谱异常
10. `mcp_error` — MCP Server 异常
11. `config_error` — 配置缺失/错误

与现有 `review_items.item_type` 映射关系：1 error_code → 0..1 review_item（严重/需人工处理的错误同时入 review queue）。

### 4.2 P7-B：Operation Log（操作日志）

**文档：** `docs/OPERATION_LOG_DESIGN.md`

记录用户动作和系统动作的结构化日志：

```
operation_id     — UUID
operation_type   — 操作类型枚举
status           — started / succeeded / failed / cancelled
started_at       — 开始时间
finished_at      — 完成时间
duration_ms      — 耗时
source_type      — 数据来源
target_ref       — 操作目标
summary          — 人类可读摘要
error_code       — 关联错误码（可选）
metadata_json    — 扩展元数据
```

覆盖的操作类型（≥20）：

| 类别 | 操作 |
|------|------|
| ZSXQ | `zsxq.groups.refresh`, `zsxq.topic.import`, `zsxq.topic.analyze`, `zsxq.sync` |
| PDF | `pdf.preview`, `pdf.extract`, `pdf.analyze` |
| Ingest | `ingest.retry`, `ingest.resume`, `ingest.confirm` |
| Vault | `vault.lint`, `vault.export` |
| Review | `review.accept`, `review.skip`, `review.resolve` |
| Search | `search.unified` |
| Graph | `graph.rebuild`, `graph.export` |
| MCP | `mcp.serve.start`, `mcp.serve.stop` |
| Config | `config.validate` |

### 4.3 P7-C：Diagnostics Center（诊断中心）

**文档：** 含在 `docs/DIAGNOSTIC_BUNDLE_DESIGN.md` 中

诊断聚合数据结构，返回系统健康快照：

```
summary:
  total_errors, total_warnings, open_review_items
subsystems:
  ingest:    {pending_jobs, failed_jobs, expired_jobs}
  review:    {open_by_severity, open_by_type}
  vault:     {last_lint_at, lint_issues_count, vault_exists}
  zsxq:      {cli_available, logged_in, groups_count, active_count}
  pdf:       {pending_ocr, extraction_failures}
  graph:     {node_count, edge_count, last_rebuild_at, needs_rebuild}
  search:    {fts_available, indexed_reports}
  mcp:       {tool_count, server_running}
config:
  llm_provider, llm_model_set, obsidian_configured, db_path_exists
recent_failures:
  [{operation_type, error_code, occurred_at, summary}]
```

### 4.4 P7-D：Diagnostic Bundle Export（诊断包导出）

**文档：** `docs/DIAGNOSTIC_BUNDLE_DESIGN.md`

一键导出 JSON/ZIP 诊断包，用于远程排查：

**包含（脱敏）：**
- System info: Python version, OS, package versions
- Config summary: LLM provider (not key), DB path exists, Obsidian path exists
- Recent operation logs (last 100)
- Failed jobs (last 50)
- Open review items summary
- Vault lint last result
- ZSXQ CLI status
- DB status: table row counts
- Test self-check result: pytest --coverage summary
- Metadata: export timestamp, git commit

**明确不包含：**
- API Key / Token / 密码
- 完整付费原文
- 用户隐私字段（手机号/成员列表/私信）
- DB 完整内容（仅 row counts）
- 报告全文

### 4.5 P7-E：Recovery Actions（恢复动作）

为常见问题设计标准恢复动作，嵌入 error 和 diagnostics 结果：

| 场景 | 动作 |
|------|------|
| zsxq-cli 未安装 | 指引安装 `zsxq-cli` |
| zsxq 未登录 | `zsxq-cli auth login` |
| LLM API Key 未配置 | 编辑 `.env` → 设置 `LLM_API_KEY` |
| ingest job 失败 | `ingest retry <job_id>` |
| Vault 健康问题 | `vault-lint --vault <path>` |
| 图谱过期 | `graph rebuild` |
| PDF 质量低 | 跳过低质量 PDF / 使用 OCR |
| ingest 过期 | `ingest resume` 查看可恢复任务 |

### 4.6 P7-F：CLI + Web/API 对接

**CLI 新增命令：**

```bash
signalvault doctor              # 全系统健康检查
signalvault diagnostics summary # 诊断摘要
signalvault diagnostics bundle --output <path>  # 导出诊断包
signalvault logs list           # 操作日志列表
signalvault logs show <id>      # 操作日志详情
```

**Web/API 对接说明（供 Codex 前端使用）：**
- `/api/diagnostics/summary` → health summary JSON
- `/api/diagnostics/bundle` → 诊断包下载
- `/api/operations/logs` → 操作日志分页查询
- 错误响应统一格式：`{error_code, user_message, suggested_actions}`
- Web UI 渲染：dashboard health cards、error banners、action buttons

当前实现状态：CLI 和后端数据结构已落地；Web 页面和 API 路由尚未统一接入，纳入 SignalVault 前端体验改造的诊断中心阶段。

## 五、模块结构（计划）

```
src/signalvault/
  diagnostics/
    __init__.py
    error_codes.py        # ErrorCode enum + ErrorRecord dataclass
    error_taxonomy.py     # 11 categories + registry
    operation_log.py      # OperationLogManager (CRUD)
    diagnostics_center.py # DiagnosticsCenter — summary aggregation
    diagnostic_bundle.py  # BundleBuilder — export + redaction
    recovery_actions.py   # SuggestedAction lookup table
  cli.py                  # + doctor, diagnostics, logs 命令组
  api/
    diagnostics_routes.py # /api/diagnostics/* 端点

db/
  models.py               # + OperationLog ORM (or reuse JobEvent)

tests/
  test_error_codes.py
  test_operation_log.py
  test_diagnostics_center.py
  test_diagnostic_bundle.py
  test_diagnostics_cli.py
```

## 六、DB 变更（计划）

### 6.1 新增表：operation_logs

```
operation_logs
  id              INTEGER PRIMARY KEY
  operation_id    TEXT UNIQUE NOT NULL    — UUID
  operation_type  TEXT NOT NULL           — 枚举值
  status          TEXT DEFAULT 'started'  — started/succeeded/failed/cancelled
  started_at      DATETIME
  finished_at     DATETIME
  duration_ms     INTEGER
  source_type     TEXT
  target_ref      TEXT
  summary         TEXT
  error_code      TEXT                    — FK-like ref to error taxonomy
  metadata_json   TEXT
  created_at      DATETIME DEFAULT NOW
```

### 6.2 可能的重用

`JobEvent` 表可作为 `operation_logs` 的子集使用，但 `operation_logs` 覆盖更广（非 Job 操作如 search、graph rebuild、config validate）。可考虑：
- Option A: 扩展 `JobEvent` 表（加 operation_type、error_code、duration_ms 等）
- Option B: 新建 `operation_logs` 表，`JobEvent` 通过 `operation_id` 关联

**推荐 Option B**：`JobEvent` 保持轻量（Job 级事件），`operation_logs` 作为更广的操作审计日志。

## 七、测试策略

| 测试文件 | 覆盖 |
|----------|------|
| `test_error_codes.py` | ErrorRecord 创建、11 类别完整性、error_code 唯一性、序列化 |
| `test_operation_log.py` | CRUD、status 转换、duration 计算、过滤查询 |
| `test_diagnostics_center.py` | Summary 聚合、各子系统状态、空 DB 不崩溃 |
| `test_diagnostic_bundle.py` | 导出完整性、密钥不泄露、原文不包含、脱敏验证 |
| `test_diagnostics_cli.py` | doctor/diagnostics/logs CLI smoke |

总计 ≥30 专项测试。Mock 策略：所有测试用 `db_session` fixture，不依赖外部服务。

## 八、边界（P7 不做）

| 排除项 | 原因 |
|--------|------|
| 前端 UI 实现 | 属 Codex 侧 |
| 自动修复错误 | 保留人工决策，只提供建议 |
| 远程上报/telemetry | 用户隐私，不做数据上传 |
| 暴露密钥/API Key | 安全硬边界 |
| 改动 analysis prompt | P7 不碰核心分析逻辑 |
| 新增信息源 | 非本阶段 |
| 实时监控/告警 | 超出本地工具定位 |
| 性能 profiling | P7 聚焦可靠性 + 诊断，不涉及性能 |
| 结构化日志框架迁移 | 保持 stdlib logging，operation_log 是应用层补充 |

## 九、分阶段计划

| 阶段 | 内容 | 依赖 |
|------|------|------|
| **P7-A** | Error Taxonomy — 错误分类 + error_code 注册表 | 无 |
| **P7-B** | Operation Log — 操作日志 CRUD + 20+ operation types | P7-A |
| **P7-C** | Diagnostics Center — 聚合查询 + summary 输出 | P7-A, P7-B |
| **P7-D** | Diagnostic Bundle — 导出 + 脱敏 + zip | P7-C |
| **P7-E** | Recovery Actions — 建议动作注册表 | P7-A |
| **P7-F** | CLI + backend data structures + Tests；Web/API routes 待前端阶段承接 | P7-C, P7-D |
| **P7-S** | 收口封板 — 验收报告 + 文档一致性 | P7-F |

## 十、与 Codex 前端的对接点

P7 交付的数据结构直接支持 Codex 前端原型：

| P7 产出 | Codex 使用 |
|---------|-----------|
| `ErrorRecord` | 错误 Banner 组件 props |
| `DiagnosticsSummary` | Dashboard Health Cards 数据源 |
| `OperationLog` | 操作历史 Timeline 组件 |
| `RecoveryAction` | "建议操作" 按钮列表 |
| `DiagnosticBundle` | 诊断导出下载按钮 |
| `/api/diagnostics/summary` | Dashboard 页面初始数据 |
| 统一错误响应格式 | 全局错误拦截器 |

P7 不画 UI、不写 CSS、不定义组件层级——只提供后端数据结构和 API 契约。
