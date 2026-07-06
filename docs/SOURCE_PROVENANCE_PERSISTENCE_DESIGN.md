# Source Provenance Persistence Design

## 结论

投资研究知识库的核心不是一次性生成答案，而是让用户能沿着检索结果回到原始材料、证据片段、报告结论和信号变化之间的链条。

当前系统已经具备报告、观点、信号、实体、操作日志和部分来源字段，但还缺少统一的“可阅读原文层”。后续应新增 `SourceDocument` 与 `SourceSegment` 两层持久化抽象，保留视频完整带时间戳已翻译逐字稿、网页原文稿、知识星球全文稿、PDF 页文本和上传文本的可阅读版本，并让报告详情页、Unified Knowledge Search、诊断中心都能复用同一套溯源锚点。

本设计不替代现有 `Episode` / `Report` / `InvestmentViewRecord` / `TrackingSignalRecord`，而是在其下方补一层更稳定的原文证据地基。

## 当前缺口

现有数据链路可以把“报告级证据”串起来：

- `Episode` 保存来源、标题、字幕路径、视频 ID、语言、来源 URL 等入口信息。
- `Report` 保存提取 JSON、报告 Markdown、LLM 元数据和分析焦点。
- `InvestmentViewRecord` 保存观点、标的、逻辑、证据强度、`source_quote`、时间戳和 PDF 页码。
- `TrackingSignalRecord` 保存信号、触发条件、证据原文和时间戳。
- `OperationLog` / 诊断页可以帮助用户理解导入和处理过程。

但这些字段更适合“结论引用”，不适合“完整阅读和再检索”：

- YouTube 分析过程中会使用字幕段落，但完整字幕和翻译字幕没有作为可阅读原文层统一入库。
- 网页和上传文本可以进入 SourceArchive / DeepNotes，但默认不作为 Unified Search 的一等搜索结果，也没有统一的段落定位结构。
- 知识星球可以进入分析流水线，但全文稿、话题 ID、作者、附件和评论等材料需要更明确的私有溯源策略。
- PDF 观点可保留页码证据，但页级文本、抽取质量和 OCR 状态需要成为可检索、可打开的证据层。

## 设计原则

1. 原文先于结论  
   所有投资观点、信号和报告结论都应能回到原文或原文片段。没有可定位原文的内容，只能作为低置信度辅助信息展示。

2. 可读材料与结构化结论分离  
   报告和观点表保持轻量；全文稿、长网页、PDF 页文本放入 Source Document 层，避免报告表承载过多职责。

3. 保留原文，不用翻译覆盖原文  
   视频字幕、网页、知识星球、PDF 提取文本都应保留 original / normalized / translated 三种状态。翻译稿是派生材料，不替代原始材料。

4. 私有来源默认本地化  
   知识星球、付费网页、上传文件等材料默认 `local_only`，诊断导出和日志中不输出全文，只输出 ID、哈希、元数据和有限摘录。

5. 兼容现有后端契约  
   现有 API、报告、观点、信号字段继续可用。新增字段采用可选外键或稳定 ID，不强迫旧数据迁移后才能使用。

## 核心数据模型

### SourceDocument

`SourceDocument` 表示一个用户可打开阅读的原始材料或派生全文稿。

建议字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 内部主键 |
| `source_doc_id` | 稳定业务 ID，可用于跨表引用 |
| `source_type` | `youtube_transcript` / `web_page` / `zsxq_topic` / `pdf_document` / `uploaded_text` / `deep_note` |
| `title` | 用户可读标题 |
| `canonical_url` | 规范 URL，网页和视频优先保存 |
| `source_url` | 原始导入 URL |
| `source_path` | 本地文件或 Vault 路径 |
| `content_hash` | 规范化正文哈希，用于去重和版本识别 |
| `language` | 当前可读文本语言 |
| `original_language` | 原始语言 |
| `translated_language` | 翻译稿语言 |
| `status` | `available` / `missing` / `private` / `expired` / `degraded` |
| `raw_text_path` | 原始文本或原始 HTML/PDF 提取材料路径 |
| `normalized_text_path` | 清洗后的可阅读正文路径 |
| `translated_text_path` | 翻译后全文稿路径 |
| `metadata_json` | 视频、网页、知识星球、PDF 等来源专属元数据 |
| `access_scope` | `public_web` / `private_subscription` / `uploaded_private` / `local_only` |
| `retention_policy` | `keep_full_text` / `metadata_only` / `redacted_export` |
| `created_at` | 首次入库时间 |
| `fetched_at` | 来源抓取时间 |
| `updated_at` | 最近更新时间 |

### SourceSegment

`SourceSegment` 表示可定位、可搜索、可引用的原文片段。

建议字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 内部主键 |
| `source_doc_id` | 指向 `SourceDocument` |
| `segment_id` | 来源内稳定片段 ID |
| `sequence_index` | 正文顺序 |
| `segment_type` | `timestamp` / `paragraph` / `page` / `topic_body` / `comment` / `quote` |
| `text_original` | 原始片段文本 |
| `text_normalized` | 清洗后片段文本 |
| `text_translated` | 翻译片段文本 |
| `start_time` | 视频/音频起始时间，秒 |
| `end_time` | 视频/音频结束时间，秒 |
| `page_number` | PDF 页码 |
| `paragraph_index` | 网页或文本段落序号 |
| `heading_path` | 网页或文档标题路径 |
| `char_start` | 全文字符起点 |
| `char_end` | 全文字符终点 |
| `locator_json` | CSS selector、topic ID、comment ID、附件 ID 等来源专属定位信息 |
| `content_hash` | 片段哈希 |
| `translation_status` | `not_needed` / `translated` / `partial` / `failed` |
| `translation_metadata_json` | 翻译模型、供应商、prompt 版本、时间 |

### 与现有表的关系

建议先做可选关联，避免破坏现有契约：

- `Episode.source_doc_id`：关联视频、网页、PDF、知识星球等主要原文。
- `Report.source_doc_id`：报告直接关联其主要原文；多来源报告可通过关联表扩展。
- `InvestmentViewRecord.source_segment_id`：观点证据定位到具体片段，同时保留 `source_quote`、`timestamp_start`、`timestamp_end`、`evidence_page` 作为兼容字段。
- `TrackingSignalRecord.source_segment_id`：信号触发证据定位到具体片段。
- `OperationLog.source_doc_id`：导入、解析、翻译、分析、修复操作可以回到具体来源。

## 来源类型持久化规则

### YouTube / 视频字幕

需要保留：

- 完整带时间戳原始字幕。
- 完整带时间戳已翻译逐字稿。
- 清洗后的语义段落版本，用于报告分析和搜索。
- 视频元数据：`video_id`、标题、频道、频道 ID、时长、语言、字幕是否自动生成、抓取时间、来源 URL。
- 翻译元数据：模型、供应商、prompt 版本、翻译时间、失败片段。

推荐结构：

- `SourceDocument.source_type = youtube_transcript`
- 原始字幕和翻译字幕分别保存为可阅读 Markdown/Text 文件。
- `SourceSegment.segment_type = timestamp`
- 每个片段保存 `start_time` / `end_time`，报告详情页可以从证据卡直接跳到完整逐字稿对应位置。

### 网页

需要保留：

- 原网页正文清洗稿。
- 可选原始 HTML 快照路径。
- 标题、作者、发布时间、抓取时间、canonical URL、内容哈希。
- 解析质量：正文抽取成功率、疑似导航噪音、缺失正文、付费墙提示。
- 段落级定位：段落序号、标题路径、必要时保存 CSS selector。

推荐结构：

- `SourceDocument.source_type = web_page`
- `SourceSegment.segment_type = paragraph`
- 同一 URL 二次抓取内容变化时创建新版本，而不是覆盖旧版本。

### 知识星球

需要保留：

- 话题全文稿。
- 话题元数据：`group_id`、`group_name`、`topic_id`、话题类型、作者、创建时间、标签、来源 URL。
- 附件元数据：文件名、类型、大小、下载状态、哈希、本地路径。
- 评论正文如果参与分析，应作为独立 `comment` 片段保存。
- 私有来源策略：默认 `private_subscription` + `local_only`，诊断导出不包含全文。

推荐结构：

- `SourceDocument.source_type = zsxq_topic`
- 主体正文使用 `SourceSegment.segment_type = topic_body`
- 评论使用 `SourceSegment.segment_type = comment`
- 附件可作为子 `SourceDocument`，通过 `parent_source_doc_id` 或关联表链接到话题。

### PDF

需要保留：

- 原 PDF 文件路径和文件哈希。
- 页级提取文本。
- OCR 状态、提取方法、页码、解析质量。
- PDF 元数据：标题、作者、页数、创建时间、文件大小。

推荐结构：

- `SourceDocument.source_type = pdf_document`
- `SourceSegment.segment_type = page`
- `InvestmentViewRecord.evidence_page` 继续保留，同时新增 `source_segment_id` 指向页级文本。

### 上传文本 / 本地文件

需要保留：

- 原始文件路径、文件名、文件哈希。
- 清洗后的可读正文。
- 文件类型、编码、导入时间。
- 如果上传的是 Markdown 或 HTML，保留标题层级和段落定位。

推荐结构：

- `SourceDocument.source_type = uploaded_text`
- `SourceSegment.segment_type = paragraph`

### Deep Notes / SourceArchive

Deep Notes 和 SourceArchive 应被视为“用户整理后的派生材料”，不是默认一手原文。

需要保留：

- 派生材料路径。
- 来源链路：由哪些 `SourceDocument` 或外部 URL 整理而来。
- 用户编辑时间和内容哈希。
- 是否允许作为主证据来源。

推荐结构：

- `SourceDocument.source_type = deep_note`
- 增加 `derived_from_source_doc_id` 或关联表。
- 搜索结果中标明“整理稿”或“派生笔记”，避免与原始来源混淆。

## 检索与前端动线影响

Unified Knowledge Search 后续应支持五类结果：

1. 报告结果：当前已有。
2. 观点结果：当前已有。
3. 信号结果：当前已有。
4. 原文材料结果：新增 `SourceDocument`。
5. 原文片段结果：新增 `SourceSegment`。

用户动线建议：

- 搜索结果先展示“结论层”，同时给出“查看原文片段”入口。
- 原文片段卡片展示来源类型、时间戳/页码/段落、原文摘录、翻译摘录和关联观点数。
- 报告详情页的证据链增加“打开完整原文”与“定位到片段”。
- 信息源工作台增加“已保留全文 / 仅保留元数据 / 解析失败”状态。
- 诊断中心在失败时提示用户缺失的是“导入失败、解析失败、翻译失败、分析失败”中的哪一层。

## 还应保留的材料

除视频逐字稿、网页原文稿、知识星球全文稿外，建议补齐以下溯源材料：

- 导入预览快照：用户确认导入前看到的标题、正文片段、解析质量和冲突提示。
- 来源版本记录：同一 URL、视频、知识星球话题或文件再次导入时保留版本差异。
- 翻译对齐记录：原文片段与翻译片段是否一一对应，哪些片段翻译失败。
- 提取对齐记录：每条观点、信号、风险、实体对应哪些 `SourceSegment`。
- 解析质量指标：网页正文抽取质量、PDF OCR 质量、字幕缺口、知识星球附件缺失。
- 附件关系：知识星球附件、网页下载文件、PDF 原文件与文本抽取稿之间的关系。
- 用户处理决策：跳过、合并、重新导入、标记为重复、手动修正标题等操作。
- 检索审计信息：可选保留用户保存的查询、筛选条件和打开过的证据链，帮助复盘研究路径。
- 隐私与导出策略：哪些材料可以进入诊断包，哪些只能留在本地。

## 迁移策略

建议分阶段实施：

1. 文档与边界确认  
   先确认本文档作为 Source Provenance 的持久化规则，不改现有后端契约。

2. Schema 增量迁移  
   新增 `source_documents`、`source_segments`，以及现有表上的可选 `source_doc_id` / `source_segment_id`。

3. YouTube 完整逐字稿持久化  
   优先落地，因为当前投资长视频是最需要时间戳溯源的来源。

4. 网页与知识星球全文稿持久化  
   统一 SourceArchive、ZSXQ 导入和搜索结果展示。

5. PDF 页文本与上传文件持久化  
   将页级证据和文件导入流程接入同一套 Source Segment。

6. Unified Knowledge Search 接入原文层  
   新增来源材料和片段结果类型，不替代现有报告/观点/信号结果。

7. 报告详情页证据链增强  
   证据卡可跳转到完整原文、时间戳、页码或段落。

8. 诊断与导出策略  
   补齐全文缺失、翻译失败、解析失败、权限限制和隐私脱敏提示。

## 非目标

- 不引入向量库。
- 不把原文层设计成 RAG 问答系统。
- 不把私有来源全文导出到诊断包或日志。
- 不改变当前报告、观点、信号的基础 API 契约。
- 不把 AI 推断内容伪装成原文。

