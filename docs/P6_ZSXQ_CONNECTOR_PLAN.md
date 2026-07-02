# P6 Plan: ZSXQ Read-only Subscription Import

> 状态：P6-A1 ✅ | P6-A2 计划中 | 2026-07-02
> 前置：P3/P4/P5 全部完成（ingest_jobs, review_items, mcp_server, pdf, unified_search, knowledge_graph）

## 一、定位

**我们不是知识星球客户端，也不是内容运营工具。**

知识星球（ZSXQ）仅作为用户已付费订阅、已授权可访问内容的**只读导入源**。
导入后用于本地投资知识库的关联、分析、统一搜索和轻量图谱化。

P6-A 只做一件事：**将用户已订阅的知识星球内容导入为可被现有 pipeline 消费的文本**，
复用 `ingest_jobs → analysis → report → views → signals → unified_search → knowledge_graph` 全链路。

## 二、授权范围管理

### 核心原则

用户订阅、加入、取消订阅等行为**只在知识星球官方客户端完成**。
本项目**不提供**订阅、关注、搜索公开星球、发现星球的能力。

本项目只做一件事：**手动刷新当前账号已授权星球的列表**，并将变更同步到本地 group registry。

### Group Registry

本地维护一份 ZSXQ group 注册表（类似 YouTube channels 表），记录当前账号可访问的星球：

```
zsxq_groups 表字段：
  group_id          — 星球 ID（来自 zsxq-cli）
  group_name        — 星球名称
  access_status     — "active" | "inaccessible"
  topic_count       — 星球主题总数（来自 zsxq-cli）
  last_refreshed_at — 最近刷新时间
  first_seen_at     — 首次发现时间
  notes             — 用户备注
```

### 刷新行为

| 场景 | 行为 |
|------|------|
| 用户执行 `zsxq groups --refresh` | 调用 zsxq-cli 获取当前账号可访问的 group list |
| 新订阅的星球 | 出现在刷新结果中 → group registry 新增，`access_status=active` |
| 已取消订阅/权限消失的星球 | 不出现在刷新结果中 → `access_status` 标记为 `inaccessible` |
| 历史数据 | **不删除**。标记为 inaccessible 的星球，其已导入 topics/reports 保留 |
| 重新订阅 | 再次刷新后 `access_status` 恢复为 `active` |

### 不做

- **不做定时扫描** — 刷新由用户手动触发
- **不做订阅推荐** — 不分析用户应该订阅什么
- **不做权限检测** — 只在用户主动刷新时检测
- **不做星球搜索** — 不提供公开星球发现功能

## 三、为什么是知识星球（续）

投资研究者的信息源中，知识星球占比较高——付费社区的分析帖、行业洞察、调研笔记。
当前系统已支持 YouTube（P0-B）、本地文件（P0-A）、网页（P2-S）、PDF（P4），知识星球是最后一个主要缺口。

## 三、复用现有基础设施

```
ZSXQ Topic (via zsxq-cli)
  │
  ▼
sources/zsxq_connector.py      ← NEW: CLI wrapper + parser
  │  ZsxqTopic { group_id, topic_id, title, content_text, ... }
  ▼
sources/zsxq_profile.py        ← NEW: ZsxqSourceProfile builder
  │  quality / eligibility / content_hash
  ▼
sources/ingest_jobs.py         ← EXISTING: source_type="zsxq_topic"
  │  job_key = "zsxq_topic:{group_id}:{topic_id}"
  ▼
analysis/pipeline.py           ← EXISTING: _run_pipeline()
  │  ZSXQ text → SubtitleSegment-like → LLM extraction
  ▼
unified_search / knowledge_graph  ← EXISTING: 自动受益
```

**关键设计原则：**
- ZSXQ 适配在 `sources/` 层完成，不侵入 `analysis/`、`llm/`、`db/` 核心
- 复用 `ingest_jobs` 的 `source_type` 机制（新增 `zsxq_topic`）
- 复用 `review_items`（新增 ZSXQ 相关的 item_type）
- `unified_search` 和 `knowledge_graph` 自动受益，无需修改

## 四、分阶段计划

### P6-A：ZSXQ Read-only Subscription Import

**目标：** 通过官方 `zsxq-cli` 导入用户已订阅的知识星球内容，进入现有分析 pipeline。

**依赖：** `zsxq-cli`（官方 CLI，需用户自行安装和登录）

**交付：**
- `sources/zsxq_connector.py` — zsxq-cli wrapper + JSON parser
- `sources/zsxq_profile.py` — ZsxqSourceProfile + eligibility check
- `sources/models.py` — `ZsxqTopic`, `ZsxqSourceProfile` 数据类
- ingest_jobs 扩展：`source_type="zsxq_topic"`, job_key 含 group_id+topic_id
- review_items 扩展：`zsxq_cli_missing`, `zsxq_auth_required`, `zsxq_permission_denied`, `zsxq_parse_failed`, `zsxq_attachment_unsupported`
- CLI: `zsxq doctor`, `zsxq groups`, `zsxq import-topic`, `zsxq sync`, `zsxq analyze`
- 不新增 pyproject.toml 依赖（zsxq-cli 由用户自行安装）

**验收标准：**
- [ ] `zsxq doctor` 检测 zsxq-cli 可用性和登录状态
- [ ] `zsxq groups` 列出本地 group registry（含 access_status）
- [ ] `zsxq groups --refresh` 刷新授权范围：新星球→active，权限消失→inaccessible
- [ ] inaccessible 星球的历史数据不删除
- [ ] `zsxq import-topic` 导入单个主题
- [ ] `zsxq sync` 批量导入指定星球的主题
- [ ] content_hash 去重
- [ ] CLI 缺失/未登录/权限不足 → graceful degrade + review_items
- [ ] 导入文本进入 `_run_pipeline()`，生成报告
- [ ] unified_search 可搜索 ZSXQ 内容
- [ ] knowledge_graph 包含 ZSXQ 来源节点
- [ ] ≥25 专项测试（mock zsxq-cli JSON）
- [ ] ruff clean

### P6-B（候选）：ZSXQ 增强

- 附件下载和 OCR（复用 P4 PDF pipeline）
- 增量同步（按 update_time 拉取新主题）
- 多星球批量导入

### P6-S：收口封板

- 验收报告、文档一致性

## 五、CLI 范围

### 允许规划的 CLI 命令

| 命令 | 功能 |
|------|------|
| `zsxq doctor` | 检测 zsxq-cli 可用性、登录状态、token 有效性 |
| `zsxq groups` | 列出本地 group registry 中的星球及 access_status |
| `zsxq groups --refresh` | 调用 zsxq-cli 刷新当前账号可访问的星球列表，更新 group registry |
| `zsxq import-topic --group-id <id> --topic-id <id>` | 导入单个主题 |
| `zsxq sync --group-id <id> --limit <n>` | 批量导入指定星球的最新主题 |
| `zsxq analyze --topic-id <id>` | 导入 + 分析单个主题（含 LLM analysis） |

### 明确不允许规划的 CLI 命令

| 禁止命令 | 原因 |
|----------|------|
| `search-groups` | 不做未订阅内容发现 |
| `subscribe` | 不做订阅操作 |
| `topic create/edit/delete` | 不做任何写入知识星球的操作 |
| `comment/reply/like` | 不做社交互动 |
| `member search` | 不收集用户信息 |
| `admin/moderation` | 不做管理操作 |
| `NPS/feedback` | 不做运营功能 |
| `api-call` / `raw` | 不暴露原始 API 调用 |

## 六、接入方式

**唯一接入方式：官方 `zsxq-cli`。**

| 约束 | 说明 |
|------|------|
| 使用官方 CLI | `zsxq-cli` — 知识星球官方提供的命令行工具 |
| 不使用社区逆向工具 | 不使用任何第三方反编译、cookie 注入、API 逆向工具 |
| 不抓 cookie | 不从浏览器或系统提取 cookie |
| 不自行反编译 API | 不逆向知识星球的内部 API |
| 不绕过权限 | 只访问当前登录账号有权限的星球和主题 |
| 不复制或输出 token | zsxq-cli 的 token 由 CLI 自行管理，不进项目日志、不进 DB |

## 七、数据边界

### ZsxqSourceProfile 字段

只保存入库分析所需的字段：

```
group_id            — 星球 ID
group_name          — 星球名称
topic_id            — 主题 ID
topic_type          — 主题类型（talk/q&a/task/file）
topic_title         — 主题标题
author_name         — 作者名（不保存头像、个人简介）
create_time         — 创建时间
update_time         — 更新时间
tags                — 标签列表
content_text        — 正文文本
attachment_metadata — 附件元数据（文件名、类型、大小，不含附件正文）
source_url          — 原始链接
content_hash        — 内容哈希（用于去重）
imported_at         — 导入时间
```

### 明确不保存的字段

| 不保存 | 原因 |
|--------|------|
| 成员列表 | 用户隐私 |
| 手机号 | 用户隐私 |
| 私信内容 | 用户隐私 |
| 群成员关系 | 用户隐私 |
| 头像 URL | 非分析所需 |
| 个人简介 | 非分析所需 |
| 阅读数/点赞数/评论数 | 非分析所需 |
| 支付信息 | 敏感数据 |
| OAuth token / refresh token | 安全边界 |

## 八、入库策略

```
source_type = "zsxq_topic"
job_key = "zsxq_topic:{group_id}:{topic_id}"
content_hash → 去重（复用 ingest_jobs partial unique index）
```

### Review Items

| item_type | 触发条件 | severity |
|-----------|----------|----------|
| `zsxq_cli_missing` | zsxq-cli 未安装或不可用 | error |
| `zsxq_auth_required` | 未登录或 token 过期 | warning |
| `zsxq_permission_denied` | 无权访问指定星球或主题 | warning |
| `zsxq_parse_failed` | JSON 解析失败 | error |
| `zsxq_attachment_unsupported` | 附件类型不支持 | info |

### 导入后链路

```
zsxq import-topic → extract → profile → quality check
  → ingest_jobs (zsxq_topic) → confirmed
  → _run_pipeline() (existing)
  → report + views + signals
  → unified_search 自动索引
  → knowledge_graph 自动包含 ZSXQ source node
```

## 九、内容使用边界

| 边界 | 说明 |
|------|------|
| 默认本地存储 | 导入内容存储在本地 SQLite + 报告文件 |
| 不提供批量转载 | 不提供原文批量导出或转载功能 |
| 保留来源链接 | 报告中保留 group_id、topic_id、source_url |
| 可输出摘要 | 支持输出 AI 生成的摘要、观点、信号 |
| 可输出证据引用 | 支持引用原文片段（source_quote） |
| 不绕过访问限制 | 不提供绕过原平台付费墙的功能 |

## 十、测试策略

```
tests/test_zsxq_connector.py   — CLI wrapper + JSON 解析
tests/test_zsxq_profile.py     — source profile + eligibility
tests/test_zsxq_ingest.py      — ingest_jobs 集成 + 去重
tests/test_zsxq_cli.py         — CLI smoke
tests/test_zsxq_review.py      — Review Queue 集成
```

**Mock 策略：**
- mock zsxq-cli JSON 输出（本地 JSON fixture 文件）
- 不依赖真实账号
- 不发起真实网络请求
- 不测试真实 OAuth
- 测试 CLI 缺失、未登录、权限不足、JSON 解析失败等异常路径
- 复用现有 fixtures（`db_session`, `seeded_db`, `tmp_path`）

## 十一、不做事项（P6 明确排除）

| 排除项 | 原因 |
|--------|------|
| 知识星球客户端 | 不做平台操作 |
| 内容运营工具 | 不做发布、编辑、删除 |
| 未订阅内容发现 | 不做搜索、推荐 |
| 订阅/购买/推荐 | 不做平台功能 |
| 写入知识星球 | 不做任何 POST/PUT/DELETE |
| 社区逆向/抓 cookie | 安全和法律边界 |
| 成员数据收集 | 用户隐私 |
| 批量转载/导出原文 | 内容使用边界 |
| 绕过付费墙 | 安全边界 |
| 自动同步/定时刷新 | 刷新由用户手动触发，不做 cron/scheduler |
| Web UI | 非当前优先 |
| Deep Research | 多轮 LLM 编排 |
| 复杂图算法 | 接口已预留 |

## 十二、与 P3/P4/P5 的关系

```
P3-A ingest_jobs      ← P6 复用：zsxq_topic source_type
P3-C review_items     ← P6 扩展：5 个新 item_type
P3-D mcp_server       ← P6 自动受益：12 tools 自动支持 ZSXQ 数据
P4-A pdf_extraction   ← P6 关联：ZSXQ 附件可走 PDF pipeline
P5-A unified_search   ← P6 自动受益：ZSXQ 内容可被搜索
P5-B knowledge_graph  ← P6 自动受益：ZSXQ source node + topic edges
```
