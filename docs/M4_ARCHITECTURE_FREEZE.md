# M4-0 Research Asset Lifecycle 架构冻结设计文档

> 状态：架构设计冻结（待评审）
> 日期：2026-08-03
> 基线：M3-C 完成，2013 tests，核心功能可运行
> 目标：从「信息采集工具」演进为「个人投资研究操作系统」

---

## 目录

1. [当前问题分析](#1-当前问题分析)
2. [架构目标](#2-架构目标)
3. [Research Asset Lifecycle 总体架构](#3-research-asset-lifecycle-总体架构)
4. [核心领域模型](#4-核心领域模型)
5. [数据模型设计](#5-数据模型设计)
6. [状态机设计](#6-状态机设计)
7. [Intake 统一入口设计](#7-intake-统一入口设计)
8. [Automation 架构设计](#8-automation-架构设计)
9. [Knowledge Graph 设计](#9-knowledge-graph-设计)
10. [Search 演进路线](#10-search-演进路线)
11. [Claim 层设计](#11-claim-层设计)
12. [M4 实施路线](#12-m4-实施路线)
13. [风险分析](#13-风险分析)
14. [与 M3 代码映射关系](#14-与-m3-代码映射关系)

---

## 1. 当前问题分析

### 1.1 架构断层问题

| 问题类别 | 具体表现 | 根因分析 |
|---------|----------|----------|
| **处理流程不一致** | PDF 自动分析，普通文本文件不分析 | 缺少统一生命周期模型，按入口硬编码路径 |
| **数据孤岛** | SourceArchive 不入库，不进入统一搜索 | SourceDocument 仅部分来源接入，入库路径割裂 |
| **自动化不足** | 无定时刷新、自动发现、自动导入 | 缺少调度器和队列消费者，ingest_jobs 承担职责过多 |
| **UI 入口碎片化** | 6+ 个并行导入入口，用户迷失 | 按功能和历史迭代设计，未从用户意图出发 |
| **知识图谱失效** | 需手动重建，不自动同步 | Graph Sync 作为阶段 5，定位滞后 |
| **能力缺失** | 归档文件无法检索，无语义搜索 | FTS5 仅覆盖部分表，未预留向量搜索能力 |

### 1.2 核心定位偏差

**当前定位**：信息采集工具
- YouTube 字幕分析工具
- PDF 报告提取工具
- 文件归档工具

**期望定位**：个人投资研究操作系统
- 统一的信息生命周期管理
- 持续积累的投资知识网络
- 研究决策支持系统

### 1.3 ingest_jobs 职责过重

当前 `ingest_jobs` 表承担过多职责：
- 导入任务
- 分析任务
- 自动化任务
- 调度任务

**问题**：
- 状态混乱（9 个状态混合不同维度）
- 查询困难（无法按任务类型筛选）
- 扩展性差（新增任务类型需修改表结构）

---

## 2. 架构目标

### 2.1 核心目标

**从「信息采集工具」演进为「个人投资研究操作系统」**

### 2.2 架构原则

1. **生命周期统一**：任何信息来源都遵循统一的处理流程
2. **资产化所有内容**：所有入库内容都成为可检索、可关联的研究资产
3. **自动化优先**：减少手工操作，但保持用户控制权
4. **知识网络驱动**：Graph 是核心价值，而非附属功能
5. **渐进式演进**：分阶段实施，每个阶段独立可用

### 2.3 核心链路

```
任何信息来源（Source）
    ↓
SourceItem（信息源对象）
    ↓
Processing Pipeline（处理流水线）
    ├─ Extract（文本提取）
    ├─ OCR（图片识别）
    ├─ Analyze（LLM 分析）
    ├─ Embed（向量化）
    └─ Sync（同步到图谱）
    ↓
Research Asset（研究资产）
    ├─ Episode
    ├─ Report
    ├─ View
    ├─ Signal
    ├─ Entity
    └─ Claim
    ↓
Knowledge Graph（知识关系）
    ├─ Company 节点
    ├─ Person 节点
    ├─ Topic 节点
    ├─ Claim 节点
    └─ 关系边
    ↓
应用层
    ├─ Search（关键词 + 语义）
    ├─ Insight（洞察发现）
    └─ Decision Support（决策支持）
```

---

## 3. Research Asset Lifecycle 总体架构

### 3.1 分层架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                     Presentation Layer                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │  Intake  │  │ Search   │  │ Dashboard│  │  Graph   │       │
│  │  /intake │  │ /search  │  │/dashboard│  │  /graph  │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    Application Layer                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Intake   │  │ Process  │  │  Search  │  │  Graph   │       │
│  │Orchestr.│  │ Pipeline │  │ Service  │  │ Service  │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      Domain Layer                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │  SourceItem  │  │ProcessingJob │  │ResearchAsset │         │
│  │   Manager    │  │   Manager    │  │   Manager    │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ ClaimManager │  │GraphManager  │  │AutomationMgr│         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                       Data Layer                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ SQLite   │  │   FTS5   │  │  Vector  │  │  Graph   │       │
│  │  (Core)  │  │(Keyword) │  │(Semantic)│  │ (Nodes)  │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 数据流转全景图

```
┌─────────────────────────────────────────────────────────────┐
│                    Intake Layer                               │
│  用户输入：URL / File / Channel / RSS / Text                │
│    ↓                                                          │
│  识别 source_type：youtube / pdf / web / file / rss        │
│    ↓                                                          │
│  创建 SourceItem（status: captured）                         │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                  Processing Layer                             │
│  创建 ProcessingJob（type: extract_text / OCR / analyze）   │
│    ↓                                                          │
│  Job 状态机：pending → running → completed / failed         │
│    ↓                                                          │
│  Pipeline 执行：Extract → Analyze → Embed → Sync            │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                   Asset Layer                                 │
│  创建 ResearchAsset：Episode + Report + Views + Signals     │
│    ↓                                                          │
│  创建 Claim：从 Report 提取核心判断                          │
│    ↓                                                          │
│  创建 SourceDocument + SourceSegments（原文追溯）            │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    Graph Layer                                │
│  增量同步到 Knowledge Graph：                                │
│    ├─ 节点：Company / Person / Topic / Claim                │
│    └─ 边：mentioned_in / derived_from / supports            │
│    ↓                                                          │
│  更新 FTS5 索引（关键词搜索）                                │
│    ↓                                                          │
│  计算 Embedding（语义搜索，预留）                            │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                 Application Layer                             │
│  统一搜索：FTS5（关键词）+ Vector（语义）                    │
│  知识图谱查询：邻居、路径、聚类                              │
│  决策支持：信号触发、观点关联、冲突检测                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 核心领域模型

### 4.1 三层模型架构

```
SourceItem（信息源对象）
    ↓ "系统要对它做什么"
ProcessingJob（处理任务）
    ↓ "加工后的结果"
ResearchAsset（研究资产）
```

### 4.2 SourceItem 模型

**定义**：表示"这个信息是什么"

**职责**：
- 记录来源元数据
- 追溯来源信息
- 管理生命周期状态

**字段设计**：

```python
class SourceItem:
    # 基础标识
    id: int                      # 主键
    source_type: str             # youtube_video / pdf_document / web_page / text_file / rss_article
    source_uri: str              # URL / 文件路径 / 唯一标识
    
    # 内容元数据
    title: str                   # 标题
    description: str             # 描述
    metadata: dict               # 扩展元数据（频道名、时长、发布时间等）
    
    # 内容追踪
    content_hash: str            # SHA-256（去重）
    captured_at: datetime        # 捕获时间
    provenance: str              # 来源说明（如何发现：用户上传 / 自动发现 / 刷新）
    
    # 状态管理
    status: str                  # captured / processing / processed / archived / failed
    
    # 关联
    source_document_id: str      # 关联的源文档（可选）
    processing_job_ids: list[int]# 关联的处理任务（多个）
    
    # 用户反馈
    user_rating: str             # valuable / neutral / irrelevant
    user_notes: str              # 用户备注
```

**来源类型枚举**：

```python
class SourceItemType(Enum):
    YOUTUBE_VIDEO = "youtube_video"
    YOUTUBE_CHANNEL = "youtube_channel"
    PDF_DOCUMENT = "pdf_document"
    WEB_PAGE = "web_page"
    TEXT_FILE = "text_file"
    RSS_ARTICLE = "rss_article"
    ZSXQ_TOPIC = "zsxq_topic"
    LOCKED_DIR_FILE = "locked_dir_file"
```

### 4.3 ProcessingJob 模型

**定义**：表示"系统要对它执行什么处理"

**职责**：
- 管理处理任务队列
- 记录执行状态和结果
- 统计成本和性能

**字段设计**：

```python
class ProcessingJob:
    # 基础标识
    id: int                      # 主键
    source_item_id: int          # 关联 SourceItem
    
    # 任务定义
    job_type: str                # extract_text / OCR / analyze / summarize / embed / sync_graph
    priority: int                # 优先级（0-9，越高越优先）
    
    # 参数
    params: dict                 # 任务参数（analyze 的 focus、depth 等）
    
    # 状态管理
    status: str                  # pending / running / completed / failed / cancelled
    started_at: datetime         # 开始时间
    completed_at: datetime       # 完成时间
    
    # 结果
    result_type: str             # research_asset / error
    result_ref: int              # 关联的 ResearchAsset ID 或错误记录
    error_message: str           # 错误信息
    
    # 成本统计
    llm_calls: int               # LLM 调用次数
    tokens_used: int             # Token 消耗
    duration_seconds: int        # 执行时长
    
    # 重试
    retry_count: int             # 已重试次数
    max_retries: int             # 最大重试次数（默认 3）
```

**任务类型枚举**：

```python
class JobType(Enum):
    # 文本处理
    EXTRACT_TEXT = "extract_text"       # 提取文本（PDF/网页/文件）
    OCR = "ocr"                         # OCR 图片识别
    
    # 内容分析
    ANALYZE = "analyze"                 # LLM 分析（生成 Report/Views/Signals）
    SUMMARIZE = "summarize"             # 生成摘要
    
    # 向量化
    EMBED = "embed"                     # 计算向量 Embedding
    
    # 知识同步
    SYNC_GRAPH = "sync_graph"           # 同步到知识图谱
    SYNC_FTS = "sync_fts"               # 同步到全文索引
```

### 4.4 ResearchAsset 模型

**定义**：表示"经过加工后的研究资产"

**职责**：
- 统一管理研究成果
- 支持检索和关联
- 形成知识网络

**资产类型**：

```python
class ResearchAssetType(Enum):
    EPISODE = "episode"                 # 原始素材会话
    REPORT = "report"                   # 分析报告
    VIEW = "investment_view"            # 投资观点
    SIGNAL = "tracking_signal"          # 跟踪信号
    ENTITY = "entity"                   # 提及实体
    CLAIM = "claim"                     # 核心判断
    SOURCE_DOCUMENT = "source_document" # 原文材料
```

**数据库实现：Base Asset + 子表模式**

采用继承模式，避免单一宽表：

```python
# 基础资产表（所有资产共享）
class ResearchAssetBase:
    # 基础标识
    id: int
    asset_type: str
    
    # 来源追溯
    source_item_id: int          # 关联 SourceItem
    episode_id: int              # 关联 Episode（可选）
    source_document_id: str      # 关联 SourceDocument
    
    # 时间戳
    created_at: datetime
    updated_at: datetime
    
    # 状态
    status: str                  # active / archived / deleted

# 子表：Episode
class EpisodeAsset(ResearchAssetBase):
    title: str
    source_url: str
    video_id: str
    language: str
    # ... episode 特有字段

# 子表：Report
class ReportAsset(ResearchAssetBase):
    report_markdown: str
    executive_summary: str
    llm_provider: str
    # ... report 特有字段

# 子表：InvestmentView
class ViewAsset(ResearchAssetBase):
    target_name: str
    view_direction: str
    logic_chain: str
    source_quote: str
    # ... view 特有字段

# 子表：Claim
class ClaimAsset(ResearchAssetBase):
    claim_text: str
    claim_type: str
    confidence: float
    source_report_id: int
    # ... claim 特有字段
```

**设计优势**：
- ✅ 职责清晰：每种资产类型有自己的表和字段
- ✅ 查询高效：不涉及大量 NULL 字段
- ✅ 扩展灵活：新增资产类型只需新增子表
- ✅ 类型安全：避免了 JSON 字段的类型风险

### 4.5 SourceDocument 作为基础资产

**重新定位**：

```
当前架构：
SourceDocument → Episode（主从关系）

新架构：
SourceDocument（基础资产）
    ↓
ResearchAsset（引用 SourceDocument）
```

**设计原则**：
- SourceDocument 是所有来源的统一锚点
- 任何来源都应创建 SourceDocument
- ResearchAsset 通过 `source_document_id` 关联

**重要关系：SourceItem / SourceDocument 多对一**

```
多个 SourceItem 可对应一个 SourceDocument

场景示例：
- YouTube 频道（SourceItem）→ 多个视频（SourceItem）→ 同一个 transcript 文档（SourceDocument）
- RSS 源（SourceItem）→ 多篇文章（SourceItem）→ 各自的 SourceDocument
- 锁定目录（SourceItem）→ 多个文件（SourceItem）→ 各自的 SourceDocument

关系：
- SourceItem：表示"发现/捕获的事件"（频道刷新、目录扫描）
- SourceDocument：表示"实际的内容文档"（视频字幕、文章正文）
```

**字段设计**：

```python
class SourceDocument:
    # 基础标识
    source_doc_id: str           # 全局唯一 ID（业务键）
    source_type: str             # youtube_transcript / pdf_document / web_page / text_file
    
    # 内容元数据
    title: str
    canonical_url: str
    source_url: str
    
    # 内容存储
    content_hash: str            # 内容哈希
    raw_text_path: str           # 原始文本文件路径
    normalized_text_path: str    # 标准化文本路径
    
    # 语言信息
    language: str
    original_language: str
    
    # 向量化（预留）
    embedding_vector: list[float]  # Embedding 向量（可选）
    embedding_model: str           # 使用的模型（可选）
    
    # 关联（多对一）
    # 注意：不直接关联 SourceItem
    # SourceItem 通过 source_document_id 关联到此表
```

---

## 5. 数据模型设计

### 5.1 ER 关系图

```
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│  SourceItem  │ 1    N  │ProcessingJob │ N    1  │ResearchAsset │
│              │◄────────┤              ├────────►│              │
│ - id         │         │ - id         │         │ - id         │
│ - source_type│         │ - job_type   │         │ - asset_type │
│ - source_uri │         │ - status     │         │ - episode_id │
│ - status     │         │ - result_ref │         │ - source_doc │
└──────┬───────┘         └──────────────┘         └──────┬───────┘
       │                                                   │
       │ 1                                                 │
       │                                                   │
       ▼                                                   ▼
┌──────────────┐                                   ┌──────────────┐
│SourceDocument│                                   │    Claim     │
│              │                                   │              │
│ - source_doc │                                   │ - claim_text │
│ - content_   │                                   │ - confidence │
│   hash       │                                   │ - source_id  │
└──────────────┘                                   └──────────────┘

┌──────────────┐         ┌──────────────┐
│KnowledgeNode │ N    N  │KnowledgeEdge │
│              │◄────────┤              │
│ - node_key   │         │ - edge_key   │
│ - node_type  │         │ - edge_type  │
│ - label      │         │ - source     │
└──────────────┘         │ - target     │
                         └──────────────┘
```

### 5.2 表结构设计

#### source_items 表

```sql
CREATE TABLE source_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- 来源标识
    source_type TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    
    -- 内容元数据
    title TEXT,
    description TEXT,
    metadata TEXT,  -- JSON
    
    -- 内容追踪
    content_hash TEXT,
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    provenance TEXT,
    
    -- 状态管理
    status TEXT DEFAULT 'captured',
    
    -- 关联
    source_document_id TEXT,
    
    -- 用户反馈
    user_rating TEXT,
    user_notes TEXT,
    
    -- 索引字段
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_source_items_type ON source_items(source_type);
CREATE INDEX idx_source_items_hash ON source_items(content_hash);
CREATE INDEX idx_source_items_status ON source_items(status);
```

#### processing_jobs 表

```sql
CREATE TABLE processing_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- 任务定义
    source_item_id INTEGER NOT NULL,
    job_type TEXT NOT NULL,
    priority INTEGER DEFAULT 5,
    
    -- 参数
    params TEXT,  -- JSON
    
    -- 状态管理
    status TEXT DEFAULT 'pending',
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    
    -- 结果
    result_type TEXT,
    result_ref INTEGER,
    error_message TEXT,
    
    -- 成本统计
    llm_calls INTEGER DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    duration_seconds INTEGER DEFAULT 0,
    
    -- 重试
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    
    -- 索引字段
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_processing_jobs_status ON processing_jobs(status);
CREATE INDEX idx_processing_jobs_source ON processing_jobs(source_item_id);
CREATE INDEX idx_processing_jobs_type ON processing_jobs(job_type);
```

#### research_assets 表（统一资产表）

```sql
CREATE TABLE research_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- 基础标识
    asset_type TEXT NOT NULL,
    
    -- 来源追溯
    source_item_id INTEGER,
    episode_id INTEGER,
    source_document_id TEXT,
    
    -- 资产内容（根据 asset_type 解释）
    content TEXT,  -- JSON 或 Markdown
    
    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- 状态
    status TEXT DEFAULT 'active'
);

CREATE INDEX idx_research_assets_type ON research_assets(asset_type);
CREATE INDEX idx_research_assets_source ON research_assets(source_item_id);
```

#### claims 表（新增）

```sql
CREATE TABLE claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- 判断内容
    claim_text TEXT NOT NULL,
    claim_type TEXT,  -- fact / prediction / opinion
    
    -- 置信度
    confidence REAL,  -- 0.0-1.0
    
    -- 来源追溯
    source_report_id INTEGER NOT NULL,
    source_view_id INTEGER,
    source_quote TEXT,
    timestamp TEXT,
    evidence_page INTEGER,
    
    -- 支持证据
    supporting_sources TEXT,  -- JSON array of source_doc_ids
    
    -- 状态
    status TEXT DEFAULT 'active',
    invalidated_at TIMESTAMP,
    invalidated_reason TEXT,
    
    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_claims_report ON claims(source_report_id);
CREATE INDEX idx_claims_type ON claims(claim_type);
```

#### source_segments 表（扩展）

```sql
ALTER TABLE source_segments ADD COLUMN embedding_vector BLOB;
ALTER TABLE source_segments ADD COLUMN embedding_model TEXT;
ALTER TABLE source_segments ADD COLUMN embedding_created_at TIMESTAMP;
```

---

## 6. 状态机设计

### 6.1 SourceItem 状态机

```
captured（已捕获）
    ↓ [create_processing_job]
processing（处理中）
    ↓ [job_completed]
processed（已处理）
    ↓ [archive]
archived（已归档）

异常路径：
    ↓ [job_failed]
failed（失败）
    ↓ [retry]
processing
```

### 6.2 ProcessingJob 状态机

```
pending（待处理）
    ↓ [worker_pick_up]
running（运行中）
    ├─ [success] → completed（已完成）
    ├─ [error] → failed（失败）
    └─ [cancel] → cancelled（已取消）

重试路径：
    failed → [retry] → pending（重试次数 < max_retries）
    
降级路径：
    failed（重试耗尽）→ [mark_source_failed] → SourceItem.status = failed
```

### 6.3 ResearchAsset 状态机

```
active（活跃）
    ↓ [archive]
archived（已归档）
    ↓ [restore]
active

删除路径：
    ↓ [soft_delete]
deleted（已删除）
```

### 6.4 Claim 状态机

```
active（活跃）
    ├─ [invalidate_by_time] → invalidated_time（时间证伪）
    ├─ [invalidate_by_fact] → invalidated_fact（事实证伪）
    └─ [invalidate_by_user] → invalidated_user（用户标记）

恢复路径：
    invalidated_* → [reactivate] → active
```

---

## 7. Intake 统一入口设计

### 7.1 设计理念

**用户认知**："我要添加研究资料"

而不是："我要选择文件入口还是频道入口"

### 7.2 路由设计

```
GET /intake
    ├─ 展示统一输入界面
    └─ 支持多种输入方式

POST /intake/submit
    ├─ 接收任意类型输入
    ├─ 自动识别 source_type
    └─ 创建 SourceItem
```

### 7.3 用户交互流程

```
┌─────────────────────────────────────────┐
│         Intake 页面布局                  │
│                                          │
│  ┌────────────────────────────────────┐ │
│  │   输入框（粘贴 URL / 拖拽文件）    │ │
│  │                                    │ │
│  │   支持的输入类型：                 │ │
│  │   • YouTube 视频 / 频道 URL        │ │
│  │   • PDF / TXT / MD / DOCX 文件    │ │
│  │   • 网页 URL                       │ │
│  │   • RSS 链接                       │ │
│  │   • 直接粘贴文本                   │ │
│  └────────────────────────────────────┘ │
│                                          │
│  ┌────────────────────────────────────┐ │
│  │   或选择高级方式：                 │ │
│  │                                    │ │
│  │   [上传文件] [添加频道] [添加RSS] │ │
│  └────────────────────────────────────┘ │
│                                          │
│  ┌────────────────────────────────────┐ │
│  │   处理偏好：                       │ │
│  │                                    │ │
│  │   自动分析：[关闭] / 高价值 / 全部│ │
│  │   关注主题：（用户 watchlist）    │ │
│  └────────────────────────────────────┘ │
│                                          │
│           [开始处理]                     │
└─────────────────────────────────────────┘
```

### 7.4 自动识别逻辑

```python
def identify_source_type(input: str) -> SourceItemType:
    """
    根据输入自动识别来源类型
    """
    # 1. 文件上传（通过 multipart/form-data 识别）
    if is_file_upload(input):
        ext = get_extension(input.filename)
        return {
            '.pdf': SourceItemType.PDF_DOCUMENT,
            '.txt': SourceItemType.TEXT_FILE,
            '.md': SourceItemType.TEXT_FILE,
            '.docx': SourceItemType.TEXT_FILE,
            '.html': SourceItemType.TEXT_FILE,
        }.get(ext, SourceItemType.TEXT_FILE)
    
    # 2. URL 识别
    if is_url(input):
        if 'youtube.com' in input or 'youtu.be' in input:
            if '/channel/' in input or '/c/' in input:
                return SourceItemType.YOUTUBE_CHANNEL
            return SourceItemType.YOUTUBE_VIDEO
        
        if is_rss_url(input):
            return SourceItemType.RSS_ARTICLE
        
        return SourceItemType.WEB_PAGE
    
    # 3. 文本内容（直接粘贴）
    if len(input) > 100:
        return SourceItemType.TEXT_FILE  # 作为文本文件处理
    
    raise ValueError("无法识别的输入类型")
```

### 7.5 Intake Orchestrator

```python
class IntakeOrchestrator:
    """统一入口编排器"""
    
    def submit(self, input: str, preferences: dict) -> SourceItem:
        """
        提交输入到处理流程
        """
        # 1. 识别来源类型
        source_type = identify_source_type(input)
        
        # 2. 创建 SourceItem
        source_item = SourceItemManager.create(
            source_type=source_type,
            source_uri=input,
            provenance="user_intake",
            metadata={
                "user_preferences": preferences
            }
        )
        
        # 3. 创建必要的 ProcessingJobs
        self._create_processing_pipeline(source_item, preferences)
        
        # 4. 返回 SourceItem（用户可查看状态）
        return source_item
    
    def _create_processing_pipeline(self, source_item: SourceItem, preferences: dict):
        """
        创建处理流水线（根据来源类型和用户偏好）
        """
        # 基础任务：文本提取
        ProcessingJobManager.create(
            source_item_id=source_item.id,
            job_type=JobType.EXTRACT_TEXT,
            priority=9
        )
        
        # 分析任务（根据用户偏好）
        if preferences.get("auto_analyze") != "off":
            ProcessingJobManager.create(
                source_item_id=source_item.id,
                job_type=JobType.ANALYZE,
                priority=5,
                params={
                    "focus": preferences.get("focus"),
                    "depth": preferences.get("depth", "standard")
                }
            )
        
        # 图谱同步任务（依赖分析完成）
        ProcessingJobManager.create(
            source_item_id=source_item.id,
            job_type=JobType.SYNC_GRAPH,
            priority=3,
            params={
                "depends_on": "analyze"  # 依赖分析任务完成
            }
        )
```

---

## 8. Automation 架构设计

### 8.1 Desktop Automation 挑战

SignalVault 是桌面应用，不是服务器，需要考虑：
- App 启动 / 关闭
- 后台 worker 生命周期
- 单实例约束
- 系统休眠恢复

### 8.2 架构设计

```
┌──────────────────────────────────────────────────────────┐
│                    SignalVault App                        │
│                                                           │
│  ┌─────────────────┐        ┌─────────────────────┐    │
│  │  Main Process   │        │  Background Worker  │    │
│  │  (UI / API)     │        │  (Scheduler)        │    │
│  │                 │        │                     │    │
│  │  - FastAPI      │        │  - APScheduler      │    │
│  │  - Web Routes   │        │  - Job Consumer     │    │
│  │  - Intake       │        │  - Task Executor    │    │
│  └─────────────────┘        └─────────────────────┘    │
│           │                            │                 │
│           └────────────┬───────────────┘                │
│                        │                                 │
│                        ▼                                 │
│           ┌─────────────────────────┐                   │
│           │  Shared State (SQLite)  │                   │
│           │                         │                   │
│           │  - source_items         │                   │
│           │  - processing_jobs      │                   │
│           │  - scheduler_state      │                   │
│           │  - locks                │                   │
│           └─────────────────────────┘                   │
└──────────────────────────────────────────────────────────┘
```

### 8.3 Scheduler 实现

```python
class DesktopScheduler:
    """桌面应用调度器"""
    
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.worker = JobConsumer()
        self._instance_lock = None
    
    def start(self):
        """启动调度器（App 启动时调用）"""
        # 1. 检查单实例
        if not self._acquire_instance_lock():
            logger.warning("Another instance is running, skip scheduler start")
            return
        
        # 2. 恢复未完成任务
        self._recover_pending_jobs()
        
        # 3. 注册定时任务
        self._register_periodic_jobs()
        
        # 4. 启动调度器
        self.scheduler.start()
        self.worker.start()
        
        logger.info("Scheduler started")
    
    def stop(self):
        """停止调度器（App 关闭时调用）"""
        # 1. 停止接收新任务
        self.scheduler.pause()
        
        # 2. 等待当前任务完成（最多 30s）
        self.worker.graceful_shutdown(timeout=30)
        
        # 3. 保存未完成任务状态
        self._persist_job_states()
        
        # 4. 释放实例锁
        self._release_instance_lock()
        
        logger.info("Scheduler stopped")
    
    def _acquire_instance_lock(self) -> bool:
        """获取单实例锁"""
        try:
            lock_file = get_app_paths().cache_dir / "scheduler.lock"
            self._instance_lock = open(lock_file, 'w')
            fcntl.flock(self._instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (IOError, OSError):
            return False
    
    def _register_periodic_jobs(self):
        """注册定时任务"""
        # 每小时扫描锁定目录
        self.scheduler.add_job(
            self._scan_locked_directories,
            'interval',
            hours=1,
            id='scan_locked_dirs'
        )
        
        # 每日 02:00 刷新活跃频道
        self.scheduler.add_job(
            self._refresh_active_channels,
            'cron',
            hour=2,
            minute=0,
            id='refresh_channels'
        )
        
        # 每 5 分钟消费处理队列
        self.scheduler.add_job(
            self._consume_processing_queue,
            'interval',
            minutes=5,
            id='consume_queue'
        )
```

### 8.4 Job Consumer

```python
class JobConsumer:
    """处理任务消费者"""
    
    def __init__(self):
        self.running = False
        self.current_job = None
    
    def start(self):
        """启动消费者"""
        self.running = True
    
    def consume_one(self) -> bool:
        """消费一个任务"""
        if not self.running:
            return False
        
        # 1. 获取待处理任务（优先级排序）
        job = ProcessingJobManager.get_next_pending_job()
        if not job:
            return False
        
        # 2. 检查预算
        if not self._check_budget():
            logger.info("Budget exhausted, pausing")
            return False
        
        # 3. 标记为运行中
        self.current_job = job
        ProcessingJobManager.mark_running(job.id)
        
        try:
            # 4. 执行任务
            result = self._execute_job(job)
            
            # 5. 标记完成
            ProcessingJobManager.mark_completed(
                job.id,
                result_type=result["type"],
                result_ref=result["ref"]
            )
            
            return True
        
        except Exception as e:
            # 6. 标记失败
            ProcessingJobManager.mark_failed(job.id, str(e))
            
            # 7. 检查是否需要重试
            if job.retry_count < job.max_retries:
                ProcessingJobManager.reset_for_retry(job.id)
            
            return False
        
        finally:
            self.current_job = None
    
    def graceful_shutdown(self, timeout: int = 30):
        """优雅关闭"""
        self.running = False
        
        # 等待当前任务完成
        if self.current_job:
            start = time.time()
            while self.current_job and (time.time() - start) < timeout:
                time.sleep(1)
```

### 8.5 用户控制

```python
class AutomationSettings:
    """自动化设置（用户可配置）"""
    
    # 开关
    enabled: bool = True
    
    # 刷新周期
    channel_refresh_interval: str = "1d"  # 每日
    locked_dir_scan_interval: str = "1h"  # 每小时
    
    # 自动分析
    auto_analyze_mode: str = "off"  # off / high_value / all
    
    # 成本预算
    daily_llm_budget: int = 10  # 每日最多 10 次 LLM
    
    # 时间窗口（避免打扰）
    quiet_hours_start: str = "23:00"
    quiet_hours_end: str = "07:00"
```

---

## 9. Knowledge Graph 设计

### 9.1 Graph 架构前置

**原则**：Graph Sync 不应作为阶段 5，而应前置为核心流程。

### 9.2 Node 类型设计

```python
class NodeType(Enum):
    # 实体节点
    COMPANY = "company"
    PERSON = "person"
    TOPIC = "topic"
    TECHNOLOGY = "technology"
    
    # 内容节点
    REPORT = "report"
    SOURCE_DOCUMENT = "source_document"
    
    # 判断节点
    CLAIM = "claim"
    VIEW = "view"
    SIGNAL = "signal"
```

### 9.3 Edge 类型设计（分级）

**重要：Graph 关系分为两类**

#### 9.3.1 确定性关系（Deterministic Edges）

**定义**：从数据直接提取，无需推断

**特点**：
- ✅ 100% 准确
- ✅ 可自动创建
- ✅ 无需人工审核

**关系类型**：

```python
class DeterministicEdgeType(Enum):
    # 结构关系
    MENTIONED_IN = "mentioned_in"       # 实体在报告中被提及
    DERIVED_FROM = "derived_from"       # 观点来源于报告
    CONTAINS = "contains"               # 报告包含观点/信号
    CITES = "cites"                     # 引用原文
    TRACKS = "tracks"                   # Signal 跟踪实体
    
    # 来源关系
    SOURCE_OF = "source_of"             # SourceDocument 是 Asset 的来源
```

**创建时机**：
- Report 生成完成 → 自动创建 mentioned_in / derived_from / contains
- SourceDocument 创建 → 自动创建 source_of

#### 9.3.2 推断性关系（Inferred Edges）

**定义**：通过语义相似度或规则推断

**特点**：
- ⚠️ 置信度 < 1.0
- ⚠️ 需要存储置信度
- ⚠️ 可能需要人工审核

**关系类型**：

```python
class InferredEdgeType(Enum):
    # 语义关系
    RELATED_TO = "related_to"           # 实体相关（语义相似）
    SIMILAR_TO = "similar_to"           # Claim 相似
    
    # 判断关系
    SUPPORTS = "supports"               # Claim 支持另一个 Claim
    CONTRADICTS = "contradicts"         # Claim 与另一个 Claim 冲突
```

**数据模型扩展**：

```python
class KnowledgeEdge:
    # 现有字段
    edge_key: str
    source_node_key: str
    target_node_key: str
    edge_type: str
    
    # 新增字段（区分确定性/推断性）
    is_deterministic: bool              # True: 确定性；False: 推断性
    confidence: float                   # 推断性关系的置信度（0.0-1.0）
    inference_method: str               # 推断方法（semantic_similarity / rule_based / llm）
    needs_review: bool                  # 是否需要人工审核
```

**创建逻辑**：

```python
def create_edge(session, source, target, edge_type, confidence=None):
    """创建边（自动判断确定性/推断性）"""
    
    is_deterministic = edge_type in DeterministicEdgeType
    
    edge = KnowledgeEdge(
        edge_key=f"{edge_type}:{source}:{target}",
        source_node_key=source,
        target_node_key=target,
        edge_type=edge_type,
        is_deterministic=is_deterministic,
        confidence=confidence if not is_deterministic else 1.0,
        needs_review=not is_deterministic and confidence < 0.7
    )
    
    session.add(edge)
    return edge
```

### 9.4 增量同步触发点

```
Report 生成完成
    ↓
触发 Graph Sync
    ├─ 1. 实体节点同步（确定性）
    │   └─ 提取 Entity → 创建/更新节点 → 建立 mentioned_in 边（置信度 1.0）
    │
    ├─ 2. 观点节点同步（确定性）
    │   └─ 提取 View → 创建节点 → 建立 derived_from 边（置信度 1.0）
    │
    ├─ 3. 信号节点同步（确定性）
    │   └─ 提取 Signal → 创建节点 → 建立 tracks 边（置信度 1.0）
    │
    ├─ 4. Claim 节点同步（确定性）
    │   └─ 提取 Claim → 创建节点
    │
    └─ 5. 推断关系发现（推断性）
        ├─ 检查 Claim 相似 → 建立 similar_to 边（置信度 0.8）
        ├─ 检查 Claim 冲突 → 建立 contradicts 边（置信度 0.7）
        └─ 检查 Claim 支持 → 建立 supports 边（置信度 0.8）
```

### 9.5 Graph 同步代码

```python
def sync_report_to_graph(report_id: int) -> dict:
    """增量同步单个报告到知识图谱"""
    session = get_session()
    report = session.query(Report).get(report_id)
    
    stats = {
        "nodes_created": 0,
        "deterministic_edges": 0,
        "inferred_edges": 0,
        "claims_extracted": 0
    }
    
    try:
        # 1. 实体节点同步（确定性）
        entities = extract_entities(report)
        for entity in entities:
            node = create_or_update_entity_node(session, entity)
            edge = create_edge(
                session, 
                source=f"entity:{entity.normalized_name}",
                target=f"report:{report_id}",
                edge_type="mentioned_in"
            )
            stats["nodes_created"] += 1
            stats["deterministic_edges"] += 1
        
        # 2. 观点节点同步（确定性）
        views = get_report_views(session, report_id)
        for view in views:
            node = create_view_node(session, view)
            edge = create_edge(
                session,
                source=f"view:{view.id}",
                target=f"report:{report_id}",
                edge_type="derived_from"
            )
            stats["nodes_created"] += 1
            stats["deterministic_edges"] += 1
        
        # 3. 信号节点同步（确定性）
        signals = get_report_signals(session, report_id)
        for signal in signals:
            node = create_signal_node(session, signal)
            edge = create_edge(
                session,
                source=f"signal:{signal.id}",
                target=f"entity:{signal.target_name}",
                edge_type="tracks"
            )
            stats["nodes_created"] += 1
            stats["deterministic_edges"] += 1
        
        # 4. Claim 节点同步（确定性）
        claims = extract_claims_from_report(report)
        for claim in claims:
            node = create_claim_node(session, claim)
            stats["nodes_created"] += 1
            stats["claims_extracted"] += 1
        
        # 5. 推断关系发现（推断性）
        for claim in claims:
            # 检查冲突
            conflicts = find_conflicting_claims(session, claim)
            for conflict in conflicts:
                edge = create_edge(
                    session,
                    source=f"claim:{claim.id}",
                    target=f"claim:{conflict.id}",
                    edge_type="contradicts",
                    confidence=0.7  # 推断置信度
                )
                stats["inferred_edges"] += 1
        
        session.commit()
        return stats
    
    except Exception as e:
        session.rollback()
        raise
```

---

## 10. Search 演进路线

### 10.1 阶段划分

```
阶段 1：FTS5 关键词搜索（当前）
    ├─ 搜索范围：reports / views / signals / entities / source_documents
    └─ 索引方式：SQLite FTS5 全文索引

阶段 2：Hybrid Search（预留）
    ├─ 搜索范围：增加向量相似度搜索
    ├─ 索引方式：FTS5 + Embedding 向量
    └─ 查询方式：关键词 + 语义混合
```

### 10.2 向量搜索预留

**数据模型预留**：

```python
class SourceSegment:
    # 现有字段
    source_doc_id: str
    segment_type: str
    text_original: str
    
    # 新增向量字段
    embedding_vector: list[float]  # Embedding 向量
    embedding_model: str           # 使用的模型（如 text-embedding-3-small）
    embedding_created_at: datetime # 向量生成时间
```

**索引方式**：
- SQLite 扩展（如 sqlite-vss）
- 或独立向量库（如 Chroma / Qdrant）

**查询流程**：

```python
def hybrid_search(query: str, top_k: int = 10) -> list[SearchResult]:
    """混合搜索：关键词 + 语义"""
    
    # 1. 关键词搜索（FTS5）
    keyword_results = fts5_search(query, limit=top_k * 2)
    
    # 2. 语义搜索（Embedding）
    query_embedding = compute_embedding(query)
    semantic_results = vector_search(query_embedding, limit=top_k * 2)
    
    # 3. 结果融合（RRF 或加权）
    merged = merge_results(keyword_results, semantic_results)
    
    # 4. 返回 Top-K
    return merged[:top_k]
```

---

## 11. Claim 层设计

### 11.1 为什么需要 Claim 层

**投资研究的核心价值**：
- 不是报告本身
- 而是观点和判断

**Claim 定义**：
- 核心判断陈述
- 可追溯来源
- 可验证真假
- 可形成网络

### 11.2 M4 实施范围（收敛）

**M4-A/B 阶段（当前实施）**：
- ✅ Claim 提取逻辑（从 Report/View/Signal 提取）
- ✅ Claim 持久化（claims 表）
- ✅ Claim 关联构建（Graph 边：supports / contradicts）

**M4-E 阶段（后置实施）**：
- ⏸️ Claim 验证机制（时间证伪、事实证伪）
- ⏸️ Claim 置信度更新（动态调整）
- ⏸️ Claim 过期检查（定时任务）

**理由**：
- Claim 提取和关联是基础能力，需优先实现
- Claim 验证需要用户反馈数据和更多样本，后置更合理

### 11.3 Claim 数据模型（M4 范围）

```python
class Claim:
    # 基础标识
    id: int
    claim_text: str              # 判断内容
    claim_type: str              # fact / prediction / opinion
    
    # 置信度
    confidence: float            # 0.0-1.0
    confidence_source: str       # speaker / llm / system
    
    # 来源追溯
    source_report_id: int
    source_view_id: int          # 可选，来自某个观点
    source_quote: str            # 原文引用
    timestamp: str               # 时间戳（视频）
    evidence_page: int           # 页码（PDF）
    
    # 支持证据
    supporting_sources: list[str]  # SourceDocument IDs
    
    # 验证状态（M4 暂不实现）
    # status: str                  # active / invalidated_time / invalidated_fact / invalidated_user
    # invalidated_at: datetime
    # invalidated_reason: str
    
    # 时间戳
    created_at: datetime
    updated_at: datetime
```

### 11.4 Claim 提取逻辑（M4 实施）

```python
def extract_claims_from_report(report: Report) -> list[Claim]:
    """从报告提取核心判断"""
    
    claims = []
    
    # 1. 从观点提取判断
    views = get_report_views(report.id)
    for view in views:
        if view.view_direction in ["bullish", "bearish"]:
            claim_text = f"{view.target_name} {view.view_direction} - {view.logic_chain[:100]}"
            
            claim = Claim(
                claim_text=claim_text,
                claim_type="prediction",
                confidence=0.7,  # 基于 speaker_confidence 推断
                source_report_id=report.id,
                source_view_id=view.id,
                source_quote=view.source_quote,
                timestamp=view.timestamp_start,
                evidence_page=view.evidence_page,
                supporting_sources=[view.source_document_id]
            )
            claims.append(claim)
    
    # 2. 从信号提取判断
    signals = get_report_signals(report.id)
    for signal in signals:
        claim_text = f"{signal.target_name} - {signal.signal}"
        
        claim = Claim(
            claim_text=claim_text,
            claim_type="prediction",
            confidence=0.6,
            source_report_id=report.id,
            source_quote=signal.source_quote,
            timestamp=signal.timestamp
        )
        claims.append(claim)
    
    return claims
```

### 11.5 Claim Graph 构建（M4 实施）

```python
def build_claim_graph(session: Session):
    """构建 Claim 关系网络"""
    
    claims = session.query(Claim).all()
    
    for claim in claims:
        # 1. 查找相似 Claim（语义相似）
        similar_claims = find_similar_claims(session, claim.claim_text, threshold=0.8)
        
        for similar in similar_claims:
            # 2. 判断关系类型
            if is_contradiction(claim.claim_text, similar.claim_text):
                # 冲突关系
                create_edge(
                    session,
                    source=f"claim:{claim.id}",
                    target=f"claim:{similar.id}",
                    edge_type="contradicts",
                    confidence=0.7  # 推断关系
                )
            elif is_support(claim.claim_text, similar.claim_text):
                # 支持关系
                create_edge(
                    session,
                    source=f"claim:{claim.id}",
                    target=f"claim:{similar.id}",
                    edge_type="supports",
                    confidence=0.8  # 推断关系
                )
```

### 11.6 Claim 验证机制（M4-E 实施）

**预留接口**：

```python
# M4-E 实现的验证接口
class ClaimValidator:
    @staticmethod
    def invalidate_by_time(claim_id: int, reason: str):
        """时间证伪（如预测已过期）"""
        pass
    
    @staticmethod
    def invalidate_by_fact(claim_id: int, evidence: str):
        """事实证伪（如新闻证明判断错误）"""
        pass
    
    @staticmethod
    def check_expired_predictions():
        """检查过期的预测性判断"""
        pass
```

---

## 12. M4 实施路线

### 12.1 阶段规划

```
M4-0：架构冻结设计（本文档）
    ↓
M4-A：Source Lifecycle 统一
    ├─ 实现 SourceItem 模型
    ├─ 实现 ProcessingJob 模型
    ├─ 迁移现有数据
    └─ 补充 SourceDocument 持久化
    ↓
M4-B：Research Asset Pipeline
    ├─ 实现统一 Pipeline 框架
    ├─ 实现 Claim 提取和持久化
    ├─ 实现 Graph 增量同步
    └─ 更新统一搜索
    ↓
M4-C：Automation
    ├─ 实现 DesktopScheduler
    ├─ 实现 JobConsumer
    ├─ 实现锁定目录扫描
    └─ 实现频道自动刷新
    ↓
M4-D：Product UX
    ├─ 实现 Intake 统一入口
    ├─ 重构主导航
    ├─ 实现用户反馈机制
    └─ 更新文档
    ↓
M4-E：Advanced Intelligence（可选）
    ├─ 实现向量搜索
    ├─ 实现 Claim Graph
    └─ 实现 Research Agent
```

### 12.2 各阶段详细目标

#### M4-A：Source Lifecycle 统一

**目标**：所有来源进入 SourceDocument 体系

**交付物**：
- 新增 `source_items` 表
- 新增 `processing_jobs` 表
- 迁移脚本：`ingest_jobs` → `source_items` + `processing_jobs`
- 补充文本文件的 SourceDocument 持久化

**验证标准**：
- 所有新来源创建 SourceItem
- 所有文本文件创建 SourceDocument
- 现有数据迁移成功

#### M4-B：Research Asset Pipeline

**目标**：Source → Asset → Graph 完整流程

**交付物**：
- 统一 Pipeline 框架（`services/pipeline_orchestrator.py`）
- Claim 提取逻辑（`services/claim_extractor.py`）
- Graph 增量同步（`services/graph_sync_service.py`）
- 更新统一搜索（覆盖 SourceDocument）

**验证标准**：
- 新报告自动生成 Claim
- Graph 自动增量更新
- 统一搜索可查到所有入库内容

#### M4-C：Automation

**目标**：自动发现、自动处理、自动运行

**交付物**：
- DesktopScheduler 实现
- JobConsumer 实现
- 锁定目录扫描逻辑
- 频道自动刷新逻辑
- 用户配置界面

**验证标准**：
- 调度器随 App 启动
- 频道按时刷新
- 锁定目录按时扫描
- 成本预算生效

#### M4-D：Product UX

**目标**：Intake 统一入口，清晰的用户流程

**交付物**：
- `/intake` 统一入口页面
- 重构主导航
- 用户反馈机制（收藏 / 有价值 / 无价值）
- 更新 USER_GUIDE.md

**验证标准**：
- 用户可在 3 步内完成导入
- UI 烟雾测试通过
- 非技术用户可用

#### M4-E：Advanced Intelligence（可选）

**目标**：Claim Graph、向量搜索、Research Agent

**交付物**：
- 向量索引（Chroma 或 SQLite-vss）
- Claim Graph 可视化
- Research Agent 原型

**验证标准**：
- 语义搜索可用
- Claim 冲突检测正确

---

## 13. 风险分析

### 13.1 架构风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 数据迁移失败 | 高 | 中 | 提供回滚脚本，先在测试环境验证，备份现有数据 |
| 模型职责拆分不清晰 | 高 | 低 | 严格边界定义，单元测试覆盖，代码评审 |
| Graph 同步性能问题 | 中 | 中 | 增量更新而非全量重建，异步处理，监控性能 |
| 向量搜索引入复杂度 | 中 | 低 | 阶段 2 再实施，使用成熟方案 |

### 13.2 产品风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 用户不理解新入口 | 高 | 中 | 清晰的引导流程，过渡期保留旧路由 |
| 自动化产生过多内容 | 中 | 中 | 成本预算控制，用户可关闭 |
| Claim 提取不准确 | 中 | 高 | LLM 辅助提取，用户可修正 |

### 13.3 技术风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| Scheduler 与 App 生命周期冲突 | 高 | 中 | 单实例锁，优雅关闭，状态持久化 |
| 多任务并发执行导致资源耗尽 | 高 | 中 | 任务队列限制，优先级调度，资源监控 |
| Embedding 计算成本高 | 中 | 高 | 批量计算，增量更新，使用小模型 |

---

## 14. 与 M3 代码映射关系

### 14.1 需重构的模块

| M3 模块 | M4 改动 | 说明 |
|---------|---------|------|
| `sources/ingest_jobs.py` | 重构 | 拆分为 `SourceItemManager` 和 `ProcessingJobManager` |
| `sources/file_import_preview.py` | 重构 | 增加 Claim 提取逻辑 |
| `services/sync_service.py` | 扩展 | 增加 Graph Sync 触发 |
| `web/routes.py` | 重构 | 收敛为 `/intake` 统一入口 |
| `db/models.py` | 扩展 | 新增 `source_items`、`processing_jobs`、`claims` 表 |

### 14.2 新增模块

| M4 模块 | 功能 |
|---------|------|
| `services/pipeline_orchestrator.py` | 统一处理流水线编排 |
| `services/source_item_manager.py` | SourceItem CRUD |
| `services/processing_job_manager.py` | ProcessingJob CRUD 和状态机 |
| `services/claim_extractor.py` | Claim 提取逻辑 |
| `services/graph_sync_service.py` | Graph 增量同步 |
| `services/desktop_scheduler.py` | 桌面调度器 |
| `services/job_consumer.py` | 任务消费者 |
| `services/intake_orchestrator.py` | Intake 入口编排（已有，需扩展） |

### 14.3 数据迁移映射

```
ingest_jobs (M3)
    ↓
source_items + processing_jobs (M4)

映射规则：
- ingest_jobs.id → source_items.id
- ingest_jobs.source_type → source_items.source_type
- ingest_jobs.source_url → source_items.source_uri
- ingest_jobs.status → source_items.status + processing_jobs.status
- ingest_jobs.preview_data → source_items.metadata
```

---

## 16. ResearchContext 未来演进

### 16.1 概念定义

**ResearchContext**：研究上下文，表示用户当前的研究焦点和背景。

**核心价值**：
- 动态调整分析策略
- 个性化内容评分
- 智能推荐相关内容

### 16.2 演进路线

#### Phase 1：静态 Watchlist（当前已实现）

**实现**：
- 用户手动维护关注列表（公司、主题、人物）
- 用于内容过滤和评分

**数据模型**：
```python
# 已有：99_System/Watchlist.yaml
watchlist:
  companies: ["NVIDIA", "OpenAI", "Tesla"]
  topics: ["AI芯片", "Agent平台", "自动驾驶"]
  persons: ["Sam Altman", "Elon Musk"]
```

#### Phase 2：动态 ResearchContext（M4-E+）

**新增能力**：
- 自动追踪用户阅读历史
- 动态调整关注权重
- 识别短期研究热点

**数据模型**：

```python
class ResearchContext:
    # 基础标识
    id: int
    user_id: int              # 用户 ID（单用户系统为 1）
    
    # 短期焦点（最近 30 天）
    short_term_focus: dict     # {"NVIDIA": 0.9, "OpenAI": 0.7}
    
    # 长期关注（最近 180 天）
    long_term_focus: dict      # {"AI芯片": 0.8, "投资策略": 0.6}
    
    # 阅读统计
    reading_history: list      # 最近阅读的 report_ids
    entity_interactions: dict  # {"NVIDIA": {"clicks": 10, "time_spent": 1200}}
    
    # 时间戳
    updated_at: datetime
    
    def get_focus_score(self, entity_name: str) -> float:
        """获取实体关注度得分（0.0-1.0）"""
        short_weight = 0.7
        long_weight = 0.3
        
        short_score = self.short_term_focus.get(entity_name, 0.0)
        long_score = self.long_term_focus.get(entity_name, 0.0)
        
        return short_weight * short_score + long_weight * long_score
```

**应用场景**：

```python
# 1. 内容评分
def calculate_value_score(source: SourceItem, context: ResearchContext) -> float:
    score = 0.0
    
    # 基础评分（来源优先级）
    score += get_priority_score(source)
    
    # 关注度加权
    for entity in extract_entities(source):
        focus_score = context.get_focus_score(entity)
        score += focus_score * 0.3
    
    return min(1.0, score)

# 2. 推荐排序
def rank_reports(reports: list[Report], context: ResearchContext) -> list[Report]:
    """按用户关注度排序报告"""
    return sorted(
        reports,
        key=lambda r: sum(
            context.get_focus_score(e) for e in get_report_entities(r)
        ),
        reverse=True
    )

# 3. 自动调整分析策略
def get_analysis_params(context: ResearchContext) -> dict:
    """根据研究上下文生成分析参数"""
    top_focus = sorted(
        context.short_term_focus.items(),
        key=lambda x: x[1],
        reverse=True
    )[:5]
    
    return {
        "focus": ", ".join([e for e, _ in top_focus]),
        "depth": "deep" if top_focus[0][1] > 0.8 else "standard"
    }
```

#### Phase 3：研究意图识别（未来）

**新增能力**：
- LLM 分析用户阅读路径
- 推断研究意图（"寻找投资机会" / "跟踪已有持仓"）
- 自动调整推荐策略

**示例**：

```python
class ResearchIntent:
    intent_type: str           # opportunity_search / position_track / topic_explore
    confidence: float
    entities: list[str]
    suggested_actions: list[str]
```

### 16.3 数据流

```
用户行为
    ├─ 阅读报告
    ├─ 点击实体
    ├─ 收藏内容
    └─ 添加反馈
    ↓
行为记录（user_actions 表）
    ↓
更新 ResearchContext
    ├─ 短期焦点（滑动窗口 30 天）
    └─ 长期关注（滑动窗口 180 天）
    ↓
应用场景
    ├─ 内容评分（影响 auto_analyze 决策）
    ├─ 推荐排序（报告列表、搜索结果）
    └─ 分析参数（动态调整 focus/depth）
```

### 16.4 与现有系统集成

**M4 阶段**：
- ⏸️ 仅保留 Watchlist（Phase 1）
- ⏸️ 预留 ResearchContext 表结构
- ⏸️ 不实现行为追踪

**M5+ 阶段**：
- ✅ 实现行为记录（user_actions 表）
- ✅ 实现动态 ResearchContext
- ✅ 集成到内容评分和推荐

### 16.5 隐私和用户控制

**原则**：
- ✅ 所有行为数据仅存储在本地 SQLite
- ✅ 用户可查看、清除自己的行为数据
- ✅ 用户可关闭行为追踪
- ✅ 数据不上传云端

---

## 17. 总结

### 15.1 架构决策总结

1. **三层模型架构**：SourceItem → ProcessingJob → ResearchAsset，职责清晰
2. **统一入口**：`/intake` 作为唯一用户入口，自动识别来源类型
3. **Graph 前置**：作为核心价值，而非附属功能
4. **Desktop Automation**：考虑桌面应用特点，单实例、优雅关闭、状态持久化
5. **Claim 层引入**：投资研究的核心是判断，而非报告
6. **渐进式实施**：M4-A 到 M4-E，每阶段独立可用

### 15.2 与原方案对比

| 维度 | 原方案 | 新方案 | 调整原因 |
|------|--------|--------|----------|
| 架构定位 | 信息源统一处理 | Research Asset Lifecycle | 产品定位升级 |
| 数据模型 | ingest_jobs 承担所有职责 | 拆分为三层模型 | 职责过重，扩展性差 |
| 入口设计 | 两个入口（文件类 + 频道类） | 一个统一入口 `/intake` | 用户认知简化 |
| 自动化 | Server 架构 | Desktop Automation | SignalVault 是桌面应用 |
| Graph 同步 | 阶段 5 | 前置为核心流程 | Graph 是核心价值 |
| Claim 层 | 无 | 新增核心层 | 投资研究重点是判断 |

### 15.3 后续开发建议

1. **优先级**：
   - P0：M4-A（数据模型统一）
   - P1：M4-B（Pipeline + Graph）
   - P2：M4-D（Intake 统一入口）
   - P3：M4-C（Automation）
   - P4：M4-E（Advanced Intelligence）

2. **迭代策略**：
   - 每个阶段独立可测试
   - 不破坏现有功能
   - 渐进式迁移，保留回退路径

3. **验证重点**：
   - 数据迁移完整性
   - Graph 同步正确性
   - 用户流程顺畅性

---

**文档状态**：架构设计冻结（待用户确认）
**下一步**：用户评审 → 修订 → 进入 M4-A 实施