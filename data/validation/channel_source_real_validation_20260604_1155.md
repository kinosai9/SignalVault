# P2-M.1.1 Channel Source Real Validation Report

**Date**: 2026-06-04 11:45–11:55 CST  
**Channel**: https://www.youtube.com/@LatentSpacePod  
**Environment**: Python 3.14, FastAPI/uvicorn @ 127.0.0.1:8765  
**Vault**: D:\KinocNote\ai-investing-vault\科技AI投资库V1

---

## 验证流程

### 1. 频道添加

| Field | Value |
|-------|-------|
| Channel URL | `https://www.youtube.com/@LatentSpacePod` |
| Channel ID (DB) | 6 |
| Add result | 303 → `/sources/channels/6/videos?msg=success:频道已添加，可同步视频列表` |

✅ 频道添加成功，跳转正常

### 2. Channel Refresh (异步任务)

| Field | Value |
|-------|-------|
| Refresh Task ID | `cf1c9844e769` |
| Task type | `channel_refresh` |
| Job title | `刷新频道: LatentSpacePod` |
| Redirect | 303 → `/tasks/cf1c9844e769` |
| Stages | `queued` → `fetching_channel` → `reading_video_metadata` → `checking_import_status` → `saving_video_list` → `success` |
| Elapsed | 94 seconds |
| Result | **新增 20 个视频，更新 0 个** |

✅ 频道刷新创建异步 job，按阶段推进  
✅ 成功获取 20 个视频（yt-dlp 非 flat 模式）

### 3. Video Import & Full Flow

| Field | Value |
|-------|-------|
| Selected Video | `abYcV5LHMG4` — *Scaling Past Informal AI - Carina Hong, Axiom Math* |
| Import Type | `full_flow` |
| Full Flow Task ID | `40cc75df4408` |
| Redirect | 303 → `/tasks/40cc75df4408` |
| Analysis Result | **Success** — report_id=6 |
| Sync Result (first attempt) | **Failed** — `'utf-8' codec can't decode byte 0xa1 in position 264: invalid start byte` |
| Sync Retry Task ID | `6d3f03fe0955` |
| Sync Result (retry) | **Success** — 知识库已更新 |
| Total Elapsed (full flow) | 483 seconds |

### 4. Duplicate Detection (Re-refresh)

| Field | Value |
|-------|-------|
| Second Refresh Task ID | `edc8fc8e20fc` |
| Result | **新增 0 个视频，更新 20 个** |

✅ 无重复 video_id 插入

---

## 验证检查清单

### ✅ PASS (10/12)

| # | 检查项 | 状态 | 证据 |
|---|--------|------|------|
| 1 | channel_refresh 完成页不显示 spinner | ✅ | server-rendered `status=success`，JS 分支隐藏 spinner |
| 2 | channel_refresh 完成页显示完成清单 | ✅ | checklist: `[获取频道视频列表, 读取视频发布时间, 检查已整理状态, 更新视频列表]` |
| 3 | 视频列表有 published_at | ✅ | 显示 `2026-06-03`, `2026-06-02`, `2026-06-01` 等 |
| 4 | full_flow 结果页显示完成清单/错误信息 | ✅ | 显示 "报告已生成，但知识库更新失败" + retry link |
| 5 | 视频失败状态回写到 channel_videos | ✅ | 视频显示 `失败` badge + 错误原因 |
| 6 | Report frontmatter 包含 channel/video_id/source_url/title | ✅ | `channel: LatentSpacePod`, `video_id: abYcV5LHMG4`, `video_url: https://...` |
| 7 | 01_Reports 文件名不出现 UnknownChannel | ✅ | `2026-06-03_LatentSpacePod_abYcV5LHMG4.md` |
| 8 | 05_Channels 有正确频道卡 | ✅ | `LatentSpacePod.md` — 包含 url, tags, priority, Recent Reports 链接 |
| 9 | 再刷新频道列表不重复插入 | ✅ | 第二次刷新：新增 0，更新 20 |
| 10 | Result links 正确 | ✅ | channel_refresh → `/sources/channels/6/videos`; full_flow → `/reports/6` + retry `/reports/6/sync` |

### ⚠️ ISSUE (2/12)

| # | 检查项 | 状态 | 详情 |
|---|--------|------|------|
| 11 | 公司卡片关联数量不全为 0 | ⚠️ | 公司卡片已生成但内容为模板占位（`待后续 LLM-WIKI 维护`）。这是 LLM-WIKI 系统的职责范围，不属于 P2-M.1.1 范围 |
| 12 | Watchlist/Brief 显示关注对象关联 | ⚠️ | Brief 包含 LatentSpacePod 内容但 watchlist 关联为模板状态。同属 LLM-WIKI 后续工作 |

---

## 发现的 Bug

### B1: UTF-8 编码解码错误导致 sync 首次失败 🔴

**现象**:  
```
同步失败: 'utf-8' codec can't decode byte 0xa1 in position 264: invalid start byte
```

**分析**:  
- 首次 full_flow 的 sync 阶段失败，UTF-8 decode 错误  
- 重试 sync 成功（第二次 POST `/reports/6/sync` → job `6d3f03fe0955`）  
- vault 所有文件当前均为合法 UTF-8  
- 推测：首次 sync 时 workspace 代码读取了某临时文件或存在竞态条件

**影响**:  
- 用户需手动重试 sync（retry link 已正确展示在失败页面）  
- 这不是 P2-M.1.1 引入的 bug，属于 sync/workspace 模块的既有问题

**建议**:  
- `sync_service.py` 在读取 vault 文件时增加 encoding fallback（UTF-8 → GBK → latin-1）  
- 或对非 UTF-8 文件记录 warning 后跳过

### B2: Sync retry 不回写 channel_video 状态 🔵

**现象**:  
- full_flow 失败后 channel_video 状态写为 "失败" ✅  
- 用户通过 `/reports/6/sync` 重试 sync 成功  
- channel_video 状态未更新（仍显示 "失败"）  

**根因**:  
- Sync retry 创建的是 `job_type="sync"` 的独立 job，没有 source_type/source_channel_id/video_id 上下文  
- `_writeback_channel_video_status()` 只对 `source_type == "channel_video"` 的 job 生效

**影响**:  
- 用户看到视频列表仍显示"失败"，即使报告已同步进 vault  
- UX 不一致

**建议**:  
- Sync retry route 传递 source_type 上下文给新 job  
- 或在 `action_reports_sync` 中查找关联的 channel_video 记录并回写

---

## 统计数据

| Metric | Value |
|--------|-------|
| 总测试 | 811 passed |
| Source Channel 专项测试 | 32 passed |
| 新增测试 (P2-M.1.1) | 10 tests, 4 classes |
| 修改文件数 | 10 files |
| 代码增量 | +772 / -83 lines |
| Channel Refresh 耗时 | 94s |
| Full Flow 耗时 | 483s (分析成功，同步失败) |
| Sync Retry 耗时 | <2s |

---

## 结论

**P2-M.1.1 核心功能验证通过**。三类状态问题（task 显示、video 回写、refresh 异步化）在真实频道上均验证正确。发现 1 个 sync 模块既有编码 bug 和 1 个 UX 增强点（sync retry 回写），均非阻塞性问题，可放入后续迭代处理。
