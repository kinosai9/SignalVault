# P3-D: MCP Server 设计

> 状态：Design | P3 | 2026-07-01

## 一、问题陈述

当前 podcast_research 的知识库只能通过以下方式访问：
1. Web Console（Jinja2 HTML 页面）
2. CLI（`python -m podcast_research reports list` 等）
3. FastAPI JSON API（`GET /api/reports` 等）

这三种方式都需要用户主动打开浏览器或终端。Claude Code / Cursor / 其他 AI Agent 无法直接查询知识库。

## 二、目标

- 用 Python `mcp` 包实现一个轻量 MCP Server
- 只读查询 9 个 tool，覆盖报告、观点、信号、实体、频道、lint、review
- stdio transport（兼容 Claude Desktop、Codex CLI、Claude Code 等 MCP 客户端）
- 不需要认证（本地信任模型）
- 不新增依赖以外的重量级基础设施

## 三、技术选型

| 组件 | 选择 | 原因 |
|------|------|------|
| MCP SDK | `mcp` (Python) | 官方 Python SDK，轻量 |
| Transport | stdio | 兼容所有 MCP 客户端 |
| 数据源 | SQLite + Vault 文件系统 | 复用现有基础设施 |
| 启动方式 | `python -m podcast_research mcp-serve` | 与现有 CLI 一致 |

## 四、Tools 详细设计

### Tool 1: `search_reports`

```python
{
    "name": "search_reports",
    "description": "搜索已入库的投资分析报告。支持关键词搜索和按来源/频道过滤。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "source": {"type": "string", "enum": ["youtube", "local", "all"], "default": "all"},
            "channel": {"type": "string", "description": "频道名称过滤"},
            "limit": {"type": "integer", "default": 10, "maximum": 50}
        },
        "required": ["query"]
    }
}
```

**实现：** 调用 `db.repository.search_reports()`（现有 FTS5），返回 id, title, channel, analyzed_at, executive_summary。

### Tool 2: `get_report`

```python
{
    "name": "get_report",
    "description": "获取指定报告的完整内容，包括投资观点、信号和 Markdown 正文。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "report_id": {"type": "integer", "description": "报告 ID"}
        },
        "required": ["report_id"]
    }
}
```

**实现：** 调用 `db.repository.get_report_detail()`（现有），返回完整 report dict（含 views, signals, markdown）。

### Tool 3: `list_entities`

```python
{
    "name": "list_entities",
    "description": "列出知识库中的实体（公司/产品/技术/人物等）。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "entity_type": {"type": "string", "description": "实体类型: company/product/technology/person/theme"},
            "name_filter": {"type": "string", "description": "名称过滤（模糊匹配）"},
            "limit": {"type": "integer", "default": 20, "maximum": 100}
        }
    }
}
```

**实现：** 查询 `entities` 表（现有），返回 id, name, normalized_name, entity_type, aliases。

### Tool 4: `get_channel`

```python
{
    "name": "get_channel",
    "description": "获取 YouTube 频道信息和最近视频列表。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "channel_id": {"type": "integer", "description": "频道 ID（可选，不传则返回全部频道列表）"},
            "include_videos": {"type": "boolean", "default": False}
        }
    }
}
```

**实现：** 查询 `channels` 表，可选关联 `channel_videos`。

### Tool 5: `search_claims`

```python
{
    "name": "search_claims",
    "description": "搜索投资观点（Claims），按标的/状态/置信度过滤。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "投资标的（公司名/产品名）"},
            "status": {"type": "string", "enum": ["active", "archived", "superseded", "all"], "default": "active"},
            "limit": {"type": "integer", "default": 20, "maximum": 100}
        }
    }
}
```

**实现：** 扫描 `06_Claims/*.md`（现有），解析 frontmatter 过滤。

### Tool 6: `search_signals`

```python
{
    "name": "search_signals",
    "description": "搜索跟踪信号（Signals），按标的/状态/信号类型过滤。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "投资标的"},
            "status": {"type": "string", "enum": ["active", "triggered", "expired", "archived", "all"], "default": "active"},
            "signal_type": {"type": "string", "description": "信号类型"},
            "limit": {"type": "integer", "default": 20, "maximum": 100}
        }
    }
}
```

**实现：** 扫描 `07_Signals/*.md`（现有），解析 frontmatter 过滤。

### Tool 7: `get_lint_issues`

```python
{
    "name": "get_lint_issues",
    "description": "获取最新的 Vault Lint 检查结果。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "severity": {"type": "string", "enum": ["error", "warning", "info", "all"], "default": "all"},
            "rule": {"type": "string", "description": "lint rule 名称过滤"},
            "limit": {"type": "integer", "default": 50, "maximum": 200}
        }
    }
}
```

**实现：** 查询 `lint_results` 表（P3-B 创建）。

### Tool 8: `get_review_items`

```python
{
    "name": "get_review_items",
    "description": "获取待处理的人工审核事项。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "review_type": {"type": "string", "description": "事项类型: lint_issue/patch_proposal/entity_merge/..."},
            "status": {"type": "string", "enum": ["pending", "in_review", "all"], "default": "pending"},
            "priority": {"type": "string", "enum": ["high", "medium", "low", "all"], "default": "all"},
            "limit": {"type": "integer", "default": 20, "maximum": 100}
        }
    }
}
```

**实现：** 查询 `review_items` 表（P3-C 创建）。

### Tool 9: `vault_status`

```python
{
    "name": "vault_status",
    "description": "获取知识库整体状态概览。",
    "inputSchema": {
        "type": "object",
        "properties": {}
    }
}
```

**返回：**
```json
{
    "vault_path": "/path/to/vault",
    "total_reports": 156,
    "total_topics": 25,
    "total_companies": 48,
    "total_claims": 320,
    "total_signals": 180,
    "active_channels": 5,
    "pending_reviews": 12,
    "lint_errors": 3,
    "lint_warnings": 15,
    "last_analyzed_at": "2026-07-01T10:30:00",
    "last_lint_run_at": "2026-07-01T09:00:00"
}
```

## 五、代码结构

```
src/podcast_research/mcp_server/
    __init__.py       # create_mcp_server(), run_mcp_server()
    tools/
        __init__.py   # register_all_tools()
        reports.py    # search_reports, get_report
        entities.py   # list_entities
        channels.py   # get_channel
        claims.py     # search_claims
        signals.py    # search_signals
        lint.py       # get_lint_issues
        review.py     # get_review_items
        vault.py      # vault_status
```

### 入口

```python
# src/podcast_research/mcp_server/__init__.py

from mcp.server import Server
from mcp.server.stdio import stdio_server

def create_mcp_server() -> Server:
    server = Server("podcast-research")
    register_all_tools(server)
    return server

async def run_mcp_server():
    server = create_mcp_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
```

### CLI 注册

```python
# cli.py
@app.command(name="mcp-serve")
def mcp_serve():
    """启动 MCP Server（stdio transport）。"""
    import asyncio
    from podcast_research.mcp_server import run_mcp_server
    asyncio.run(run_mcp_server())
```

## 六、Claude Desktop 配置

```json
{
    "mcpServers": {
        "podcast-research": {
            "command": "python",
            "args": ["-m", "podcast_research", "mcp-serve"],
            "env": {
                "OBSIDIAN_VAULT_PATH": "/path/to/vault"
            }
        }
    }
}
```

## 七、安全性

| 措施 | 说明 |
|------|------|
| 只读 | 所有 tool 只查询，不修改 DB 或 vault |
| 本地监听 | stdio transport，不暴露网络端口 |
| 无认证 | 本地信任模型（用户自己运行 MCP server） |
| 路径限制 | vault_status 返回 vault_path 但不暴露绝对路径给 tool 输入 |
| 数据量限制 | 所有 tool 有 max limit（50-200），防止返回海量数据 |

## 八、测试计划

```
tests/test_mcp_server.py:

class TestMCPServerStartup:
    def test_server_creates_without_error
    def test_all_tools_registered

class TestMCPTools:
    class TestSearchReports:
        def test_search_by_keyword
        def test_search_by_source
        def test_search_empty_result
        def test_search_limit

    class TestGetReport:
        def test_get_existing_report
        def test_get_nonexistent_report

    class TestListEntities:
        def test_list_all
        def test_filter_by_type
        def test_filter_by_name

    class TestGetChannel:
        def test_get_channel_list
        def test_get_channel_with_videos

    class TestSearchClaims:
        def test_search_by_target
        def test_filter_by_status

    class TestSearchSignals:
        def test_search_by_target
        def test_filter_by_status

    class TestVaultStatus:
        def test_returns_all_counts

class TestMCPReadOnly:
    def test_no_write_operations_exposed
    def test_tools_do_not_modify_db
```

预计 ≥10 tests（部分依赖 P3-B/P3-C 表，在对应阶段实现）。

## 九、依赖

```
# pyproject.toml 新增
dependencies = [
    ...
    "mcp>=1.0",
]
```

`mcp` 是纯 Python 包，无系统依赖。

## 十、不做什么

- 不暴露写入操作（accept review、update claim status 等）
- 不暴露 DB 原始查询
- 不做 streaming / SSE transport
- 不做 OAuth / API Key 认证
- 不托管远程 server
- 不与其他 MCP server 集成
