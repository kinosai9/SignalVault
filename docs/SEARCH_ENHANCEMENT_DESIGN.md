# P5-A: Unified Search Enhancement Design

> 状态：Implemented ✅ | P5-A | 2026-07-02
> 前置阅读：`docs/P5_SEARCH_GRAPH_PLAN.md`

## 零、As-Implemented 摘要

**模块：** `db/unified_search.py`（~440 行）

**架构：**
```
CLI: search "NVIDIA" / MCP: unified_search
  → unified_search()
    ├─ FTS5 path (report_search_fts) → Fast, if available
    └─ LIKE fallback (4 tables) → Always available
    → Metadata filters (source_type/entity_type/view_direction/signal_status)
    → Lightweight relevance scoring
    → UnifiedSearchResult[] (22 fields) sorted by relevance_score
```

**覆盖范围：** reports, investment_views, tracking_signals, entities
**FTS5 fallback：** 自动检测 FTS5 可用性，不可用时 graceful fallback 到 LIKE
**Relevance：** 启发式评分 — entity exact match > source_quote > logic_chain > title > report body

**CLI 入口：**
```bash
podcast-research search "NVIDIA" --type investment_view --json --limit 30
```

**MCP 入口：** `unified_search` tool（第 9 个只读 tool）

---

## 一、目标

将当前仅覆盖报告粒度的 FTS5 搜索升级为可跨报告、观点、信号、实体、证据的统一搜索层。
一次查询返回混合结果，每条结果可追溯到来源报告和具体证据位置。

## 二、统一搜索结果 Schema

所有搜索结果归一化为 `UnifiedSearchResult`：

```python
@dataclass
class UnifiedSearchResult:
    result_type: str        # "report" | "investment_view" | "tracking_signal"
                            # | "entity" | "evidence_snippet"
    title: str              # 报告标题 或 观点摘要 或 信号描述
    snippet: str            # 匹配上下文（带高亮标记 <mark>...</mark>）
    relevance_score: float  # 0.0–1.0，跨类型可比
    matched_fields: list[str]  # ["report_markdown", "logic_chain", ...]

    # 来源追溯
    report_id: int
    source_type: str        # "youtube" | "pdf_upload" | "local"
    source_path: str        # video_url 或 pdf source_path
    channel_name: str = ""  # YouTube 频道名

    # 证据定位（至少一个非空）
    timestamp: str = ""     # "00:12:30" 或 "p.12"
    page_number: int | None = None
    source_quote: str = ""  # 原文引用摘要
    content_hash: str = ""  # source_hash (PDF) 或 video_id (YouTube)

    # 关联信息
    target_name: str = ""       # 观点/信号涉及的标的
    view_direction: str = ""    # bullish/bearish/neutral
    entity_type: str = ""       # company/topic/technology

    # 原始数据（用于详情查询）
    _raw: dict | None = None
```

## 三、搜索策略：FTS5 + LIKE + Metadata Filter

### 3.1 三层搜索架构

```
用户查询 "NVIDIA GPU 市场份额"
    │
    ├─→ Layer 1: FTS5 全文搜索（优先）
    │     ├─ report_search_fts（已有，扩展索引列）
    │     ├─ view_search_fts（新增：观点级 FTS5 表）
    │     ├─ signal_search_fts（新增：信号级 FTS5 表）
    │     └─ entity_search_fts（新增：实体级 FTS5 表）
    │
    ├─→ Layer 2: LIKE 模糊匹配（FTS5 不可用时的 fallback）
    │     ├─ reports.report_markdown LIKE '%keyword%'
    │     ├─ investment_views.logic_chain / target_name LIKE '%keyword%'
    │     ├─ tracking_signals.signal / trigger_condition LIKE '%keyword%'
    │     └─ entities.name / normalized_name LIKE '%keyword%'
    │
    └─→ Layer 3: Metadata Filter（叠加在 FTS/LIKE 之上）
          ├─ source_type: youtube / pdf_upload / local / all
          ├─ date_from / date_to: 报告时间范围
          ├─ entity_type: company / topic / technology / person
          ├─ view_direction: bullish / bearish / neutral
          ├─ evidence_type: timestamp / page / quote
          └─ result_types: ["report", "investment_view", ...]
```

### 3.2 FTS5 表扩展

**现有 `report_search_fts`（保留）：**
```
report_id, title, source_type, focus_areas, executive_summary,
report_markdown, targets_text, entities_text, views_text, signals_text,
source_url, video_id
```

**新增 `view_search_fts`：**
```sql
CREATE VIRTUAL TABLE view_search_fts USING fts5(
    view_id UNINDEXED,
    report_id UNINDEXED,
    target_name,
    normalized_target_name,
    logic_chain,
    source_quote,
    evidence_detail,
    risk_warning,
    view_direction,
    evidence_type,       -- "timestamp" | "page" | "quote"
    page_number UNINDEXED,
    timestamp UNINDEXED,
    source_type UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
);
```

**新增 `signal_search_fts`：**
```sql
CREATE VIRTUAL TABLE signal_search_fts USING fts5(
    signal_id UNINDEXED,
    report_id UNINDEXED,
    target_name,
    signal,
    trigger_condition,
    source_quote,
    status UNINDEXED,
    source_type UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
);
```

**新增 `entity_search_fts`：**
```sql
CREATE VIRTUAL TABLE entity_search_fts USING fts5(
    entity_id UNINDEXED,
    name,
    normalized_name,
    entity_type,
    aliases,
    report_ids UNINDEXED,    -- JSON array of report IDs mentioning this entity
    view_count UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
);
```

### 3.3 跨类型 Relevance 评分

```
FTS5 rank → 归一化到 0.0–1.0（同类型内排序）
    × result_type_weight:
        report:            0.8  (高价值但数量少)
        investment_view:   1.0  (核心内容)
        tracking_signal:   0.7
        entity:            0.6
        evidence_snippet:  0.9  (精确匹配原文)

    × match_field_bonus:
        target_name 完全匹配:     +0.2
        source_quote 匹配:         +0.15
        logic_chain 匹配:          +0.1
        report_markdown 模糊匹配:   +0.05
```

### 3.4 LIKE Fallback

当 SQLite 不支持 FTS5 时，fallback 到多表 LIKE 查询：

```python
def _unified_search_like(session, keyword, filters, limit):
    results = []
    seen: set[tuple[str, int]] = set()  # (result_type, id)

    # 1. Reports
    pattern = f"%{keyword}%"
    for r in session.query(Report).filter(
        Report.report_markdown.like(pattern)
    ).limit(limit):
        key = ("report", r.id)
        if key not in seen:
            seen.add(key)
            results.append(_make_result("report", r, keyword))

    # 2. Investment Views
    for v in session.query(InvestmentViewRecord).filter(
        or_(
            InvestmentViewRecord.logic_chain.like(pattern),
            InvestmentViewRecord.target_name.like(pattern),
            InvestmentViewRecord.source_quote.like(pattern),
        )
    ).limit(limit):
        key = ("investment_view", v.id)
        if key not in seen:
            seen.add(key)
            results.append(_make_result("investment_view", v, keyword))

    # 3. Tracking Signals (similar)
    # 4. Entities (similar)

    return sorted(results, key=lambda r: r.relevance_score, reverse=True)[:limit]
```

## 四、统一搜索 API

### 4.1 函数签名

```python
# db/unified_search.py

def unified_search(
    session: Session,
    keyword: str,
    result_types: list[str] | None = None,  # ["report", "investment_view", ...]
    source_type: str = "all",               # "youtube" | "pdf_upload" | "local" | "all"
    entity_type: str | None = None,
    view_direction: str = "all",
    date_from: str | None = None,           # ISO date
    date_to: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[UnifiedSearchResult]:
    ...
```

### 4.2 使用示例

```python
# 搜索 NVIDIA 相关所有内容
results = unified_search(session, "NVIDIA")

# 只搜索投资观点
results = unified_search(session, "GPU", result_types=["investment_view"])

# 搜索 PDF 来源中关于 AI 的观点
results = unified_search(
    session, "AI infrastructure",
    source_type="pdf_upload",
    result_types=["investment_view", "evidence_snippet"],
)

# 搜索最近一个月的 bullish 观点
results = unified_search(
    session, "半导体",
    view_direction="bullish",
    date_from="2026-06-01",
)
```

## 五、CLI 入口

扩展 `reports search` 命令，增加 `--unified` flag：

```bash
# 现有行为：只搜索报告
python -m podcast_research reports search "NVIDIA"

# P5-A 新行为：统一搜索
python -m podcast_research reports search "NVIDIA" --unified
python -m podcast_research reports search "GPU" --unified --types investment_view
python -m podcast_research reports search "AI" --unified --source pdf_upload
python -m podcast_research reports search "半导体" --unified --direction bullish
```

或新增独立命令：

```bash
python -m podcast_research search "NVIDIA"                    # 统一搜索
python -m podcast_research search "NVIDIA" --types view,signal
python -m podcast_research search "AI" --source pdf --limit 30
```

## 六、MCP Tool: `unified_search`

```json
{
    "name": "unified_search",
    "description": "统一搜索知识库：报告、投资观点、跟踪信号、实体、证据片段。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "result_types": {
                "type": "array",
                "items": {"type": "string", "enum": ["report", "investment_view", "tracking_signal", "entity", "evidence_snippet"]},
                "description": "限定结果类型"
            },
            "source_type": {"type": "string", "enum": ["youtube", "pdf_upload", "local", "all"], "default": "all"},
            "entity_type": {"type": "string", "description": "实体类型过滤"},
            "view_direction": {"type": "string", "enum": ["bullish", "bearish", "neutral", "all"], "default": "all"},
            "date_from": {"type": "string", "description": "起始日期 ISO"},
            "date_to": {"type": "string", "description": "结束日期 ISO"},
            "limit": {"type": "integer", "default": 20, "maximum": 100}
        },
        "required": ["query"]
    }
}
```

## 七、模块结构

```
src/podcast_research/db/
    fts.py               ← 扩展：view_search_fts / signal_search_fts / entity_search_fts
    unified_search.py    ← NEW: 统一搜索主入口 + UnifiedSearchResult
    models.py            ← 不变

src/podcast_research/mcp_server/
    tools.py             ← 扩展：新增 unified_search tool
    serializers.py       ← 扩展：serialize_unified_search_result

tests/
    test_unified_search.py ← NEW: ~35 tests
```

## 八、边界情况

| 场景 | 处理 |
|------|------|
| 空关键词 | 返回空列表 + 提示 |
| FTS5 不可用 | 自动 fallback 到 LIKE |
| 搜索结果过多 | 默认 limit=20，max=100 |
| 无匹配 | 返回空列表（不报错） |
| CJK + ASCII 混合 | 已有 tokenize 逻辑复用 |
| PDF evidence 搜索 | FTS 索引 evidence_page + source_path |
| 同一报告多个匹配 | 去重取最高分 |
