# 投资音视频研究助手 — 产品需求与工程落地说明书（PRD v1.2）

**文档版本**：v1.2-数据源重构版  
**日期**：2026-05-27  
**状态**：设计思路与实现目标背景文档  
**目标读者**：产品负责人、后端/前端开发工程师、AI 工程师、测试工程师、后续 Claude Code / Codex 执行代理  
**项目定位**：面向 YouTube 投资访谈、播客字幕与本地字幕文件的投资音视频研究工具  

---

## 1. 修订说明

本版本基于 v1.1 优化版重构数据源与 MVP 范围，核心调整如下：

1. **产品名称与定位调整**  
   从”投资播客研究助手”调整为”投资音视频研究助手”，覆盖范围从单一播客扩展到 YouTube 投资访谈、播客字幕和本地字幕文件等公开音视频内容。产品定位聚焦于：
   - 音视频字幕内容结构化整理；
   - 投资观点、风险、标的、待验证信号的提取；
   - 历史观点追踪与研究辅助；
   - 不输出买卖建议，不替代投资决策。

2. **数据源优先级重构**  
   验证了 xyz-dl 获取小宇宙字幕的链路，发现稳定性和可控性存在问题。v1.2 将数据源优先级调整为：
   - 第一优先：本地字幕文件（.srt / .vtt / .txt）
   - 第二优先：YouTube 视频字幕（youtube-transcript-api）
   - 第三优先：yt-dlp / yt-dlp-transcript（YouTube 字幕备用方案）
   - 后续可选：小宇宙 xyz / xyz-dl（降级为可选 Adapter）
   - 后续版本：Whisper 本地转写
   小宇宙不再是 P0 主数据源，xyz-dl 不再作为 P0 依赖。

3. **MVP 拆为 P0-A 和 P0-B**  
   - P0-A：本地字幕文件分析闭环（与 v1.1 P0 一致，已实现）
   - P0-B：YouTube 字幕 Adapter，复用 P0-A 分析 pipeline
   真实 LLM API 调用不在 P0 范围，P0-A 和 P0-B 均使用 mock provider。

4. **技术架构 Data Adapter 层调整**  
   Adapter 层新增 YouTubeTranscriptAdapter（基于 youtube-transcript-api）和 YtDlpAdapter（备用方案）。小宇宙相关 Adapter（XyzDlAdapter、XyzApiAdapter）降级为后续可选实现。

5. **结构化抽取从”一步生成报告”改为”两阶段处理”**  
   - 第一阶段：事实抽取，生成严格 JSON；
   - 第二阶段：基于 JSON 生成可读 Markdown 报告。  
   这样更利于调试、回溯、对比分析和后续检索。

6. **强化合规与可信度设计**  
   每条投资观点必须绑定原文引用与时间戳；无法溯源的内容只能进入”不确定项/待确认项”，不得进入核心观点矩阵。

---

## 2. 项目背景

投资类音视频内容已经成为个人投资者、财经研究者、行业观察者获取观点的重要信息源。YouTube 上有大量基金经理、券商研究员、投资机构、财经媒体和独立研究者的访谈视频；小宇宙等播客平台也聚集了大量长音频对谈内容。这些内容具有以下特点：

- 信息密度高，但以音频/视频形态存在；
- 单期节目通常 40-120 分钟，完整收听成本高；
- 嘉宾观点分散在对谈中，难以快速定位；
- 标的、行业、宏观判断缺少结构化记录；
- 跨期观点变化难以追踪；
- 非 IT 用户难以自行完成字幕获取、清洗、LLM 分析和知识库沉淀。

YouTube 字幕覆盖率高、获取方式稳定（youtube-transcript-api），是最可控的外部数据源。小宇宙字幕获取链路（xyz-dl）稳定性不足，降级为后续可选数据源。

因此，本项目希望构建一个本地化、低门槛、轻量级的投资音视频研究工具，将已有字幕转化为可查询、可对比、可追踪的结构化研究资料。

---

## 3. 产品定位

### 3.1 一句话定位

**投资音视频研究助手：从 YouTube 投资访谈、播客字幕和本地字幕文件中结构化提取投资观点、标的、风险提示和待验证信号，帮助用户进行内容研究、观点追踪和跨期对比。**

### 3.2 产品不做什么

本工具不是：

- 投资顾问；
- 自动荐股工具；
- 交易信号系统；
- 量化策略系统；
- 播客内容商业化搬运工具；
- 大规模爬虫系统。

### 3.3 产品核心原则

| 原则 | 说明 |
|---|---|
| 只整理，不荐股 | 系统只结构化音视频中已表达的观点，不输出买入/卖出建议。 |
| 有引用，才入库 | 所有核心观点必须绑定原文关键句和时间戳。 |
| 本地优先 | 报告、字幕、配置、本地索引默认保存在用户电脑。 |
| 非 IT 用户可用 | 用户不需要理解 CLI、API、Token、数据库等技术细节。 |
| MVP 保持窄闭环 | P0-A 先跑通本地字幕，P0-B 再接 YouTube，不追求一开始覆盖全部平台。 |
| 工程可替换 | 对 YouTube API、youtube-transcript-api、LLM 服务商均做适配层封装，避免强耦合。小宇宙相关能力降级为可选 Adapter。 |

---

## 4. 目标用户与典型场景

### 4.1 目标用户

| 用户类型 | 说明 |
|---|---|
| 个人投资者 | 关注财经播客，希望快速提取标的、行业和风险观点。 |
| 财经内容研究者 | 需要整理不同嘉宾在不同节目中的观点变化。 |
| 投资学习者 | 希望通过播客建立自己的观点笔记库。 |
| 非 IT 用户 | 不熟悉 API、命令行、数据库，但能使用桌面应用或网页应用。 |

### 4.2 核心痛点

1. 播客收听耗时长，无法快速判断是否值得完整收听；
2. 嘉宾观点散落在长对话中，难以整理；
3. 同一标的在不同节目中的观点难以汇总；
4. 同一嘉宾在不同时间的观点变化难以追踪；
5. 播客笔记通常碎片化，无法形成可查询的本地知识库；
6. 非 IT 用户难以独立搭建字幕抓取、清洗、LLM 分析与 RAG 查询流程。

### 4.3 典型场景

#### 场景 A：单期快速研究

用户提供本地字幕文件或 YouTube 视频链接，系统获取字幕，生成结构化报告，包括：

- 本期讨论了哪些标的/行业；
- 嘉宾看多、看空或中性的理由；
- 风险提示；
- 原文关键引用；
- 可后续验证的信号。

#### 场景 B：标的观点汇总

用户输入“宁德时代”，系统从历史报告中汇总所有相关观点：

- 哪几期节目提到过；
- 哪些嘉宾表达了看多/看空/中性；
- 核心分歧是什么；
- 最近一次观点是什么；
- 每条观点对应的节目标题、日期和时间戳。

#### 场景 C：跨期观点变化

用户选择同一节目或同一嘉宾的多期报告，系统生成观点变化矩阵：

- 对某行业是否从乐观转为谨慎；
- 观点变化是否有明确触发因素；
- 哪些判断后续需要验证；
- 是否存在前后矛盾或口径变化。

---

## 5. 开源项目调研与借鉴方向

本项目目前没有找到一个可直接照搬的完整开源实现。现有项目多集中在”YouTube 字幕获取””播客下载/转写/摘要””播客 RAG””桌面客户端”几个局部方向。v1.2 方案采用”能力拆解 + 分层借鉴”的方式，数据源优先级从小宇宙转向 YouTube。

### 5.1 YouTube 数据源相关（P0-B 重点参考）

| 开源项目 | 项目定位 | 参考价值 | 本项目借鉴方向 | 注意事项 |
|---|---|---|---|---|
| `jdepoix/youtube-transcript-api` | YouTube 字幕获取 Python 库，支持多语言、手动/自动字幕 | P0-B 核心 Adapter 的直接底层依赖 | 作为 YouTubeTranscriptAdapter 的底层调用库；借鉴其字幕格式解析、语言选择、fallback 逻辑 | 依赖 YouTube 字幕可用性；部分视频无字幕需降级处理 |
| `yt-dlp/yt-dlp` | 通用媒体和字幕下载工具，支持 YouTube 及众多平台 | 作为 YouTube 字幕获取的备用方案 | 作为 YtDlpAdapter 底层；备用方案当 youtube-transcript-api 不可用时调用 | 功能强大但依赖重；P0-B 优先使用 youtube-transcript-api |
| `haron/yt-dlp-transcript` | 轻量 transcript CLI 封装，基于 yt-dlp | 对 yt-dlp 字幕获取的简化封装有参考价值 | 借鉴其将 yt-dlp 字幕能力封装为简洁 API 的方式 | 仅作为封装模式参考，不直接依赖 |
| `RAG-YouTube-QNA-summarizer` | YouTube transcript RAG 问答流程 | 对 YouTube 字幕 + RAG 问答的完整链路有参考价值 | P1/P2 全局问答阶段参考其 RAG 问答流程设计 | 属于问答而非结构化抽取，差异化借鉴 |
| `YouTubeRAG` | YouTube 字幕总结和问答 | 对 YouTube 字幕的总结与问答有参考价值 | 借鉴其字幕处理与问答交互设计 | 同上，侧重问答而非投资观点结构化抽取 |

### 5.2 小宇宙数据源相关（降级为后续可选 Adapter）

| 开源项目 | 项目定位 | 参考价值 | 本项目借鉴方向 | 注意事项 |
|---|---|---|---|---|
| `ultrazg/xyz` | 小宇宙 FM 非官方 API 封装 | 支持小宇宙节目、单集、登录、订阅等接口逻辑 | 后续可选 Adapter，P0 不依赖 | 非官方 API 存在变动风险；不作为 P0 数据源 |
| `shiquda/xyz-dl` | 小宇宙播客 CLI 下载工具，支持单集、专辑、字幕下载 | 曾作为字幕获取候选，但稳定性验证不通过 | 后续可选 Adapter，P0 不依赖 | AGPL-3.0 许可需注意；稳定性不足，降级为可选 |
| `ultrazg/horizon` | Wails + React 构建的小宇宙桌面客户端 | 有”小宇宙客户端 + 本地 API 服务 + 桌面封装”的工程形态 | 后续桌面端交互参考 | 它是播客客户端，不是分析工具；技术栈为 Go/Wails |

### 5.3 播客转写与摘要相关

| 开源项目 | 项目定位 | 参考价值 | 本项目借鉴方向 | 注意事项 |
|---|---|---|---|---|
| `wendy7756/podcast-transcriber` | 多平台播客转写与 AI 摘要工具 | 支持播客转写、摘要、前端交互 | 借鉴非 IT 用户界面、多平台 URL 输入、摘要展示形式 | MVP 阶段不做音频转写 |
| `winterfx/Podcast-Transcription` | 支持小宇宙播客转写、Whisper、摘要、SRT 输出 | 对”播客 + 转写 + 摘要”有参考价值 | 后续 Whisper 兜底时参考 | P0 不依赖 |
| `rrrrrredy/xiaoyuzhou-podcast` | 小宇宙播客获取、faster-whisper 转写、总结 | 与小宇宙和 agent/skill 场景相关 | 后续 Skill 化封装参考 | 需要音频下载和转写，P0 不依赖 |

### 5.4 播客处理流水线与本地知识库相关

| 开源项目 | 项目定位 | 参考价值 | 本项目借鉴方向 | 注意事项 |
|---|---|---|---|---|
| `haasonsaas/parakeet-podcast-processor` / P³ | RSS 抓取、转写、结构化摘要、本地 LLM、DuckDB、Markdown/JSON 导出 | 流水线命令分层清晰：fetch / transcribe / digest / export / status | 借鉴处理流水线分层、任务状态、Markdown/JSON 双输出 | 偏 Apple Silicon 与本地转写；P0 不引入其转写链路 |
| `MichaelShoemaker/history_of_rome_podcast_llm` | 将完整播客全集转为可检索、带时间戳的 LLM 语料 | 对大规模播客语料入库、时间戳溯源、RAG 查询有参考意义 | 借鉴”播客全集 → 时间戳文本 → 可查询语料”的组织方式 | 面向固定历史播客，不是动态单集分析 |
| `deanpeters/lennysan-rag-o-matic` | 面向非技术用户的播客语料 RAG 工具 | 强调低门槛、可学习、CLI/浏览器双入口、真实引用 | 借鉴非技术用户体验、低门槛 RAG、引用来源、逐阶段垂直切片开发方法 | 领域是 PM 研究，不是投资分析 |
| `allenhutchison/podcast-rag` | 播客库 RAG 系统，支持转写、元数据抽取、语义搜索和自动引用 | 对”播客库问答 + 引用”的通用模式有参考价值 | 借鉴自动引用、播客库级检索和问答设计 | P1/P2 可以先用结构化检索 + SQLite FTS |

### 5.5 本地转写与说话人分离相关

| 开源项目 | 项目定位 | 参考价值 | 本项目借鉴方向 | 注意事项 |
|---|---|---|---|---|
| `transcriptionstream/transcriptionstream` | 自托管离线转写与说话人分离服务 | 对本地转写、说话人分离、离线摘要有参考价值 | 后续无字幕兜底和本地隐私化处理可参考 | P0 不依赖；初版只做字幕文本上的角色推断 |

### 5.6 本项目与现有开源项目的差异

现有项目大多解决以下问题：

- YouTube 字幕获取与问答；
- 播客下载与转写；
- 通用摘要；
- 播客语料问答；
- 小宇宙客户端；
- 本地转写服务。

本项目的差异化目标是：

1. 不是泛播客/视频摘要，而是**投资观点结构化抽取**；
2. 不是先下载音频，而是优先使用**已有字幕**（本地文件 + YouTube）；
3. 不是只输出摘要，而是输出**可入库、可对比、可检索的投资观点对象**；
4. 不是一次性问答，而是形成**标的、嘉宾、行业、风险、验证信号**的长期跟踪库；
5. 不是面向开发者，而是面向**非 IT 用户**的本地轻量工具。

---

## 6. MVP 范围重构

### 6.1 P0-A：本地字幕分析闭环

P0-A 是第一阶段必须完成的最小可用闭环，目前已实现。

#### P0-A 目标

用户提供本地 `.srt` / `.vtt` / `.txt` 字幕文件，系统解析清洗后通过 mock LLM 生成结构化投资研究报告并入库。

> 注：YouTube 链接、小宇宙链接、xyz-dl、真实 LLM API 调用均不在 P0-A 范围。

#### P0-A 必须实现

1. 本地 `.srt` / `.vtt` / `.txt` 字幕文件读取；
2. 字幕格式识别与解析；
3. 字幕清洗与时间戳保留；
4. 两阶段 LLM 分析（mock provider）：
   - 阶段一：事实抽取 JSON；
   - 阶段二：研究报告 Markdown；
5. 本地 SQLite 存储（5张核心表：episodes, reports, investment_views, tracking_signals, entities）；
6. CLI 命令行入口，支持 `--mock` 模式；
7. 基础错误提示与日志。

#### P0-A 暂不实现

- YouTube 字幕获取；
- 小宇宙链接导入与元数据获取；
- xyz-dl 字幕下载；
- 真实 LLM API 调用；
- 说话人推断逻辑（mock 阶段硬编码 speaker_label）；
- 节目关键词搜索；
- 批量探测字幕；
- 多平台播客支持；
- Whisper 本地转写；
- 多期对比；
- 全局知识库问答；
- PDF/Word 导出；
- 定时抓取与推送；
- 前端报告详情页；
- podcasts / qa_logs 等非核心表。

### 6.2 P0-B：YouTube 字幕 Adapter

P0-B 在 P0-A 闭环跑通后，接入 YouTube 字幕作为第一个外部数据源。

#### P0-B 目标

用户提供 YouTube 视频 URL，系统通过 youtube-transcript-api 获取字幕，转换为统一的 TranscriptSegment 格式，复用 P0-A 的分析 pipeline。

> 注：P0-B 同样使用 mock LLM，不调用真实 LLM API。yt-dlp 作为备用字幕获取方案。

#### P0-B 必须实现

1. YouTube URL 解析与验证；
2. youtube-transcript-api 字幕获取 Adapter；
3. YouTube 字幕 → TranscriptSegment 格式转换；
4. CLI 支持 `--youtube <url>` 输入；
5. YouTube 视频元数据获取（标题、时长等）；
6. 无字幕视频的降级提示；
7. yt-dlp 字幕获取备用 Adapter（可选）。

#### P0-B 暂不实现

- YouTube 视频下载；
- YouTube 频道批量分析；
- 真实 LLM API 调用；
- 小宇宙链接接入；
- YouTube 搜索功能。

### 6.3 P1：历史报告与检索闭环

#### P1 目标

用户可以管理历史报告，并基于标的、嘉宾、行业、关键词进行检索和问答。

#### P1 功能

1. 历史报告列表；
2. 报告按节目、日期、标的、行业、嘉宾、关键词筛选；
3. 单报告问答；
4. 全局问答第一版：结构化过滤 + SQLite FTS5 + LLM 归纳；
5. 标的别名与实体归一化；
6. 投资观点表、待验证信号表、实体表独立入库。

### 6.4 P2：真实 LLM + 小宇宙可选 Adapter

#### P2 目标

接入真实 LLM API，并可选地接入小宇宙 Adapter 作为补充数据源。

#### P2 功能

1. 真实 LLM provider（OpenAI-compatible）接入；
2. 小宇宙单集链接解析（可选 Adapter）；
3. xyz-dl 字幕下载 Adapter（可选）；
4. 说话人推断逻辑；
5. 元数据获取（podcasts 表）。

### 6.5 P3：跨期观点追踪闭环

#### P3 目标

支持多期报告对比，输出观点变化、共识分歧和待验证信号。

#### P3 功能

1. 多报告选择；
2. 同一标的跨期观点聚合；
3. 同一嘉宾/同一节目观点时间线；
4. 看多/看空/中性观点变化矩阵；
5. 待验证信号状态管理；
6. 对比结果保存与追问。

---

## 7. 产品功能需求

## 7.1 数据导入模块

### 7.1.1 本地字幕导入（P0-A）

#### 功能描述

用户选择本地 `.srt` / `.vtt` / `.txt` 字幕文件，系统解析并保留时间戳。

#### 输入

- 本地字幕文件路径；
- 可选：用户自定义关注点；
- 可选：分析模板。

#### 输出

- 解析后的 TranscriptSegment 列表；
- 时间戳映射。

#### 设计要求

1. 本地字幕是 P0-A 主入口；
2. 格式识别失败时提示用户确认文件格式；
3. 解析成功后进入分析 pipeline。

### 7.1.2 YouTube 视频链接导入（P0-B）

#### 功能描述

用户提供 YouTube 视频 URL，系统通过 youtube-transcript-api 获取字幕，转换为统一 TranscriptSegment 格式，复用 P0-A 分析 pipeline。

#### 输入

- YouTube 视频 URL；
- 可选：字幕语言选择（默认 zh-Hans / en）；
- 可选：用户自定义关注点。

#### 输出

- 视频元数据（标题、时长、频道）；
- 字幕 TranscriptSegment 列表。

#### 设计要求

1. YouTube URL 是 P0-B 主入口；
2. URL 解析失败时提示用户确认链接格式；
3. 无字幕视频提示"该视频暂无可用字幕"；
4. youtube-transcript-api 失败时可选降级到 yt-dlp 方案；
5. 同一视频已分析过时提示"已有报告"。

### 7.1.3 小宇宙链接导入（P2 可选）

#### 功能描述

用户从小宇宙 App 或网页复制单集分享链接，粘贴到应用中，系统解析单集 ID 并通过可选 Adapter 获取字幕。

> 注：小宇宙链接导入不在 P0 范围，降级为 P2 可选 Adapter。

### 7.1.4 节目搜索（P1/P3）

#### 功能描述

用户输入节目或频道关键词，系统返回匹配列表。

#### 设计调整

该能力不作为 P0 必需功能。原因：

- 搜索接口可能不稳定；
- 关键词搜索准确率不一定高；
- 直接提供 URL 或本地文件更可控。

### 7.1.5 字幕获取策略

#### 数据源优先级

| 优先级 | 数据源 | 说明 |
|---|---|---|
| 1 | 本地字幕文件 | .srt / .vtt / .txt，P0-A 主入口 |
| 2 | youtube-transcript-api | YouTube 视频字幕，P0-B 主入口 |
| 3 | yt-dlp / yt-dlp-transcript | YouTube 字幕备用方案 |
| 4 | 小宇宙 xyz / xyz-dl | 后续可选 Adapter（P2） |
| 5 | Whisper 本地转写 | 后续版本考虑 |

#### 约束

1. P0 默认不下载音频/视频；
2. 如无字幕，提示”暂无可用字幕，暂不支持分析”；
3. 不在 P0 阶段自动转写音频；
4. 字幕临时文件默认保留 7 天；
5. 字幕哈希用于重复分析检测。

---

## 7.2 字幕预处理模块

### 7.2.1 格式识别

支持：

- `.srt`；
- `.vtt`（WebVTT，P0-A 新增）；
- `.txt`。

### 7.2.2 文本清洗

处理内容包括：

1. 移除重复时间轴；
2. 合并过短字幕片段；
3. 保留时间戳映射；
4. 识别明显广告口播、片头片尾；
5. 生成 `cleaned_segments`。

### 7.2.3 时间戳映射

每个文本段落保留：

```json
{
  "segment_id": "seg_001",
  "start_time": "00:12:34",
  "end_time": "00:12:58",
  "text": "……"
}
```

---

## 7.3 说话人/角色推断模块

### 7.3.1 设计原则

P0 不承诺真实 speaker diarization，只做“文本角色推断”。

原因：

- 字幕通常不包含真实 speaker tag；
- 纯文本推断主持人/嘉宾存在误判；
- 没有音频时无法做真正的声纹级说话人分离。

### 7.3.2 三层降级策略

| 层级 | 条件 | 处理方式 | 输出 |
|---|---|---|---|
| L1 | 字幕自带 speaker tag | 正则提取 | speaker + high confidence |
| L2 | 无 speaker tag，但上下文可推断 | LLM 根据提问句、称谓、身份自述推断 | speaker + medium/low confidence |
| L3 | 无法推断 | 标注为“未识别发言人” | unknown speaker |

### 7.3.3 输出字段

```json
{
  "speaker_label": "嘉宾A",
  "speaker_role": "guest",
  "speaker_confidence": "medium",
  "speaker_evidence": "该段使用‘我们基金’等表达，结合上下文推断为嘉宾发言",
  "identity_claim": "某基金经理（来自标题或原文，不由模型猜测）"
}
```

### 7.3.4 约束

1. 不允许模型凭空补全嘉宾真实身份；
2. 无明确依据时只写“嘉宾A/嘉宾B/主持人/未识别发言人”；
3. 所有推断必须标注置信度；
4. 低置信度发言人不得作为强结论依据。

---

## 7.4 投资观点抽取模块

### 7.4.1 两阶段处理架构

#### 阶段一：事实抽取 JSON

目标：从字幕中提取可验证、可引用、可入库的结构化对象。

输出对象包括：

- `mentioned_entities`：提到的公司、股票、基金、行业、政策、人物；
- `investment_views`：投资观点；
- `risks`：风险提示；
- `tracking_signals`：待验证信号；
- `key_quotes`：关键原文；
- `uncertain_items`：不确定或无法归因的信息。

#### 阶段二：研究报告 Markdown

目标：基于阶段一 JSON 生成非技术用户可读报告。

报告包括：

1. 免责声明；
2. 执行摘要；
3. 核心观点矩阵；
4. 标的/行业聚合；
5. 风险提示；
6. 待验证信号；
7. 分歧与不确定性；
8. 关键原文引用；
9. AI 处理说明。

### 7.4.2 投资观点核心字段

```json
{
  "target_name": "宁德时代",
  "target_type": "stock",
  "ticker": "300750",
  "market": "A股",
  "view_direction": "bullish",
  "view_direction_label": "看多",
  "logic_chain": "储能需求增长带动电池出货，海外业务仍有扩张空间",
  "time_horizon": "medium",
  "confidence": "cautious",
  "speaker_label": "嘉宾A",
  "speaker_confidence": "medium",
  "evidence": {
    "evidence_type": "行业数据/个人判断/财报/政策/估值/未给依据",
    "evidence_detail": "原文中提到的具体依据",
    "evidence_strength": "medium",
    "missing_info": "缺少具体财报数据或估值水平"
  },
  "risk_warning": "海外政策与价格竞争风险",
  "actionability": {
    "is_actionable": false,
    "action_type": "research_followup",
    "required_followup": ["查看最新财报", "跟踪储能订单数据"]
  },
  "source_quote": "原文关键句",
  "timestamp_start": "00:32:10",
  "timestamp_end": "00:32:45"
}
```

### 7.4.3 观点入库规则

只有满足以下条件的内容才进入核心观点表：

1. 明确出现投资标的、行业、基金、资产类别或宏观变量；
2. 明确表达方向或判断；
3. 有原文引用；
4. 有时间戳；
5. 不属于模型推测。

不满足条件的内容进入：

- `uncertain_items`；
- `general_notes`；
- `non_investment_summary`。

---

## 7.5 报告管理模块

### 7.5.1 报告存储

每份报告保存：

- 单集元数据；
- 原始字幕哈希；
- 清洗后的文本；
- 事实抽取 JSON；
- Markdown 报告；
- 投资观点明细；
- 风险提示；
- 待验证信号；
- 使用的模型与 Prompt 版本。

### 7.5.2 报告展示

报告详情页结构：

1. 顶部：节目、单集、日期、分析时间、模型信息；
2. 免责声明；
3. 执行摘要；
4. 核心观点矩阵；
5. 标的/行业分组；
6. 风险提示；
7. 待验证信号；
8. 关键原文引用；
9. 不确定项；
10. 单报告问答入口。

### 7.5.3 报告重新分析

同一单集允许重新分析，系统保留历史版本：

- `report_version`；
- `prompt_version`；
- `model_name`；
- `analysis_timestamp`。

---

## 7.6 历史检索与 AI 问答模块

### 7.6.1 检索策略

P1 阶段不强制引入向量数据库。采用三层检索：

1. **结构化过滤**  
   按标的、行业、嘉宾、节目、日期、方向、时间维度过滤。

2. **SQLite FTS5 全文检索**  
   检索报告正文、逻辑链、原文引用、风险提示。

3. **LLM 归纳回答**  
   将候选观点、引用和报告元数据交给 LLM 归纳，输出带来源的回答。

### 7.6.2 全局问答输出要求

每个回答必须包含：

- 结论摘要；
- 分观点列表；
- 来源报告；
- 播客日期；
- 时间戳；
- 区分事实、原文观点、AI 归纳。

### 7.6.3 后续向量库扩展

当报告数量超过一定规模，或用户问法明显超出关键词检索能力时，可引入：

- Chroma；
- Qdrant；
- pgvector；
- SQLite-vec。

但 v1.1 不作为 P0/P1 强依赖。

---

## 7.7 多期对比模块

### 7.7.1 第一阶段只做“同一标的跨期对比”

为避免 P2 过大，优先实现：

- 用户选择一个标的；
- 系统列出所有相关观点；
- 按时间排序；
- 输出观点变化与分歧。

### 7.7.2 后续扩展

| 对比类型 | 说明 |
|---|---|
| 标的画像 | 某标的在所有播客中的观点分布。 |
| 嘉宾追踪 | 某嘉宾在不同节目/不同时间中的观点变化。 |
| 节目追踪 | 某节目长期讨论主题变化。 |
| 行业观点 | 某行业在不同节目中的共识与分歧。 |
| 待验证信号 | 历史节目中提出的“观察点”是否已经到期或被验证。 |

---

## 8. 技术架构

### 8.1 总体架构

```text
┌─────────────────────────────────────────────────────────────┐
│ Frontend / Desktop Shell                                    │
│ Next.js / React + shadcn/ui + TailwindCSS + Tauri            │
│ - 粘贴单集链接                                               │
│ - 分析任务进度                                               │
│ - 报告展示                                                   │
│ - 历史检索                                                   │
│ - 多期对比                                                   │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP / WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│ Backend Application Layer                                   │
│ FastAPI + Uvicorn                                           │
│ - API 路由                                                   │
│ - 任务调度                                                   │
│ - LLM 调用封装                                               │
│ - 报告生成                                                   │
│ - 本地配置管理                                               │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│ Data Adapter Layer                                          │
│ - YouTubeTranscriptAdapter (youtube-transcript-api)         │
│ - YtDlpAdapter (yt-dlp, 备用)                               │
│ - LocalSubtitleAdapter                                      │
│ - XyzDlAdapter (可选, P2)                                   │
│ - XyzApiAdapter (可选, P2)                                  │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│ Processing Pipeline                                         │
│ - SubtitleCleaner                                           │
│ - SpeakerRoleInferencer                                     │
│ - InvestmentFactExtractor                                   │
│ - ReportRenderer                                            │
│ - ReportIndexer                                             │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│ Local Storage                                                │
│ SQLite + local files                                         │
│ - signalvault.db                                        │
│ - subtitles/                                                 │
│ - reports/                                                   │
│ - logs/                                                      │
└─────────────────────────────────────────────────────────────┘
```

### 8.2 技术栈建议

| 层级 | 技术 | 说明 |
|---|---|---|
| 桌面壳 | Tauri v2 | 轻量桌面封装，适合本地工具。 |
| 前端 | React / Next.js + shadcn/ui + TailwindCSS | 易于快速搭建现代 UI。 |
| 后端 | FastAPI | Python 生态适合调用字幕工具、LLM 和文本处理。 |
| 数据库 | SQLite + FTS5 | 本地单用户足够；支持全文检索。 |
| ORM | SQLAlchemy 2.0 | 成熟稳定，便于迁移。 |
| 任务调度 | FastAPI BackgroundTasks / asyncio | P0 不引入 Celery/Redis。 |
| LLM 调用 | LiteLLM 或自建 OpenAI-compatible Client | 统一多模型接入。 |
| 字幕工具 | youtube-transcript-api Adapter | P0-B YouTube 字幕获取，通过 Adapter 隔离，不直接暴露给业务层。yt-dlp 作为备用。 |
| 日志 | Python logging + RotatingFileHandler | 保留本地诊断日志。 |

### 8.3 为什么 P0 不引入 Celery/Redis

P0 是单用户本地应用，并发为 1。引入 Celery/Redis 会增加安装和打包复杂度。建议：

- P0：使用 FastAPI BackgroundTasks 或 asyncio；
- P1/P2：如任务队列复杂度上升，再评估轻量任务表；
- 多用户服务端版：再引入 Celery/RQ/Arq。

---

## 9. 数据模型设计

### 9.1 podcasts

```sql
CREATE TABLE podcasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL DEFAULT 'xiaoyuzhou',
    source_podcast_id TEXT,
    name TEXT NOT NULL,
    cover_url TEXT,
    description TEXT,
    last_episode_date DATE,
    is_favorite BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 9.2 episodes

```sql
CREATE TABLE episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    podcast_id INTEGER,
    source TEXT NOT NULL DEFAULT 'xiaoyuzhou',
    source_episode_id TEXT UNIQUE,
    source_url TEXT,
    title TEXT NOT NULL,
    publish_date DATE,
    duration INTEGER,
    subtitle_status TEXT DEFAULT 'unknown',
    subtitle_path TEXT,
    subtitle_format TEXT,
    subtitle_hash TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (podcast_id) REFERENCES podcasts(id)
);
```

### 9.3 reports

```sql
CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id INTEGER NOT NULL,
    report_version INTEGER DEFAULT 1,
    task_id TEXT UNIQUE,

    focus_template_id INTEGER,
    custom_focus TEXT,
    analysis_depth TEXT,
    llm_provider TEXT,
    llm_model TEXT,
    prompt_version TEXT,

    raw_subtitle_hash TEXT,
    cleaned_text_path TEXT,

    extraction_json TEXT NOT NULL,
    report_markdown TEXT,
    executive_summary TEXT,

    analysis_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (episode_id) REFERENCES episodes(id)
);
```

### 9.4 investment_views

```sql
CREATE TABLE investment_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL,
    target_name TEXT,
    normalized_target_name TEXT,
    target_type TEXT,
    ticker TEXT,
    market TEXT,
    view_direction TEXT,
    confidence TEXT,
    time_horizon TEXT,
    logic_chain TEXT,
    evidence_type TEXT,
    evidence_detail TEXT,
    evidence_strength TEXT,
    missing_info TEXT,
    risk_warning TEXT,
    speaker_label TEXT,
    speaker_role TEXT,
    speaker_confidence TEXT,
    source_quote TEXT,
    timestamp_start TEXT,
    timestamp_end TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (report_id) REFERENCES reports(id)
);
```

### 9.5 tracking_signals

```sql
CREATE TABLE tracking_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL,
    target_name TEXT,
    signal TEXT,
    trigger_condition TEXT,
    expected_date TEXT,
    status TEXT DEFAULT 'open',
    source_quote TEXT,
    timestamp TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (report_id) REFERENCES reports(id)
);
```

### 9.6 entities

```sql
CREATE TABLE entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    normalized_name TEXT,
    entity_type TEXT,
    aliases TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 9.7 qa_logs

```sql
CREATE TABLE qa_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    scope TEXT NOT NULL,
    retrieved_context TEXT,
    answer TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 10. 核心业务流程

### 10.1 P0-A 本地字幕分析流程

```text
[用户提供本地 .srt / .vtt / .txt 字幕文件]
    → [CLI 输入文件路径]
    → [字幕格式识别]
    → [字幕解析，输出 segments + timestamp map]
    → [字幕清洗：去空行、合并短段、去重、标记疑似广告]
    → [LLM 阶段一（mock）：事实抽取 JSON]
    → [校验 JSON Schema]
    → [入库 investment_views / tracking_signals / entities]
    → [LLM 阶段二（mock）：生成 Markdown 报告]
    → [保存 report + 写出 Markdown 文件]
    → [CLI 输出摘要]
```

### 10.1b P0-B YouTube 字幕分析流程

```text
[用户提供 YouTube 视频 URL]
    → [CLI 输入 --youtube <url>]
    → [URL 解析与验证]
    → [youtube-transcript-api 获取字幕]
    → [转换为统一 TranscriptSegment]
    → [复用 P0-A 字幕清洗 → mock 抽取 → 渲染 → 入库流程]
    → [CLI 输出摘要]
```

### 10.2 P1 历史检索流程

```text
[用户输入标的/关键词/嘉宾]
    → [结构化字段过滤]
    → [SQLite FTS5 检索报告正文和引用]
    → [合并候选观点]
    → [LLM 归纳回答]
    → [输出答案 + 来源报告 + 时间戳]
```

### 10.3 P2 对比分析流程

```text
[用户选择标的或多份报告]
    → [读取 investment_views]
    → [按时间排序]
    → [聚合方向、逻辑、证据、风险]
    → [LLM 分析观点变化]
    → [输出观点时间线 / 共识分歧 / 待验证信号]
    → [保存 comparison_result]
```

---

## 11. Prompt 工程规范

### 11.1 总体原则

1. 先抽取事实，再生成报告；
2. 所有结论必须有原文引用；
3. 不得把 AI 推测写成嘉宾观点；
4. 不得输出投资建议；
5. 无法确定的信息进入不确定项；
6. JSON 输出必须通过 schema 校验。

### 11.2 阶段一：事实抽取 Prompt 目标

角色：投资播客事实抽取器。  
任务：只从原文中抽取事实、观点、风险、信号，不做投资建议。

输出字段：

```json
{
  "metadata": {},
  "mentioned_entities": [],
  "investment_views": [],
  "risks": [],
  "tracking_signals": [],
  "key_quotes": [],
  "uncertain_items": []
}
```

### 11.3 阶段二：报告生成 Prompt 目标

角色：投资研究内容整理助手。  
任务：基于阶段一 JSON 生成清晰、可读、带免责声明的研究报告。

报告必须包含：

- 免责声明；
- 执行摘要；
- 核心观点矩阵；
- 风险提示；
- 待验证信号；
- 不确定项；
- 原文引用。

### 11.4 全局问答 Prompt 目标

基于检索到的结构化观点和原文引用回答用户问题。输出必须区分：

- 播客原文明确表达；
- AI 归纳总结；
- 信息不足；
- 不构成投资建议。

---

## 12. 非功能需求

### 12.1 性能目标

| 指标 | P0 目标 |
|---|---|
| 单集链接解析 | < 5 秒 |
| 字幕检测 | < 15 秒 |
| 字幕下载 | < 30 秒 |
| 字幕清洗 | < 10 秒 |
| 单期分析总耗时 | < 180 秒 |
| 报告打开 | < 2 秒 |
| 历史报告检索 | < 1 秒 |

### 12.2 可用性目标

1. 用户只需要复制链接、选择模板、点击分析；
2. 不暴露 CLI、Token、device_id、base_url 等技术概念；
3. 错误信息使用普通语言解释；
4. 分析过程显示步骤进度；
5. 分析失败允许重试；
6. 已下载字幕和已生成中间结果可复用。

### 12.3 可靠性目标

1. 字幕下载失败时记录日志；
2. LLM 调用失败时自动重试 2 次；
3. JSON 解析失败时尝试修复一次；
4. 任务中断后保留中间文件；
5. 数据库写入使用事务；
6. 所有报告可追溯 prompt_version 和 model_name。

### 12.4 安全与合规目标

1. API Key 本地加密存储；
2. 字幕和报告默认只保存在本地；
3. 不上传用户历史报告到非用户配置的服务；
4. 遵守播客平台协议，禁止高频抓取；
5. 报告必须包含投资风险免责声明；
6. 不输出“应买入/应卖出/目标价”等操作性建议。

---

## 13. 五步工程化落地顺序

### 第一步：CLI 本地字幕验证器（P0-A）

#### 目标

先不做复杂前端，验证核心链路能否跑通。

#### 输入示例

```bash
python -m signalvault analyze data/subtitles/sample.srt --mock
```

#### 输出目录

```text
data/
  subtitles/
  reports/
  signalvault.db
logs/
```

#### 必须验证

1. 字幕是否能正确解析；
2. 字幕清洗是否可用；
3. mock LLM 是否能稳定输出 JSON；
4. 报告是否能落盘；
5. SQLite 是否能保存结构化观点；
6. CLI mock 模式是否能完整跑通。

#### 验收标准

使用 1-2 个本地中文投资播客字幕文件测试，mock 模式下 100% 能生成可读报告并成功入库。

---

### 第二步：YouTube 字幕 Adapter（P0-B）

#### 目标

接入 YouTube 作为第一个外部数据源，复用 P0-A pipeline。

#### 功能

1. YouTube URL 解析与验证；
2. youtube-transcript-api 字幕获取；
3. 字幕 → TranscriptSegment 转换；
4. CLI `--youtube <url>` 支持；
5. 无字幕降级提示；
6. yt-dlp 备用方案（可选）。

#### 验收标准

使用 2-3 个中文投资访谈 YouTube 视频链接测试，mock 模式下能获取字幕并生成可读报告。

---

### 第三步：本地报告查看页

#### 目标

在核心链路跑通后，做最小报告 UI。

#### 功能

1. 报告列表；
2. 报告详情；
3. 核心观点矩阵；
4. 原文引用与时间戳；
5. 标的筛选；
6. 风险提示与待验证信号展示。

#### 验收标准

用户可以不打开文件夹，直接在浏览器/桌面窗口中查看报告。

---

### 第四步：YouTube 链接一键分析 UI

#### 目标

形成非 IT 用户可用的最小产品入口。

#### 功能

1. 粘贴 YouTube 视频链接；
2. 自动获取字幕；
3. 选择关注点模板；
4. 点击”开始分析”；
5. 显示进度条；
6. 完成后自动打开报告；
7. 失败时显示可理解的错误信息。

#### 验收标准

非 IT 用户无需命令行即可完成一次完整分析。

---

### 第五步：历史报告全局查询

#### 目标

让工具从“单次摘要工具”升级为“本地研究库”。

#### 功能

1. 按标的查询；
2. 按嘉宾查询；
3. 按节目查询；
4. 按日期查询；
5. 全局问答；
6. 回答带来源和时间戳。

#### 技术路线

先用：

- SQLite 结构化表；
- SQLite FTS5；
- LLM 归纳。

暂不强依赖向量数据库。

#### 验收标准

用户输入“宁德时代”“港股红利”“新能源”等关键词，可以看到相关观点和来源报告。

---

### 第六步：多期观点对比

#### 目标

实现项目的核心差异化能力：观点追踪。

#### 第一版范围

只做“同一标的跨期观点变化”。

#### 功能

1. 选择标的；
2. 展示该标的历史观点列表；
3. 按时间排序；
4. 识别方向变化；
5. 汇总共识与分歧；
6. 输出待验证信号。

#### 验收标准

用户可以看到某个标的在不同播客/不同时间中的观点变化，而不是只能看到单期摘要。

---

## 14. 开发里程碑建议

| 阶段 | 时间建议 | 主要产出 |
|---|---|---|
| Week 1 | P0-A CLI 验证 | 字幕解析、清洗、mock LLM JSON 抽取、SQLite 入库（已完成） |
| Week 2 | P0-B YouTube Adapter | YouTube URL 解析、youtube-transcript-api 字幕获取、TranscriptSegment 转换、CLI --youtube |
| Week 3 | 报告生成与 Schema 稳定 | Markdown 报告、JSON Schema 校验、投资观点表设计 |
| Week 4 | 最小 Web UI | 报告列表、详情页、观点矩阵、进度展示 |
| Week 5 | YouTube 链接一键分析 UI | 粘贴链接、模板选择、任务进度、错误提示 |
| Week 6 | 历史检索 | 结构化过滤、FTS5、全局问答第一版 |
| Week 7 | 标的对比 | 同一标的跨期观点变化、对比报告保存 |

---

## 15. 验收标准

### 15.1 P0-A 验收标准

- [ ] 可通过 CLI 输入本地 .srt / .vtt / .txt 字幕文件路径；
- [ ] 可解析字幕并保留时间戳；
- [ ] 可清洗字幕；
- [ ] mock LLM 可生成事实抽取 JSON；
- [ ] mock LLM 可生成 Markdown 报告；
- [ ] 报告包含免责声明；
- [ ] 每条核心观点包含原文引用和时间戳；
- [ ] 报告可保存到 SQLite；
- [ ] CLI mock 模式完整跑通；
- [ ] 所有 pytest 测试通过。

### 15.1b P0-B 验收标准

- [ ] 可通过 CLI 输入 YouTube 视频 URL（--youtube）；
- [ ] 可解析 YouTube URL 并获取视频元数据；
- [ ] youtube-transcript-api 可获取字幕并转为 TranscriptSegment；
- [ ] 无字幕视频提示降级信息；
- [ ] 复用 P0-A 分析 pipeline 生成完整报告；
- [ ] YouTube 相关 Adapter 测试通过。

### 15.2 P1 验收标准

- [ ] 可查看历史报告；
- [ ] 可按标的、节目、日期、关键词筛选；
- [ ] 可针对单报告提问；
- [ ] 可全局查询历史观点；
- [ ] 回答包含来源报告和时间戳。

### 15.3 P2 验收标准

- [ ] 可调用真实 LLM API 生成事实抽取 JSON；
- [ ] 可调用真实 LLM API 生成 Markdown 报告；
- [ ] 小宇宙链接可选接入（Adapter）；
- [ ] 说话人推断逻辑可用；
- [ ] LLM Provider 可在 mock/real 间切换。

### 15.4 P3 验收标准

- [ ] 可选择某一标的；
- [ ] 可展示该标的历史观点；
- [ ] 可输出观点变化时间线；
- [ ] 可识别共识、分歧和方向变化；
- [ ] 可保存对比报告。

---

## 16. 风险与缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|---|---|---|---|
| YouTube 字幕覆盖率不足 | 中 | 高 | P0-B 前用目标视频样本测试；youtube-transcript-api + yt-dlp 双方案降级；后续 Whisper 兜底 |
| YouTube 字幕 API 变化 | 低 | 中 | Adapter 隔离；yt-dlp 作为备用方案 |
| 小宇宙接口/xyz-dl 不稳定 | 高 | 中 | 降级为可选 Adapter，P0 不依赖 |
| 说话人推断不准 | 高 | 中 | 标注置信度；不承诺真实身份；低置信度不进入强结论 |
| LLM 编造观点 | 中 | 高 | 强制引用和时间戳；JSON Schema 校验；无引用不得入核心观点 |
| 非 IT 用户配置困难 | 中 | 中 | 服务商预设；默认模板；隐藏高级配置 |
| 投资合规风险 | 中 | 高 | 强免责声明；禁止输出买卖建议；区分原文观点和 AI 归纳 |

---

## 17. 后续版本规划

### v1.1

- 标的画像自动聚合；
- 嘉宾追踪视图；
- 待验证信号状态管理；
- 报告导出 Markdown / Obsidian。

### v1.2

- 无字幕播客本地 Whisper / faster-whisper 兜底；
- RSS 输入；
- 多平台播客链接解析；
- 本地模型/Ollama 支持。

### v2.0

- 团队共享报告库；
- 服务端部署；
- 向量数据库增强检索；
- 定时抓取与推送；
- 标的行情/财报外部数据交叉验证。

---

## 18. 附录：建议给 Claude Code / Codex 的执行边界

### 18.1 第一轮只实现 P0 CLI

不要一开始生成完整桌面应用。第一轮目标是：

1. 建立项目目录；
2. 实现 Pydantic 数据模型；
3. 实现 SQLAlchemy ORM 与 SQLite 入库；
4. 实现字幕解析与清洗；
5. 实现 mock LLM provider；
6. 实现分析 pipeline；
7. 实现 Markdown 报告渲染；
8. 实现 CLI 命令。

### 18.2 第二轮再做最小 UI

在 CLI 跑通后，再做：

1. FastAPI API；
2. 报告列表 API；
3. 报告详情 API；
4. 前端报告页。

### 18.3 不要提前做的事项

1. 不要先做账号系统；
2. 不要先做团队协作；
3. 不要先做向量库；
4. 不要先做复杂桌面打包；
5. 不要先做多平台；
6. 不要先做自动推送；
7. 不要先做音频转写。

---

## 19. 参考项目链接

### YouTube 数据源（P0-B 重点参考）
- jdepoix/youtube-transcript-api：<https://github.com/jdepoix/youtube-transcript-api>
- yt-dlp/yt-dlp：<https://github.com/yt-dlp/yt-dlp>
- haron/yt-dlp-transcript：<https://github.com/haron/yt-dlp-transcript>
- RAG-YouTube-QNA-summarizer：<https://github.com/RAG-YouTube-QNA-summarizer>
- YouTubeRAG：<https://github.com/YouTubeRAG>

### 小宇宙数据源（后续可选 Adapter）
- ultrazg/xyz：<https://github.com/ultrazg/xyz>
- shiquda/xyz-dl：<https://github.com/shiquda/xyz-dl>
- ultrazg/horizon：<https://github.com/ultrazg/horizon>

### 播客处理与知识库
- wendy7756/podcast-transcriber：<https://github.com/wendy7756/podcast-transcriber>
- winterfx/Podcast-Transcription：<https://github.com/winterfx/Podcast-Transcription>
- rrrrrredy/xiaoyuzhou-podcast：<https://github.com/rrrrrredy/xiaoyuzhou-podcast>
- haasonsaas/parakeet-podcast-processor：<https://github.com/haasonsaas/parakeet-podcast-processor>
- MichaelShoemaker/history_of_rome_podcast_llm：<https://github.com/MichaelShoemaker/history_of_rome_podcast_llm>
- deanpeters/lennysan-rag-o-matic：<https://github.com/deanpeters/lennysan-rag-o-matic>
- allenhutchison/podcast-rag：<https://github.com/allenhutchison/podcast-rag>
- transcriptionstream/transcriptionstream：<https://github.com/transcriptionstream/transcriptionstream>

---

## 20. 总结

本项目第一阶段不应被定义为”一个完整播客平台”或”万能音视频总结器”，而应被定义为：

> 一个面向非 IT 用户的本地投资音视频研究助手，优先基于本地字幕和 YouTube 已有字幕，将单期音视频内容转化为带引用、带时间戳、可入库、可检索、可对比的投资观点结构化资料。

最短落地路径是：

1. CLI 验证本地字幕核心链路（P0-A）；
2. YouTube 字幕 Adapter（P0-B）；
3. 本地报告查看页；
4. YouTube 链接一键分析 UI；
5. 历史报告全局查询；
6. 多期观点对比。

只要这六步跑通，项目就能从”音视频摘要工具”升级为”可长期沉淀的个人投资研究资料库”。
