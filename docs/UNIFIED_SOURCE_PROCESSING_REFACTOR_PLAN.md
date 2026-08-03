# 信息源统一处理逻辑重构方案

> 状态：方案设计完成（待用户确认）
> 日期：2026-08-03
> 基线：M3-C 完成，2013 tests，后端服务可用
> 范围：统一信息源入口、自动化处理、研究资产库完整闭环

---

## 0. 执行摘要

### 问题定位

用户反馈的四个核心问题（处理流程不一致、数据孤岛、缺少自动化、UI入口混乱）根源在于：**系统缺少统一编排层**。

当前架构是「功能驱动 + 历史迭代叠加」，入口路由、来源处理、数据生命周期散落在各模块，没有从"用户意图"出发的统一路由和状态机。

### 解决方案

**补齐编排层**，形成两个统一入口：

1. **文件类入口**：上传文件或锁定目录 → 自动检测 → 用户选择归档/分析 → 统一入库
2. **频道/固定源类入口**：添加关注源 → 配置自动化策略 → 系统自动刷新、评分、分析 → 统一入库

两类入库后统一进入：
- 研究资产库（Episode + Report + Views/Signals + SourceDocument）
- 统一搜索（FTS5 全文检索）
- 知识图谱（knowledge_nodes + knowledge_edges）

### 实施策略

分 5 个阶段渐进式重构，每个阶段独立可验证：
- 阶段 1：数据模型统一（低风险）
- 阶段 2：文本文件分析能力（中等风险）
- 阶段 3：自动化调度（中等风险）
- 阶段 4：UI 入口收敛（高风险）
- 阶段 5：图数据库自动同步（低风险）

---

## 1. 现状分析（基于 3 个探索 Agents）

### 1.1 文件上传处理现状

**完整流程**：
```
上传文件 → 验证（扩展名/大小/编码）
  → 内容提取（TXT/MD/HTML/DOCX/PDF）
  → 预览构建（冲突检测、推荐决策）
  → 用户确认
    ├─ 文本文件 → 仅归档到 SourceArchive（不入库）
    └─ PDF → 自动分析 → Episode + Report + Views/Signals + SourceDocument
```

**关键发现**：
- ✅ PDF：自动 LLM 分析，完整入库
- ❌ 普通文本文件：仅归档，不入库，不进入统一搜索
- ❌ 缺失文本文件的 SourceDocument 持久化
- ❌ 缺失文本文件的分析入口（无 `analyze_text_file()` 函数）

**数据流对比**：

| 来源 | SourceDocument | Episode | Report | Views/Signals | 统一搜索 |
|------|----------------|---------|--------|---------------|----------|
| PDF | ✅ | ✅ | ✅ | ✅ | ✅ |
| YouTube | ✅ | ✅ | ✅ | ✅ | ✅ |
| ZSXQ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 文本文件 | ❌ | ❌ | ❌ | ❌ | ❌ |
| 网页导入 | ⚠️ 部分 | ❌ | ❌ | ❌ | ❌ |

### 1.2 频道视频处理现状

**完整流程**：
```
添加频道 → channels 表
  → 手动刷新 → channel_refresh job → yt-dlp 获取视频列表
  → channel_videos 表（status: new）
  → 手动选择视频导入 → full_flow job
  → LLM 分析 → Episode + Report + Views/Signals + SourceDocument
  → 同步到 Obsidian Vault
```

**关键发现**：
- ✅ 完整的分析流程
- ✅ 源追溯持久化
- ❌ **无定时刷新**（全仓无 APScheduler/cron）
- ❌ 无自动发现新视频
- ❌ 无自动导入队列
- ❌ 无视频价值评分机制

**自动化缺失清单**：
1. 频道自动刷新（需定时调度）
2. 新视频自动发现（需比较发布时间）
3. 高价值视频自动识别（需评分机制）
4. 批量导入队列（需后台 worker）

### 1.3 统一搜索与图数据库现状

**统一搜索覆盖**（`unified_search.py`）：
- ✅ Reports（report_markdown, executive_summary）
- ✅ Investment Views（target_name, logic_chain, source_quote）
- ✅ Tracking Signals（signal, trigger_condition）
- ✅ Entities（name, normalized_name）
- ✅ Source Documents（title, source_url）
- ✅ Source Segments（text_original）
- ❌ **归档文件**（只在 Obsidian Vault，不在数据库）

**图数据库现状**：
- ✅ 有 `knowledge_nodes` 和 `knowledge_edges` 表
- ✅ 有 `rebuild_knowledge_graph()` 函数
- ❌ **需手动触发**，不自动同步
- ❌ Web 无可视化入口

---

## 2. 根本原因分析

### 2.1 架构层面

**缺少统一编排层**：

```
当前架构：
用户 → 6+ 个入口 → 分散的处理逻辑 → 不一致的入库路径

期望架构：
用户 → 2 个统一入口 → 编排层（orchestrator）→ 统一的处理流程 → 统一入库
```

**入口碎片化统计**：
- YouTube：4+ 个入口（CLI `--youtube-url`、CLI `channels analyze-video`、Web `/content/new`、Web `/sources/channels`）
- 报告生成：8 个入口（4 CLI + 4 Web）
- 网页导入：Web `/sources/import`
- 文件上传：Web `/sources/files/import`
- 固定源：Web `/sources/tracked`

### 2.2 数据孤岛

**入库路径不一致**：
- 进入 `sources/` 模块的来源永远不会到 LLM（`import_preview.py`、`file_import_preview.py`）
- 进入 `services/analyze_service.py` 的直接到 LLM
- 两者之间没有桥

**证据**（代码路径分析）：
```python
# 网页/文件/Tracked 导入只做归档
import_preview.execute_import_action()      # 只写 markdown
file_import_preview.confirm_file_import()   # 只写 markdown
tracked_source_service.import_entries()     # 只写 markdown

# analyze_from_transcript() 唯一调用方
analyze_service.py:127  # YouTube 专用
```

### 2.3 状态机缺失

**ingest_jobs 状态不全**：
```python
VALID_STATUSES = {
    "pending_preview", "preview_failed",
    "confirmed_archive", "skipped", "expired",
    # ❌ 缺失分析相关状态
    # "pending_analysis", "analyzing", "analysis_completed"
}
```

**无队列消费者**：
- 所有 confirm 由 Web 路由同步触发
- 没有 worker 自动消费 ingest_jobs

---

## 3. 统一数据模型设计

### 3.1 核心原则

**所有来源最终都转换为统一的研究资产**：

```
来源类型 → 统一处理 → 研究资产库
├─ YouTube 视频  → Episode + Report + Views/Signals + SourceDocument
├─ PDF 文档     → Episode + Report + Views/Signals + SourceDocument
├─ 网页         → Episode + Report（可选）+ SourceDocument
├─ 文本文件     → Episode + Report（可选）+ SourceDocument
└─ ZSXQ topic  → Episode + Report + Views/Signals + SourceDocument
```

**入库标准**：
- **必须有**：`SourceDocument`（原文追溯，统一搜索的基础）
- **可选**：`Episode + Report`（LLM 分析，用户选择或系统判定）

### 3.2 数据表扩展

#### 扩展 ingest_jobs 表

```sql
-- 新增字段
ALTER TABLE ingest_jobs ADD COLUMN auto_eligible BOOLEAN DEFAULT 0;
ALTER TABLE ingest_jobs ADD COLUMN value_score REAL DEFAULT 0.0;
ALTER TABLE ingest_jobs ADD COLUMN analysis_mode TEXT DEFAULT 'off';
ALTER TABLE ingest_jobs ADD COLUMN scheduled_at TIMESTAMP;
```

**字段说明**：
- `auto_eligible`：是否可自动处理（无冲突、质量良好）
- `value_score`：内容价值评分（0.0-1.0）
- `analysis_mode`：分析模式（off/high_value/all）
- `scheduled_at`：调度时间

#### 新增 scheduler_config 表

```sql
CREATE TABLE scheduler_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,           -- 'channel', 'tracked_source', 'locked_directory'
    source_id INTEGER NOT NULL,
    refresh_interval TEXT NOT NULL,      -- '1h', '1d', '1w'
    auto_analyze_mode TEXT DEFAULT 'off', -- 'off', 'high_value', 'all'
    cost_budget INTEGER DEFAULT 0,        -- 每日 LLM 调用预算
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 扩展状态机

```python
VALID_STATUSES = frozenset({
    # 现有状态
    "pending_preview",
    "preview_failed",
    "confirmed_archive",
    "confirmed_deep_notes",
    "confirmed_derived_only",
    "confirmed_linked",
    "skipped",
    "expired",
    "overwritten",
    "auto_archived",
    "auto_ignored",
    
    # 新增分析相关状态
    "pending_analysis",      # 待分析（用户确认或自动排队）
    "analyzing",              # 正在分析（worker 处理中）
    "analysis_failed",        # 分析失败
    "analysis_completed",     # 分析完成
    
    # 新增自动化状态
    "auto_queued",            # 自动排队中（等待 worker）
    "auto_analyzing",         # 自动分析中
})
```

---

## 4. 两个统一入口设计

### 4.1 入口 1：文件类信息源

**路由**：`/sources/files`（收敛现有 `/sources/files/import`）

#### 用户流程

```
上传文件 / 锁定目录
  ↓
系统自动检测
  ├─ 文件类型识别（PDF/DOCX/TXT/MD/HTML）
  ├─ 质量评估（文本长度、解析质量）
  └─ 价值预判（是否值得 LLM 分析）
  ↓
显示预览页面
  ├─ 文件信息（名称、大小、类型）
  ├─ 内容摘要（前 500 字）
  ├─ 价值评分（0.0-1.0）
  └─ 推荐操作
  ↓
用户选择操作
  ├─ 仅归档（默认，快速，无成本）
  │   └─ SourceDocument + SourceArchive
  ├─ 归档并分析（需确认，有成本）
  │   └─ SourceDocument + Episode + Report + Views/Signals
  └─ 批量处理（目录模式）
  ↓
入库完成 → 跳转处理中心 → 统一搜索可查
```

#### 锁定目录模式

**配置项**：
```yaml
# scheduler_config 表记录
locked_directory:
  path: "/Users/kinosai/Documents/Research"
  refresh_interval: "1h"              # 每小时扫描
  auto_analyze_mode: "high_value"     # 高价值自动分析
  cost_budget: 10                      # 每日最多 10 次 LLM
```

**扫描逻辑**：
```python
def scan_locked_directory(directory_id: int):
    config = get_scheduler_config(directory_id)
    new_files = detect_new_files(config.path, config.last_run_at)
    
    for file in new_files:
        score = calculate_value_score(file)
        job = IngestJobManager.create_job(
            source_type="locked_directory_file",
            source_path=file.path,
            auto_eligible=(score >= 0.5),
            value_score=score,
        )
        
        if score >= 0.8 and config.auto_analyze_mode == "all":
            # 高价值 + 全自动模式 → 自动排队分析
            job.status = "auto_queued"
        elif score >= 0.5 and config.auto_analyze_mode == "high_value":
            # 中等价值 + 高价值模式 → 自动排队分析
            job.status = "auto_queued"
        else:
            # 低价值或关闭自动 → 待确认
            job.status = "pending_preview"
```

### 4.2 入口 2：频道/固定源类信息源

**路由**：`/sources/tracked`（收敛 `/sources/channels`）

#### 用户流程

```
添加关注源
  ├─ YouTube 频道（粘贴频道 URL）
  ├─ 固定网页源（粘贴 RSS/网页 URL）
  └─ 其他支持源（RSS、Atom 等）
  ↓
配置自动化策略
  ├─ 刷新周期（每日/每周/每月）
  ├─ 自动分析模式（off/high_value/all）
  ├─ 成本上限（每日 LLM 调用预算）
  └─ 过滤规则（关键词、时长限制）
  ↓
系统自动运行
  ├─ 定时刷新（后台调度器）
  │   ├─ 频道：yt-dlp 获取最新视频
  │   └─ 网页：httpx 抓取新条目
  │
  ├─ 发现新内容
  │   ├─ 比较发布时间与上次刷新时间
  │   └─ 写入 channel_videos / tracked_source_entries
  │
  ├─ 价值评分（实时计算）
  │   ├─ 来源优先级（core: 1.0, watch: 0.7, archive: 0.4）
  │   ├─ 内容时长（> 30min: +0.2）
  │   ├─ 关键词匹配（watchlist 命中: +0.3）
  │   └─ 解析质量（good: +0.1）
  │
  └─ 自动决策
      ├─ score >= 0.8 → 自动分析队列
      ├─ 0.5 <= score < 0.8 → 仅归档
      ├─ score < 0.5 → 跳过
      └─ 边界情况 → 人工确认队列
  ↓
入库完成 → 统一搜索可查 → 图数据库自动关联
```

#### 自动化配置示例

```yaml
# 频道自动化配置
channel_automation:
  channel_id: 123
  refresh_interval: "1d"               # 每日刷新
  auto_analyze_mode: "high_value"      # 高价值自动分析
  cost_budget: 5                        # 每日最多 5 个视频
  filters:
    min_duration: 600                   # 最短 10 分钟
    keywords: ["AI", "投资", "科技"]    # 关键词匹配
```

---

## 5. 自动化机制设计

### 5.1 调度器（APScheduler）

**技术选型**：APScheduler 3.x（Python 原生，无外部依赖）

**架构**：
```python
# services/scheduler_service.py
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

jobstores = {
    'default': SQLAlchemyJobStore(url='sqlite:///data/signalvault.db')
}

scheduler = BackgroundScheduler(jobstores=jobstores)

def start_scheduler():
    """启动调度器，注册定时任务"""
    # 每小时扫描锁定目录
    scheduler.add_job(
        scan_locked_directories,
        'interval',
        hours=1,
        id='scan_locked_dirs'
    )
    
    # 每日 02:00 刷新活跃频道
    scheduler.add_job(
        refresh_active_channels,
        'cron',
        hour=2,
        minute=0,
        id='refresh_channels'
    )
    
    # 每周一 03:00 刷新固定信息源
    scheduler.add_job(
        refresh_tracked_sources,
        'cron',
        day_of_week='mon',
        hour=3,
        minute=0,
        id='refresh_tracked'
    )
    
    scheduler.start()
```

**启动方式**：
- Web 启动时自动启动（在 `create_app()` 中调用）
- 提供 CLI 命令手动控制：`signalvault scheduler start/stop/status`

### 5.2 内容价值评分器

**评分维度**：
```python
# services/value_scorer.py
def calculate_value_score(source: dict, content: dict) -> float:
    """
    计算内容价值评分（0.0-1.0）
    
    维度：
    1. 来源优先级（40%）
    2. 内容质量（30%）
    3. 关键词匹配（20%）
    4. 用户偏好（10%）
    """
    score = 0.0
    
    # 1. 来源优先级
    priority_weights = {
        "core": 0.4,
        "watch": 0.28,
        "archive": 0.16,
    }
    score += priority_weights.get(source.get("priority"), 0.16)
    
    # 2. 内容质量
    quality_bonus = {
        "good": 0.12,
        "degraded": 0.06,
        "minimal": 0.0,
    }
    score += quality_bonus.get(content.get("parse_quality"), 0.0)
    
    # 3. 关键词匹配
    keywords = get_user_watchlist_keywords()
    matched = sum(1 for kw in keywords if kw in content.get("title", ""))
    score += min(0.2, matched * 0.05)
    
    # 4. 用户偏好（时长）
    duration = content.get("duration_seconds", 0)
    if duration >= 1800:  # >= 30 min
        score += 0.08
    elif duration >= 600:  # >= 10 min
        score += 0.04
    
    return min(1.0, score)
```

**评分结果映射**：
- `score >= 0.8`：高价值，建议自动分析
- `0.5 <= score < 0.8`：中价值，仅归档
- `score < 0.5`：低价值，跳过或人工确认

### 5.3 队列消费者（Worker）

**工作流程**：
```python
# services/queue_worker.py
def process_auto_queue():
    """自动处理队列中的任务"""
    jobs = IngestJobManager.get_jobs_by_status("auto_queued", limit=10)
    
    for job in jobs:
        # 检查预算
        if not check_budget_available():
            logger.warning("Budget exhausted, pausing auto-processing")
            break
        
        # 标记为处理中
        IngestJobManager.update_status(job.id, "auto_analyzing")
        
        try:
            # 执行分析
            if job.source_type == "locked_directory_file":
                result = analyze_text_file(job.source_path)
            elif job.source_type == "channel_video":
                result = analyze_video(job.source_url)
            
            # 标记完成
            IngestJobManager.update_status(job.id, "analysis_completed")
            
        except Exception as e:
            # 标记失败
            IngestJobManager.mark_failed(job.id, str(e))
```

**成本控制**：
```python
def check_budget_available() -> bool:
    """检查当日 LLM 调用预算"""
    config = get_global_config()
    daily_budget = config.get("daily_llm_budget", 10)
    
    today_calls = count_today_llm_calls()
    return today_calls < daily_budget
```

---

## 6. 模块重构方案

### 6.1 新增模块

| 模块 | 文件路径 | 功能 |
|------|----------|------|
| **文本文件分析** | `sources/text_analysis.py` | 文本文件的 LLM 分析逻辑（参考 `pdf_analysis.py`） |
| **调度服务** | `services/scheduler_service.py` | APScheduler 封装、定时任务管理 |
| **价值评分** | `services/value_scorer.py` | 内容价值评分算法 |
| **队列消费者** | `services/queue_worker.py` | 自动处理队列的后台 worker |

### 6.2 重构模块

| 模块 | 改动类型 | 说明 |
|------|----------|------|
| `sources/file_import_preview.py` | 扩展 | 增加"归档并分析"选项，调用 `text_analysis.py` |
| `sources/ingest_jobs.py` | 扩展 | 新增分析状态、队列查询方法、worker 消费接口 |
| `services/sync_service.py` | 扩展 | 同步完成后自动调用 `rebuild_knowledge_graph()` |
| `web/routes.py` | 重构 | 收敛入口路由，统一为两个主入口 |
| `db/source_provenance.py` | 扩展 | 补充文本文件的 SourceDocument 持久化 |

### 6.3 API 设计

#### 新增 API

```
# 文件类
POST /api/sources/files/analyze        # 文本文件分析入口
POST /api/sources/lock-directory       # 锁定目录配置

# 频道/固定源类
POST /api/scheduler/config             # 配置自动刷新策略
GET  /api/scheduler/status             # 查看调度状态
POST /api/scheduler/trigger            # 手动触发刷新
POST /api/scheduler/pause              # 暂停自动刷新
POST /api/scheduler/resume             # 恢复自动刷新

# 队列处理
GET  /api/queue/stats                  # 队列统计
POST /api/queue/process                # 手动处理队列
POST /api/queue/pause                  # 暂停自动处理

# 价值评分
GET  /api/value-score/{job_id}         # 查询内容价值评分

# 图数据库
GET  /api/graph/node/{node_key}        # 查询节点
GET  /api/graph/neighborhood/{node_key} # 查询邻居节点
POST /api/graph/rebuild                # 手动重建图谱
```

#### 路由收敛

```
旧路由 → 301 重定向 → 新路由
/sources/channels          → /sources/tracked
/sources/files/import      → /sources/files
/sources/import            → /intake
/content/new               → /intake
```

---

## 7. UI 流程设计

### 7.1 入口 1：文件类（/sources/files）

**页面结构**：
```
/sources/files
├─ 上传文件卡片
│   ├─ 拖拽上传区域
│   ├─ 支持格式说明（.pdf/.docx/.txt/.md/.html）
│   └─ 批量上传（最多 10 个文件）
│
├─ 锁定目录卡片
│   ├─ 目录路径输入
│   ├─ 扫描频率选择（每小时/每天）
│   ├─ 自动分析模式选择
│   └─ 已监控文件列表（新发现高亮）
│
└─ 处理状态卡片
    ├─ 待处理（N 个）
    ├─ 处理中（N 个）
    ├─ 今日完成（归档 N 个，分析 N 个）
    └─ 查看处理中心 →
```

**操作流程**（上传文件）：
1. 拖拽文件到上传区域
2. 系统自动检测并显示预览：
   - 文件信息（名称、大小、类型）
   - 内容摘要（前 500 字）
   - 价值评分（0.85 - 高价值）
   - 推荐操作：归档并分析
3. 用户选择操作：
   - [仅归档] 快速，无成本
   - [归档并分析] 推荐，有 LLM 成本
4. 提交 → 后台处理 → 跳转处理中心

### 7.2 入口 2：频道/固定源类（/sources/tracked）

**页面结构**：
```
/sources/tracked
├─ 添加源卡片
│   ├─ YouTube 频道 URL 输入
│   ├─ 固定网页 URL 输入
│   └─ 高级配置（刷新周期、自动分析、成本预算）
│
├─ 已关注源列表
│   ├─ 源名称 + 状态（正常/刷新中/异常）
│   ├─ 下次刷新时间
│   ├─ 新发现内容数（N 个待处理）
│   └─ 操作：[立即刷新] [暂停] [配置]
│
└─ 自动化统计
    ├─ 今日刷新次数：5 次
    ├─ 发现新内容：12 个
    ├─ 自动分析：3 个（消耗 3 次 LLM）
    └─ 预算剩余：7/10 次
```

**操作流程**（添加频道）：
1. 粘贴 YouTube 频道 URL
2. 系统识别并显示频道信息：
   - 频道名称、头像、订阅数
   - 最近 5 个视频预览
3. 配置自动化策略：
   - 刷新周期：[每日] / 每周 / 每月
   - 自动分析：[关闭] / 高价值 / 全部
   - 成本上限：[5] 次/日
4. 保存 → 系统自动开始刷新

### 7.3 处理中心（/processing）扩展

**新增功能**：
```
/processing
├─ 自动化队列卡片
│   ├─ 待自动处理（N 个）
│   ├─ 自动处理中（N 个）
│   └─ 成本预算：已用 3/10 次
│
├─ 来源分组视图
│   ├─ 文件类（锁定目录 + 上传）
│   ├─ 频道类（YouTube 频道）
│   └─ 固定源类（网页源）
│
└─ 批量操作
    ├─ 批量归档（选中项）
    ├─ 批量分析（选中项，有成本）
    └─ 批量跳过
```

---

## 8. 图数据库自动同步

### 8.1 集成到 sync_service

**改动位置**：`services/sync_service.py::sync_report_to_knowledge_base()`

```python
def sync_report_to_knowledge_base(report_id: int) -> dict:
    """同步报告到知识库，并自动更新图数据库"""
    # ... 现有同步逻辑（导出报告、更新卡片、生成观点/信号）...
    
    # 新增：自动更新图数据库
    from signalvault.db.knowledge_graph import update_knowledge_graph_for_report
    
    try:
        graph_result = update_knowledge_graph_for_report(session, report_id)
        result["graph_updated"] = graph_result
    except Exception as e:
        logger.warning(f"Graph update failed for report {report_id}: {e}")
        result["graph_error"] = str(e)
    
    return result
```

### 8.2 增量更新函数

**新增函数**：`db/knowledge_graph.py::update_knowledge_graph_for_report()`

```python
def update_knowledge_graph_for_report(session: Session, report_id: int) -> dict:
    """增量更新单个报告的图节点和边"""
    # 1. 删除旧节点和边
    session.query(KnowledgeEdge).filter(
        KnowledgeEdge.source_node_key.like(f"report:{report_id}:%")
    ).delete()
    
    session.query(KnowledgeNode).filter(
        KnowledgeNode.node_key == f"report:{report_id}"
    ).delete()
    
    # 2. 构建新节点和边
    report = session.query(Report).get(report_id)
    
    # 报告节点
    _build_report_node(session, report)
    
    # 实体节点和 mentioned_in 边
    _build_entity_nodes(session, report)
    _build_mentioned_in_edges(session, report)
    
    # 观点节点和 derived_from 边
    _build_view_nodes(session, report)
    _build_derived_from_edges(session, report)
    
    # 信号节点和 tracks 边
    _build_signal_nodes(session, report)
    _build_tracks_edges(session, report)
    
    session.commit()
    
    return {
        "nodes_added": session.query(KnowledgeNode).filter(
            KnowledgeNode.node_key.like(f"%:{report_id}")
        ).count(),
        "edges_added": session.query(KnowledgeEdge).filter(
            KnowledgeEdge.source_node_key.like(f"%:{report_id}")
        ).count()
    }
```

### 8.3 Web 可视化入口

**新增路由**：`GET /graph`

**页面功能**：
- 搜索节点（实体/报告/观点/信号）
- 展示节点邻居（1 层关系）
- 点击节点跳转详情页

---

## 9. 实施计划

### 阶段 1：数据模型统一（低风险，2-3 天）

**范围**：
- ✅ 数据库迁移脚本（新增字段、新表）
- ✅ 补充文本文件的 SourceDocument 持久化
- ✅ 扩展 ingest_jobs 状态机

**验证**：
- 迁移脚本在测试环境成功执行
- 现有 2013 tests 不失败
- 新字段可读写

**提交物**：
- `migrations/003_add_automation_fields.sql`
- `db/source_provenance.py` 扩展

### 阶段 2：文本文件分析能力（中等风险，3-5 天）

**范围**：
- ✅ 新增 `sources/text_analysis.py`（参考 `pdf_analysis.py`）
- ✅ 扩展 `file_import_preview.py`（增加分析选项）
- ✅ 新增 `/api/sources/files/analyze` API
- ✅ 预览页面增加"归档并分析"按钮

**验证**：
- 上传 TXT/MD 文件可触发 LLM 分析
- 分析结果入库到 reports/views/signals/entities
- SourceDocument 正确持久化
- 统一搜索可查到分析结果

**提交物**：
- `sources/text_analysis.py`
- `tests/test_text_analysis.py`

### 阶段 3：自动化调度（中等风险，5-7 天）

**范围**：
- ✅ 新增 `services/scheduler_service.py`
- ✅ 新增 `services/value_scorer.py`
- ✅ 新增 `services/queue_worker.py`
- ✅ 新增 `/api/scheduler/*` API
- ✅ Web 启动时自动加载调度器
- ✅ CLI 命令：`signalvault scheduler start/stop/status`

**验证**：
- 调度任务按时触发（检查日志）
- 锁定目录自动扫描新文件
- 频道自动刷新获取新视频
- 价值评分算法正确
- 成本预算机制生效

**提交物**：
- `services/scheduler_service.py`
- `services/value_scorer.py`
- `services/queue_worker.py`
- `tests/test_scheduler.py`

### 阶段 4：UI 入口收敛（高风险，5-7 天）

**范围**：
- ✅ 重构 `/sources/files`（收敛现有路由）
- ✅ 重构 `/sources/tracked`（收敛频道管理）
- ✅ 扩展 `/processing`（新增自动化队列视图）
- ✅ 更新主导航（两个入口 + 处理中心）
- ✅ 旧路由 301 重定向
- ✅ 更新用户文档

**验证**：
- UI smoke tests 通过
- 用户测试：可在 5 分钟内完成首次导入
- 旧路由 301 重定向生效
- 用户不迷失（清晰的流程引导）

**提交物**：
- 重构的 HTML 模板
- 更新的 `web/routes.py`
- 更新的 `docs/USER_GUIDE.md`

### 阶段 5：图数据库自动同步（低风险，2-3 天）

**范围**：
- ✅ 在 `sync_service.py` 中集成图更新
- ✅ 新增 `update_knowledge_graph_for_report()` 增量更新
- ✅ 新增 `/graph` 可视化页面
- ✅ 新增 `/api/graph/*` API

**验证**：
- 新报告自动进入图谱
- 图谱查询正确返回关联节点
- Web 可视化页面正常渲染

**提交物**：
- `db/knowledge_graph.py` 扩展
- `web/templates/graph.html`
- `tests/test_knowledge_graph.py`

---

## 10. 验证方案

### 10.1 功能测试

```bash
# 1. 文件类入口测试
curl -X POST /api/sources/files/upload -F "file=@test.txt"
curl -X POST /api/sources/files/analyze -d '{"job_id": 123}'
# 预期：SourceDocument + Episode + Report 入库

# 2. 锁定目录测试
curl -X POST /api/sources/lock-directory -d '{"path": "/tmp/research"}'
echo "test content" > /tmp/research/test.md
sleep 3600  # 等待自动扫描
# 预期：自动发现新文件，入队处理

# 3. 频道自动化测试
curl -X POST /api/scheduler/config -d '{
  "source_type": "channel",
  "source_id": 1,
  "refresh_interval": "1d",
  "auto_analyze_mode": "high_value",
  "cost_budget": 5
}'
curl -X POST /api/scheduler/trigger -d '{"source_type": "channel", "source_id": 1}'
# 预期：频道刷新，新视频入队

# 4. 统一搜索测试
curl -X GET "/api/search?q=test&result_types=report,source_document"
# 预期：返回 report + source_document 结果

# 5. 图数据库测试
curl -X GET "/api/graph/node/report:1"
curl -X GET "/api/graph/neighborhood/report:1"
# 预期：返回节点及其邻居
```

### 10.2 集成测试

```bash
# 完整流程测试（文件类）
1. 上传文本文件 → 选择"归档并分析"
2. 等待分析完成
3. 检查入库：Episode + Report + Views/Signals + SourceDocument
4. 统一搜索查询该文件内容 → 找到
5. 图数据库查询该报告节点 → 存在

# 完整流程测试（频道类）
1. 添加频道 → 配置自动刷新（每日）
2. 等待自动刷新（或手动触发）
3. 检查发现新视频 → 自动评分
4. 高价值视频自动分析 → 低价值仅归档
5. 统一搜索查询该视频内容 → 找到
6. 图数据库查询关联 → 正确
```

### 10.3 用户验收标准

- ✅ 非技术用户可在 **5 分钟内**完成首次导入（当前：15+ 分钟）
- ✅ 两个入口清晰，用户不会迷失（当前：6+ 个入口，用户困惑）
- ✅ 自动化可配置，成本可控（当前：全手动）
- ✅ 所有入库内容可搜索、可追溯（当前：归档文件无法搜索）
- ✅ 知识图谱自动维护（当前：需手动重建）

---

## 11. 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 调度器引入增加系统复杂度 | 高 | 高 | 使用 APScheduler（轻量级），提供手动关闭开关，完善监控 |
| LLM 成本失控 | 高 | 中 | 用户必须设置预算上限，默认关闭自动分析，实时监控调用量 |
| 数据迁移失败 | 高 | 低 | 提供回滚脚本，先在测试环境验证，备份现有数据库 |
| UI 变更影响现有用户习惯 | 中 | 中 | 保留旧路由 301 重定向，提供过渡期文档，用户调研 |
| 图数据库性能问题 | 低 | 低 | 增量更新而非全量重建，设置并发限制，异步处理 |
| 队列消费者失败 | 中 | 中 | 失败自动重试（最多 3 次），记录失败原因，提供手动恢复 |

---

## 12. 成功标准

**功能完整性**：
- ✅ 所有来源统一入库到 SourceDocument
- ✅ 用户可选择是否 LLM 分析（文本文件）
- ✅ 频道可配置自动刷新（每日/每周/每月）
- ✅ 锁定目录自动检测新增文件
- ✅ 统一搜索覆盖所有入库内容
- ✅ 图数据库自动同步
- ✅ 成本预算机制生效

**用户体验**：
- ✅ 用户操作流程 ≤ 3 步完成导入
- ✅ 非技术用户 5 分钟内完成首次导入
- ✅ UI 入口清晰（2 个主入口）
- ✅ 状态可见（待处理、处理中、已完成）

**技术指标**：
- ✅ 现有 2013 tests 不失败
- ✅ 新增测试覆盖新功能
- ✅ 代码质量：ruff check 通过
- ✅ 文档完善：USER_GUIDE.md 更新

---

## 附录：关键文件路径

### 新增文件
```
sources/text_analysis.py                    # 文本文件分析
services/scheduler_service.py               # 调度器
services/value_scorer.py                     # 价值评分
services/queue_worker.py                     # 队列消费者
migrations/003_add_automation_fields.sql    # 数据库迁移
```

### 重构文件
```
sources/file_import_preview.py               # 增加分析选项
sources/ingest_jobs.py                       # 新增状态和方法
services/sync_service.py                     # 集成图更新
web/routes.py                                # 入口收敛
db/source_provenance.py                      # 补充文本文件持久化
db/knowledge_graph.py                        # 增量更新函数
```

### 新增模板
```
web/templates/sources/files.html             # 文件类入口
web/templates/sources/tracked.html           # 频道/固定源类入口
web/templates/graph.html                     # 图数据库可视化
web/templates/queue.html                     # 自动化队列视图
```

---

**方案完成日期**：2026-08-03
**下一步**：等待用户确认，进入实施阶段