# P7-C/D: Diagnostics Center & Diagnostic Bundle Design

> 状态：P7-C Implemented | P7-D Implemented | 2026-07-03
> 读者：Claude Code (实现) + Codex (前端对接)

## 一、目标

两部分能力：

1. **Diagnostics Center（P7-C）**：聚合查询系统各子系统状态，输出统一健康快照，供 CLI `doctor` / `diagnostics summary` 和 Web Dashboard 使用。
2. **Diagnostic Bundle（P7-D）**：一键导出脱敏诊断包（JSON/ZIP），供远程排查使用。

## 二、Diagnostics Center — 聚合查询

### 2.1 DiagnosticsSummary 数据结构

```python
@dataclass
class DiagnosticsSummary:
    """System health snapshot — CLI table + Web Dashboard 数据源."""

    generated_at: str = ""               # ISO timestamp
    overall_status: str = "healthy"      # healthy / degraded / unhealthy

    # ── Counts ──
    total_errors_24h: int = 0
    total_warnings_24h: int = 0
    open_review_items: int = 0

    # ── Subsystems ──
    ingest: IngestStatus = field(default_factory=IngestStatus)
    review: ReviewStatus = field(default_factory=ReviewStatus)
    vault: VaultStatus = field(default_factory=VaultStatus)
    zsxq: ZsxqStatus = field(default_factory=ZsxqStatus)
    pdf: PdfStatus = field(default_factory=PdfStatus)
    graph: GraphStatus = field(default_factory=GraphStatus)
    search: SearchStatus = field(default_factory=SearchStatus)
    mcp: McpStatus = field(default_factory=McpStatus)
    config: ConfigStatus = field(default_factory=ConfigStatus)

    # ── Recent failures ──
    recent_failures: list[FailureEntry] = field(default_factory=list)
```

### 2.2 子系统状态

```python
@dataclass
class IngestStatus:
    pending_jobs: int = 0
    failed_jobs: int = 0
    expired_jobs: int = 0
    jobs_by_source: dict = field(default_factory=dict)  # {"zsxq_topic": 3, "pdf_upload": 2}
    status: str = "healthy"  # healthy / degraded / unhealthy

@dataclass
class ReviewStatus:
    open_items: int = 0
    by_severity: dict = field(default_factory=dict)   # {"error": 2, "warning": 5}
    by_type: dict = field(default_factory=dict)        # {"zsxq_cli_missing": 1, ...}
    needs_attention: list[str] = field(default_factory=list)  # high-severity item titles
    status: str = "healthy"

@dataclass
class VaultStatus:
    vault_configured: bool = False
    vault_exists: bool = False
    last_lint_at: str = ""
    lint_issues: int = 0
    lint_issues_by_rule: dict = field(default_factory=dict)
    status: str = "healthy"

@dataclass
class ZsxqStatus:
    cli_available: bool = False
    cli_version: str = ""
    logged_in: bool = False
    groups_total: int = 0
    groups_active: int = 0
    groups_inaccessible: int = 0
    last_refresh_at: str = ""
    status: str = "healthy"

@dataclass
class PdfStatus:
    pending_ocr: int = 0          # PDFs marked as needs_ocr
    extraction_failures: int = 0  # quality=failed PDFs
    total_analyzed: int = 0
    status: str = "healthy"

@dataclass
class GraphStatus:
    node_count: int = 0
    edge_count: int = 0
    last_rebuild_at: str = ""
    needs_rebuild: bool = False   # True if new data exists after last rebuild
    status: str = "healthy"

@dataclass
class SearchStatus:
    fts_available: bool = True
    indexed_reports: int = 0
    fallback_mode: bool = False
    status: str = "healthy"

@dataclass
class McpStatus:
    server_running: bool = False
    tool_count: int = 8
    tools: list[str] = field(default_factory=list)
    status: str = "healthy"

@dataclass
class ConfigStatus:
    llm_provider: str = ""           # "mock" | "openai-compatible"
    llm_model_set: bool = False      # LLM_MODEL is configured
    llm_key_set: bool = False        # LLM_API_KEY is configured (value not shown)
    obsidian_configured: bool = False
    obsidian_vault_exists: bool = False
    db_path_exists: bool = False
    data_dir_exists: bool = False
    zsxq_cli_on_path: bool = False
    missing_items: list[str] = field(default_factory=list)
        # ["LLM_API_KEY", "OBSIDIAN_VAULT_PATH", "zsxq-cli"]
    status: str = "healthy"

@dataclass
class FailureEntry:
    operation_type: str = ""
    error_code: str = ""
    summary: str = ""
    occurred_at: str = ""
    operation_id: str = ""
```

### 2.3 overall_status 判定

```python
def _compute_overall_status(summary: DiagnosticsSummary) -> str:
    """healthy / degraded / unhealthy"""

    # Blocker in any subsystem → unhealthy
    blocker_subsystems = [
        s for s in [summary.ingest, summary.config, summary.zsxq]
        if s.status == "unhealthy"
    ]
    if blocker_subsystems:
        return "unhealthy"

    # Any degraded subsystem → degraded
    degraded_subsystems = [
        s for s in [summary.ingest, summary.review, summary.vault,
                     summary.zsxq, summary.pdf, summary.graph,
                     summary.search, summary.mcp, summary.config]
        if s.status == "degraded"
    ]
    if degraded_subsystems or summary.open_review_items > 0:
        return "degraded"

    return "healthy"
```

每个子系统自己判定 status：
- `healthy`：无异常
- `degraded`：部分功能受限但核心可用（如 FTS 降级为 LIKE、Z SXQ 未登录但不影响其他功能）
- `unhealthy`：核心功能不可用（如 DB 损坏、配置缺失导致无法启动）

### 2.4 DiagnosticsCenter API

```python
class DiagnosticsCenter:
    """Aggregate system health across all subsystems."""

    @staticmethod
    def get_summary(session=None) -> DiagnosticsSummary:
        """Query all subsystems and build a health snapshot."""
        ...

    @staticmethod
    def get_subsystem(subsystem: str, session=None) -> dict:
        """Get detailed status for a single subsystem."""
        ...

    @staticmethod
    def get_recent_failures(limit: int = 20, session=None) -> list[FailureEntry]:
        """Get recent operation failures from operation_logs."""
        ...

    @staticmethod
    def get_config_summary() -> ConfigStatus:
        """Check configuration without revealing secret values."""
        ...
```

## 三、Diagnostic Bundle — 一键导出

### 3.1 Bundle 结构

```
diagnostic_bundle_{timestamp}.zip
  ├── summary.json              # DiagnosticsSummary
  ├── config.json               # ConfigStatus (脱敏)
  ├── operations.json           # 最近 100 条 operation_logs
  ├── failed_jobs.json          # 最近 50 条失败 job
  ├── review_items.json         # open review items 摘要（不含完整原文）
  ├── vault_lint.json           # 最近一次 lint 结果
  ├── zsxq_status.json          # ZSXQ CLI 状态 + group registry 摘要
  ├── db_info.json              # 表名 + row counts + DB 文件大小
  ├── environment.json          # Python 版本 / OS / 包版本
  └── self_check.json           # pytest --tb=short 结果摘要
```

### 3.2 Redaction Rules（脱敏规则）

```python
REDACTION_RULES = {
    # 绝对不包含
    "never_include": [
        "LLM_API_KEY",           # 环境变量值
        "LLM_BASE_URL",          # 可能含 key
        "OBSIDIAN_VAULT_PATH",   # 用户路径隐私（只记录 exists: true/false）
        "DB_PATH",               # 同 Vault path
        "zsxq token",            # zsxq-cli 认证信息
        "report_markdown",       # 完整报告原文
        "content_text",          # 完整付费原文（ZSXQ topic 正文）
        "source_quote",          # 原文引用（只记录字符数）
        "member data",           # 成员/手机号/私信
        "preview_data 全文",      # ingest_jobs preview_data 只取前 200 chars
    ],

    # 脱敏后包含
    "include_redacted": [
        "LLM_PROVIDER",          # "mock" or "openai-compatible"
        "LLM_MODEL",             # 模型名（不含 key）
        "LLM_API_KEY",           # → "set" / "not_set"
        "OBSIDIAN_VAULT_PATH",   # → "configured" / "not_configured"
        "DB_PATH",               # → "exists" / "missing"
    ],
}
```

### 3.3 DiagnosticBundleBuilder

```python
class DiagnosticBundleBuilder:
    """Build a diagnostic bundle with redaction."""

    @staticmethod
    def build(output_dir: Path, session=None) -> Path:
        """Build and return path to the zip bundle."""
        ...

    @staticmethod
    def _build_summary(session) -> dict:
        """Aggregate DiagnosticsSummary → dict."""
        ...

    @staticmethod
    def _build_config_redacted() -> dict:
        """Config summary with keys redacted."""
        ...

    @staticmethod
    def _build_operations(session, limit: int = 100) -> list[dict]:
        """Recent operation logs → list of dicts."""
        ...

    @staticmethod
    def _build_failed_jobs(session, limit: int = 50) -> list[dict]:
        """Recent failed ingest_jobs → list of dicts."""
        ...

    @staticmethod
    def _build_review_summary(session) -> list[dict]:
        """Open review items (title + type + severity, no full content)."""
        ...

    @staticmethod
    def _build_vault_lint_last(session) -> dict | None:
        """Last vault lint result summary."""
        ...

    @staticmethod
    def _build_zsxq_status() -> dict:
        """ZSXQ CLI status + group counts."""
        ...

    @staticmethod
    def _build_db_info(session) -> dict:
        """Table row counts + DB file size."""
        ...

    @staticmethod
    def _build_environment() -> dict:
        """Python version, OS, package versions."""
        ...

    @staticmethod
    def _build_self_check() -> dict:
        """Run pytest --tb=short and capture exit code + summary."""
        ...

    @staticmethod
    def _redact_config(config: dict) -> dict:
        """Apply redaction rules to config dict."""
        ...
```

### 3.4 使用示例

```bash
# 导出诊断包
$ podcast-research diagnostics bundle --output ./diagnostics
  📦 收集系统信息...
  ✅ summary.json
  ✅ config.json (脱敏)
  ✅ operations.json (100 条)
  ✅ failed_jobs.json (3 条)
  ✅ review_items.json (5 open)
  ✅ vault_lint.json
  ✅ zsxq_status.json
  ✅ db_info.json
  ✅ environment.json
  ✅ self_check.json
  📦 打包完成: ./diagnostics/diagnostic_bundle_20260703_143000.zip (45 KB)

# 发送给技术支持
$ # 将 zip 文件发送给技术支持人员即可
```

## 四、CLI 命令设计

### 4.1 doctor — 全系统健康检查

```bash
$ podcast-research doctor

  System Health: degraded

  ── Ingest ───────────────────────────────────────────
  ✅ 正常    pending: 3  jobs
  ⚠️ 注意    failed: 1 job (ingest retry 42)

  ── Review ───────────────────────────────────────────
  ⚠️ 注意    5 open items (2 error, 3 warning)
              zsxq_cli_missing: 1

  ── ZSXQ ────────────────────────────────────────────
  ❌ 异常    zsxq-cli not found
              → 安装 zsxq-cli: pip install zsxq-cli

  ── Config ───────────────────────────────────────────
  ⚠️ 注意    LLM_API_KEY 未配置 (mock 模式可用)
              OBSIDIAN_VAULT_PATH 未配置

  ── Database ─────────────────────────────────────────
  ✅ 正常    12 tables, 1,234 rows, 2.1 MB

  ── Graph ───────────────────────────────────────────
  ✅ 正常    45 nodes, 128 edges (last rebuild: 07-03 14:00)

  Suggestions:
    • 安装 zsxq-cli 以启用知识星球导入
    • 配置 LLM_API_KEY 以使用真实 AI 分析
    • ingest retry 42 重试失败任务
```

### 4.2 diagnostics summary — JSON 摘要

```bash
$ podcast-research diagnostics summary
# 输出 JSON（适合程序消费）

$ podcast-research diagnostics summary --format table
# 输出表格（适合人类阅读）
```

### 4.3 diagnostics bundle — 导出

```bash
$ podcast-research diagnostics bundle
# 默认输出到 ./diagnostics/

$ podcast-research diagnostics bundle --output /tmp/diag
# 指定输出目录
```

### 4.4 logs — 操作日志查询

```bash
$ podcast-research logs list
# 最近 50 条操作日志

$ podcast-research logs list --type zsxq.topic.analyze
# 按操作类型过滤

$ podcast-research logs list --status failed
# 只看失败的

$ podcast-research logs show op_abc123
# 查看单条日志详情
```

## 五、Web/API 对接（供 Codex）

### 5.1 API 端点

```
GET  /api/diagnostics/summary        → DiagnosticsSummary JSON
GET  /api/diagnostics/subsystem/{name} → 单个子系统详情
POST /api/diagnostics/bundle          → 触发导出，返回 bundle zip
GET  /api/operations/logs?type=&status=&limit=    → OperationLog[]
GET  /api/operations/logs/{operation_id}          → OperationLog detail
```

### 5.2 前端组件映射

| API 数据 | 前端组件 |
|----------|---------|
| `DiagnosticsSummary.overall_status` | Dashboard 顶部健康 Badge (green/yellow/red) |
| `DiagnosticsSummary.ingest` | Ingest Status Card |
| `DiagnosticsSummary.zsxq` | ZSXQ Status Card |
| `DiagnosticsSummary.config` | Config Status Card |
| `DiagnosticsSummary.recent_failures` | Recent Errors List |
| `OperationLog[]` | Operation Timeline |
| `DiagnosticBundle` | "导出诊断包" 按钮 → 下载 zip |

### 5.3 错误响应统一格式

所有 API 错误响应使用统一结构：

```json
{
  "success": false,
  "error": {
    "error_code": "AUTH_ZSXQ_001",
    "severity": "error",
    "user_message": "知识星球未登录。",
    "technical_detail": "...",
    "suggested_actions": ["运行 zsxq-cli auth login"],
    "trace_id": "op_abc123"
  }
}
```

## 六、Recovery Actions 注册表（P7-E）

```python
# 建议动作 → CLI 命令映射
RECOVERY_ACTIONS = {
    "zsxq_login": {
        "label": "登录知识星球",
        "cli": "zsxq-cli auth login",
        "doctor_check": "zsxq.logged_in",
    },
    "zsxq_install": {
        "label": "安装 zsxq-cli",
        "cli": "pip install zsxq-cli",
        "doctor_check": "zsxq.cli_available",
    },
    "llm_config": {
        "label": "配置 LLM API Key",
        "cli": "编辑 .env 文件，设置 LLM_API_KEY",
        "doctor_check": "config.llm_key_set",
    },
    "ingest_retry": {
        "label": "重试失败任务",
        "cli_template": "podcast-research ingest retry {job_id}",
        "doctor_check": "ingest.failed_jobs",
    },
    "vault_lint": {
        "label": "检查 Vault 健康",
        "cli": "podcast-research vault-lint --vault <path>",
        "doctor_check": "vault.lint_issues",
    },
    "graph_rebuild": {
        "label": "重建知识图谱",
        "cli": "podcast-research graph rebuild",
        "doctor_check": "graph.needs_rebuild",
    },
    "pdf_skip_low_quality": {
        "label": "跳过低质量 PDF",
        "cli": "podcast-research review skip {item_id}",
        "doctor_check": "pdf.pending_ocr",
    },
    "review_queue": {
        "label": "查看审核队列",
        "cli": "podcast-research review list",
        "doctor_check": "review.open_items",
    },
}
```

## 七、测试策略

| 测试 | 覆盖 |
|------|------|
| DiagnosticsSummary 空 DB 不崩溃 | 所有 counts 为 0, status 为 healthy |
| 各子系统 status 判定 | healthy/degraded/unhealthy 逻辑 |
| overall_status 聚合 | blocker > degraded > healthy 优先级 |
| ConfigStatus 不泄露密钥 | LLM_API_KEY="set"，不显示值 |
| Bundle 完整性 | 所有 10 个文件生成 |
| Bundle 脱敏验证 | 密钥/路径/原文不出现 |
| Redaction 规则完整性 | 所有 never_include 字段不存在 |
| CLI doctor smoke | exit_code=0，输出包含各子系统 |
| CLI diagnostics summary --json | 合法 JSON |
| CLI logs list/show | 输出格式正确 |
| Degraded dependency graceful | zsxq-cli 缺失不崩，标记 degraded |
