# P3-D: MCP Server 设计

> 状态：Implemented | P3-D | 2026-07-02

## 一、目标

用 Python `mcp` 包实现轻量只读 MCP Server，让 Claude Code / Codex 等 MCP 客户端
可以直接查询 signalvault 的知识库（报告、观点、信号、实体、频道、review items）。

## 二、技术选型

| 组件 | 选择 | 原因 |
|------|------|------|
| MCP SDK | `mcp>=1.0` (Python) | 官方 Python SDK，轻量 |
| Transport | stdio | 兼容所有 MCP 客户端 |
| 数据源 | SQLite | 复用现有 DB |
| 启动方式 | `python -m signalvault mcp-serve` | 与现有 CLI 一致 |

## 三、代码结构

```
src/signalvault/mcp_server/
    __init__.py       # 导出 create_mcp_server(), run_mcp_server(), TOOLS, handle_call_tool
    server.py         # Server 创建 + stdio runner
    tools.py          # 8 个 Tool 定义 + 查询函数 + handle_call_tool 分发器
    serializers.py    # JSON-safe 序列化辅助函数
```

### 架构

```
MCP Client (Claude Code / Codex)
    │ stdio (JSON-RPC)
    ▼
server.py: create_mcp_server()
    ├─ @server.list_tools() → TOOLS (8 tools)
    └─ @server.call_tool()  → handle_call_tool(name, args)
                                    │
                                    ▼
                              tools.py: _query_*() functions
                                    │
                                    ▼
                              db/repository.py + db/models.py
                              sources/review_items.py
```

核心 query 函数与 MCP 适配层拆开：
- `_query_*()` — 纯同步函数，接收 filter 参数，返回 dict/list
- `handle_call_tool()` — async 分发器，调用 `_query_*()` 并包装为 `TextContent`

## 四、Tools 列表（8 个，全部只读）

### 1. `search_reports`

搜索报告，支持关键词 + 来源过滤。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| query | string | 是 | 搜索关键词 |
| source | enum | 否 | youtube / local / all（默认 all） |
| channel | string | 否 | 频道名模糊匹配 |
| limit | integer | 否 | 默认 10，最大 50 |

返回：报告摘要列表（id, title, source_type, video_id, focus_areas, view_count, match_excerpt, created_at 等）

### 2. `get_report`

获取报告完整内容。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| report_id | integer | 是 | 报告 ID |

返回：报告详情（含 views 列表、signals 列表、report_markdown 正文）

### 3. `list_channels`

列出 YouTube 频道。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| active_only | boolean | 否 | 只返回活跃频道（默认 False） |

返回：频道列表（id, name, url, tags, priority, is_active, video_counts, total_videos 等）

### 4. `search_entities`

搜索实体（公司/产品/技术/人物）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| entity_type | string | 否 | 实体类型过滤 |
| name_filter | string | 否 | 名称模糊匹配 |
| limit | integer | 否 | 默认 20，最大 100 |

返回：实体列表（name, normalized_name, entity_type, aliases）

### 5. `get_entity_profile`

获取实体详情 + 关联投资观点。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| entity_name | string | 是 | 实体名（精确匹配） |

返回：实体 profile（name, entity_type, report_count, view_count, last_seen, recent_views）

### 6. `list_investment_views`

列出投资观点。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| target_name | string | 否 | 标的名称模糊匹配 |
| view_direction | enum | 否 | bullish / bearish / neutral / all（默认 all） |
| ai_value_chain_layer | string | 否 | AI 价值链层级过滤 |
| limit | integer | 否 | 默认 20，最大 100 |

返回：观点列表（target_name, view_direction, logic_chain, confidence, source_quote, report_id 等）

### 7. `list_tracking_signals`

列出跟踪信号。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| target_name | string | 否 | 标的名称模糊匹配 |
| status | enum | 否 | open / triggered / resolved / all（默认 open） |
| limit | integer | 否 | 默认 20，最大 100 |

返回：信号列表（target_name, signal, trigger_condition, status, report_id 等）

### 8. `list_review_items`

列出待审核事项。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| item_type | string | 否 | 事项类型过滤 |
| status | enum | 否 | open / accepted / skipped / resolved / all（默认 open） |
| severity | enum | 否 | error / warning / info / all（默认 all） |
| limit | integer | 否 | 默认 20，最大 100 |

返回：review items 列表（id, item_type, severity, status, title, description, source_path 等）

## 五、启动方式与集成

### 5.1 CLI 启动

```bash
# 使用默认数据库路径（data/signalvault.db）
python -m signalvault mcp-serve

# 指定数据库路径（覆盖 .env 中的 DB_PATH）
python -m signalvault mcp-serve --db-path /path/to/signalvault.db
```

`--db-path` 参数可选。不传时使用 `config.py` 中的 `DB_PATH`（默认 `data/signalvault.db`）。

启动后 MCP server 在 stdio 上等待 JSON-RPC 请求，不监听任何网络端口。stderr 输出启动日志，stdout 用于 MCP 协议通信。

### 5.2 Claude Code 集成

在项目根目录的 `.claude/settings.json` 中添加：

```json
{
    "mcpServers": {
        "signalvault": {
            "command": "python",
            "args": ["-m", "signalvault", "mcp-serve"]
        }
    }
}
```

Claude Code 启动时自动发现并连接。连接后 Claude 可以调用 8 个只读 tool 查询知识库。

**推荐使用方式：**
- "搜索最近关于 NVIDIA 的报告" → `search_reports("NVIDIA")`
- "列出所有审核队列中的 open items" → `list_review_items(status="open")`
- "宁德时代有哪些投资观点" → `get_entity_profile("宁德时代")`
- "最近跟踪哪些信号" → `list_tracking_signals(status="open")`

### 5.3 Codex CLI 集成

Codex CLI 的 MCP 配置与 Claude Desktop 相同格式，在 Codex 配置文件中添加：

```json
{
    "mcpServers": {
        "signalvault": {
            "command": "python",
            "args": ["-m", "signalvault", "mcp-serve"],
            "env": {
                "DB_PATH": "/absolute/path/to/data/signalvault.db"
            }
        }
    }
}
```

### 5.4 Claude Desktop 集成

```json
{
    "mcpServers": {
        "signalvault": {
            "command": "python",
            "args": ["-m", "signalvault", "mcp-serve"],
            "env": {
                "DB_PATH": "/absolute/path/to/data/signalvault.db"
            }
        }
    }
}
```

注意：Claude Desktop 需要绝对路径。`DB_PATH` 环境变量指向 SQLite 数据库文件。

### 5.5 Cursor 集成

Cursor 支持 MCP，在 Cursor 的 MCP 配置中添加相同配置即可。

## 六、安全性

| 措施 | 说明 |
|------|------|
| **只读** | 所有 tool 只查询，不修改 DB 或 Vault。无 INSERT/UPDATE/DELETE |
| **本地 stdio** | 不监听任何 TCP 端口，不暴露 HTTP 端点 |
| **无认证** | 本地信任模型（用户自己运行 MCP server，仅本机可访问） |
| **数量限制** | 所有 tool 有 max limit（50-100），防止单次查询返回海量数据 |
| **无写入 tool** | 不暴露 accept/skip/resolve/retry/run/ingest 等写入操作 |
| **无原始 SQL** | 所有查询通过 repository 层的参数化查询，不拼接 SQL |

### ⚠️ 重要安全边界

1. **不要暴露到远程网络。** stdio transport 设计为本地进程间通信。不要将 MCP server 包装为 HTTP/SSE 端点暴露到公网或局域网。
2. **不要授予写入权限。** 当前 8 个 tool 全部只读。如需执行 accept review、retry job 等操作，使用 CLI 或 Web Console。
3. **数据库文件权限。** 确保 SQLite 数据库文件的文件系统权限仅限当前用户可读写。
4. **不要在生产服务器上以 root 运行。** 使用普通用户权限运行 MCP server。

## 七、测试

`tests/test_mcp_server.py` — 71 tests：

- **Server smoke**: 创建 server、tool 注册、tool 描述验证
- **Read-only 验证**: tool 名称无写入关键字、查询不修改 DB
- **search_reports**: 搜索、无结果、limit、结构验证
- **get_report**: 找到/未找到、views/signals 包含、JSON 序列化
- **list_channels**: 空 DB、active_only、结构验证
- **search_entities**: 类型过滤、名称过滤、空 DB、limit
- **get_entity_profile**: 找到/未找到、关联 views、JSON 序列化
- **list_investment_views**: target/direction 过滤、空 DB、limit
- **list_tracking_signals**: target/status 过滤、空 DB、limit
- **list_review_items**: 空数据稳定返回、limit
- **Empty DB**: 全部 8 个查询函数在空 DB 上的稳定行为
- **Tool handler**: 全部 8 个 tool 的分发测试、unknown tool、JSON 输出

## 八、依赖

```
# pyproject.toml
dependencies = [
    ...
    "mcp>=1.0",
]
```

## 九、设计决策

### 为什么是 8 个 tool 而不是设计文档中的 9 个

设计阶段列出了 9 个 tool（含 `vault_status`），实现阶段聚焦在 SQLite DB 数据查询。
Vault 文件系统扫描（`vault_status`, `get_lint_issues`, `search_claims`）留给后续迭代。
当前 8 个 tool 覆盖了 DB 中所有核心表。

### 为什么 query 函数与 MCP 适配层拆开

- 核心 query 函数（`_query_*()`）是同步的、无 MCP 依赖、可独立单测
- MCP 适配层（`handle_call_tool()`）是异步的、依赖 mcp 包、做轻量 smoke test
- 如果 mcp 包在测试环境不稳定，query 函数仍然可以完整测试

## 十、不做什么

- 不暴露写入操作（accept review、update claim status 等）
- 不暴露 DB 原始查询
- **不做 streaming / SSE transport（禁止远程暴露）**
- 不做 OAuth / API Key 认证
- **不托管远程 server — MCP server 仅本机 stdio 使用**
- 不扫描 Vault 文件系统（当前版本只查 DB）
- 不与其他 MCP server 集成
- **不将 MCP server 包装为 HTTP endpoint — 这会破坏安全模型**
