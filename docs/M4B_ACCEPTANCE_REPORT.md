# M4-B: Research Asset Pipeline 验收报告

> 日期：2026-08-03
> 基线：M4-A Source Lifecycle Unified 完成
> 状态：✅ 交付完成

---

## 1. 目标概述

M4-B 阶段目标：实现 **Source → Asset → Graph** 完整研究资产生命周期流水线。

依据 `docs/M4_ARCHITECTURE_FREEZE.md` 第 12.2 节，交付四个核心模块：

| # | 模块 | 文件 | 状态 |
|---|------|------|------|
| M4-B.1 | Pipeline Orchestrator | `services/pipeline_orchestrator.py` | ✅ |
| M4-B.2 | Claim Extractor | `services/claim_extractor.py` | ✅ |
| M4-B.3 | Graph Sync Service | `services/graph_sync_service.py` | ✅ |
| M4-B.4 | Unified Search 扩展 | `db/unified_search.py` (update) | ✅ |

---

## 2. 交付物详情

### 2.1 Pipeline Orchestrator (`services/pipeline_orchestrator.py`)

**核心能力**：
- 四阶段流水线：Extract → Analyze → Claim Extract → Graph Sync
- SourceItem 驱动的统一编排：任何 `source_type` 进入同一管道
- ProcessingJob 追踪：每个阶段创建/更新 ProcessingJob（成本统计、状态管理）
- 优雅降级：单阶段失败不阻断下游（如 Claim 提取失败不影响 Graph 同步）
- 来源类型路由：YouTube → `analyze_youtube_url()`，PDF → `analyze_pdf()`，文本文件 → 跳过分析

**数据类**：
- `StageResult`：单阶段结果（status, job_id, result_ref, duration, tokens）
- `PipelineResult`：全管道结果（stages 列表, claim_count, graph_synced, 统计属性）
- `PipelineOrchestrator`：编排器（`run()` + `run_for_source()` 两入口）

**跳过策略** (`_STAGE_SKIP_MAP`)：
| source_type | 跳过阶段 | 原因 |
|-------------|----------|------|
| youtube_video | extract | 字幕提取在 adapter 层 |
| youtube_channel | extract, analyze | 频道不直接分析 |
| pdf_document | extract | 提取在 pdf_analysis 内部 |
| web_page | analyze, claim_extract, graph_sync | 纯文本暂不分析 |
| text_file | analyze, claim_extract, graph_sync | 纯文本暂不分析 |

---

### 2.2 Claim Extractor (`services/claim_extractor.py`)

**核心能力**：
- 从 InvestmentView 提取 Claim：看多/看空观点 → `"{target} {方向} — {逻辑}"` 格式 claim
- 从 TrackingSignal 提取 Claim：`"{target} — {信号描述}"` 格式 claim
- 确定性提取（无需 LLM）：直接从结构化数据映射
- 置信度映射：speaker_confidence (high/medium/low) → 数值 (0.85/0.65/0.40)
- 幂等性：同一 report+view 不重复提取
- 批量提取：`extract_all()` 处理所有现有报告

**Claim 数据模型**（已在 M4-A 迁移中建表）：
```python
class Claim:
    claim_text: str         # 判断内容
    claim_type: str         # fact / prediction / opinion
    confidence: float       # 0.0-1.0
    confidence_source: str  # speaker / llm / system
    source_report_id: int   # 来源报告
    source_view_id: int     # 来源观点（可选）
    source_quote: str       # 原文引用
    timestamp: str          # 时间戳
    evidence_page: int      # PDF 页码
```

---

### 2.3 Graph Sync Service (`services/graph_sync_service.py`)

**核心能力**：
- 增量同步：`sync_report_to_graph(report_id)` 只处理单个报告
- 6 阶段节点/边构建：
  1. Report 节点
  2. View 节点 + Entity 节点 + mentioned_in/derived_from 边
  3. Signal 节点 + derived_from/tracks 边
  4. Evidence 节点 + cites 边
  5. Claim 节点 + derived_from 边 + 推断边 (supports/contradicts)
  6. SourceDocument 链接边
- 边分类：确定性 (confidence=1.0) vs 推断性 (confidence < 1.0)
- 幂等：复用 `knowledge_graph._upsert_node/edge` 的 upsert 语义

**推断边启发式**：
| 条件 | 边类型 | 置信度 |
|------|--------|--------|
| 相同实体 + 相同方向 | supports | 0.7 |
| 相同实体 + 相反方向 | contradicts | 0.6 |
| 非预测性 claim + 共享实体 | related_to | 0.5 |

---

### 2.4 Unified Search 扩展

**变更**（`db/unified_search.py`）：
- 新增 `claim` 作为可搜索类型（LIKE fallback 路径）
- 默认搜索类型集合扩展为 `{report, investment_view, tracking_signal, entity, source_document, claim}`
- Claim 搜索结果包含 `claim_type`, `confidence`, `confidence_source` 等元数据

---

## 3. 测试覆盖

| 测试类 | 测试数 | 覆盖内容 |
|--------|--------|---------|
| TestPipelineOrchestrator | 7 | 创建运行、跳过策略、状态更新、auto flags、dataclass、不存在处理、run_for_source |
| TestClaimExtractor | 9 | 从 view 提取、从 signal 提取、幂等性、中性非逻辑 view 跳过、置信度映射、按 report 查询、按实体查询、批量提取、便捷函数 |
| TestGraphSyncService | 8 | 节点创建、幂等性、确定性边、signals 同步、边类型、批量同步、edge_exists 辅助、不存在 report |
| TestUnifiedSearchM4B | 4 | claims 搜索、source_document 搜索、默认类型扩展、序列化 |
| TestM4BIntegration | 2 | 全链路集成、置信度差异验证 |
| **合计** | **30** | |

---

## 4. 验证结果

```
M4-B 专项测试:   30 passed
M4-A 回归测试:   12 passed (SourceItem) + 15 passed (ProcessingJob)
知识图谱回归:     27 passed (knowledge_graph, 无破坏)
统一搜索回归:     35 passed (unified_search, 无破坏)
ruff lint:        clean (0 errors)
```

**关键验证点**：
- ✅ Claim 提取幂等：重复提取不产生重复记录
- ✅ Claim 置信度差异：speaker_confidence high→0.85, low→0.40
- ✅ Graph 增量同步幂等：重复同步零新增
- ✅ 全链路：SourceItem → Pipeline → Claim → Graph → Search 端到端可用
- ✅ 统一搜索扩展：默认搜索包含 claim + source_document

---

## 5. 架构边界

**M4-B 不做的**：
- ❌ 向量搜索（M4-E 预留）
- ❌ Claim 验证机制（时间证伪、事实证伪 — M4-E）
- ❌ Claim 置信度动态更新（M4-E）
- ❌ 自动化调度执行（M4-C）
- ❌ Intake 统一入口 UI（M4-D）
- ❌ Claim Graph 可视化（M4-E）

---

## 6. 与 M4 架构文档对照

| 架构文档要求 | 实现 | 偏差说明 |
|-------------|------|---------|
| Pipeline 框架 | `PipelineOrchestrator` 四阶段编排 | ✅ 一致 |
| Claim 提取 | `ClaimExtractor` 确定性提取 | ✅ 一致 |
| Graph 增量同步 | `graph_sync_service.py` 按 report 增量 | ✅ 一致 |
| 统一搜索扩展 | 新增 claim + source_document 搜索 | ✅ 一致 |
| Claim 验证 | 未实现 | ⏸️ M4-E 范围 |

---

## 7. 下一步

- **M4-C Automation**：DesktopScheduler + JobConsumer + 锁定目录扫描 + 频道自动刷新
- **M4-D Product UX**：/intake 统一入口 + 主线导航 + 用户反馈
- **M4-E Advanced Intelligence**：向量搜索 + Claim Graph 可视化 + Research Agent
