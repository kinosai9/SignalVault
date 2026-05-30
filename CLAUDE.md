---

# CLAUDE.md

## 项目名称

投资音视频研究助手 / Investment Media Research Assistant

## 项目定位

本项目是一个面向非 IT 用户的本地化音视频研究工具，用于从 YouTube 投资访谈、播客字幕和本地字幕文件等公开音视频内容中，结构化提取投资观点、标的、风险提示、待验证信号和关键原文引用。

本项目不是投资建议工具，不提供买入、卖出、持有等决策建议。

## 当前阶段

P2-A2.1（Channel/Video Metadata Propagation）+ P2-A2（跨频道 Prompt v2 质量评估）已完成。P0-A 到 P2-A2 全部交付。

**P0 已跑通：**

本地字幕文件 / YouTube URL → 解析 → 清洗 → mock/真实 LLM 抽取 → Markdown 报告 → SQLite 入库 → CLI 输出。

**P1-A 已跑通：**

`reports list / show / search / targets / sources` 子命令查询已入库报告，Rich 表格输出。

**P1-B 已跑通：**

FastAPI 本地只读 API（`/api/reports`, `/api/reports/{id}`, `/api/search` 等 9 个端点），`serve` 命令启动 uvicorn。API 测试复用 `db_session` fixture 实现数据库隔离。

**P1-C 已跑通：**

Jinja2 HTML 页面（`/reports`, `/reports/{id}`, `/search`），极简 CSS，复用现有 repository 查询层。不做复杂前端框架。`web/` 与 `api/` 分离：api/ 提供 JSON，web/ 提供 HTML。

**P1-D 已跑通：**

SQLite FTS5 全文搜索，CJK 字符逐字索引。`search_reports` 优先 FTS5，不可用时 fallback LIKE。

**P1-F 已跑通：**

`channels seed-tech-ai` 播种 5 个核心频道 → `channels list --tag ai --priority core` 过滤 → `channels tag <id> --add/--remove/--set` 标签管理。

**P1-E 已跑通：**

YouTube 频道关注（`channels add/list/refresh/videos/analyze-video`），yt-dlp 获取频道视频列表，频道视频状态管理（new/analyzed/skipped），视频去重。168 tests passed。

## 数据源优先级

| 优先级 | 数据源 | 阶段 |
|---|---|---|
| 1 | 本地字幕文件（.srt / .vtt / .txt） | P0-A |
| 2 | YouTube 视频字幕（youtube-transcript-api） | P0-B |
| 3 | yt-dlp / yt-dlp-transcript（YouTube 字幕备用） | P0-B 可选 |
| 4 | 小宇宙 xyz / xyz-dl | P2 可选 Adapter |
| 5 | Whisper 本地转写 | 后续版本 |

## 架构边界

### adapters/ — 数据源适配层

`adapters/` 只负责数据源适配，将不同来源的字幕/文本转换为统一的 TranscriptSegment 格式。

已规划或实现的 Adapter：

| Adapter | 数据源 | 阶段 |
|---|---|---|
| LocalSubtitleAdapter | 本地 .srt/.vtt/.txt 文件 | P0-A（已通过 subtitles/parser 实现） |
| YouTubeTranscriptAdapter | youtube-transcript-api | P0-B |
| YtDlpAdapter | yt-dlp 字幕下载 | P0-B 可选 |
| XyzDlAdapter | xyz-dl 小宇宙字幕 | P2 可选 |
| XyzApiAdapter | 小宇宙 API | P2 可选 |
| ManualTextAdapter | 手工粘贴文本 | 后续 |

注意：当前 P0-A 的字幕解析逻辑在 `subtitles/parser.py` 中实现，尚未迁移到 `adapters/` 目录。这不影响 P0-A 功能，P0-B 实现 YouTube Adapter 时需统一 Adapter 入口。

### llm/ — 模型供应商适配层

`llm/` 只负责模型供应商适配，不涉及数据源获取。

| Provider | 说明 | 阶段 |
|---|---|---|
| MockLLMProvider | 规则引擎 mock，P0-A/P0-B 默认 | P0-A（已实现） |
| OpenAICompatibleProvider | httpx + OpenAI-compatible API | P2 |
| GeminiProvider | Google Gemini API | 后续可选 |

**边界规则：不要把 LLM provider 强行移入 adapters/。** adapters 适配数据，llm 适配模型，职责不同。

### P0-A LLM 使用规则

- P0-A 默认使用 mock provider 进行测试，保证测试可稳定运行。
- 真实 LLM（OpenAI-compatible provider）只作为手动集成验证，不在自动化测试中调用。
- CLI `--no-mock` 切换到真实 LLM，但需要 .env 中配置 LLM_API_KEY。

### Mock Provider 定位

- mock provider 是基于中文关键词匹配的规则引擎，**仅用于工程闭环测试**。
- mock provider 不代表真实语义抽取能力。
- 英文字幕、复杂投资观点、隐含逻辑链需要使用真实 LLM provider。
- 默认 pytest 使用 mock provider，不调用真实 API。
- 真实 LLM 测试作为手动集成验证，不进入默认测试。
- 英文视频在 mock 模式下输出 0 条观点是预期行为，不是 bug。
- 不要为了提升 mock 英文输出而扩展英文关键词规则，除非非常轻量且不影响工程测试定位。

### 真实 LLM 手动验证规则

- 真实 LLM 调用命令仅作为手动验证，不进入自动化测试。
- 调用前确保 `.env` 配置正确（LLM_PROVIDER / LLM_API_KEY / LLM_BASE_URL / LLM_MODEL）。
- 长视频（2000+ 段字幕）可能触发 token 上限，当前不实现分块处理。
- 失败时优先检查 `logs/` 日志，不要将 API Key 打印到终端或日志。

## 核心原则

1. 先跑通最短闭环，再做 UI。
2. 先支持本地字幕文件，再接入 YouTube 字幕 Adapter。
3. 先使用 mock LLM，确保测试可稳定运行。
4. P0 不依赖小宇宙，不接入 xyz-dl，不调用真实 LLM API。
5. 所有核心投资观点必须绑定原文引用和时间戳。
6. 不允许输出投资建议。
7. 不允许将 AI 推断伪装成嘉宾原话。
8. 对不确定内容必须显式标注。
9. 所有外部依赖必须通过 adapter 隔离。
10. 面向非 IT 用户，错误提示要可理解。
11. 每次修改后必须说明改动内容、测试结果和下一步建议。

## 禁止在 P0 实现的内容

- 真实 LLM API 调用（手动验证除外）
- 小宇宙链接接入和 xyz-dl 字幕下载
- YouTube 视频下载
- YouTube 频道批量分析
- Tauri 桌面封装
- Next.js 完整前端
- Whisper 本地转写
- 多平台 RSS 支持
- 钉钉/微信推送
- PDF/Word 导出
- 团队协作
- 云端同步
- 向量数据库

## P1-A 范围规则

- P1-A 仍然是 CLI-first，不做 FastAPI、HTML 页面、Web UI。
- 搜索使用 LIKE，不上 FTS5。
- 不做 RAG、向量数据库、AI 问答。
- 不做跨报告对比、观点变化时间线。
- source_type 通过运行时推断（video_id / source_url），不新增 DB 列。
- reports 子命令通过 `ctx.invoked_subcommand` 守卫实现，不破坏现有分析命令。

## P1-B 范围规则

- P1-B 是只读 API 层，不做分析任务提交、报告编辑/删除、AI 问答、多报告对比。
- API 层不写复杂 SQL，只复用 repository 查询函数。
- FastAPI app 使用 `create_app()` 工厂模式，支持测试注入临时数据库。
- API 测试复用 `db_session` fixture 实现数据库隔离，不访问真实 `data/podcast_analyst.db`。
- `serve` 命令默认绑定 127.0.0.1:8000，不作为公共服务暴露。
- 不做鉴权、登录、CORS 配置（本地单用户场景）。

## P1-C 范围规则

- P1-C 是只读 HTML 页面层，复用现有 API routes 和 repository 查询层。
- `web/` 与 `api/` 分离：api/ 返回 JSON，web/ 返回 HTML。
- Jinja2 模板渲染，不做 React / Next.js / Vue / SPA。
- CSS 极简：白底、系统字体、表格可读，不引入 Tailwind / Bootstrap。
- HTML 页面测试复用 `seeded_db` + `api_client` fixtures，不污染真实 data/。
- 不做：报告编辑/删除、AI 问答、多报告对比、FTS5、复杂图表。
- 不做：Jinja2X 高级模板、宏、自定义 filter（保持模板简单）。
- 不做：分页（当前单页展示全部，数据量少时不引入复杂度）。

## P1-D 范围规则

- P1-D 使用 SQLite FTS5 增强全文搜索，不引入外部搜索引擎（Elasticsearch、MeiliSearch 等）。
- FTS5 虚拟表为可重建索引，不作为主数据源。主数据仍在 reports / investment_views / entities / tracking_signals 表中。
- 搜索策略：优先 FTS5 → FTS 失败或无数据时 fallback LIKE。
- CJK 预处理：索引和查询时在 CJK 字符间插入空格，确保 unicode61 tokenizer 能逐字索引。
- CLI/API/HTML 接口不变，用户无感知。
- 不做：向量数据库、RAG 问答、LLM 搜索重排、复杂中文分词器（jieba 等）。

## P1-E 范围规则

- yt-dlp 仅用于获取频道视频元数据（--flat-playlist），不下载视频/音频。
- channels 表存储关注的频道，channel_videos 存储视频元数据和状态。
- 视频去重按 channel_id + video_id。
- 默认不做自动分析，必须手动 `channels analyze-video`。
- 已分析视频默认跳过，dry-run 模式先检查。
- 批量分析必须有 `--max-analyze` 限制，防止误操作全频道分析。
- 测试中 mock yt-dlp 输出，不访问真实 YouTube。
- 不做：自动定时抓取、YouTube Data API、频道推荐、评论抓取、RAG。

## P1-F 范围规则

- channels 表扩展 tags / priority / default_focus / default_limit / default_max_analyze / notes 字段。
- tags 存 JSON 数组字符串，不做复杂 channel_tags 多对多表。
- tag 查询用 Python 层 JSON 解析过滤，数据量小无需复杂化。
- priority 取值 core / secondary / archive。
- seed-tech-ai 必须幂等：重复执行不重复插入，按 youtube_channel_id 去重。
- 默认不新增自动分析命令，analyze-video 保持原行为（默认 mock，真实 LLM 需显式 --no-mock）。
- 不做：自动批量真实 LLM、Obsidian 导出、RAG、多对多 tags 表。

## P2-A1 范围规则

- 本轮只做 prompt/schema/report 增强，不做 Obsidian、RAG、多报告对比、长视频 chunking。
- extract_facts() 新增 focus_areas 参数，向后兼容（默认 None）。
- InvestmentView 新增 7 个可选字段，全部有默认值，不影响旧代码和旧 JSON。
- ExtractionResult 新增 prompt_version（默认 "tech_ai_v2"）、tech_industry_insights、non_focus_items。
- evidence_type 枚举升级为 10 个值，旧值如 "未给依据" 不再使用（改为 unsupported_claim）。
- time_horizon 默认 "unknown"，不允许空字符串。
- speaker_label 默认 "unknown_speaker"，speaker_role 默认 "podcast_participant"。
- 真实 LLM 测试不进默认 pytest。手动验证用 --no-mock。

## P2-A1 Hardening 规则

- target_name 禁止过于宽泛的名称（Broad Market / Economy / AI Industry / Technology Sector 等）。
- investment_relevance 严格分级：high/medium/low，high 不超过 40%，无具体证据不得高于 medium。
- TechIndustryInsight 增加 topic_tags 字段，支持 Obsidian Topic Card 等后续应用的 topic signal。
- 报告 Tech/Industry Insights 章节展示 topic_tags。
- 以上规则已写入 EXTRACT_FACTS_SYSTEM prompt，通过 7 个 hardening 测试验证。

## P2-A2.1 范围规则

- channels analyze-video 自动从 channels/channel_videos 表补齐频道名、视频标题、URL、发布时间。
- source_info_override 优先级：channel_videos.title > YouTube adapter title > video_id。
- metadata 通过 analyze_from_transcript(source_info_override=) 传递到 pipeline。
- 普通 --youtube-url 路径不受影响（无频道元数据仍正常运行）。
- Markdown 报告数据来源部分展示：来源频道、视频标题、视频 ID、视频链接、发布日期、字幕语言、频道标签。
- 测试不污染 data/。

## P2-A2 范围规则

- 跨频道评估工具：eval reports / export / summary CLI 子命令。
- 评估统计基于 DB 中已存在的 reports + extraction_json + investment_views。
- Generic target 检测：Broad Market、Economy、Investors、Consumers、Society、AI Industry、Technology Sector、Market、Companies、Startups（共 10 个）。
- CSV 导出含 22 个字段，Markdown 总结按频道分组。
- 测试复用 seeded_db fixture，CSV/MD 输出到 tmp_path，不污染 data/。
- 不做 prompt 修改、chunking、Obsidian、RAG。

## P2-B 范围规则

- P2-B 实现长视频分块分析（Long Transcript Chunking），解决 2000+ 段字幕 token 超限问题。
- chunking 策略：按 segment 边界拆分，保留上下文重叠窗口，map-reduce 合并。
- 不分块的短字幕行为完全不变。
- 不引入 LangChain / LlamaIndex 等外部编排框架。

## 技术栈

- Python 3.12+
- Typer
- FastAPI
- uvicorn
- Pydantic v2
- SQLAlchemy 2.x
- SQLite
- Jinja2（预留给 P1/P2 模板化报告渲染，P0-A 继续允许 mock/LLM 直接生成 Markdown）
- httpx
- python-dotenv
- youtube-transcript-api（P0-B）
- yt-dlp（P0-B 可选）
- pytest
- rich
- logging

## Jinja2 定位

Jinja2 依赖已声明在 pyproject.toml，但 P0-A 报告生成未使用。定位：

- **P0-A/P0-B**：报告由 mock provider 拼接或真实 LLM 生成 Markdown，不使用 Jinja2。
- **P1/P2**：Jinja2 用于模板化报告渲染（结构化报告模板、报告导出格式切换等），届时再启用。
- 当前不做大规模改造，保留依赖即可。

## Pipeline 规则

1. 不要重写 pipeline。`analyze()` 和 `analyze_from_transcript()` 共用 `_run_pipeline()` 内部逻辑。
2. 修改 pipeline 时必须确保本地字幕路径调用不受影响。
3. YouTube 模式通过 `analyze_from_transcript()` 进入，不修改 `analyze()` 签名。

## Mock 测试规则

1. 所有 YouTube adapter 测试必须 mock `YouTubeTranscriptApi`，不调用真实 API。
2. 所有 CLI YouTube 测试必须 mock adapter，不依赖网络。
3. `NoTranscriptFound` 构造函数需要 3 个参数（video_id, requested_language_codes, transcript_data），测试中用 MagicMock() 作为 transcript_data。
4. 真实 YouTube 视频集成验证仅作为手动操作，不在自动化测试中执行。

LLM 分析必须分两阶段：

1. 事实抽取 JSON
2. 报告 Markdown 生成

核心观点字段至少包括：

- target_name
- target_type
- view_direction
- logic_chain
- evidence_type
- evidence_strength
- risk_warning
- speaker_label
- speaker_confidence
- source_quote
- timestamp
- uncertainty

没有 source_quote 和 timestamp 的内容不得进入核心观点矩阵。

## API Key 安全规则

1. API Key 不得写入代码。
2. `.env` 不得提交 Git。
3. `.gitignore` 必须排除 `.env` 和 `.env.local`。
4. 日志不得打印完整 API Key。
5. README 只提供 `.env.example`，不提供真实 `.env` 内容。
6. 如果 `.env` 曾进入 Git 历史，必须立即更换 API Key。
7. YouTube API 使用不需要 API Key（youtube-transcript-api 免认证）。
8. 后续接入小宇宙认证信息时，必须通过配置文件或环境变量读取。

## 测试要求

每次新增核心功能必须补测试。

P0-A 最低测试覆盖（已完成）：

- 字幕解析
- 字幕清洗
- mock LLM pipeline
- SQLite 写入
- Markdown 报告生成
- CLI mock 模式运行
- CLI --focus/--depth 参数

P0-B 最低测试覆盖（已实现）：

- YouTube URL 解析与验证（test_youtube_utils.py）
- youtube-transcript-api mock 字幕获取（test_youtube_transcript_adapter.py）
- 字幕 → SubtitleSegment 格式转换
- 缓存读写
- YouTube CLI 模式运行（test_cli.py mock --youtube-url）
- 无字幕视频降级提示
- 语言 fallback

P0-B 待做：

- 真实 YouTube 投资访谈视频链接集成验证（手动）
- YouTube 视频元数据获取（标题、频道名等）

## 每次任务完成后的汇报格式

请按以下格式汇报：

```markdown
## 本轮完成

- ...

## 修改文件

- ...

## 运行命令

```bash  
```

## 测试结果

- ...

## 风险与待确认

- ...

## 下一步建议

- ...