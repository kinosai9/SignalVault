# P6-A: ZSXQ Connector Design

> 状态：P6-A1 Implemented | P6-A2 Implemented | 2026-07-03
> 前置阅读：`docs/P6_ZSXQ_CONNECTOR_PLAN.md`

## 〇、授权范围刷新

### Group Registry

本地维护一份 `zsxq_groups` 注册表，记录当前账号可访问的星球。语义是 **read-only source registry**，类似 YouTube channels 表，但只做只读同步：

- 用户订阅/加入/取消订阅 → 在知识星球官方客户端完成
- 本项目只在用户主动执行 `zsxq groups --refresh` 时调用 zsxq-cli 获取当前授权列表
- 权限消失的星球**不删除历史数据**，标记 `access_status="inaccessible"`
- 新增订阅的星球在刷新后出现为 `access_status="active"`
- 不做定时扫描，不做星球发现

### 刷新流程

```
zsxq groups --refresh
  → zsxq-cli: zsxq group list --json
  → 解析 JSON → [{group_id, name, topic_count}, ...]
  → 对比本地 zsxq_groups 表:
      ├─ JSON 中有、本地无 → INSERT (access_status="active", first_seen_at=now)
      ├─ JSON 中有、本地有且 status="inaccessible" → UPDATE access_status="active"
      ├─ JSON 中有、本地有且 status="active" → UPDATE last_refreshed_at
      └─ 本地有、JSON 中无 → UPDATE access_status="inaccessible" (不删除)
  → 返回变更摘要: {added: N, reactivated: N, deactivated: N, unchanged: N}
```

### access_status 状态机

```
         ┌──────────────────┐
         │     active       │  ← 用户有权限访问
         └──────┬───────────┘
                │ 权限消失（刷新后 group 不在 CLI 返回列表中）
                ▼
         ┌──────────────────┐
         │  inaccessible    │  ← 用户已取消订阅或权限被移除
         └──────┬───────────┘
                │ 重新订阅（刷新后 group 再次出现）
                ▼
         ┌──────────────────┐
         │     active       │  ← 恢复为 active
         └──────────────────┘
```

历史数据不删除：标记为 inaccessible 时，该星球已导入的 topics/reports/views 全部保留，unified_search 和 knowledge_graph 中仍然可查。

---

## 一、数据模型

### 1.1 ZsxqGroup（sources/models.py 或 db/models.py）

```python
@dataclass
class ZsxqGroup:
    """Local group registry entry — read-only source registry."""
    group_id: str = ""
    group_name: str = ""
    access_status: str = "active"     # "active" | "inaccessible"
    topic_count: int = 0              # from zsxq-cli
    last_refreshed_at: str = ""
    first_seen_at: str = ""
    notes: str = ""
```

如果持久化到 SQLite（推荐），可建 `zsxq_groups` 表（类似 `channels` 表但只读）。

### 1.2 ZsxqTopic（sources/models.py）

```python
@dataclass
class ZsxqTopic:
    """Parsed ZSXQ topic from zsxq-cli JSON output."""
    group_id: str = ""
    group_name: str = ""
    topic_id: str = ""
    topic_type: str = ""            # "talk" | "q&a" | "task" | "file"
    topic_title: str = ""
    author_name: str = ""
    create_time: str = ""           # ISO format
    update_time: str = ""
    tags: list[str] = field(default_factory=list)
    content_text: str = ""          # plain text (HTML stripped)
    content_html: str = ""          # raw HTML (for reference, not indexed)
    attachment_metadata: list[dict] = field(default_factory=list)
        # [{"name": "...", "type": "pdf/image/...", "size": 1234, "url": "..."}]
    source_url: str = ""
    content_hash: str = ""
    char_count: int = 0
    parse_quality: str = "good"     # "good" | "degraded" | "minimal"
    quality_warnings: list[str] = field(default_factory=list)
```

### 1.2 ZsxqSourceProfile（sources/models.py）

```python
@dataclass
class ZsxqSourceProfile:
    """Profile built from ZsxqTopic after quality checks."""
    group_id: str = ""
    group_name: str = ""
    group_access_status: str = "active"  # "active" | "inaccessible"
    topic_id: str = ""
    topic_type: str = ""
    topic_title: str = ""
    author_name: str = ""
    create_time: str = ""
    update_time: str = ""
    tags: list[str] = field(default_factory=list)
    content_text: str = ""
    content_hash: str = ""
    source_url: str = ""
    import_eligible: bool = False
    ineligible_reason: str = ""
    parse_quality: str = "good"
    quality_warnings: list[str] = field(default_factory=list)
    imported_at: str = ""
```

`group_access_status` 来自 group registry。如果星球已标记为 inaccessible，该星球的所有 topic import 仍可执行（用户可能仍有缓存的 topic JSON），但 `group_access_status` 字段会反映当前授权状态。

### 1.3 与现有模型的关系

`ZsxqSourceProfile` 与 `UploadedFileProfile`（P2-S.3.3）风格一致——都是只读 profile，不做写入。
`ZsxqTopic` 是 zsxq-cli 输出的内部表示，不直接暴露给 ingest_jobs。

## 二、zsxq-cli 接入

### 2.1 CLI Wrapper

```python
# sources/zsxq_connector.py

def check_zsxq_cli() -> dict:
    """Check zsxq-cli availability and login status.

    Returns:
        {"available": bool, "version": str, "logged_in": bool,
         "error": str}
    """
    import subprocess, shutil
    if not shutil.which("zsxq"):
        return {"available": False, "version": "", "logged_in": False,
                "error": "zsxq-cli not found in PATH"}
    # zsxq whoami → check login
    ...

def list_groups() -> list[dict]:
    """List groups the current user has access to.

    Returns list of {"group_id": ..., "name": ..., "topic_count": ...}
    """
    # zsxq groups list --json
    ...

def fetch_topic(group_id: str, topic_id: str) -> ZsxqTopic:
    """Fetch a single topic by group_id and topic_id.

    Raises ZsxqCliError if CLI missing/not logged in.
    Raises ZsxqPermissionError if access denied.
    Raises ZsxqParseError if JSON output cannot be parsed.
    """
    # zsxq topic get --group-id <id> --topic-id <id> --json
    ...

def fetch_topics(group_id: str, limit: int = 20,
                 since: str | None = None) -> list[ZsxqTopic]:
    """Fetch recent topics from a group.

    Args:
        group_id: ZSXQ group ID.
        limit: Max topics to fetch.
        since: ISO datetime — only fetch topics updated after this.
    """
    # zsxq topic list --group-id <id> --limit <n> --json
    ...
```

### 2.2 异常定义

```python
class ZsxqCliError(Exception):
    """zsxq-cli not found or execution failed."""
    pass

class ZsxqAuthError(Exception):
    """Not logged in or token expired."""
    pass

class ZsxqPermissionError(Exception):
    """Access denied to group or topic."""
    pass

class ZsxqParseError(Exception):
    """JSON output parse failed."""
    pass
```

### 2.3 Graceful Degrade

每个 CLI 调用点都 wrap try/except，返回结构化结果（不是抛异常到上层崩掉）：

```python
try:
    topic = fetch_topic(group_id, topic_id)
except ZsxqCliError:
    → review_items: zsxq_cli_missing
except ZsxqAuthError:
    → review_items: zsxq_auth_required
except ZsxqPermissionError:
    → review_items: zsxq_permission_denied
except ZsxqParseError:
    → review_items: zsxq_parse_failed
```

## 三、Source Profile + Eligibility

### 3.1 Profile Builder

```python
# sources/zsxq_profile.py

def build_zsxq_source_profile(topic: ZsxqTopic) -> ZsxqSourceProfile:
    """Build a source profile from a ZsxqTopic.

    Checks:
      1. content_text length ≥ 100 chars
      2. content_hash exists
      3. parse_quality != "minimal"
    """
    eligible = True
    reason = ""
    warnings = list(topic.quality_warnings)

    if topic.parse_quality == "minimal":
        eligible = False
        reason = "内容解析质量过低，无法提取有效文本。"

    if len(topic.content_text) < 100:
        eligible = False
        reason = f"文本内容过短（{len(topic.content_text)} 字），不适合分析。"

    if not topic.content_hash:
        eligible = False
        reason = "无法计算内容哈希。"

    return ZsxqSourceProfile(
        group_id=topic.group_id,
        group_name=topic.group_name,
        topic_id=topic.topic_id,
        topic_type=topic.topic_type,
        topic_title=topic.topic_title,
        author_name=topic.author_name,
        create_time=topic.create_time,
        update_time=topic.update_time,
        tags=topic.tags,
        content_text=topic.content_text,
        content_hash=topic.content_hash,
        source_url=topic.source_url,
        import_eligible=eligible,
        ineligible_reason=reason,
        parse_quality=topic.parse_quality,
        quality_warnings=warnings,
        imported_at=datetime.now().isoformat(),
    )
```

### 3.2 附件处理

附件不下载正文，只保存元数据。如果附件是 PDF：
1. 用户可单独用 `pdf import` 导入（复用 P4 pipeline）
2. 在 `attachment_metadata` 中记录文件信息
3. 如果附件类型不支持 → `zsxq_attachment_unsupported` review item（info 级别）

## 四、ingest_jobs 复用

### 4.1 source_type 和 job_key

```python
# sources/ingest_jobs.py — 新增

if source_type == "zsxq_topic":
    import hashlib
    raw = f"{group_id}:{topic_id}"
    key_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"zsxq_topic:{key_hash}"
```

`_make_job_key()` 需要接收 `group_id` 和 `topic_id` 参数。扩展现有签名或在 payload 中传入。

### 4.2 导入流程

```
zsxq import-topic --group-id X --topic-id Y
  → fetch_topic(X, Y) → ZsxqTopic
  → build_zsxq_source_profile(topic) → ZsxqSourceProfile
  → IngestJobManager.create_job(
      source_type="zsxq_topic",
      source_hash=topic.content_hash,
      source_name=topic.topic_title,
      preview_data=json.dumps(profile),
    )
  → status = "pending_preview"
  → 用户确认 → status = "confirmed_archive"
  → 进入 analysis pipeline (_run_pipeline)
  → report + views + signals + entities
```

### 4.3 去重

同一 topic（content_hash 相同）→ `uq_ingest_jobs_key_status` 部分唯一索引阻止重复 `pending_preview`。

## 五、Analysis Pipeline 接入

### 5.1 ZSXQ 文本 → LLM

```python
# ZSXQ 文本进入 _run_pipeline()
# 文本作为 subtitle-less 输入，与 PDF 分析路径一致

source_info = {
    "source_type": "zsxq_topic",
    "source_url": topic.source_url,
    "zsxq_group_id": topic.group_id,
    "zsxq_group_name": topic.group_name,
    "zsxq_topic_id": topic.topic_id,
    "zsxq_author": topic.author_name,
    "zsxq_create_time": topic.create_time,
    "title": topic.topic_title,
}

episode_extra = {
    "source": "zsxq_topic",
    "source_url": topic.source_url,
}
```

### 5.2 source_info_override

```python
# 这些字段出现在 report frontmatter 中
source_info_override = {
    "zsxq_group_id": topic.group_id,
    "zsxq_group_name": topic.group_name,
    "zsxq_topic_id": topic.topic_id,
    "zsxq_author": topic.author_name,
}
```

## 六、Review Queue 集成

### 6.1 item_type 扩展

```python
# sources/review_items.py — VALID_ITEM_TYPES 扩展

"zsxq_cli_missing",
"zsxq_auth_required",
"zsxq_permission_denied",
"zsxq_parse_failed",
"zsxq_attachment_unsupported",
```

### 6.2 入队规则

| 场景 | item_type | severity |
|------|-----------|----------|
| zsxq-cli 未安装 | `zsxq_cli_missing` | error |
| 未登录 / token 过期 | `zsxq_auth_required` | warning |
| 无权访问星球/主题 | `zsxq_permission_denied` | warning |
| JSON 解析失败 | `zsxq_parse_failed` | error |
| 附件类型不支持 | `zsxq_attachment_unsupported` | info |

## 七、CLI 命令设计

### 7.1 zsxq doctor

```bash
$ python -m podcast_research zsxq doctor

ZSXQ CLI Check
  CLI: zsxq v1.2.3 (/usr/local/bin/zsxq) ✓
  Login: logged in as @username ✓
  Token: valid (expires 2026-08-01)

  All checks passed.
```

### 7.2 zsxq groups

```bash
# 查看本地 group registry（不调用 zsxq-cli）
$ python -m podcast_research zsxq groups

ZSXQ Group Registry (3):
  ID          Name                  Status        Topics   Last Refreshed
  ......................................................................
  12345678    投资研究社区            active        1,234   2026-07-02
  87654321    AI产业观察              active        567     2026-07-02
  11223344    宏观经济学苑            inaccessible  890     2026-06-15

  Note: inaccessible groups retain historical data.
        Use --refresh to update authorization status.
```

```bash
# 刷新授权范围（调用 zsxq-cli）
$ python -m podcast_research zsxq groups --refresh

Refreshing ZSXQ group authorization...
  Calling zsxq-cli: zsxq group list --json...

  Changes:
    + Added:    1 (新订阅星球)
    ↻ Reactivated: 0
    − Deactivated: 1 (宏观经济学苑 — 权限已消失)
    = Unchanged: 2

  Current: 3 groups (2 active, 1 inaccessible)

  Note: Deactivated groups retain all imported data.
        To re-enable, re-subscribe in ZSXQ app and run --refresh again.
```

### 7.3 zsxq import-topic

```bash
$ python -m podcast_research zsxq import-topic \
    --group-id 12345678 --topic-id 9876543210

📥 Importing topic 9876543210 from 投资研究社区
  Title: 2025 Q4 AI 芯片需求分析
  Author: @tech_analyst
  Quality: good (2,340 chars)
  Eligible: yes

  Actions:
    [confirm_archive] Import and analyze
    [skip] Skip
```

### 7.4 zsxq sync

```bash
$ python -m podcast_research zsxq sync \
    --group-id 12345678 --limit 20

Syncing 投资研究社区...
  Topics found: 20
  New (not yet imported): 5
  Already imported (skipped): 15

  Imported: 5 topics → pending_preview
  Use `ingest list --type zsxq_topic` to review.
```

### 7.5 zsxq analyze

```bash
$ python -m podcast_research zsxq analyze \
    --topic-id 9876543210 --mock --focus "AI芯片"

📥 Fetching topic + 📄 Analyzing...
  Report ID: 42
  Views: 3
  Entities: 2
```

## 八、模块结构

```
src/podcast_research/sources/
    models.py              ← 扩展：ZsxqGroup, ZsxqTopic, ZsxqSourceProfile
    zsxq_connector.py      ← NEW: zsxq-cli wrapper + parser
    zsxq_profile.py        ← NEW: profile builder + eligibility
    zsxq_registry.py       ← NEW: group registry CRUD (refresh/status/query)
    ingest_jobs.py         ← 扩展：zsxq_topic source_type
    review_items.py        ← 扩展：5 个新 item_type

src/podcast_research/db/
    models.py              ← 扩展：ZsxqGroup ORM（如持久化到 SQLite）

src/podcast_research/
    cli.py                 ← 扩展：zsxq 命令组

tests/
    test_zsxq_registry.py  ← NEW: group registry refresh/status
    test_zsxq_connector.py ← NEW: ~10 tests
    test_zsxq_profile.py   ← NEW: ~5 tests
    test_zsxq_ingest.py    ← NEW: ~5 tests
    test_zsxq_cli.py       ← NEW: ~5 tests
```

## 九、P5 自动受益（As-Implemented）

P6-A 对 P5 做了最小修改（仅 source_type 识别），分析产物自动受益：

| P5 能力 | 修改程度 | 如何支持 ZSXQ |
|----------|----------|---------------|
| `unified_search` | 1 行 | `_infer_source_type()` → `zsxq_topic` |
| `knowledge_graph._build_source_nodes()` | 8 行 | 从 `episodes WHERE source="zsxq_topic"` 创建 source nodes |
| `get_entity_neighborhood` | 0 行 | ZSXQ 中提到的实体自动进入图谱 |
| `get_evidence_trail` | 0 行 | ZSXQ 观点可追溯到 source_url + topic_id |
| `list_graph_edges` | 0 行 | ZSXQ source node → report edges 自动生成 |
| MCP Server (8 tools) | 0 行 | 所有 tool 自动支持 ZSXQ 数据 |

## 十、边界情况

| 场景 | 处理 |
|------|------|
| zsxq-cli 未安装 | `zsxq doctor` 提示安装 → `zsxq_cli_missing` review |
| 未登录 / token 过期 | `zsxq_auth_required` review → 提示执行 `zsxq login` |
| 无权访问星球 | `zsxq_permission_denied` review → 不重试 |
| JSON 输出格式变化 | `zsxq_parse_failed` review → 人工检查 CLI 版本 |
| 主题内容为空 | `parse_quality="minimal"` → import_eligible=False |
| 附件为不支持格式 | `zsxq_attachment_unsupported` review (info) → 不阻塞 |
| 网络超时 | 重试 1 次，仍失败 → error + 不崩溃 |
| topic_id 重复导入 | content_hash 去重 → ingest_jobs unique index 阻止 |
| 超大正文（>50K 字符） | 复用现有 chunking 机制 |

## 十一、As-Implemented 摘要 (P6-S)

### 模块结构（实际）

```
sources/zsxq_models.py     — ZsxqGroup, ZsxqTopic, ZsxqSourceProfile + compute_content_hash
sources/zsxq_cli.py        — CLI wrapper (subprocess): check_cli, list_groups, fetch_topic, fetch_topics + 4 exceptions
sources/zsxq_registry.py   — Group Registry JSON CRUD: list, get, refresh (added/reactivated/deactivated/unchanged)
sources/zsxq_import.py     — Import pipeline: build_zsxq_source_profile, import_topic_to_ingest, sync_group_to_ingest
sources/zsxq_analysis.py   — Analysis pipeline: analyze_zsxq_topic, build_zsxq_analysis_source, _check_zsxq_analysis_eligibility, _topic_to_segments, import_and_analyze
sources/ingest_jobs.py     — Extended: source_type="zsxq_topic"
sources/review_items.py    — Extended: 8 ZSXQ item_types
db/repository.py           — Extended: _infer_source_type → zsxq_topic, pdf_upload
db/unified_search.py       — Extended: _infer_source_type → zsxq_topic
db/knowledge_graph.py      — Extended: _build_source_nodes → ZSXQ source nodes
cli.py                     — Extended: zsxq command group (6 commands)
```

### Evidence / source_info 传递

ZSXQ 没有视频 timestamp，没有 PDF page。追溯通过 `source_info` 实现：

```python
source_info = {
    "source_type": "zsxq_topic",
    "source_url": profile.source_url,       # → episode.source_url
    "zsxq_group_id": profile.group_id,
    "zsxq_group_name": profile.group_name,
    "zsxq_topic_id": profile.topic_id,
    "zsxq_topic_type": profile.topic_type,
    "zsxq_author": profile.author_name,
    "zsxq_create_time": profile.create_time,
    "zsxq_tags": profile.tags,
    "zsxq_content_hash": profile.content_hash,
}

episode_extra = {
    "source": "zsxq_topic",                 # → episode.source
    "source_url": profile.source_url,
    "video_id": "",                         # ZSXQ 无 video_id
    "language": "zh",
}
```

追溯路径：`report.id → episode.source_url/source → source_info.zsxq_group_id/zsxq_topic_id`

### 只读安全边界

- 6 个 CLI 命令全部只读（doctor/groups/import-topic/sync/analyze）
- zsxq-cli 仅调用 `group list`/`topic detail`/`auth status`（全部只读）
- 不调用 `api raw/call`，不暴露原始 API
- Token 不进日志/DB/代码
- 附件仅存元数据，不下载正文
- 不做定时扫描，不做未订阅内容获取
