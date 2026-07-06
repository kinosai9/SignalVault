# P4 验收报告

> 日期：2026-07-02 | 状态：P4-S 收口完成

## 一、P4 目标与定位

把 PDF 材料接入 signalvault 的知识库后端。
P3 解决了"知识库变成可恢复、可审计、可被 Agent 查询的后端"，P4 解决"PDF 材料怎么进入这个后端"。

P4 不改变分析引擎，不新增 LLM provider，不引入新的知识组织形式。
P4 只做一件事：**把 PDF 变成可被现有 pipeline 消费的文本**，然后复用 `ingest_jobs → analysis → report → card → export` 全链路。

## 二、子阶段交付

### P4-A：PDF 文本提取 ✅

| 维度 | 内容 |
|------|------|
| **新增文件** | `sources/pdf_extraction.py`（~340 行） |
| **数据类** | `PdfPage`, `PdfMetadata`, `PdfExtractionResult` |
| **核心函数** | `extract_pdf()` (pdfplumber 逐页提取)、`try_ocr_pdf()` (OCR skeleton)、`build_pdf_review_findings()` (review 集成) |
| **依赖** | `pdfplumber>=0.11`（MIT，无系统依赖） |
| **ingest_jobs** | `source_type="pdf_upload"`，复用全部 CRUD + 去重 |
| **review_items** | `pdf_needs_ocr`, `pdf_quality_issue`, `pdf_extraction_failed` |
| **CLI** | `pdf preview <path>` / `pdf extract <path>`（`--json`/`--write-review`/`--output`） |
| **测试** | 47 tests |

### P4-B：PDF 分析闭环 + 页码级 Evidence ✅

| 维度 | 内容 |
|------|------|
| **新增文件** | `sources/pdf_analysis.py`（~260 行） |
| **核心函数** | `analyze_pdf()` (主入口)、`build_pdf_source_profile()`、`_pages_to_segments()`、`_check_analysis_eligibility()` |
| **DB 扩展** | `InvestmentViewRecord.evidence_page: int | None`（含 migration） |
| **Model 扩展** | `Evidence.page_number: int | None` |
| **review_items** | `pdf_analysis_skipped`, `pdf_evidence_missing` |
| **MCP** | `serialize_investment_view` → `evidence_page`；`serialize_report_detail` → `source_file`/`source_hash`/`page_count` |
| **CLI** | `pdf analyze <path>`（`--mock`/`--no-mock`/`--focus`/`--write-review`） |
| **测试** | 31 tests |

## 三、CLI 命令清单（P4 新增 3 条）

```bash
# PDF 预览（不写入 DB）
python -m signalvault pdf preview <file.pdf>
python -m signalvault pdf preview <file.pdf> --json
python -m signalvault pdf preview <file.pdf> --write-review

# PDF 文本提取
python -m signalvault pdf extract <file.pdf>
python -m signalvault pdf extract <file.pdf> --json
python -m signalvault pdf extract <file.pdf> -o output.txt

# PDF 分析（生成投资研究报告）
python -m signalvault pdf analyze <file.pdf>                     # mock 分析
python -m signalvault pdf analyze <file.pdf> --no-mock           # 真实 LLM
python -m signalvault pdf analyze <file.pdf> --focus "AI投资"
python -m signalvault pdf analyze <file.pdf> --write-review
```

## 四、数据模型变化

### P4 新增 source_type

| source_type | ingest_jobs job_key | 用途 |
|-------------|---------------------|------|
| `pdf_upload` | `pdf_upload:{content_hash}` | PDF 文件导入任务 |

### P4 新增 ReviewItem item_type（5 个）

| item_type | 阶段 | 触发条件 |
|-----------|------|----------|
| `pdf_needs_ocr` | P4-A | 文本提取字符数极低，可能需要 OCR |
| `pdf_quality_issue` | P4-A | 部分页文本质量差（空白/partial/failed） |
| `pdf_extraction_failed` | P4-A | PDF 加密/损坏/无法打开 |
| `pdf_analysis_skipped` | P4-B | quality=minimal/failed，不进入 LLM 分析 |
| `pdf_evidence_missing` | P4-B | 预留：观点缺少页码追溯 |

### P4 新增 DB 列

| 表 | 列 | 类型 | 用途 |
|----|-----|------|------|
| `investment_views` | `evidence_page` | INTEGER, nullable | PDF 页码追溯 |

### P4 新增 Model 字段

| Model | 字段 | 类型 | 用途 |
|-------|------|------|------|
| `Evidence` | `page_number` | int \| None | PDF 页码（1-indexed） |

## 五、页码追溯链路

```
PDF Page 12
  → SubtitleSegment(segment_id="page_12", start_time="p.12", text="...")
    → LLM extraction: InvestmentView(source_quote="...", timestamp_start="p.12")
      → Evidence(page_number=12)
        → InvestmentViewRecord(evidence_page=12)
          → MCP: get_report → views[].evidence_page = 12
          → CLI: reports show → 观点带页码
```

页码标记 `[Page N]` 保留在 source_info 和 report frontmatter 中，LLM 在 prompt 引导下引用页码。

## 六、Quality Gate 行为

| PDF 质量 | 行为 |
|----------|------|
| **good** | → 进入 LLM analysis pipeline，生成报告 |
| **degraded** | → 进入 analysis（标注 degraded_ocr_recommended，建议 OCR） |
| **minimal + needs_ocr** | → 跳过分析，写入 `pdf_analysis_skipped` review item |
| **minimal（无 OCR 标记）** | → 跳过分析（字符数 < 200） |
| **failed** | → 跳过分析，写入 `pdf_extraction_failed` review item |

所有质量判断在 `_check_analysis_eligibility()` 中完成，LLM 调用前确认。

## 七、OCR 策略边界

| 当前状态 | 说明 |
|----------|------|
| OCR skeleton | `try_ocr_pdf()` 已实现，无 tesseract 时 graceful degrade |
| 不要求本地 OCR | 不强制安装 tesseract/PaddleOCR/任何系统级 OCR |
| 不默认调用外部 API | 未配置 OCR provider 时不发起任何网络请求 |
| 不内置 API Key | 所有 OCR provider 需用户自行配置 Key |
| 扫描型 PDF | 标记 `needs_ocr=True` → Review Queue → 人工决定处理方式 |
| 后续设计 | 可插拔 OCR Provider 架构（P4-D 或后续） |

## 八、MCP 自动受益

P4 不新增 MCP tool。现有 8 个 tool 自动支持 PDF 数据：

| Tool | PDF 自动支持 |
|------|-------------|
| `search_reports` | `source_type` 字段可区分 pdf / youtube / local |
| `get_report` | 返回 `source_file`, `source_hash`, `page_count` |
| `list_investment_views` | 返回 `evidence_page`（PDF 页码） |
| `list_tracking_signals` | 信号来自 PDF 时带 `report_id` 追溯 |
| `list_review_items` | 可查询 `pdf_needs_ocr` / `pdf_quality_issue` 等类型 |

## 九、测试结果

| 指标 | 数值 |
|------|------|
| **总测试数** | 1641 |
| **P4 新增测试** | 78（47 + 31） |
| **通过率** | 100%（1641/1641） |
| **ruff** | clean（0 errors） |
| **已知 Warnings** | 2（uvicorn websockets deprecation，P2-O 以来已知） |

```
tests/test_pdf_extraction.py  — 47 tests (P4-A)
tests/test_pdf_analysis.py    — 31 tests (P4-B)
其余 1563 tests                — P0-P3 存量
─────────────────────────────────────
总计                            1641 tests
```

## 十、未做事项（P4 明确排除）

| 排除项 | 原因 |
|--------|------|
| 真实 OCR Provider（Tencent/Aliyun/Azure/Google/Mistral） | P4-D 或后续 |
| Web 上传 PDF（非技术用户入口） | P4-C 候选 |
| 表格结构化提取 | 需要独立设计 |
| 图表/图片理解 | 需要多模态模型 |
| Deep Research | 多轮 LLM 编排 |
| 复杂知识图谱 | 需要独立设计 |
| 写入型 MCP tool | 安全边界 |
| 自动定时 PDF 抓取 | 依赖外部调度器 |
| 强制本地 OCR 环境 | OCR 仅 skeleton，graceful degrade |
| 默认上传文件到外部服务 | OCR provider 需用户显式配置 |

## 十一、后续候选

| 阶段 | 内容 | 优先级 |
|------|------|--------|
| P4-C | Web 上传 PDF + 非技术用户入口 | 中 |
| P4-D | OCR Provider 实现（至少一个 provider） | 中 |
| P5 | 搜索增强与知识图谱化 | 低 |
| P5 | 多期观点对比 | 低 |

## 十二、验收结论

**P4-A/P4-B 全部验收通过。P4-S 收口完成。**

P4 交付了 PDF 文本提取与分析闭环两项能力，将 PDF 材料从"不支持"升级为"可提取→可分析→可追溯→可被 MCP 查询"的完整链路。

78 个 P4 专项测试，1641 个全量测试，ruff clean，所有 CLI 命令可用。
