# Source Ingestion（信息源摄入）

## 目标

Sources 模块提供统一的「外部信息 → 知识库」摄入管道。基础导入流程负责：

1. 识别来源类型
2. 预览可导入内容
3. 检测冲突
4. 推荐操作
5. 用户确认后写入

部分信息源已经具备分析闭环：PDF 通过 `sources/pdf_analysis.py` 接入 `_run_pipeline()`，ZSXQ 主题通过 `sources/zsxq_analysis.py` 接入 `_run_pipeline()`。网页和普通文本文件默认仍以 SourceArchive/Deep Notes 归档为主，不自动生成投资报告。

可阅读原文层的持久化规则见 `docs/SOURCE_PROVENANCE_PERSISTENCE_DESIGN.md`。SourceDocument / SourceSegment schema 与 CRUD 已落地，YouTube、PDF、ZSXQ 和上传文件已接入持久化 hook；报告页可打开完整原文并按需翻译。统一搜索底层已具备原文材料/片段查询能力，但当前 Web 搜索页仍只展示报告、观点、信号和实体四类结论层结果。

## 当前入口

| 入口 | 路径/命令 | 用途 |
|------|-----------|------|
| YouTube 频道 | `/sources/channels` | 长期跟踪 YouTube 频道，发现新视频并分析导入 |
| 网页导入 | `/sources/import` | 粘贴任意网页 URL，解析内容后由用户决定导入方式 |
| 固定信息源 | `/sources/tracked` | 跟踪固定外部网页源，刷新并批量导入新条目 |
| 文件 / PDF | `/sources/files/import`；`pdf preview/extract/analyze` | 文本文件预览归档；PDF Web 上传或 CLI 分析，保留页码证据 |
| 知识星球 | `/sources/zsxq`；`zsxq doctor/groups/import-topic/sync/analyze` | 刷新已授权星球、只读导入/同步主题并可进入分析 pipeline |

Web 统一入口：`GET /sources`；所有新增资料的首选入口是 `GET /sources/import/new`。CLI 保留给批量处理、自动化和排障。

## 统一处理原则

Web 导入入口遵循同一管道：

```text
识别来源 → 生成预览 → 冲突检测 → 推荐操作 → 用户确认入库
```

### 1. 识别来源（Profile）

- 判断来源类型（YouTube、网页、固定源、文件、PDF、ZSXQ）
- 评估可追踪性和可分析性
- 不做任何写入

### 2. 生成预览（Preview）

- 解析内容，提取标题、摘要、元数据
- 计算 `content_hash`
- 判断解析质量（good / degraded / minimal）
- 存储到预览存储或 `ingest_jobs`
- 不做任何 Vault 写入

### 3. 冲突检测（Conflict Detection）

- 按 `content_hash` 检测完全重复（severity: blocker）
- 按 title 检测标题重复（severity: warning）
- 按 canonical_url 检测 URL 重复（severity: warning）
- 检测已有 Deep Notes 或 Report 关联（severity: info）

### 4. 推荐操作（Recommendation）

- 根据来源类型、冲突、解析质量推荐最佳操作
- 提供备选操作列表
- 用户可选择与推荐不同的操作

### 5. 用户确认入库（Confirm）

- 用户确认后才执行写入
- 写入操作一步完成
- Web 端普通文件归档到 SourceArchive 后记录 frontmatter 元数据
- 可分析来源通过对应 workflow 进入 report / views / signals

## 单网页 URL 导入

`GET /sources/import` → 粘贴 URL → `POST /sources/import/preview` → 查看预览 → `POST /sources/import/confirm`

- 支持的类型：YouTube 视频页、All-In ZH 笔记页、通用网页
- 检测 YouTube 视频 ID → 建议创建 Deep Notes
- 已有 Report 的 YouTube 视频 → 建议关联 Deep Notes
- 已有 Deep Notes 的 YouTube 视频 → 建议覆盖或跳过
- 通用网页 → 建议归档为 SourceArchive
- 普通网页导入不自动生成投资报告

## 固定外部源跟踪

`GET /sources/tracked` → 添加源 → `POST /sources/tracked/profile` → 查看 profiling 结果 → 创建跟踪源 → 刷新 → 导入条目

- 当前支持 All-In Podcast ZH 笔记（`allin_zh_notes` adapter）
- 刷新时自动发现新条目，生成预览
- 条目状态：new → preview_ready → imported | skipped | failed
- 重新发现已有条目时标记为 existing，不重复生成预览
- 不支持跟踪的 URL → 建议改用单网页导入

## 文本文件上传导入

`GET /sources/files/import` → 选择文件 → `POST /sources/files/preview` → 查看预览 → `POST /sources/files/confirm`

- 支持类型：`.md`, `.txt`, `.html`, `.htm`
- 文件大小限制：5 MB
- 解析质量评估：good / degraded / minimal
- 默认归档到 SourceArchive
- 内容哈希去重：完全相同的内容自动建议跳过
- 普通文本文件上传不自动生成投资报告

## PDF 文档入库与分析

Web：打开 `/sources/files/import`，上传不超过 20 MB 的文本型 PDF，系统先逐页提取并生成预览；用户确认后进入 PDF 分析流水线并跳转到报告详情。

CLI：

```bash
python -m signalvault pdf preview report.pdf
python -m signalvault pdf extract report.pdf
python -m signalvault pdf analyze report.pdf --focus "AI投资"
```

- `source_type = pdf_upload`
- 支持文本型 PDF 的逐页提取
- 分析结果写入 reports / investment_views / tracking_signals
- PDF 观点保留 `evidence_page`
- 扫描型或低质量 PDF 写入 Review Queue：`pdf_needs_ocr`、`pdf_quality_issue`、`pdf_extraction_failed`、`pdf_analysis_skipped`
- 当前不自动调用外部 OCR，不默认上传文件到外部服务
- Web PDF 分析当前使用 mock provider 完成工程闭环；需要真实 LLM、指定关注点或批量处理时使用 CLI `pdf analyze --no-mock`

## ZSXQ 知识星球只读导入与分析

Web：打开 `/sources/zsxq`，先检查 CLI 与登录状态、刷新已授权星球，再按星球同步最近主题；也可输入 topic ID 选择“只导入”或“导入并分析”。

CLI：

```bash
python -m signalvault zsxq doctor
python -m signalvault zsxq groups --refresh
python -m signalvault zsxq import-topic --group-id <id> --topic-id <id>
python -m signalvault zsxq analyze --group-id <id> --topic-id <id> --focus "AI芯片"
```

- `source_type = zsxq_topic`
- 只读取用户已订阅星球内容
- 不做订阅、发布、评论、点赞、删除、运营管理
- topic 内容可导入 ingest_jobs，也可进入 `_run_pipeline()` 生成报告/观点/信号
- 证据追溯通过 `group_id + topic_id + source_url + source_quote`

## SourceArchive / DeepNotes / Report 边界

| 产物 | 触发条件 | 写入位置 |
|------|----------|----------|
| SourceArchive | 通用网页导入、普通文本文件上传 | `01_Reports/SourceArchive/*.md` |
| Deep Notes | YouTube 视频导入（有/无关联 Report） | `02_DeepNotes/<episode_slug>.md` |
| Report（投资报告） | YouTube / PDF / ZSXQ 分析流水线 | `01_Reports/<yymmdd>_<title>_report.md` |

- **SourceArchive** 是普通资料默认归档位置。不涉及观点抽取。
- **Deep Notes** 仅用于有明确 episode / external notes 场景。
- **Report** 不因普通网页导入或普通文本文件上传自动触发；PDF/ZSXQ 使用各自 analyze workflow 可生成 Report。
- **Source Document / Source Segment** 是已落地的统一原文层，用于全文阅读、片段定位和证据链追溯；它不替代 SourceArchive / Deep Notes / Report，而是为这些产物提供统一来源锚点。当前 Web 直接入口集中在报告完整原文页，原文材料/片段尚未作为 Web 搜索筛选项开放。

## 统一状态文案

详见 `signalvault.sources.models.SOURCE_STATUS_LABELS`：

| 内部状态 | 用户文案 |
|----------|----------|
| pending | 待处理 |
| preview_ready | 待确认 |
| new | 新发现 |
| existing | 已发现 |
| imported | 已入库 |
| skipped | 已跳过 |
| failed | 失败 |
| active | 正常 |
| degraded | 解析退化 |
| unsupported | 暂不支持 |
| needs_review | 需人工确认 |

## 统一操作文案

详见 `signalvault.sources.models.ACTION_LABELS`：

| 操作 | 按钮文案 |
|------|----------|
| preview | 生成预览 |
| confirm_archive | 确认归档 |
| import_as_source_archive | 归档为资料 |
| import_as_deep_notes_linked | 导入为关联精读笔记 |
| import_as_deep_notes_derived_only | 导入为独立精读笔记 |
| skip | 跳过 |
| overwrite_deep_notes | 覆盖精读笔记 |
| refresh | 更新 |
| batch_import | 导入选中项 |
| back | 返回修改 |

## 当前仍不支持或不默认启用

- OCR 图片文字识别自动化
- Office 文档（`.docx`, `.xlsx` 等）
- Embedding / 向量检索
- 普通网页/普通文本文件自动生成 Report
- 定时自动抓取
- RSS feed adapter
- ZSXQ 写入型客户端能力（发布/评论/点赞/删除/订阅）

## 后续扩展建议

- Unified Knowledge Search Web 页开放原文材料和原文片段结果类型
- 信息源工作台展示“已保留全文 / 仅元数据 / 解析失败”的来源保留状态
- 观点、信号证据卡直接定位到 `source_segment_id`
- 网页正文版本记录与更细粒度段落定位
- RSS/Atom adapter
- OCR 图片文字（Tesseract local 或可插拔 OCR provider）
- 适配器插件注册机制
