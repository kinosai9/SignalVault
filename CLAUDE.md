---

# CLAUDE.md

## 项目名称

投资音视频研究助手 / Investment Media Research Assistant

## 项目定位

本项目是一个面向非 IT 用户的本地化音视频研究工具，用于从 YouTube 投资访谈、播客字幕和本地字幕文件等公开音视频内容中，结构化提取投资观点、标的、风险提示、待验证信号和关键原文引用。

本项目不是投资建议工具，不提供买入、卖出、持有等决策建议。

## 当前阶段

P0 全部完成（P0-A 本地字幕 + P0-B YouTube 字幕，82 tests passed）。
P1-A 已完成（CLI 报告库查询）。
P1-B 已完成（FastAPI 只读 API，129 tests passed）。

**P0 已跑通：**

本地字幕文件 / YouTube URL → 解析 → 清洗 → mock/真实 LLM 抽取 → Markdown 报告 → SQLite 入库 → CLI 输出。

**P1-A 已跑通：**

`reports list / show / search / targets / sources` 子命令查询已入库报告，Rich 表格输出。

**P1-B 已跑通：**

FastAPI 本地只读 API（`/api/reports`, `/api/reports/{id}`, `/api/search` 等 9 个端点），`serve` 命令启动 uvicorn。API 测试复用 `db_session` fixture 实现数据库隔离。

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
- 不做 Jinja2 HTML 页面（留给 P1-C）。
- 不做鉴权、登录、CORS 配置（本地单用户场景）。

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