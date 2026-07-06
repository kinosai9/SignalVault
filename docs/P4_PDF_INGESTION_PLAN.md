# P4 Plan: PDF Document Ingestion Expansion

> 状态：P4-A ✅ | P4-B ✅ | P4-S 收口 | 2026-07-02
> 前置：P3-A/B/C/D 全部完成（ingest_jobs, vault_lint, review_items, mcp_server）

## 一、定位

P3 解决了"知识库变成可恢复、可审计、可被 Agent 查询的后端"。
P4 解决"PDF 材料怎么进入这个后端"。

投资研究的日常材料中，PDF 占比很高：券商研报、财报、招股书、行业白皮书、会议纪要。
当前系统仅支持 `.txt` / `.md` / `.html` 三种文本格式的文件上传，PDF 被标记为"不支持"。

**P4 不改变分析引擎，不新增 LLM provider，不引入新的知识组织形式。**
P4 只做一件事：**把 PDF 变成可被现有 pipeline 消费的文本**，然后复用 `ingest_jobs → analysis → report → card → export` 全链路。

## 二、为什么 P4 优先

原路线图标注 P4 为"多期观点对比"。但在与真实用户（Kinoc 团队）讨论后，PDF 入库的紧迫性更高：

| 对比维度 | 多期观点对比 | PDF 入库 |
|----------|-------------|----------|
| 用户痛点 | 需要积累足够多期报告才有价值 | 每天都有 PDF 材料无法入库 |
| 复用现有设施 | 需要新的对比分析引擎 | 完全复用 P3 ingest_jobs + analysis pipeline |
| 风险 | 高（新分析逻辑） | 低（适配器模式，隔离在 sources/ 层） |
| 对知识库价值 | 锦上添花 | 补全关键数据源 |

**决策：P4 调整为 PDF 入库优先，多期观点对比推迟到 P5。**

## 三、复用 P3 基础设施

```
PDF 文件
  │
  ▼
sources/pdf_profile.py         ← NEW: 替代 file_profile.py 的 PDF 分支
  │  UploadedPdfProfile (extends existing profile pattern)
  ▼
sources/pdf_extractor.py       ← NEW: 文本提取 + OCR 后备
  │  PdfExtractionResult { pages: [{number, text, method, confidence}] }
  ▼
sources/file_import_preview.py ← EXISTING: build_file_import_preview()
  │  FileImportPreview (复用，PDF extracted_text 作为 content.text)
  ▼
sources/ingest_jobs.py         ← EXISTING: IngestJobManager
  │  source_type="pdf_upload"
  │  job_key = "pdf_upload:{content_hash}"
  ▼
analysis/pipeline.py           ← EXISTING: analyze()
  │  PDF 文本作为 subtitle-less transcript 进入分析
  │  source_info_override 携带 PDF 元数据
  ▼
db/repository.py               ← EXISTING: save_report / save_investment_views
  │  evidence 字段扩展 page_number
  ▼
exporters/obsidian.py          ← EXISTING: export_to_vault()
  │  PDF 报告出现在 01_Reports/，带 source_type="pdf"
```

**关键设计原则：**
- PDF 适配在 `sources/` 层完成，不侵入 `analysis/`、`llm/`、`db/` 核心逻辑
- 复用 `FileImportPreview` 数据结构，PDF 提取结果作为 `content.text` 传入
- `ingest_jobs` 的 `source_type` 新增 `"pdf_upload"`，复用全部 CRUD 方法
- Review Queue 承接低质量提取问题（`item_type="pdf_quality_issue"`）

## 四、分阶段计划

### P4-A：文本型 PDF 提取 ✅ 已完成（2026-07-02）

**实现摘要：**

- 新增 `sources/pdf_extraction.py` — `PdfPage`, `PdfMetadata`, `PdfExtractionResult` 数据类 + `extract_pdf()` 主函数 + `try_ocr_pdf()` OCR skeleton + `build_pdf_review_findings()` review 集成
- 依赖：`pdfplumber>=0.11`（MIT，无系统依赖）
- `ingest_jobs` 扩展：`source_type="pdf_upload"`，复用全部 CRUD + 去重
- `review_items` 扩展：新增 `pdf_needs_ocr`、`pdf_quality_issue`、`pdf_extraction_failed` 三种 item_type
- CLI: `pdf preview <path>` / `pdf extract <path>`（支持 `--json`、`--write-review`、`--output`）
- 47 个专项测试

**验收标准：**
- [x] 文本型 PDF 逐页提取，每页带页码标记（`[Page N]`）
- [x] 提取质量评估：good / degraded / minimal / failed
- [x] 扫描型 PDF 检测（低字符量 → `needs_ocr=True`）
- [x] ingest_jobs `pdf_upload` 创建/去重/列表
- [x] review_items 自动写入低质量问题
- [x] CLI `pdf preview` + `pdf extract` 可用
- [x] ruff clean，47 tests

**尚未完成：**
- 尚未接入完整 LLM analysis pipeline（PDF 文本可通过现有 CLI 手动分析）
- 尚未做表格/图表结构化提取
- OCR 仅 skeleton（graceful degrade），未进入业务闭环

### P4-B：OCR Provider Strategy（设计阶段，未实现）

**设计原则：**

P4 默认优先支持文本型 PDF。扫描型/低文本 PDF 不作为 P4-A 的强制识别范围。
当文本提取质量不足时，系统标记 `needs_ocr=True` 并写入 Review Queue，
但**不默认发起任何 OCR 调用**。

后续 OCR 能力采用**可插拔 OCR Provider 架构**：
- 用户自行选择并配置 OCR 服务商；
- 用户自行提供 API Key；
- 系统不内置任何 OCR 服务商的 API Key 或默认端点；
- 未配置 OCR Provider 时，系统 graceful degrade，不崩溃，不发起网络请求；
- 不强制要求用户安装 tesseract、PaddleOCR 或任何系统级 OCR 引擎。

#### OCR Provider Interface

```python
# sources/ocr_provider.py (P4-B design, not implemented)

from abc import ABC, abstractmethod

class OcrResult:
    """Single OCR result — returned by any OCR provider."""
    text: str
    confidence: float          # 0.0–1.0
    page_number: int           # 1-indexed
    provider: str              # provider name for traceability
    quality: str               # "good" | "partial" | "empty" | "failed"
    duration_ms: int           # round-trip time
    raw_response: dict | None  # provider-specific, for debugging

class OcrPageResult:
    """Per-page OCR result."""
    page_number: int
    pages: list[OcrResult]
    overall_confidence: float

class OcrProvider(ABC):
    """Pluggable OCR provider interface."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def recognize(self, file_path: str, pages: list[int] | None = None,
                  language: str = "auto") -> OcrPageResult: ...

    @abstractmethod
    def health_check(self) -> bool: ...
```

#### Provider Registry

```python
# sources/ocr_registry.py (P4-B design, not implemented)

_registry: dict[str, type[OcrProvider]] = {}

def register_ocr_provider(name: str, provider_cls: type[OcrProvider]) -> None: ...
def get_ocr_provider(name: str) -> OcrProvider: ...
def list_ocr_providers() -> list[str]: ...
def get_configured_provider(config: OcrConfig) -> OcrProvider | None: ...
```

#### Provider Config

```python
# sources/ocr_config.py (P4-B design, not implemented)

@dataclass
class OcrConfig:
    provider: str = ""           # e.g. "tencent", "aliyun", "mock"
    api_key: str = ""            # user-supplied
    api_secret: str = ""         # user-supplied (if needed by provider)
    endpoint: str = ""           # user-supplied or provider default
    max_pages_per_request: int = 50
    max_file_size_bytes: int = 20 * 1024 * 1024  # 20 MB
    language: str = "auto"       # "chi_sim+eng", "auto", etc.
    timeout_seconds: int = 120
    enabled: bool = False        # user must explicitly enable
```

配置来源：`.env` 文件或环境变量。系统**不硬编码任何默认 provider 或 endpoint**。

#### Mock Provider（测试用）

```python
# sources/ocr_mock.py (P4-B design, not implemented)

class MockOcrProvider(OcrProvider):
    """Returns predefined text from in-memory dict. No network, no filesystem.

    Used in tests. Registered as provider="mock".
    """
    name = "mock"

    def __init__(self, responses: dict[int, str] | None = None):
        self._responses = responses or {}

    def recognize(self, file_path, pages=None, language="auto"):
        # Return pre-configured text per page number
        ...
```

#### Candidate External Providers（候选，不在当前阶段实现）

以下为设计阶段的候选 provider 列表，**当前不绑定任何厂商，不内置任何 API Key**：

| Provider | 注册名 | 说明 |
|----------|--------|------|
| Tencent Cloud OCR | `tencent` | 腾讯云通用印刷体识别 |
| Aliyun OCR | `aliyun` | 阿里云 OCR 文档识别 |
| Baidu OCR | `baidu` | 百度云文字识别 |
| Azure Document Intelligence | `azure` | Microsoft Azure 文档智能 |
| Google Document AI | `google` | Google Cloud Document AI |
| Mistral OCR | `mistral` | Mistral AI vision-based OCR |
| OpenAI-compatible Vision | `openai_vision` | GPT-4V / compatible vision models |

每个 provider 的实现职责：接收 PDF 文件路径 → 转换格式（如 PDF → image）→ 调用 API → 归一化为 `OcrPageResult`。

#### OCR 调用安全边界

| 措施 | 说明 |
|------|------|
| **显式启用** | `OCR_ENABLED=true` 在 `.env` 中显式设置才启用 |
| **用户自备 Key** | API Key 由用户配置，不进代码、不进 git |
| **页数限制** | `max_pages_per_request` 防止单次请求过大 |
| **文件大小限制** | `max_file_size_bytes` 防止上传超大文件 |
| **超时控制** | `timeout_seconds` 防止 hang |
| **不默认上传** | 未配置 OCR 时不发起任何外部网络请求 |
| **成本可见** | 日志记录每次 OCR 调用的页数、耗时、provider |

### P4-B：PDF Analysis Pipeline + Page-level Evidence ✅ 已完成（2026-07-02）

**实现摘要：**

- 新增 `sources/pdf_analysis.py` — `build_pdf_source_profile()` + `analyze_pdf()` + `_pages_to_segments()` + `_check_analysis_eligibility()`
- `analysis/models.py` — `Evidence` 增加 `page_number: int | None`
- `db/models.py` — `InvestmentViewRecord` 增加 `evidence_page: int | None`（含 migration）
- `db/repository.py` — `save_investment_views` 保存 `evidence_page`；`get_report_detail` 返回 `evidence_page`
- `sources/review_items.py` — 新增 `pdf_analysis_skipped` / `pdf_evidence_missing` item_type
- `mcp_server/serializers.py` — `serialize_investment_view` 返回 `evidence_page`；`serialize_report_detail` 返回 `source_file`/`source_hash`/`page_count`
- CLI: `pdf analyze <path>`（支持 `--mock`/`--no-mock`、`--focus`、`--write-review`、`--output`）
- 31 个专项测试

**架构：**
```
PDF → extract_pdf() (P4-A)
    → build_pdf_source_profile()
    → _check_analysis_eligibility()
         ├─ quality=minimal/failed → skip, write review
         └─ quality=good/degraded → _pages_to_segments()
              → _run_pipeline() (existing)
                   → report + views + signals (with evidence_page)
```

**验收标准：**
- [x] PDF 文本进入 `_run_pipeline()` 生成报告
- [x] 页码标记 `[Page N]` 保留在 source_info 中
- [x] `evidence_page` 从 pipeline 传递到 investment_views DB 记录
- [x] quality=minimal/failed → 不调用 LLM，写入 review_items
- [x] needs_ocr=True + quality=degraded → 允许分析但标记 degraded
- [x] MCP tools 自动返回 `evidence_page`、`source_file`、`source_hash`
- [x] CLI `pdf analyze` 可用（mock + real LLM）
- [x] ruff clean，31 tests

### P4-C（候选）：Web 上传 + 非技术用户入口

**目标：** Web 上传支持 PDF，让非 CLI 用户也能使用。

**交付（计划，未实现）：**
- Web 上传页面支持 PDF（复用现有文件上传表单）
- PDF preview 页面显示提取质量、元数据、文本预览

### P4-D（候选）：OCR Provider 实现

**目标：** 实现至少一个 OCR Provider（如 Tencent Cloud OCR 或 Mistral OCR）。

### P4-S：收口封板 ✅ 已完成（2026-07-02）

**交付：**
- `docs/P4_ACCEPTANCE_REPORT.md` — 完整验收报告
- 本文档更新 — P4-A/P4-B 完成状态、P4-S 收口
- `docs/PDF_EXTRACTION_DESIGN.md` — as-implemented section
- `README.md` — PDF 入库工作流章节
- `CHANGELOG.md` — P4-S closeout 条目

## 五、CLI 入口设计

```
# PDF 预览（不写入）
python -m signalvault pdf preview <file.pdf>
python -m signalvault pdf preview <file.pdf> --json

# PDF 导入（preview → confirm 两步，复用现有文件导入模式）
python -m signalvault pdf import <file.pdf>
python -m signalvault pdf import <file.pdf> --focus "新能源,AI投资" --depth deep
python -m signalvault pdf import <file.pdf> --no-mock  # 真实 LLM 分析
python -m signalvault pdf import <file.pdf> --ocr       # 强制 OCR
```

CLI 命令组：`pdf`（新增 typer subgroup，与 `ingest`、`review`、`channels` 平级）

## 六、Web 入口设计

复用现有文件上传页面（`/content/new` 或 `/sources/upload`）：

1. 用户选择 PDF 文件上传
2. 后端调用 `pdf_profile` → `pdf_extractor`
3. 返回预览页面：页码数、提取质量、文本预览、元数据
4. 用户确认 → `ingest_jobs.create_job(source_type="pdf_upload")` → 进入分析队列
5. 分析完成 → 报告入库 → 可搜索/可导出

## 七、数据模型扩展

### Evidence 扩展（analysis/models.py）

```python
class Evidence(BaseModel):
    # ... existing fields ...
    page_number: int | None = None  # P4: PDF 页码（1-indexed）
```

### InvestmentViewRecord 扩展（db/models.py）

```python
class InvestmentViewRecord(Base):
    # ... existing columns ...
    evidence_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

### 新增 PdfPage（sources/models.py）

```python
@dataclass
class PdfPage:
    page_number: int           # 1-indexed
    text: str                  # 提取的文本
    char_count: int
    extraction_method: str     # "text" | "ocr"
    confidence: float          # 0.0-1.0
    is_blank: bool
    warnings: list[str]
```

### 新增 PdfExtractionResult（sources/models.py）

```python
@dataclass
class PdfExtractionResult:
    total_pages: int
    pages: list[PdfPage]
    full_text: str             # 拼接全文（带页码标记）
    metadata: dict             # PDF 元数据
    extraction_method: str     # "text" | "ocr" | "mixed"
    overall_confidence: float
    quality: str               # "good" | "degraded" | "minimal"
    warnings: list[str]
```

## 八、Review Queue 集成

| 触发条件 | item_type | severity |
|----------|-----------|----------|
| OCR confidence < 0.7 | `pdf_quality_issue` | warning |
| 某页字符数 < 50（疑似图表页） | `pdf_quality_issue` | info |
| 全文提取字符数 < 2000 | `pdf_quality_issue` | error |
| 扫描型 PDF 无 OCR 环境 | `pdf_needs_ocr` | warning |

与 P3-C 完全复用：`ReviewItemManager.create_item()` 或 `create_from_lint_findings()`。

## 九、测试策略

```
tests/test_pdf_profile.py      — PDF 文件验证、元数据提取、类型检测
tests/test_pdf_extractor.py    — 文本提取、页码标记、质量评估
tests/test_pdf_ocr.py          — OCR 提取、graceful degrade、confidence
tests/test_pdf_ingest.py       — ingest_jobs 集成、去重、状态迁移
tests/test_pdf_pipeline.py     — PDF → analyze → report 端到端
tests/test_pdf_review.py       — Review Queue 集成
tests/test_pdf_cli.py          — CLI 命令
tests/test_pdf_web.py          — Web 上传/预览
```

- 测试用 PDF：程序化生成（reportlab 或 fpdf2），不依赖真实 PDF 文件
- OCR mock：mock `pytesseract.image_to_string()` 返回预设文本
- 复用现有 fixtures：`db_session`, `seeded_db`, `tmp_path`

## 十、不做事项（P4 明确排除）

| 排除项 | 原因 |
|--------|------|
| **PDF 表格结构化提取** | 需要独立设计，表格→JSON→观点映射是独立的 NL2SQL 问题 |
| **PDF 图片/图表理解** | 需要多模态模型，超出当前 LLM 接口 |
| **扫描件批量 OCR 队列** | OCR 为可选 provider，P4 不做异步 OCR 队列 |
| **PDF 注释/高亮提取** | 非投资研究核心场景 |
| **PDF 电子签名验证** | 不在范围 |
| **完整桌面 UI** | Web Console 已覆盖 |
| **复杂知识图谱** | 超出范围 |
| **Deep Research** | 多轮 LLM 编排，P5+ |
| **写入型 MCP tool** | 安全边界保持不变 |
| **新增 LLM provider** | 保持 OpenAI-compatible 单一接口 |
| **自动定时 PDF 抓取** | 依赖外部调度器 |
| **P4-A 做完整 OCR** | OCR 仅 skeleton；扫描型 PDF → needs_ocr + Review Queue |
| **P4-A 做表格结构化** | 不在 P4 范围 |
| **P4-A 做图表理解** | 需要多模态模型 |
| **P4-A 默认上传文件到外部服务** | 安全边界；OCR 需用户显式配置 provider + API Key |
| **内置 OCR API Key** | API Key 由用户配置，不进代码、不进 git |
| **默认发起外部 OCR 请求** | 未配置 OCR provider 时不发起任何网络请求 |
| **强制安装 tesseract/PaddleOCR** | 不要求任何系统级 OCR 依赖 |

## 十一、依赖

```
# pyproject.toml 当前状态（P4-A 已实现）
dependencies = [
    ...
    "pdfplumber>=0.11",       # P4-A: 文本型 PDF 提取（MIT）
    "mcp>=1.0",               # P3-D: MCP Server
]

[project.optional-dependencies]
dev = [
    ...
    "reportlab>=4.0",         # dev: 程序化生成测试 PDF
]
# OCR 相关依赖不在 pyproject.toml 中定义
# 每个 OCR provider 自行声明其依赖（如 tencentcloud-sdk-python）
# 用户按需安装，系统不强制
```

**依赖原则：**
- `pdfplumber` 是唯一的 PDF 相关核心依赖（MIT 许可，无系统依赖）
- 不内置 `pymupdf`（AGPL 许可风险，仅在性能需要时作为可选替换）
- OCR 相关依赖不在项目 `pyproject.toml` 中定义
- 每个 OCR provider 自行管理其 SDK 依赖
- 用户按需安装，系统 graceful degrade

## 十二、风险与缓解

| 风险 | 缓解 |
|------|------|
| PDF 提取文本乱码（编码/CJK 字体） | pdfplumber 自带 CJK 支持；pymupdf 基于 MuPDF 原生处理 |
| 扫描件 OCR 质量不可控 | 明确标注"OCR 提取"；低 confidence 入 review_items |
| 大 PDF（100+ 页）提取慢 | 先 profile 页数，超阈值提示用户；逐页提取可中断 |
| 表格/多栏布局提取错乱 | pdfplumber 支持表格提取（P4 不做结构化，但保留扩展点） |
| OCR 外部服务依赖 | OCR provider 由用户显式配置 + 自备 API Key；未配置时 graceful degrade |
| PDF 文件过大（>50MB） | 复用现有 MAX_UPLOAD_BYTES 限制（可调整为 20MB for PDF） |

## 十三、与 P3 四件套的关系

```
P3-A ingest_jobs    ← P4 复用：pdf_upload source_type，全部 CRUD 方法
P3-B vault_lint     ← P4 独立：不影响 lint rules
P3-C review_items   ← P4 扩展：新增 pdf_quality_issue / pdf_needs_ocr 类型
P3-D mcp_server     ← P4 自动受益：8 个 tool 的 search_reports/get_report 自动支持 PDF 数据
```

P4 不破坏 P3 任何现有功能，仅在 `sources/` 层新增适配器，在 `analysis/models.py` 扩展一个可选字段。
