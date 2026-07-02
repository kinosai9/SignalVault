# P4: PDF Extraction Design

> 状态：P4-A ✅ | P4-B ✅ | P4-S Implemented | 2026-07-02
> 前置阅读：`docs/P4_PDF_INGESTION_PLAN.md`

## 零、As-Implemented 摘要（P4-A + P4-B）

### P4-A：文本提取

```
PDF 文件
  → pdfplumber.open()
  → 逐页 extract_text()
  → PdfPage { page_number, text, char_count, extraction_method, quality }
  → PdfExtractionResult { pages, full_text, metadata, quality, needs_ocr, error_message }
  → build_pdf_review_findings() → ReviewItemManager
  → ingest_jobs (source_type="pdf_upload")
```

实际模块：`sources/pdf_extraction.py`（PdfPage / PdfMetadata / PdfExtractionResult / extract_pdf / try_ocr_pdf / build_pdf_review_findings）

### P4-B：分析闭环

```
PdfExtractionResult
  → build_pdf_source_profile() → 标准化 source_profile dict
  → _check_analysis_eligibility()
       ├─ quality=good/degraded → eligible
       ├─ quality=minimal/failed → skip, write pdf_analysis_skipped
       └─ needs_ocr + minimal → skip, write pdf_needs_ocr
  → _pages_to_segments()
       └─ page.text → SubtitleSegment(segment_id="page_N", start_time="p.{N}")
  → _run_pipeline() (existing, unchanged)
       └─ InvestmentView(evidence__page_number=N)
            → InvestmentViewRecord(evidence_page=N)
```

实际模块：`sources/pdf_analysis.py`（analyze_pdf / build_pdf_source_profile / _pages_to_segments / _check_analysis_eligibility）

### Evidence 传递方式

| 环节 | 页码载体 |
|------|----------|
| PDF Page | `SubtitleSegment.start_time = "p.{N}"` |
| LLM Extraction | `InvestmentView.timestamp_start = "p.{N}"` |
| Pydantic Model | `Evidence.page_number = N` |
| DB Record | `InvestmentViewRecord.evidence_page = N` |
| MCP Response | `views[].evidence_page = N` |

### Quality Gate

| quality | 行为 |
|---------|------|
| good | → analysis |
| degraded | → analysis (marked degraded_ocr_recommended) |
| minimal + needs_ocr | → skip, write review |
| minimal (chars < 200) | → skip, write review |
| failed | → skip, write review |

---

## 一、提取路径架构

```
PDF 文件
    │
    ├─→ [文本型检测] pdfplumber/pymupdf 尝试文本提取
    │       │
    │       ├─ 成功（char_count > 阈值）→ "text" 路径
    │       │       └─ PdfPage(extraction_method="text", confidence=1.0)
    │       │
    │       └─ 失败或字符极少 → 自动降级
    │               │
    │               └─→ [扫描型检测] OCR 后备
    │                       │
    │                       ├─ Tesseract 可用 → "ocr" 路径
    │                       │       └─ PdfPage(extraction_method="ocr", confidence=ocr_conf)
    │                       │
    │                       └─ Tesseract 不可用 → graceful degrade
    │                               └─ PdfExtractionResult(quality="minimal", warnings=[...])
    │
    ▼
PdfExtractionResult { pages, full_text, metadata, quality }
```

**双路径自动决策，用户无感。** 不需要用户选择"文本型还是扫描型"——系统自动检测并走最优路径。

## 二、数据模型

### 2.1 PdfPage

```python
# sources/models.py

@dataclass
class PdfPage:
    """Single page extraction result."""
    page_number: int              # 1-indexed
    text: str                     # 提取的文本内容
    char_count: int               # 字符数（含空格）
    extraction_method: str        # "text" | "ocr"
    confidence: float             # 0.0 ~ 1.0
    is_blank: bool                # 字符数 < 20 视为空白
    has_table_hint: bool          # 检测到表格特征（数字密集、对齐空白）
    warnings: list[str] = field(default_factory=list)
```

### 2.2 PdfExtractionResult

```python
# sources/models.py

@dataclass
class PdfExtractionResult:
    """Full PDF extraction result — all pages + metadata."""
    total_pages: int
    pages: list[PdfPage]
    full_text: str                # 拼接全文，格式：
                                  # [Page 1]
                                  # <page text>
                                  # [Page 2]
                                  # ...
    metadata: PdfMetadata
    extraction_method: str        # "text" | "ocr" | "mixed"
                                  # "mixed" = 部分页 text + 部分页 ocr
    overall_confidence: float     # 所有页 confidence 的均值
    quality: str                  # "good" | "degraded" | "minimal"
    total_chars: int
    warnings: list[str] = field(default_factory=list)
```

### 2.3 PdfMetadata

```python
# sources/models.py

@dataclass
class PdfMetadata:
    """PDF document metadata extracted from file properties."""
    title: str = ""
    author: str = ""
    subject: str = ""
    creator: str = ""
    producer: str = ""
    creation_date: str = ""       # ISO format
    modification_date: str = ""
    page_count: int = 0
    file_size_bytes: int = 0
    is_encrypted: bool = False
    is_scanned: bool = False      # 检测为扫描型 PDF
```

### 2.4 Existing Model Extensions

**Evidence（analysis/models.py）— 增加页码字段：**

```python
class Evidence(BaseModel):
    evidence_type: str = "unsupported_claim"
    evidence_detail: str = ""
    evidence_strength: str = "medium"
    missing_info: str = ""
    page_number: int | None = None  # P4: PDF 页码 (1-indexed)
```

**InvestmentViewRecord（db/models.py）— 增加页码列：**

```python
class InvestmentViewRecord(Base):
    # ... existing 26 columns ...
    evidence_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

迁移时使用 `ALTER TABLE investment_views ADD COLUMN evidence_page INTEGER`（P4 不加新表，只扩展一个可选列）。

## 三、文本提取路径（主路径）

### 3.1 提取器选择

| 库 | 优点 | 缺点 | 推荐 |
|----|------|------|------|
| `pdfplumber` | 精确字符位置、表格支持、CJK 兼容 | 大文件较慢 | **首选** |
| `pymupdf` (fitz) | 极快、内存效率高 | 授权为 AGPL（商用需付费） | 备选 |
| `PyPDF2` | 纯 Python、MIT | 提取质量一般、CJK 支持弱 | 不考虑 |

**决策：首选 `pdfplumber`**（MIT 许可，质量最好）。如果性能瓶颈明显，可增加 pymupdf 作为可选引擎（通过 feature flag 切换）。

### 3.2 逐页提取流程

```python
def extract_text_pdf(file_path: Path) -> PdfExtractionResult:
    import pdfplumber

    pages: list[PdfPage] = []
    warnings: list[str] = []

    with pdfplumber.open(file_path) as pdf:
        metadata = _extract_metadata(pdf)
        total = len(pdf.pages)

        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            char_count = len(text)

            is_blank = char_count < 20
            method = "text"
            confidence = 1.0 if not is_blank else 0.5

            page_warnings = []
            if is_blank:
                page_warnings.append("页面几乎为空")
            if _detect_table_hint(text):
                page_warnings.append("可能包含表格（非结构化）")

            pages.append(PdfPage(
                page_number=i,
                text=text,
                char_count=char_count,
                extraction_method=method,
                confidence=confidence,
                is_blank=is_blank,
                has_table_hint=_detect_table_hint(text),
                warnings=page_warnings,
            ))

    # Build full_text with page markers
    full_text = _build_full_text(pages)

    # Quality assessment
    total_chars = sum(p.char_count for p in pages)
    non_blank = [p for p in pages if not p.is_blank]
    avg_chars_per_page = total_chars / max(len(pages), 1)

    if total_chars < 500:
        quality = "minimal"
        warnings.append("全文提取字符数不足 500，可能为扫描件或图片 PDF。建议使用 OCR。")
    elif avg_chars_per_page < 100:
        quality = "degraded"
        warnings.append("每页平均字符数偏低，部分页面可能为图表。")
    elif len(non_blank) < len(pages) * 0.3:
        quality = "degraded"
        warnings.append("超过 70% 页面为空或字符极少。")
    else:
        quality = "good"

    return PdfExtractionResult(
        total_pages=total,
        pages=pages,
        full_text=full_text,
        metadata=metadata,
        extraction_method="text",
        overall_confidence=1.0 if quality == "good" else 0.6,
        quality=quality,
        total_chars=total_chars,
        warnings=warnings,
    )
```

### 3.3 full_text 格式

```
[Page 1]
<page 1 text content>

[Page 2]
<page 2 text content>

...
```

页码标记使 LLM 可以在 extraction 中引用页码。`InvestmentView.source_quote` 可以直接引用带页码的文本片段。

## 四、OCR 路径

### 4.1 当前实现（P4-A）：Skeleton + Graceful Degrade

P4-A 的 OCR 仅为 skeleton。`try_ocr_pdf()` 函数已存在（`sources/pdf_extraction.py`），行为如下：

```python
def try_ocr_pdf(file_path: str | Path) -> PdfExtractionResult:
    """Attempt OCR on a scanned PDF. Graceful degrade if deps unavailable.

    P4-A behavior:
    - If pytesseract + pdf2image ARE installed AND tesseract IS on PATH:
      → performs OCR and returns results
    - If any dependency is missing:
      → returns PdfExtractionResult with quality="minimal", needs_ocr=True,
        and a descriptive error_message — NEVER crashes
    - If tesseract not on PATH:
      → returns PdfExtractionResult with quality="minimal" + install hint
    """
```

**当前已实现的关键行为：**

| 场景 | 行为 |
|------|------|
| OCR 依赖不可用 | `quality="minimal"`, `needs_ocr=True`, `error_message` 含安装提示 |
| Tesseract 不在 PATH | `quality="minimal"`, `needs_ocr=True` |
| PDF 转图片失败 | `quality="failed"`, `error_message` 含错误详情 |
| 文本提取质量低 | `extract_pdf()` 自动设置 `needs_ocr=True` |
| Review 集成 | `build_pdf_review_findings()` 产生 `pdf_needs_ocr` / `pdf_quality_issue` / `pdf_extraction_failed` |

**当前不做的：**
- 不自动发起任何外部 OCR API 调用
- 不内置任何 OCR 服务商 API Key
- 不要求用户安装 tesseract 或任何系统级 OCR 引擎
- 不将用户文件上传到外部服务

### 4.2 后续设计（P4-B）：Pluggable OCR Provider

OCR 采用可插拔 provider 架构。用户自行选择服务商、自行配置 API Key、显式启用。

#### OCRProvider Interface

```python
# sources/ocr_provider.py (P4-B, not implemented)

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class OcrResult:
    """Normalized OCR output from any provider."""
    text: str
    confidence: float           # 0.0–1.0
    page_number: int            # 1-indexed
    provider: str               # provider name for traceability
    quality: str                # "good" | "partial" | "empty" | "failed"
    duration_ms: int = 0
    raw_response: dict | None = field(default=None, repr=False)


@dataclass
class OcrPageResult:
    """Per-page OCR result — returned by OcrProvider.recognize()."""
    page_number: int
    pages: list[OcrResult]
    overall_confidence: float


class OcrProvider(ABC):
    """Pluggable OCR provider interface.

    Each implementation adapts a specific OCR service (Tencent, Aliyun,
    Azure, etc.) to the common OcrPageResult format.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique provider name, e.g. 'tencent', 'aliyun', 'mock'."""
        ...

    @abstractmethod
    def recognize(
        self,
        file_path: str,
        pages: list[int] | None = None,
        language: str = "auto",
    ) -> OcrPageResult:
        """Recognize text from a PDF file. May raise on network/auth errors."""
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the provider is configured and reachable."""
        ...
```

#### OcrConfig

```python
# sources/ocr_config.py (P4-B, not implemented)

@dataclass
class OcrConfig:
    provider: str = ""            # e.g. "tencent", "aliyun", "mock"
    api_key: str = ""             # user-supplied, NEVER hardcoded
    api_secret: str = ""          # user-supplied if needed
    endpoint: str = ""            # user-supplied or provider default
    max_pages_per_request: int = 50
    max_file_size_bytes: int = 20 * 1024 * 1024
    language: str = "auto"
    timeout_seconds: int = 120
    enabled: bool = False         # user must explicitly enable

    @classmethod
    def from_env(cls) -> "OcrConfig":
        """Load OCR config from environment variables."""
        ...
```

环境变量映射（`.env` 文件）：

```bash
# OCR configuration (all optional — OCR disabled if not set)
OCR_ENABLED=false               # explicit opt-in
OCR_PROVIDER=                   # tencent | aliyun | azure | ...
OCR_API_KEY=                    # user-supplied
OCR_API_SECRET=                 # user-supplied (if needed)
OCR_ENDPOINT=                   # user-supplied (if non-default)
OCR_MAX_PAGES=50
OCR_MAX_FILE_SIZE_MB=20
OCR_TIMEOUT_SECONDS=120
```

#### Provider Registry

```python
# sources/ocr_registry.py (P4-B, not implemented)

_registry: dict[str, type[OcrProvider]] = {}

def register_ocr_provider(name: str, provider_cls: type[OcrProvider]) -> None:
    """Register an OCR provider implementation."""
    ...

def get_ocr_provider(name: str) -> OcrProvider:
    """Get a provider instance by name."""
    ...

def get_configured_provider(config: OcrConfig) -> OcrProvider | None:
    """Create and return the configured OCR provider, or None if disabled."""
    if not config.enabled or not config.provider:
        return None
    provider_cls = _registry.get(config.provider)
    if provider_cls is None:
        return None
    return provider_cls(config)
```

#### Mock Provider（测试用）

```python
# sources/ocr_mock.py (P4-B, not implemented)

class MockOcrProvider(OcrProvider):
    """Returns predefined text. No network, no filesystem beyond reading PDF.

    Registered as provider="mock". Used in pytest.
    """
    name = "mock"

    def __init__(self, config: OcrConfig):
        self._config = config
        self._responses: dict[int, str] = {}

    def set_page_text(self, page_number: int, text: str) -> None:
        self._responses[page_number] = text

    def recognize(self, file_path, pages=None, language="auto"):
        # Return pre-configured text mapped by page number
        ...
```

#### Candidate External Providers（候选，不在 P4-A 实现）

以下 provider 仅作为设计参考，**当前不实现、不绑定、不内置 Key**：

| Provider | 注册名 | SDK / API |
|----------|--------|-----------|
| Tencent Cloud OCR | `tencent` | `tencentcloud-sdk-python` |
| Aliyun OCR | `aliyun` | `alibabacloud-ocr-api` |
| Baidu OCR | `baidu` | `baidu-aip` |
| Azure Document Intelligence | `azure` | `azure-ai-documentintelligence` |
| Google Document AI | `google` | `google-cloud-documentai` |
| Mistral OCR | `mistral` | Mistral API (vision) |
| OpenAI-compatible Vision | `openai_vision` | OpenAI-compatible `/chat/completions` |

#### OCR 结果必须进入同一 PdfExtractionResult

OCR 输出不另起一套 pipeline。无论 OCR provider 是什么，结果必须归一化到 `PdfExtractionResult`：

```python
def ocr_to_extraction_result(ocr_result: OcrPageResult, file_path: str) -> PdfExtractionResult:
    """Convert OcrPageResult to the standard PdfExtractionResult.

    This ensures all downstream code (ingest_jobs, review_items, analysis
    pipeline) works identically regardless of OCR provider.
    """
    pages = []
    for r in ocr_result.pages:
        pages.append(PdfPage(
            page_number=r.page_number,
            text=r.text,
            char_count=len(r.text),
            extraction_method="ocr",
            # quality from OCR confidence
            quality="good" if r.confidence >= 0.8
                    else "partial" if r.confidence >= 0.5
                    else "failed",
        ))
    # ... build PdfExtractionResult ...
```

#### OCR 安全边界

| 措施 | 说明 |
|------|------|
| **显式启用** | `OCR_ENABLED=true` 才启用任何 OCR 调用 |
| **用户自备 Key** | API Key 不进代码、不进 git、不进日志 |
| **页数限制** | `max_pages_per_request` 可配置 |
| **文件大小限制** | `max_file_size_bytes` 可配置 |
| **超时控制** | `timeout_seconds` 可配置 |
| **可关闭** | `OCR_ENABLED=false` 时 `get_configured_provider()` 返回 None |
| **低置信度入 review** | OCR confidence < 阈值 → `pdf_quality_issue` |
| **成本可见** | 日志记录每次调用的 provider、页数、耗时 |
| **不默认上传** | 未配置 OCR 时不发起任何外部网络请求 |

### 4.3 Graceful Degrade（已实现）

P4-A 已实现完整的 graceful degrade 链：

```
extract_pdf() → quality="minimal" + needs_ocr=True
    │
    ├─ try_ocr_pdf()
    │     ├─ pytesseract 不可用 → quality="minimal" + error_message
    │     ├─ tesseract 不在 PATH → quality="minimal" + error_message
    │     └─ pdf2image 失败 → quality="failed" + error_message
    │
    └─ build_pdf_review_findings()
          ├─ quality="failed" → pdf_extraction_failed (error)
          ├─ needs_ocr=True → pdf_needs_ocr (warning)
          └─ 低质量页 → pdf_quality_issue (warning/info)
```

每个失败点都返回结构化的 `PdfExtractionResult`（不是抛异常），上层调用者可以正常处理。

## 五、ingest_jobs 复用

### 5.1 新的 source_type

```python
# sources/ingest_jobs.py

# 扩展 _make_job_key():
if source_type == "pdf_upload":
    return f"pdf_upload:{source_hash}"
```

### 5.2 复用现有流程

```
pdf preview → IngestJobManager.create_job(
    source_type="pdf_upload",
    source_hash=content_hash,
    source_name=pdf_title,
    preview_data=json.dumps(extraction_result),
    ...
)
→ status = "pending_preview"
→ 用户确认 confirm_job(preview_id, action="confirm_archive")
→ status = "confirmed_archive"
→ 触发 analysis pipeline
```

不新增 ingest_jobs 状态，不新增表，不修改 IngestJobManager 核心逻辑。
唯一变更：`_make_job_key()` 增加 `pdf_upload` 分支。

### 5.3 去重

同一 PDF（content_hash 相同）的重复上传 → 部分唯一索引 `uq_ingest_jobs_key_status` 阻止重复 `pending_preview`。

## 六、Analysis Pipeline 接入

### 6.1 PDF 文本 → LLM 分析

```python
# PDF 文本作为 "transcript-less" 输入进入分析
# 使用 analyze() 路径（不是 analyze_from_transcript()）

from podcast_research.analysis.pipeline import analyze

# 将 PdfExtractionResult.full_text 写入临时 .txt 文件
# 或直接传给 LLM（如果文本长度在 token 限制内）
# 长 PDF（>50K 字符）使用现有 chunking 机制
```

### 6.2 source_info_override

```python
source_info_override = {
    "source_type": "pdf",
    "pdf_filename": original_filename,
    "pdf_title": metadata.title,
    "pdf_author": metadata.author,
    "pdf_pages": extraction_result.total_pages,
    "pdf_extraction_method": extraction_result.extraction_method,
    "pdf_quality": extraction_result.quality,
}
```

这些字段出现在报告的 frontmatter 中，提供完整的 PDF 来源追溯。

### 6.3 页码注入

在 PDF 文本传入 LLM 前，每段文本前插入页码标记：

```
[Page 12]
在 2025 年 Q4，公司营收同比增长 35%，主要受益于 AI 基础设施投入增加...

[Page 13]
毛利率从 58% 提升至 62%，管理层在电话会议中指出...
```

LLM 在 `source_quote` 中引用时，自然包含页码上下文。Prompt 中增加指令：

```
当引用原文时，如果文本中包含 [Page N] 标记，请在 source_quote 中保留页码信息。
```

## 七、Review Queue 集成

### 7.1 新增 item_type

```python
# sources/review_items.py — VALID_ITEM_TYPES 扩展

VALID_ITEM_TYPES = frozenset({
    # ... existing 8 types ...
    "pdf_quality_issue",    # P4: PDF 提取质量问题
    "pdf_needs_ocr",        # P4: 扫描件需要 OCR
})
```

### 7.2 自动入队规则

```python
def check_pdf_quality(extraction: PdfExtractionResult) -> list[dict]:
    """Generate review items for PDF quality issues."""
    findings = []

    # 全文字符数过低
    if extraction.total_chars < 2000:
        findings.append({
            "rule": "pdf_quality_issue",
            "severity": "error",
            "file_path": extraction.metadata.title or "unknown.pdf",
            "message": f"PDF 全文字符数仅 {extraction.total_chars}，可能无法有效分析。",
            "detail": f"提取方式: {extraction.extraction_method}, 页数: {extraction.total_pages}",
        })

    # OCR 置信度低的页面
    for page in extraction.pages:
        if page.extraction_method == "ocr" and page.confidence < 0.7:
            findings.append({
                "rule": "pdf_quality_issue",
                "severity": "warning",
                "file_path": f"{extraction.metadata.title or 'pdf'}:p.{page.page_number}",
                "message": f"第 {page.page_number} 页 OCR 置信度仅 {page.confidence:.0%}。",
                "detail": f"字符数: {page.char_count}",
            })

    # 需要 OCR 但不可用
    if extraction.extraction_method == "ocr" and extraction.quality == "minimal":
        findings.append({
            "rule": "pdf_needs_ocr",
            "severity": "warning",
            "file_path": extraction.metadata.title or "unknown.pdf",
            "message": "PDF 需要 OCR 但 OCR 环境不可用。",
            "detail": extraction.warnings[0] if extraction.warnings else "",
        })

    return findings
```

入队方式：`ReviewItemManager.create_from_lint_findings(findings)`（复用 P3-C 已有方法）。

## 八、模块结构

```
src/podcast_research/sources/
    models.py               ← 扩展：PdfPage, PdfExtractionResult, PdfMetadata
    pdf_profile.py          ← NEW: PDF 文件验证、元数据提取、类型检测
    pdf_extractor.py        ← NEW: 文本提取入口 + 质量评估
    pdf_ocr.py              ← NEW: OCR 引擎封装（P4-B）
    file_profile.py         ← 扩展：ALLOWED_EXTENSIONS 增加 .pdf
    file_content_extractor.py ← 扩展：增加 _extract_pdf() 分支
    ingest_jobs.py          ← 扩展：_make_job_key() 增加 pdf_upload
    review_items.py         ← 扩展：VALID_ITEM_TYPES 增加 2 个 PDF 类型

src/podcast_research/analysis/
    models.py               ← 扩展：Evidence.page_number

src/podcast_research/db/
    models.py               ← 扩展：InvestmentViewRecord.evidence_page
    session.py              ← 扩展：_migrate_investment_views 增加 evidence_page 列

src/podcast_research/
    cli.py                  ← 扩展：新增 pdf 命令组

tests/
    test_pdf_profile.py     ← NEW
    test_pdf_extractor.py   ← NEW
    test_pdf_ocr.py         ← NEW
    test_pdf_ingest.py      ← NEW
    test_pdf_pipeline.py    ← NEW
    test_pdf_cli.py         ← NEW
```

## 九、边界情况处理

| 场景 | 处理方式 |
|------|----------|
| **加密 PDF** | `pdfplumber` 检测加密 → `PdfExtractionResult(quality="minimal", warnings=["PDF 已加密"])` → 不崩 |
| **空 PDF（0 页）** | `PdfExtractionResult(total_pages=0, quality="minimal")` |
| **超大 PDF（200+ 页）** | Profile 阶段检测 → 警告"文件较大，提取可能需要较长时间" |
| **混合 PDF（部分文本 + 部分图片）** | 逐页决策：文本页走 text，空白页尝试 OCR → `extraction_method="mixed"` |
| **CJK 字符乱码** | pdfplumber 原生支持 CJK；OCR 指定 `chi_sim+eng` 语言包 |
| **PDF 中包含嵌入字体但无 Unicode 映射** | pdfplumber 的 `extract_text()` 会返回乱码 → 降级到 OCR |
| **文件名含特殊字符** | 复用 `sanitize_filename()` |
| **PDF > 20MB** | `MAX_UPLOAD_BYTES` 调整为 20MB（PDF 上限） |
| **并发上传同一 PDF** | ingest_jobs partial unique index 阻止重复 pending_preview |

## 十、质量分级决策树

```
total_chars >= 5000 AND avg_chars_per_page >= 200 AND blank_ratio < 30%
    → quality = "good"

total_chars >= 2000 AND avg_chars_per_page >= 100
    → quality = "degraded"

total_chars >= 500
    → quality = "degraded"（弱）
    入 review_items: pdf_quality_issue (warning)

total_chars < 500
    → quality = "minimal"
    入 review_items: pdf_needs_ocr (warning)
    如果 text 路径提取失败 → 自动尝试 OCR

OCR 路径:
    avg_confidence >= 0.8 → quality = "degraded"（OCR 天然降一级）
    avg_confidence >= 0.5 → quality = "degraded"
    入 review_items: pdf_quality_issue (warning)
    avg_confidence < 0.5 → quality = "minimal"
    入 review_items: pdf_quality_issue (error)
```

## 十一、CLI 输出示例

```
$ python -m podcast_research pdf preview research_report.pdf

📄 PDF Preview: research_report.pdf
  Pages: 24
  Extraction method: text
  Quality: good
  Total characters: 48,230
  Average chars/page: 2,009
  Blank pages: 2 (pages 1, 24)

  Metadata:
    Title: 2025 Q4 AI Infrastructure Report
    Author: Research Dept
    Created: 2025-12-15

  Page samples:
    [Page 3] (2,140 chars)
    In Q4 2025, global AI infrastructure spending reached $78B...

    [Page 5] (1,980 chars)
    NVIDIA maintains 82% market share in data center GPUs...

  Warnings: none

  Actions:
    [confirm_archive] Import and analyze
    [skip] Skip
```

## 十二、与现有文件导入的关系

PDF 导入复用现有文件导入的两步流程（preview → confirm），但有两个关键区别：

1. **提取器不同：** `.txt/.md/.html` 走 `extract_text_from_uploaded_file()`，`.pdf` 走 `extract_text_pdf()`
2. **页码追踪：** PDF 保留页码信息，文本文件没有这个维度
3. **OCR 后备：** PDF 有 OCR 后备路径，文本文件不需要

在 `file_content_extractor.py` 中的集成方式：

```python
def extract_text_from_uploaded_file(file_path, original_filename, content_hash, detected_encoding):
    ext = Path(original_filename).suffix.lower()

    if ext == ".pdf":
        return _extract_pdf(file_path, original_filename, content_hash)
    # ... existing logic for .txt, .md, .html ...
```

`_extract_pdf()` 返回的 `ExtractedFileContent` 中：
- `text` = `PdfExtractionResult.full_text`
- `title` = `PdfMetadata.title` or filename
- `parse_quality` = `PdfExtractionResult.quality`
- `quality_warnings` = `PdfExtractionResult.warnings`
- `blocks_count` = 非空白页数
