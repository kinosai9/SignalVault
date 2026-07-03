# P7-A: Error Taxonomy Design

> 状态：Implemented | 2026-07-03
> 读者：Claude Code (实现) + Codex (前端对接)

## 一、目标

将当前分散在 4 个异常类、5 个 `error_type` 字符串、17 个 `review_items.item_type` 中的错误信息，统一为结构化、可查询、面向用户友好的错误分类体系。

**设计约束：**
- 新增 `error_code` 不替代现有 `review_items`，而是与其互补——严重错误入 review queue，所有错误有 error_code
- 用户看到的永远是 `user_message`（中文），技术细节折叠在 `technical_detail` 中
- 每个错误至少包含 1 个 `suggested_action`

## 二、ErrorRecord 数据结构

```python
@dataclass
class ErrorRecord:
    """统一错误记录 — CLI/API/Web 通用。"""

    # Identity
    error_code: str            # 唯一错误码，格式: CATEGORY_SUBCATEGORY_NNN
                               # 示例: "ZSXQ_AUTH_001", "PDF_EXTRACT_002"

    # Severity
    severity: str              # "info" | "warning" | "error" | "blocker"
                               # blocker = 阻断性错误，后续操作无法进行

    # User-facing
    user_message: str          # 中文，面向非 IT 用户，≤200 字
    user_message_detail: str = ""  # 补充说明（可选）

    # Technical
    technical_detail: str = ""  # 技术细节，默认折叠
    exception_type: str = ""    # 原始异常类名
    trace_id: str = ""          # 关联 operation_id / job_id

    # Recovery
    suggested_actions: list[str] = field(default_factory=list)
        # ["重新登录 zsxq-cli", "检查 .env 中的 LLM_API_KEY"]

    # Routing
    related_command: str = ""   # 关联 CLI 命令
    source_type: str = ""       # "youtube" | "pdf_upload" | "zsxq_topic" | "local"
    entity_ref: str = ""        # 关联实体: "group:G001", "topic:T001", "job:42"

    # Review queue
    create_review_item: bool = False  # 是否同时创建 review_item
    review_item_type: str = ""        # 映射到 VALID_ITEM_TYPES

    # Metadata
    created_at: str = ""
    metadata: dict = field(default_factory=dict)
```

## 三、11 大错误类别

### 3.1 SOURCE — 信息源获取失败

| error_code | severity | 触发条件 | user_message |
|------------|----------|----------|-------------|
| `SOURCE_FETCH_001` | error | 网络请求失败/超时 | 无法获取信息源内容。请检查网络连接后重试。 |
| `SOURCE_FETCH_002` | warning | 信息源返回空内容 | 信息源返回内容为空，可能已被删除或链接失效。 |
| `SOURCE_PARSE_001` | error | 内容解析失败（HTML/JSON/字幕格式） | 内容格式解析失败。信息源格式可能已变更。 |
| `SOURCE_UNSUPPORTED_001` | warning | 不支持的信息源类型 | 当前版本不支持该信息源类型。 |

**关联 source_type：** youtube / pdf_upload / zsxq_topic / url_import / local

### 3.2 AUTH — 认证/授权失败

| error_code | severity | 触发条件 | user_message |
|------------|----------|----------|-------------|
| `AUTH_ZSXQ_001` | error | zsxq-cli 未登录 | 知识星球未登录。请在终端运行 `zsxq-cli auth login` 后重试。 |
| `AUTH_ZSXQ_002` | warning | zsxq token 即将过期 | 知识星球登录状态即将过期，建议重新登录。 |
| `AUTH_LLM_001` | blocker | LLM API Key 未配置 | 未配置 LLM API Key。请在 .env 文件中设置 LLM_API_KEY。 |
| `AUTH_LLM_002` | error | LLM API Key 无效 | LLM API Key 验证失败。请检查 .env 中的 LLM_API_KEY 是否正确。 |
| `AUTH_YOUTUBE_001` | warning | YouTube API key 未配置 | YouTube API 未配置，字幕获取可能受限。 |

### 3.3 PERMISSION — 权限不足

| error_code | severity | 触发条件 | user_message |
|------------|----------|----------|-------------|
| `PERM_ZSXQ_001` | warning | 无权访问该星球 | 无权访问该知识星球。请确认已在知识星球 App 中订阅该星球。 |
| `PERM_ZSXQ_002` | warning | 无权访问该主题 | 无权访问该主题，可能需要更高会员等级。 |
| `PERM_VAULT_001` | error | Obsidian Vault 目录无写权限 | Obsidian Vault 目录无写入权限。请检查目录权限设置。 |
| `PERM_DB_001` | blocker | 数据库文件无读写权限 | 数据库文件无法访问。请检查 data/ 目录权限。 |

### 3.4 EXTRACTION — 内容提取失败

| error_code | severity | 触发条件 | user_message |
|------------|----------|----------|-------------|
| `EXTRACT_PDF_001` | error | PDF 文本提取失败 | PDF 文本提取失败。文件可能已损坏或为扫描版（建议使用 OCR 工具预处理）。 |
| `EXTRACT_PDF_002` | warning | PDF 文本质量过低 | PDF 提取的文本质量较低（大部分页面为空或乱码）。 |
| `EXTRACT_PDF_003` | warning | PDF 需要 OCR | 该 PDF 为扫描版，需要 OCR 处理。当前不支持自动 OCR。 |
| `EXTRACT_YT_001` | warning | YouTube 字幕不可用 | 该视频无可用字幕（可能未生成或已禁用）。 |
| `EXTRACT_ZSXQ_001` | warning | ZSXQ 主题正文为空 | 该知识星球主题正文为空，无法提取有效内容。 |
| `EXTRACT_ZSXQ_002` | warning | ZSXQ 内容过短 | 该主题正文字数不足，不适合进行分析。 |

### 3.5 ANALYSIS — 分析 pipeline 失败

| error_code | severity | 触发条件 | user_message |
|------------|----------|----------|-------------|
| `ANALYSIS_PIPELINE_001` | error | pipeline 执行异常 | 分析过程出现异常。系统已记录错误详情，可重试。 |
| `ANALYSIS_CHUNK_001` | error | 分块分析失败 | 长文本分块分析时某一块处理失败。 |
| `ANALYSIS_MERGE_001` | warning | 分块结果合并异常 | 分析结果合并时出现数据丢失，部分观点可能不完整。 |
| `ANALYSIS_ELIGIBILITY_001` | info | 内容不符合分析条件 | 该内容不满足分析条件（过短/质量过低/来源不可用）。 |

### 3.6 LLM — LLM 调用失败

| error_code | severity | 触发条件 | user_message |
|------------|----------|----------|-------------|
| `LLM_CALL_001` | error | LLM API 请求失败 | AI 模型调用失败。请检查网络连接和 API 配置。 |
| `LLM_CALL_002` | error | LLM 返回格式异常 | AI 模型返回了无法解析的内容。系统将使用降级策略。 |
| `LLM_CALL_003` | warning | LLM token 超限 | 内容超出 AI 模型处理上限，系统已自动分段处理。 |
| `LLM_CALL_004` | error | LLM 调用超时 | AI 模型响应超时。可尝试缩短内容或更换模型。 |
| `LLM_CALL_005` | warning | LLM 返回语言不一致 | AI 模型返回了中英混合内容，报告已生成但建议复核。 |

### 3.7 DATABASE — 数据库异常

| error_code | severity | 触发条件 | user_message |
|------------|----------|----------|-------------|
| `DB_CONNECT_001` | blocker | 数据库连接失败 | 无法连接到数据库。请检查 data/ 目录是否存在且可访问。 |
| `DB_WRITE_001` | error | 数据库写入失败 | 数据保存失败。可能是磁盘空间不足。 |
| `DB_MIGRATE_001` | error | 数据库结构变更失败 | 数据库升级失败。建议备份 data/ 目录后重新初始化。 |
| `DB_CORRUPT_001` | blocker | 数据库文件损坏 | 数据库文件可能已损坏。建议从备份恢复。 |
| `DB_LOCKED_001` | warning | 数据库被锁定 | 数据库正被其他进程使用。请关闭其他实例后重试。 |

### 3.8 VAULT — Obsidian Vault 异常

| error_code | severity | 触发条件 | user_message |
|------------|----------|----------|-------------|
| `VAULT_NOT_FOUND_001` | warning | Vault 路径不存在 | Obsidian Vault 路径未配置或不存在。请在 .env 中设置 OBSIDIAN_VAULT_PATH。 |
| `VAULT_LINT_001` | warning | Vault lint 发现问题 | Obsidian Vault 存在格式问题。运行 vault-lint 查看详情。 |
| `VAULT_EXPORT_001` | error | Vault 导出失败 | 报告导出到 Obsidian 失败。请检查 Vault 目录权限。 |

### 3.9 SEARCH_GRAPH — 搜索/图谱异常

| error_code | severity | 触发条件 | user_message |
|------------|----------|----------|-------------|
| `SEARCH_FTS_001` | info | FTS5 不可用，已降级为 LIKE | 全文搜索功能受限（使用基础搜索模式）。功能仍可用。 |
| `GRAPH_BUILD_001` | warning | 图谱重建部分失败 | 知识图谱重建时部分节点未成功创建。可尝试重新 rebuild。 |
| `GRAPH_EMPTY_001` | info | 图谱为空 | 知识图谱中暂无数据。分析内容后图谱将自动填充。 |

### 3.10 MCP — MCP Server 异常

| error_code | severity | 触发条件 | user_message |
|------------|----------|----------|-------------|
| `MCP_START_001` | error | MCP Server 启动失败 | MCP Server 启动失败。请检查端口是否被占用。 |
| `MCP_TOOL_001` | warning | MCP Tool 执行异常 | MCP 工具执行时出现错误。部分功能可能暂时不可用。 |
| `MCP_DB_001` | error | MCP Server 数据库连接失败 | MCP Server 无法连接到数据库。请确认服务配置正确。 |

### 3.11 CONFIG — 配置缺失/错误

| error_code | severity | 触发条件 | user_message |
|------------|----------|----------|-------------|
| `CONFIG_MISSING_001` | warning | LLM Provider 未配置 | 未配置 AI 模型。系统将使用 Mock 模式运行（仅用于测试）。 |
| `CONFIG_MISSING_002` | warning | Obsidian Vault 未配置 | 未配置 Obsidian 知识库路径。报告将不会自动导出到 Obsidian。 |
| `CONFIG_INVALID_001` | error | .env 配置格式错误 | 配置文件格式有误。请检查 .env 文件。 |
| `CONFIG_DEP_001` | error | 外部依赖缺失 | 缺少必要的外部工具。请运行 doctor 检查。 |

## 四、Error Code 注册表

所有 error_code 通过 `ErrorCodeRegistry` 集中管理：

```python
class ErrorCodeRegistry:
    """Central registry of all known error codes."""

    _codes: dict[str, ErrorRecord] = {}

    @classmethod
    def register(cls, record: ErrorRecord) -> None:
        if record.error_code in cls._codes:
            raise ValueError(f"Duplicate error_code: {record.error_code}")
        cls._codes[record.error_code] = record

    @classmethod
    def get(cls, error_code: str) -> ErrorRecord | None:
        return cls._codes.get(error_code)

    @classmethod
    def list_by_category(cls, category: str) -> list[ErrorRecord]: ...

    @classmethod
    def list_by_severity(cls, severity: str) -> list[ErrorRecord]: ...

    @classmethod
    def list_by_source_type(cls, source_type: str) -> list[ErrorRecord]: ...
```

注册表在模块加载时初始化，所有 error_code 集中声明，确保唯一性和完整性。

## 五、与 Review Items 的关系

```
ErrorRecord                     ReviewItem
─────────────                   ──────────
error_code       ──映射──→      item_type (当 create_review_item=True)
severity         ──映射──→      severity
user_message     ──映射──→      title
technical_detail ──映射──→      description
entity_ref       ──映射──→      source_path
```

**规则：**
- `severity >= warning` 的错误默认 `create_review_item=True`
- `severity == info` 的错误不创建 review_item（仅日志记录）
- 一个 error_code 对应零个或一个 review_item（去重：同 source_path + 同 item_type 不重复创建）

## 六、当前 error_type 迁移映射

| 现有 | 新 error_code |
|------|--------------|
| `AnalyzeResult.error_type="invalid_url"` | `SOURCE_FETCH_001` |
| `AnalyzeResult.error_type="no_subtitle"` | `EXTRACT_YT_001` |
| `AnalyzeResult.error_type="llm_config"` | `AUTH_LLM_001` |
| `AnalyzeResult.error_type="token_limit"` | `LLM_CALL_003` |
| `AnalyzeResult.error_type="unknown"` | `ANALYSIS_PIPELINE_001` |
| `ZsxqCliMissingError` | `CONFIG_DEP_001` |
| `ZsxqAuthRequiredError` | `AUTH_ZSXQ_001` |
| `ZsxqPermissionDeniedError` | `PERM_ZSXQ_001` |
| `ZsxqParseError` | `SOURCE_PARSE_001` |
| `pdf_needs_ocr` (review) | `EXTRACT_PDF_003` |
| `pdf_quality_issue` (review) | `EXTRACT_PDF_002` |
| `pdf_extraction_failed` (review) | `EXTRACT_PDF_001` |
| `pdf_analysis_skipped` (review) | `ANALYSIS_ELIGIBILITY_001` |
| `zsxq_analysis_skipped` (review) | `ANALYSIS_ELIGIBILITY_001` |
| `zsxq_content_too_short` (review) | `EXTRACT_ZSXQ_002` |
| `zsxq_evidence_missing` (review) | `EXTRACT_ZSXQ_001` |

## 七、使用示例

### 7.1 创建错误记录

```python
from podcast_research.diagnostics.error_codes import ErrorCodeRegistry

# 获取预定义错误
err = ErrorCodeRegistry.get("AUTH_ZSXQ_001")

# 填充运行时上下文
err.trace_id = operation_id
err.entity_ref = f"group:{group_id}"
err.metadata = {"cli_output": stderr}
```

### 7.2 CLI 输出

```
Error [AUTH_ZSXQ_001]: 知识星球未登录
  请在终端运行 zsxq-cli auth login 后重试。
  关联命令: zsxq doctor
  详情: zsxq-cli returned "not logged in" (trace: op_abc123)
```

### 7.3 API 响应

```json
{
  "success": false,
  "error": {
    "error_code": "AUTH_ZSXQ_001",
    "severity": "error",
    "user_message": "知识星球未登录。请在终端运行 `zsxq-cli auth login` 后重试。",
    "suggested_actions": [
      "运行 zsxq-cli auth login",
      "运行 podcast-research zsxq doctor 检查状态"
    ],
    "trace_id": "op_abc123"
  }
}
```

### 7.4 Web 前端消费（供 Codex）

```typescript
// ErrorBanner 组件 props
interface ErrorBannerProps {
  errorCode: string;        // "AUTH_ZSXQ_001"
  severity: "info" | "warning" | "error" | "blocker";
  userMessage: string;      // 直接展示
  suggestedActions: string[]; // 渲染为按钮列表
  onActionClick: (action: string) => void;
}
```

## 八、测试策略

| 测试 | 覆盖 |
|------|------|
| ErrorRecord 默认值 | 所有字段默认值合理 |
| 11 类别各至少 1 个 error_code | 类别完整性 |
| error_code 全局唯一 | 无重复 error_code |
| severity 值合法 | 仅 info/warning/error/blocker |
| suggested_actions 非空 | 每个 error 至少 1 条建议 |
| user_message 中文 | 所有消息为中文 |
| 序列化/反序列化 | JSON round-trip |
| 注册表 CRUD | get/list_by_category/list_by_severity |
| 迁移映射完整性 | 所有现有 error_type 有对应 error_code |
