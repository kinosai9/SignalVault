# P6 Acceptance Report: ZSXQ Read-only Subscription Import

> 状态：**Complete** | 2026-07-03
> 验收人：Claude Code
> 总测试：1771 passed | ruff：clean

## 一、P6 目标与定位

**将用户已付费订阅的知识星球内容，作为只读导入源，接入现有 6 层分析基础设施。**

```
ZSXQ Topic (zsxq-cli)
  → sources/zsxq_cli.py (fetch)
  → sources/zsxq_import.py (profile + eligibility + ingest_job)
  → sources/zsxq_analysis.py (eligibility → segments → _run_pipeline)
  → analysis/pipeline.py (LLM extraction → report + views + signals)
  → db/unified_search.py (FTS5 + LIKE, source_type=zsxq_topic)
  → db/knowledge_graph.py (source nodes + edges, auto)
```

**不是知识星球客户端。不做发布、评论、订阅、搜索、定时扫描。**

## 二、P6-A1 交付内容（Read-only Import）

| 模块 | 文件 | 功能 |
|------|------|------|
| Data Models | `sources/zsxq_models.py` | `ZsxqGroup`, `ZsxqTopic`, `ZsxqSourceProfile` + `compute_content_hash` |
| CLI Wrapper | `sources/zsxq_cli.py` | `check_cli()`, `list_groups()`, `fetch_topic()`, `fetch_topics()` + 4 exception types |
| Group Registry | `sources/zsxq_registry.py` | JSON-file registry — `list_registry()`, `get_group()`, `refresh_registry()` (added/reactivated/deactivated/unchanged) |
| Topic Import | `sources/zsxq_import.py` | `build_zsxq_source_profile()`, `import_topic_to_ingest()`, `sync_group_to_ingest()` |
| Ingest Jobs | `sources/ingest_jobs.py` | `source_type="zsxq_topic"`, `_make_job_key()` extension |
| Review Items | `sources/review_items.py` | 5 item_types: `zsxq_cli_missing`, `zsxq_auth_required`, `zsxq_permission_denied`, `zsxq_parse_failed`, `zsxq_attachment_unsupported` |
| CLI | `cli.py` | `zsxq doctor`, `zsxq groups (--refresh)`, `zsxq import-topic`, `zsxq sync` |
| Tests | `tests/test_zsxq_import.py` | 29 tests (models, registry, profile, ingest, errors, review, CLI smoke) |

## 三、P6-A2 交付内容（Topic Analysis Pipeline）

| 模块 | 文件 | 功能 |
|------|------|------|
| Analysis | `sources/zsxq_analysis.py` | `analyze_zsxq_topic()`, `build_zsxq_analysis_source()`, `_check_zsxq_analysis_eligibility()`, `_topic_to_segments()`, `import_and_analyze()` |
| Pipeline Reuse | `analysis/pipeline.py` | 复用 `_run_pipeline()` — 无新 LLM pipeline |
| Review Items | `sources/review_items.py` | +3 item_types: `zsxq_analysis_skipped`, `zsxq_content_too_short`, `zsxq_evidence_missing` |
| Source Type | `db/repository.py` | `_infer_source_type()` → `zsxq_topic` + `pdf_upload` |
| Source Type | `db/unified_search.py` | `_infer_source_type()` → `zsxq_topic` |
| Graph | `db/knowledge_graph.py` | `_build_source_nodes()` → ZSXQ source nodes |
| CLI | `cli.py` | `zsxq analyze --group-id --topic-id --mock --focus --output --depth` |
| Tests | `tests/test_zsxq_analysis.py` | 39 tests (segments, eligibility, source_info, mock pipeline, evidence, review, CLI, search, graph) |

## 四、完整 CLI 命令清单

```bash
# ── Doctor ──────────────────────────────────────────────────
python -m signalvault zsxq doctor
# 检测 zsxq-cli 可用性、版本、登录状态

# ── Group Registry ──────────────────────────────────────────
python -m signalvault zsxq groups
# 列出本地 group registry（含 access_status）

python -m signalvault zsxq groups --refresh
# 调用 zsxq-cli 刷新授权星球列表
# 返回: +added / ↻reactivated / −deactivated / =unchanged

# ── Import ──────────────────────────────────────────────────
python -m signalvault zsxq import-topic --group-id <id> --topic-id <id>
# 导入单个主题为 ingest_job（不进入 LLM 分析）

python -m signalvault zsxq sync --group-id <id> --limit 20
# 批量导入星球最新主题

# ── Analyze ─────────────────────────────────────────────────
python -m signalvault zsxq analyze --group-id <id> --topic-id <id>
# 导入 + eligibility + LLM 分析（默认 mock）

python -m signalvault zsxq analyze --group-id <id> --topic-id <id> --mock --focus "AI芯片"
# Mock 模式 + 指定关注点

python -m signalvault zsxq analyze --group-id <id> --topic-id <id> --output ./reports
# 指定报告输出目录
```

## 五、数据模型与 source_type

### 5.1 统一 source_type

```
source_type = "zsxq_topic"
```

跨 `ingest_jobs`, `episodes.source`, `unified_search`, `knowledge_graph` 统一使用。

### 5.2 ZsxqGroup

```
group_id, group_name, access_status, topic_count,
last_refreshed_at, first_seen_at, notes
```

持久化到 `data/zsxq_groups.json`。`access_status` 状态机：`active ↔ inaccessible`（历史数据不删除）。

### 5.3 ZsxqTopic

```
group_id, group_name, topic_id, topic_type, topic_title,
author_name, create_time, update_time, tags,
content_text, attachment_metadata, source_url,
content_hash, char_count, parse_quality
```

`content_hash` = SHA256[:16]，用于去重。

### 5.4 ZsxqSourceProfile

```
source_type="zsxq_topic", group_id, group_name, group_access_status,
topic_id, topic_type, topic_title, author_name,
create_time, update_time, tags,
content_text, content_hash, source_url,
attachment_metadata, import_eligible, ineligible_reason,
parse_quality, quality_warnings, imported_at
```

`import_eligible` 由 `build_zsxq_source_profile()` 判定（≥100 chars + hash + 非 minimal quality）。

### 5.5 Group Registry

- 存储：`data/zsxq_groups.json`
- 刷新逻辑：`zsxq groups --refresh` → zsxq-cli `group list --json` → 对比本地
- 权限消失：标记 `inaccessible`，不删除历史数据
- 重新订阅：标记恢复 `active`

## 六、Review Items 清单

| item_type | 触发条件 | severity | 来源 |
|-----------|----------|----------|------|
| `zsxq_cli_missing` | ZSXQ CLI 未安装 | error | P6-A1 |
| `zsxq_auth_required` | 未登录/token 过期 | warning | P6-A1 |
| `zsxq_permission_denied` | 无权访问星球/主题 | warning | P6-A1 |
| `zsxq_parse_failed` | JSON 解析失败 | error | P6-A1 |
| `zsxq_attachment_unsupported` | 附件类型不支持 | info | P6-A1 |
| `zsxq_analysis_skipped` | 星球状态非 active / 附件为主 / 解析质量低 | warning | P6-A2 |
| `zsxq_content_too_short` | 正文为空或过短 (< 100 chars) | warning | P6-A2 |
| `zsxq_evidence_missing` | profile 缺少 topic_id/group_id | warning | P6-A2 |

## 七、Analysis Pipeline 链路

```
import_topic_to_ingest()          ← P6-A1
  │  ZsxqTopic → ZsxqSourceProfile
  ▼
import_and_analyze()             ← P6-A2
  ├─ import_topic_to_ingest()    ← P6-A1 复用
  ├─ profile.import_eligible?
  │    └─ No → return {success: false}
  └─ analyze_zsxq_topic()       ← P6-A2
       ├─ _check_zsxq_analysis_eligibility()
       │    ├─ content_text empty/short?
       │    ├─ group_access_status != "active"?
       │    ├─ attachment-only + minimal body?
       │    ├─ parse_quality == "minimal"?
       │    └─ missing topic_id/group_id?
       ├─ _topic_to_segments()
       │    └─ 1 ZsxqTopic → 1 SubtitleSegment (segment_id="zsxq_{topic_id}")
       ├─ build_zsxq_analysis_source()
       │    └─ source_info + episode_extra (source="zsxq_topic")
       └─ _run_pipeline()       ← EXISTING (no changes)
            ├─ clean_segments()
            ├─ provider.extract_facts()
            ├─ provider.render_report()
            ├─ save_episode(source="zsxq_topic")
            ├─ save_report()
            ├─ save_investment_views()
            ├─ save_tracking_signals()
            ├─ save_entities()
            └─ write files
```

### Evidence 传递

ZSXQ 没有视频 timestamp，没有 PDF page。Evidence 通过 `source_info` 传递：

```
source_type = "zsxq_topic"
source_url  = <原始链接>
zsxq_group_id
zsxq_topic_id
```

报告/观点/信号入库后，可通过 `report_id → episode.source = "zsxq_topic"` 追溯。

## 八、unified_search / knowledge_graph 自动受益

### 8.1 unified_search

- `_infer_source_type()` 识别 `episode.source == "zsxq_topic"` → `source_type="zsxq_topic"`
- ZSXQ 产生的 report/views/signals 通过 FTS5 + LIKE 可搜索
- `source_type` filter 支持 `zsxq_topic`
- 无需新增 FTS 索引或搜索逻辑

### 8.2 knowledge_graph

- `_build_source_nodes()` 从 `episodes WHERE source="zsxq_topic"` 创建 source nodes
- `_build_report_nodes()` 对所有 report 生效（含 ZSXQ report）
- `_build_mentioned_in_edges()` / `_build_derived_from_edges()` 自动连接
- Graph rebuild 幂等：`node_key` + `edge_key` 去重

### 8.3 MCP Server

8 个现有 MCP tool 自动支持 ZSXQ 数据（`search_reports`, `get_report`, `search_entities`, `list_investment_views`, `list_tracking_signals`, `list_review_items` 等）。无需新增 tool。

## 九、测试结果

```
Full suite: 1771 passed, 0 failed, 2 warnings
  - test_zsxq_import.py: 29 tests
  - test_zsxq_analysis.py: 39 tests

Warnings: websockets deprecation (unrelated to ZSXQ)

Ruff: All checks passed.
```

**68 个 ZSXQ 专项测试**，全部使用 mock provider / mock zsxq-cli JSON，不依赖真实账号、网络、LLM。

覆盖矩阵：

| 维度 | P6-A1 | P6-A2 |
|------|-------|-------|
| Models / dataclasses | ✅ | — |
| Group registry CRUD + refresh | ✅ | — |
| Source profile builder | ✅ | — |
| Ingest jobs create + dedup | ✅ | — |
| Error → review mapping | ✅ | — |
| CLI smoke (doctor/groups/import/sync) | ✅ | ✅ (analyze) |
| topic → segments | — | ✅ |
| Eligibility gates (8 cases) | — | ✅ |
| source_info builder | — | ✅ |
| Mock pipeline integration | — | ✅ |
| Report metadata (group/topic) | — | ✅ |
| Evidence traceability | — | ✅ |
| Review items P6-A2 | — | ✅ |
| unified_search zsxq | — | ✅ |
| knowledge_graph zsxq | — | ✅ |
| Edge cases | — | ✅ |

## 十、明确未做事项

| 排除项 | 原因 |
|--------|------|
| `search-groups` | 不做未订阅内容发现 |
| 订阅/购买/推荐 | 不做平台功能 |
| 发帖/评论/点赞/删除 | 不做社交互动 |
| member search/admin/moderation | 不做管理操作 |
| `api call` / `raw` | 不暴露原始 API |
| cookie 提取 / 逆向 API | 安全和法律边界 |
| 定时扫描 / cron / scheduler | 刷新由用户手动触发 |
| 未订阅内容获取 | 只访问用户已订阅星球 |
| 附件批量下载 | 附件只保存元数据 |
| 附件 OCR / 内容提取 | P6-B 候选 |
| Web UI (ZSXQ 管理界面) | 非当前优先 |
| 新 MCP tool | 现有 8 tool 已覆盖 |
| 新外部依赖 | ZSXQ CLI 由用户从官方 GitHub 仓库自行安装/构建 |

## 十一、P6-B 候选

| 候选 | 说明 |
|------|------|
| 附件 PDF 复用 P4 pipeline | 下载附件 → pdfplumber 提取 → 分析 |
| Web 信息源界面 | ZSXQ topics 在 Web UI 可预览/管理 |
| 更细粒度评论/问答上下文 | 解析 Q&A topic 中的多轮对话结构 |
| 增量同步 | 按 update_time 拉取新主题 |

以上均为候选，不属 P6 范围。
