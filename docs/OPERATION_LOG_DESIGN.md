# P7-B: Operation Log Design

> 状态：Implemented | 2026-07-03
> 读者：Claude Code (实现) + Codex (前端对接)

## 一、目标

为所有用户发起的操作和系统自动动作建立统一的结构化审计日志。当前系统通过 48 个 `logging.getLogger(__name__)` 输出非结构化日志到文件——对非 IT 用户不可见，对远程排查效率低。

Operation Log 是**应用层结构化日志**，与 stdlib logging（调试用途）互补：
- **stdlib logging**：DEBUG/INFO 级别，开发者排查用，写入 `logs/` 文件
- **operation_log**：用户可见的操作记录，写入 SQLite，CLI/Web 可查询

## 二、OperationLog 数据模型

### 2.1 DB 表

```sql
CREATE TABLE operation_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id    TEXT UNIQUE NOT NULL,       -- UUID4
    operation_type  TEXT NOT NULL,              -- 枚举值
    status          TEXT NOT NULL DEFAULT 'started',
                                                -- started / succeeded / failed / cancelled
    started_at      DATETIME NOT NULL,
    finished_at     DATETIME,
    duration_ms     INTEGER,
    source_type     TEXT DEFAULT '',
    target_ref      TEXT DEFAULT '',            -- "group:G001", "topic:T001", "job:42"
    summary         TEXT DEFAULT '',            -- 人类可读摘要，≤500 chars
    error_code      TEXT DEFAULT '',            -- 关联 ErrorRecord.error_code
    error_detail    TEXT DEFAULT '',            -- 错误补充信息
    initiated_by    TEXT DEFAULT 'user',        -- user / system / mcp
    metadata_json   TEXT DEFAULT '{}',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_operation_logs_type ON operation_logs(operation_type);
CREATE INDEX idx_operation_logs_status ON operation_logs(status);
CREATE INDEX idx_operation_logs_started ON operation_logs(started_at);
CREATE INDEX idx_operation_logs_target ON operation_logs(target_ref);
```

### 2.2 Python dataclass

```python
@dataclass
class OperationLog:
    operation_id: str = ""       # UUID4
    operation_type: str = ""     # OperationType 枚举
    status: str = "started"      # started / succeeded / failed / cancelled
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    source_type: str = ""        # youtube / pdf_upload / zsxq_topic / local
    target_ref: str = ""         # 操作目标引用
    summary: str = ""            # 人类可读
    error_code: str = ""         # 关联 ErrorCode
    error_detail: str = ""
    initiated_by: str = "user"   # user / system / mcp
    metadata_json: str = "{}"
```

## 三、操作类型枚举（≥22）

### 3.1 ZSXQ 操作

| operation_type | 触发 | 描述 |
|---------------|------|------|
| `zsxq.groups.refresh` | `zsxq groups --refresh` | 刷新授权星球列表 |
| `zsxq.topic.import` | `zsxq import-topic` | 导入单个主题 |
| `zsxq.topic.analyze` | `zsxq analyze` | 导入 + 分析单个主题 |
| `zsxq.sync` | `zsxq sync` | 批量导入星球主题 |

### 3.2 PDF 操作

| operation_type | 触发 | 描述 |
|---------------|------|------|
| `pdf.preview` | `pdf preview` | 预览 PDF 质量 |
| `pdf.extract` | `pdf extract` | 提取 PDF 文本 |
| `pdf.analyze` | `pdf analyze` | 提取 + 分析 PDF |

### 3.3 Ingest 操作

| operation_type | 触发 | 描述 |
|---------------|------|------|
| `ingest.confirm` | `ingest confirm` | 确认摄入任务 |
| `ingest.retry` | `ingest retry` | 重试失败任务 |
| `ingest.resume` | `ingest resume` | 恢复待处理任务 |
| `ingest.expire` | 系统自动 | 过期任务清理 |

### 3.4 Vault 操作

| operation_type | 触发 | 描述 |
|---------------|------|------|
| `vault.lint` | `vault-lint` | Vault 健康检查 |
| `vault.export` | obsidian export 命令 | 导出报告到 Obsidian |

### 3.5 Review 操作

| operation_type | 触发 | 描述 |
|---------------|------|------|
| `review.accept` | `review accept` | 接受审核项 |
| `review.skip` | `review skip` | 跳过审核项 |
| `review.resolve` | `review resolve` | 解决审核项 |

### 3.6 Search 操作

| operation_type | 触发 | 描述 |
|---------------|------|------|
| `search.unified` | `search` 命令 / Web 搜索 | 统一搜索 |

### 3.7 Graph 操作

| operation_type | 触发 | 描述 |
|---------------|------|------|
| `graph.rebuild` | `graph rebuild` | 重建知识图谱 |
| `graph.export` | `graph export` | 导出图谱 JSON |

### 3.8 MCP 操作

| operation_type | 触发 | 描述 |
|---------------|------|------|
| `mcp.serve.start` | `mcp-serve` | MCP Server 启动 |
| `mcp.serve.stop` | 进程终止 | MCP Server 停止 |

### 3.9 System 操作

| operation_type | 触发 | 描述 |
|---------------|------|------|
| `system.doctor` | `doctor` | 全系统健康检查 |
| `system.diagnostics.bundle` | `diagnostics bundle` | 导出诊断包 |

## 四、OperationLogManager

```python
class OperationLogManager:
    """CRUD for operation_logs table."""

    @staticmethod
    def start(operation_type: str, source_type: str = "",
              target_ref: str = "", initiated_by: str = "user",
              metadata: dict | None = None,
              session=None) -> OperationLog:
        """开始一个操作，返回带 operation_id 的 OperationLog。status='started'."""
        ...

    @staticmethod
    def succeed(op: OperationLog, summary: str = "",
                metadata: dict | None = None,
                session=None) -> OperationLog:
        """标记操作成功。自动计算 duration_ms。"""
        ...

    @staticmethod
    def fail(op: OperationLog, error_code: str = "",
             error_detail: str = "", summary: str = "",
             session=None) -> OperationLog:
        """标记操作失败。自动计算 duration_ms。"""
        ...

    @staticmethod
    def cancel(op: OperationLog, reason: str = "",
               session=None) -> OperationLog:
        """标记操作取消。"""
        ...

    @staticmethod
    def list_recent(limit: int = 50, operation_type: str | None = None,
                    status: str | None = None,
                    session=None) -> list[OperationLog]: ...

    @staticmethod
    def get(operation_id: str, session=None) -> OperationLog | None: ...

    @staticmethod
    def count_by_type(session=None) -> dict[str, int]: ...

    @staticmethod
    def recent_failures(limit: int = 20, session=None) -> list[OperationLog]: ...
```

## 五、使用示例

### 5.1 典型操作生命周期

```python
from signalvault.diagnostics.operation_log import OperationLogManager

# 1. 开始操作
op = OperationLogManager.start(
    operation_type="zsxq.topic.analyze",
    source_type="zsxq_topic",
    target_ref=f"group:{group_id}/topic:{topic_id}",
    metadata={"group_name": group_name, "topic_title": topic_title},
)
# op.operation_id = "uuid-xxx"
# op.status = "started"

try:
    result = import_and_analyze(group_id, topic_id, ...)
    # 2. 成功
    OperationLogManager.succeed(
        op,
        summary=f"分析完成: {topic_title}, report_id={result['analysis']['report_id']}",
        metadata={"report_id": result["analysis"]["report_id"]},
    )
except Exception as e:
    # 3. 失败
    OperationLogManager.fail(
        op,
        error_code="ANALYSIS_PIPELINE_001",
        error_detail=str(e)[:500],
        summary=f"分析失败: {topic_title}",
    )
```

### 5.2 CLI 查询

```bash
$ signalvault logs list
  ID       操作                          状态      耗时     时间
  op_001   zsxq.topic.analyze            success   3.2s    07-03 14:30
  op_002   pdf.preview                   success   0.5s    07-03 14:28
  op_003   graph.rebuild                 success   1.1s    07-03 14:25
  op_004   zsxq.groups.refresh           failed    0.8s    07-03 14:20

$ signalvault logs show op_004
  Operation: zsxq.groups.refresh
  Status:    failed
  Error:     AUTH_ZSXQ_001 — 知识星球未登录
  Summary:   zsxq-cli returned "not logged in"
  Duration:  0.8s
  Suggested: 运行 zsxq-cli auth login
```

### 5.3 Web 对接（供 Codex）

```typescript
// OperationTimeline 组件
interface OperationLogEntry {
  operationId: string;
  operationType: string;       // 用于图标选择
  status: "started" | "succeeded" | "failed" | "cancelled";
  summary: string;
  durationMs: number;
  errorCode?: string;          // 失败时展示错误详情
  startedAt: string;
  finishedAt?: string;
}
```

## 六、与现有 JobEvent 的关系

| 维度 | JobEvent | OperationLog |
|------|----------|-------------|
| 覆盖范围 | 仅 Job 生命周期 | 所有用户/系统操作 |
| 粒度 | 阶段级 (stage) | 操作级 |
| 关联 | job_id | operation_id (独立) |
| 保留 | 不变 | 新增 |
| 迁移 | 不迁移 | `JobEvent` 可通过 `operation_id` 关联到 OperationLog |

**不需要迁移现有 JobEvent。** OperationLog 是新增能力，JobEvent 保持现有结构。两者通过 `operation_id` 可选关联。

## 七、测试策略

| 测试 | 覆盖 |
|------|------|
| start → succeed 完整生命周期 | status 转换、duration_ms 计算 |
| start → fail 完整生命周期 | error_code 记录 |
| start → cancel | cancelled 状态 |
| list_recent 排序和过滤 | 按 type/status 过滤 |
| recent_failures 仅返回失败 | 状态过滤正确 |
| 并发操作不冲突 | UUID 唯一 |
| 空 DB 查询不崩溃 | 边界情况 |
| 序列化 → JSON | CLI/API 输出 |
