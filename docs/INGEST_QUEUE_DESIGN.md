# P3-A: 持久化摄入队列设计

> 状态：Design | P3 | 2026-07-01

## 一、问题陈述

### 当前状态

```
_preview_store: dict[str, ImportPreview]     # 内存，重启丢失
_file_preview_store: dict[str, FileImportPreview]  # 内存，重启丢失
_profile_store: dict[str, SourceProfile]     # 内存，重启丢失
_import_results_store: dict[int, list[dict]] # 内存，刷新即清
```

### 痛點

1. **重启丢失**：`python -m signalvault serve` 重启后所有待确认预览消失
2. **无状态追踪**：无法知道"这个 URL 三天前预览过，用户当时跳过了"
3. **无去重**：同一 URL 多次预览生成多个 ImportPreview，浪费 LLM 调用
4. **无统计**：无法统计摄入成功率、失败原因分布、平均确认时间
5. **多 worker 不兼容**：内存 dict 不能跨进程共享

## 二、目标

- 所有摄入任务（URL 预览、文件上传、Tracked Source entry、Source Profile）统一写入 `ingest_jobs` 表
- 服务重启后可恢复
- source_hash 自动去重
- 过期任务自动清理
- Dashboard 统计从表查询
- 不影响现有四类入口的核心流程

## 三、DB Schema（已实现）

### `ingest_jobs` 表 — 22 列

| # | 列名 | 类型 | 说明 |
|---|------|------|------|
| 1 | `id` | INTEGER PK | 自增主键 |
| 2 | `job_key` | VARCHAR(256) NOT NULL | 去重键（`source_type:hash`） |
| 3 | `source_type` | VARCHAR(20) NOT NULL | `url_import` / `file_upload` / `tracked_entry` / `source_profile` |
| 4 | `source_url` | VARCHAR(500) | 原始 URL |
| 5 | `source_hash` | VARCHAR(64) | 内容 SHA256 |
| 6 | `source_name` | VARCHAR(500) | 文件名或页面标题 |
| 7 | `status` | VARCHAR(30) | 见状态机（§四） |
| 8 | `retry_count` | INTEGER | 重试次数（max 3） |
| 9 | `preview_data` | TEXT | JSON 序列化的 ImportPreview / FileImportPreview / SourceProfile |
| 10 | `preview_id` | VARCHAR(20) | 与现有 12-char hex preview_id 兼容 |
| 11 | `action` | VARCHAR(50) | 用户选择的操作（ActionEnum value） |
| 12 | `action_label` | VARCHAR(100) | 用户看到的操作文案 |
| 13 | `result_path` | VARCHAR(500) | 归档/导入后的文件路径 |
| 14 | `result_message` | TEXT | 结果消息 |
| 15 | `error_message` | TEXT | 失败原因 |
| 16 | `tracked_source_id` | INTEGER | 关联的 TrackedSource |
| 17 | `tracked_entry_id` | INTEGER | 关联的 TrackedSourceEntry |
| 18 | `created_at` | DATETIME | 创建时间 |
| 19 | `confirmed_at` | DATETIME | 确认时间 |
| 20 | `expires_at` | DATETIME | 过期时间（默认 +24h） |

### 去重设计

**部分唯一索引：**
```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_ingest_jobs_key_status
    ON ingest_jobs(job_key, status)
    WHERE status = 'pending_preview'
```

- 仅对 `pending_preview` 状态生效 — 同一来源只能有一个待确认预览
- 已确认/已跳过/已过期的 job 不受此约束 → 同一 URL 可以多次导入
- 索引在 `_migrate_ingest_jobs_table` 中创建，无论表是否已存在都会执行

**`job_key` 构造：**
```
url_import:    "url_import:{sha256(source_url)[:16]}"
file_upload:   "file_upload:{source_hash}"
tracked_entry: "tracked_entry:{tracked_source_id}:{sha256(source_url)[:16]}"
source_profile:"source_profile:{sha256(source_url)[:16]}"
```

## 四、状态机（已实现）

```
                           create_job()
                                │
                     ┌──────────▼──────────┐
                     │   pending_preview   │ ← retry_job() 从 failed/expired 返回
                     └──────┬─────┬────────┘
                            │     │
              ┌─────────────┤     └──────────────┐
              │             │                    │
    confirm_job()    mark_failed()         expire_old_jobs()
    ┌─────┬────┬──┐       │                    │
    ▼     ▼    ▼  ▼       ▼                    ▼
confirmed_*  skipped  preview_failed        expired
(archive/    overwritten   │
 deep_notes/              │ retry_job() (retry_count < 3)
 linked/                  └──► pending_preview
 derived_only)                  │ retry_job() (retry_count >= 3)
                                └──► 拒绝重试 (None)

confirmed_*/skipped/expired 为终端状态，不可再转换
```

### 状态值一览

| status | 含义 | 触发条件 |
|--------|------|----------|
| `pending_preview` | 等待用户确认 | `create_job()` / `retry_job()` |
| `preview_failed` | 预览生成失败 | `mark_failed()` |
| `confirmed_archive` | 已归档到 SourceArchive | `confirm_job(action=confirm_archive)` |
| `confirmed_deep_notes` | 已导入 Deep Notes | `confirm_job(action=import_as_deep_notes)` |
| `confirmed_derived_only` | 已导入为独立 Deep Notes | `confirm_job(action=import_as_deep_notes_derived_only)` |
| `confirmed_linked` | 已导入并关联 Report | `confirm_job(action=import_as_deep_notes_linked)` |
| `skipped` | 用户跳过 | `confirm_job(action=skip)` |
| `expired` | 超时未确认 | `expire_old_jobs()` |
| `overwritten` | 已覆盖 | `confirm_job(action=overwrite_deep_notes)` |

## 五、CLI 使用示例（已实现）

```bash
# 列出所有待确认的摄入任务
python -m signalvault ingest list --status pending_preview

# 按类型过滤
python -m signalvault ingest list --type url_import --limit 20

# 查看任务详情
python -m signalvault ingest show 1

# 重试失败的任务（重置为 pending_preview，最多 3 次）
python -m signalvault ingest retry 1

# 服务重启后查看恢复摘要
python -m signalvault ingest resume
```

## 四、代码变更

### 4.1 新增模块

```
sources/
  ingest_jobs.py     # IngestJobManager 类
    - create_job(source_type, source_url, source_hash, ...) -> ingest_job
    - get_pending_previews(source_type=None) -> list[IngestJob]
    - confirm_job(job_id, action, result_path) -> None
    - skip_job(job_id) -> None
    - find_by_job_key(job_key) -> IngestJob | None
    - expire_old_jobs() -> int  # 清理过期任务
    - count_by_status(source_type=None) -> dict[str, int]
    - count_by_source_type() -> dict[str, int]
```

### 4.2 修改 routes.py

| 当前代码 | 变更 |
|----------|------|
| `_preview_store[pid] = preview` | `IngestJobManager.create_job(...)` |
| `_preview_store.pop(pid)` | `IngestJobManager.confirm_job(...)` |
| `_file_preview_store[pid] = preview` | `IngestJobManager.create_job(...)` |
| `_file_preview_store.pop(pid)` | `IngestJobManager.confirm_job(...)` |
| `_profile_store[pid] = profile` | `IngestJobManager.create_job(...)` |
| `_profile_store.pop(pid)` | `IngestJobManager.confirm_job(...)` |
| `_import_results_store[tsid] = results` | 保留在内存（一次性显示），但结果持久化到 ingest_jobs |
| `len(_preview_store)` | `IngestJobManager.count_by_status()['pending_preview']` |
| `len(_file_preview_store)` | 同上，按 source_type 过滤 |

### 4.3 修改 preview 构建流程

当前 `build_import_preview()` 和 `build_file_import_preview()` 不变。在调用它们的 route handler 中，新增去重检查：

```python
# 在 action_source_import_preview 中：
job_key = f"url_import:{sha256(url)}"
existing = IngestJobManager.find_by_job_key(job_key)
if existing and existing.status == "pending_preview":
    # 返回已有预览，不重新生成
    preview = ImportPreview.from_json(existing.preview_data)
else:
    preview = build_import_preview(url, vp)
    IngestJobManager.create_job(
        source_type="url_import",
        source_url=url,
        source_hash=preview.content_hash,
        job_key=job_key,
        preview_data=preview.to_json(),
        preview_id=preview.preview_id,
    )
```

### 4.4 兼容现有 preview_id

`preview_id` 字段保持 12-char hex，存储在 `ingest_jobs` 表中，前端模板中的 `<input type="hidden" name="preview_id" value="...">` 不变。提交确认时仍通过 `preview_id` 查询。

### 4.5 Dashboard 统计

```python
# _build_sources_dashboard_context() 中：
url_preview_count = IngestJobManager.count_by_status("url_import")["pending_preview"]
file_preview_count = IngestJobManager.count_by_status("file_upload")["pending_preview"]
```

### 4.6 过期清理

在 `serve` 启动时注册后台任务：
```python
import asyncio
async def cleanup_expired_jobs():
    while True:
        IngestJobManager.expire_old_jobs()
        await asyncio.sleep(3600)  # 每小时

# 在 create_app() 中：
@app.on_event("startup")
async def start_cleanup():
    asyncio.create_task(cleanup_expired_jobs())
```

## 六、迁移路径

### Phase 1：双写 ✅ 已完成（2026-07-01）
- 新增 `ingest_jobs` 表 + `IngestJobManager`
- route handlers 同时写入内存 store 和 `ingest_jobs`
- 读取优先从内存 store（保持现有行为）
- Dashboard 统计：内存优先，为空时回退到 `ingest_jobs`（重启恢复）
- 54 tests

### Phase 2：切换（计划中）
- 读取全面从 `ingest_jobs` 走
- 移除 `_preview_store` 等内存 dict 的写入（保留读取兼容）
- Dashboard 统计完全切换到 `ingest_jobs`

### Phase 3：清理（计划中）
- 移除 `_preview_store`、`_file_preview_store`、`_profile_store`
- `_import_results_store` 保留（一次性显示）
- 清理 routes.py 中相关代码

## 六、API 不变性保证

| 对外接口 | 变更 |
|----------|------|
| `POST /sources/import/preview` | 不改变请求/响应格式 |
| `POST /sources/import/confirm` | 不改变请求/响应格式 |
| `POST /sources/files/preview` | 不改变请求/响应格式 |
| `POST /sources/files/confirm` | 不改变请求/响应格式 |
| `GET /sources` | Dashboard 统计数据源改为 ingest_jobs |
| `GET /sources/tracked/{id}/entries` | 不改变请求/响应格式 |
| `POST /sources/tracked/{id}/refresh` | 不改变请求/响应格式 |
| `POST /sources/tracked/{id}/import` | 不改变请求/响应格式 |

前端模板无需修改。

## 七、测试计划

```
tests/test_ingest_jobs.py:

class TestIngestJobManager:
    def test_create_url_import_job
    def test_create_file_upload_job
    def test_create_tracked_entry_job
    def test_create_source_profile_job
    def test_find_by_job_key
    def test_find_by_job_key_not_found
    def test_get_pending_previews
    def test_get_pending_previews_by_type
    def test_confirm_job
    def test_skip_job
    def test_expire_old_jobs
    def test_count_by_status
    def test_count_by_source_type
    def test_job_key_uniqueness  # 同一 job_key + pending 不重复
    def test_job_key_allows_reimport  # 已 skip/expire 后可重新导入

class TestIngestJobDedup:
    def test_same_url_returns_existing_preview
    def test_same_file_hash_returns_existing_preview
    def test_different_url_creates_new_job

class TestDashboardWithIngestJobs:
    def test_url_preview_count_from_db
    def test_file_preview_count_from_db

class TestMigration:
    def test_preview_store_and_db_consistent  # 双写一致性
    def test_confirm_updates_both
```

预计 ≥20 tests。

## 八、回滚计划

如果 P3-A 上线后出现问题：
1. `ingest_jobs` 表只新增不修改，不影响现有功能
2. route handlers 保留 `_preview_store` 写入（Phase 1 双写）
3. 紧急回滚：删除 `ingest_jobs` 表 + 移除 IngestJobManager 调用
4. 现有 1385 tests 全部保留，新增测试独立

## 九、不做什么

- 不实现消息队列（RabbitMQ/Redis）
- 不实现分布式摄入（多 worker）
- 不修改现有 DB 表结构
- 不改变前端 UI
- ingest_jobs 不存实际文件内容（仅存 metadata + JSON preview_data）
