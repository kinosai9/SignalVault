# TODO.md

## P0-A：本地字幕分析闭环

> P0-A 输入源仅限本地 .srt / .vtt / .txt 字幕文件。
> 数据模型 5 张核心表：episodes, reports, investment_views, tracking_signals, entities。
> P0-A 不接入 YouTube、小宇宙链接、xyz-dl、真实 LLM API。
> P0-A 默认使用 mock provider 测试，真实 LLM 只作为手动集成验证。

### 0. 项目初始化

- [x] 创建 pyproject.toml（依赖声明 + entry point）
- [x] 创建 .env.example
- [x] 创建 .gitignore
- [x] 创建完整目录骨架 + __init__.py

### 1. 配置与日志

- [x] 实现 config.py（.env 加载 + mock/real provider 切换）
- [x] 实现 logging_config.py（console + RotatingFileHandler → logs/）

### 2. 数据模型

- [x] 实现 Pydantic 数据模型（analysis/models.py：ExtractionResult, InvestmentView, TrackingSignal 等）
- [x] ExtractionResult 增加 focus_areas 字段
- [x] 实现 SQLAlchemy ORM（db/models.py：5 张核心表）
- [x] Report 表增加 focus_areas、analysis_depth 字段
- [x] 实现 db/session.py（engine, SessionLocal, init_db）
- [x] 实现 db/repository.py（基础写入方法，含 focus_areas）
- [x] 编写 test_db.py

### 3. 字幕解析与清洗

- [x] 实现 SRT parser（subtitles/parser.py）
- [x] 实现 TXT parser
- [x] 实现 VTT parser（WebVTT 格式支持）
- [x] 实现 subtitles/cleaner.py（去空行、合并短段、去重、标记疑似广告）
- [x] 创建 sample.srt 示例文件
- [x] 编写 test_parser.py
- [x] 编写 test_cleaner.py

### 4. LLM 抽象

- [x] 定义 LLMProvider base class（llm/base.py）
- [x] 实现 MockLLMProvider（llm/mock_provider.py）
- [x] MockLLMProvider render_report 展示 focus_areas
- [x] 设计事实抽取 prompt 模板（llm/prompts.py）
- [x] 设计报告生成 prompt 模板

### 5. 分析 Pipeline

- [x] 实现 analyze pipeline（analysis/pipeline.py）
- [x] 串联：解析 → 清洗 → mock 抽取 → 渲染 → 入库
- [x] focus_areas 和 analysis_depth 传入 pipeline
- [x] 写出 report_json + report_markdown 到 data/reports/
- [x] 编写 test_pipeline_mock.py

### 6. Markdown 报告渲染

- [x] 实现 MockLLMProvider 报告渲染（含免责声明、观点矩阵、风险提示、引用）
- [x] 报告展示关注点
- [x] 编写 test_report.py

### 7. CLI

- [x] 实现 `python -m podcast_research --subtitle-file <file> --mock`
- [x] 支持 --focus（关注点过滤，逗号分隔）
- [x] 支持 --depth（分析深度：standard / deep）
- [x] 支持 --output（输出目录）
- [x] 支持 --verbose（详细日志）
- [x] 使用 rich 输出进度
- [x] mock 模式完整跑通
- [x] 编写 test_cli.py（含 --focus 和 --depth 测试）

### 8. 工具函数

- [x] 实现 utils/hash.py（文件哈希）
- [x] 实现 utils/timestamp.py（时间戳格式化）

---

## P0-A Hardening（收口项）

> 确保 P0-A 工程基线稳定、文档一致、测试可信。
> 不在本轮实现新功能，只做收口和固化。

### 9. TODO 与实际状态同步

- [x] TODO.md 勾选已完成的 P0-A 项
- [x] TODO.md 标注未完成项（VTT parser）
- [x] TODO.md 明确 P0-A/P0-B 分界

### 10. CLI --focus 补齐

- [x] CLI --focus 参数实现（逗号分隔 → list[str]）
- [x] CLI --depth 参数实现（standard / deep）
- [x] focus_areas 传入 pipeline 和 extraction
- [x] focus_areas 写入 Report ORM 和 extraction_json
- [x] Markdown 报告展示关注点
- [x] CLI 测试覆盖 --focus 和 --depth

### 11. .env 安全检查

- [x] .env 未被 git 跟踪（git ls-files .env 返回空）
- [x] .env 未进入 git 历史（git log --all -- .env 返回空）
- [x] .gitignore 正确排除 .env
- [x] README.md 只提供 .env.example 引用

### 12. adapters/ 与 llm/ 边界说明

- [x] CLAUDE.md 明确：adapters/ 只负责数据源适配，llm/ 只负责模型供应商适配
- [x] 不将 LLM provider 移入 adapters/

### 13. Jinja2 定位说明

- [x] CLAUDE.md 明确：Jinja2 预留给 P1/P2 模板化报告渲染
- [x] P0-A 继续允许 mock/LLM 直接生成 Markdown

### 14. 测试回归

- [x] 25 tests passed（含新增 --focus/--depth 2 个测试）
- [x] CLI mock 模式完整跑通（含 --focus "新能源,港股,AI算力"）
- [x] 报告包含关注点展示
- [x] extraction JSON 包含 focus_areas
- [x] VTT parser 14 个新测试（格式检测 + 解析 + 标签清理 + NOTE 跳过 + 短时间戳 + cue settings）

---

## P0-B：YouTube 字幕 Adapter

> P0-B 在 P0-A hardening 完成后进入。
> 同样使用 mock LLM，不调用真实 LLM API。
> yt-dlp 作为备用字幕获取方案。

### 15. YouTube Adapter 核心

- [x] 安装 youtube-transcript-api 依赖
- [x] 实现 utils/youtube.py（extract_video_id + is_youtube_url）
- [x] 实现 adapters/base.py（TranscriptAdapter 基类 + TranscriptResult）
- [x] 实现 adapters/youtube_transcript.py（YouTubeTranscriptAdapter）
- [x] YouTube 字幕 → SubtitleSegment 格式转换
- [x] 无字幕视频的降级提示（TranscriptsDisabled / NoTranscriptFound）
- [x] 语言优先级 fallback（zh-Hans > zh > zh-Hant > en > zh-CN）
- [x] 字幕缓存（data/transcripts/youtube/{video_id}.json）
- [ ] YouTube 视频元数据获取（标题、时长、频道名）

### 16. YouTube Pipeline 与 CLI

- [x] pipeline.py 新增 analyze_from_transcript()（接收 TranscriptResult）
- [x] pipeline.py 重构：共享 _run_pipeline()，原有 analyze() 不受影响
- [x] CLI --youtube-url 参数（与 --subtitle-file 二选一）
- [x] CLI --youtube-lang 参数（字幕语言优先级）
- [x] CLI 互斥校验与错误提示

### 17. yt-dlp 备用 Adapter（可选）

- [ ] 实现 YtDlpAdapter（adapters/yt_dlp_adapter.py）
- [ ] youtube-transcript-api 失败时自动降级到 yt-dlp

### 18. P0-B 测试

- [x] 编写 test_youtube_utils.py（URL 解析 12 个测试）
- [x] 编写 test_youtube_transcript_adapter.py（mock adapter 16 个测试）
- [x] 编写 test_cli.py YouTube 相关测试（互斥校验 + mock YouTube URL）
- [ ] 真实 YouTube 投资访谈视频链接集成验证

---

## P0-B Hardening（工程基线稳定化）

> 把 YouTube 单视频字幕数据源整理成稳定工程基线，为后续真实 LLM 分析和 P1 报告库做准备。

### 19. YouTube 元数据结构

- [x] TranscriptResult 补齐 channel_name / is_generated / fetched_at 字段
- [x] TranscriptResult 增加 transcript_segment_count property
- [x] Episode DB 表增加 source_url / video_id / language 列
- [x] DB migration: 旧库自动 ALTER TABLE 补齐新列
- [x] YouTube adapter 填充新元数据字段
- [x] 缓存序列化包含新字段
- [x] pipeline 传递 source_info 和 episode_extra
- [x] mock report 渲染展示数据来源（YouTube / 本地）
- [x] YouTube 报告展示：来源、视频 ID、字幕语言、字幕段数、原始链接
- [ ] YouTube 视频元数据获取（标题、频道名）— 需 YouTube Data API 或 HTML 解析，不在 P0-B 实现

### 20. Mock Provider 定位明确

- [x] CLAUDE.md 增加 Mock Provider 定位章节
- [x] README.md 增加 Mock Provider 定位说明
- [x] 明确英文视频 mock 模式 0 观点是预期行为
- [x] 不扩展英文关键词规则

### 21. 真实 LLM 手动验证

- [x] README.md 增加「手动集成测试：YouTube + Real LLM」章节
- [x] CLAUDE.md 增加真实 LLM 手动验证规则
- [x] CLI 改善 LLM 失败时的错误提示
- [x] 采用方案 A：README 手动命令，不新增脚本

### 22. 长字幕处理风险

- [x] pipeline 增加输入段数日志
- [x] pipeline 增加总字符数和粗略 token 估计日志
- [x] pipeline 增加长字幕警告（> 1000 段 / > 50000 字符）
- [ ] Long transcript chunking（分块分析）
- [ ] Map-reduce extraction（多块抽取 → 合并）
- [ ] Token budget estimation（精确 token 计数）
- [ ] Long-video report merging（多块报告合并）

### 23. P0-B Hardening 测试

- [x] YouTube metadata 字段存在测试
- [x] Markdown 报告展示 YouTube source 信息测试
- [x] mock provider 英文 0 观点时仍生成合法报告测试
- [x] 原有 67 个测试全部通过（VTT 新增后总计 82 个）

---

## P1：本地报告查看页

- [ ] FastAPI 项目初始化
- [ ] 报告列表 API
- [ ] 报告详情 API
- [ ] InvestmentView 查询 API
- [ ] 简单 HTML 页面

---

## P2：真实 LLM + 小宇宙可选 Adapter

- [ ] 真实 LLM provider（OpenAI-compatible）完整接入与 prompt 调优
- [ ] 长视频分块分析（chunking + map-reduce）
- [ ] Token budget 管理
- [ ] 小宇宙单集链接解析（可选 Adapter）
- [ ] xyz-dl 字幕下载 Adapter（可选）
- [ ] 说话人推断逻辑
- [ ] 元数据获取（podcasts 表）

---

## P3：历史报告全局查询

- [ ] SQLite FTS5
- [ ] 结构化过滤
- [ ] LLM 总结回答
- [ ] 引用来源展示
- [ ] qa_logs 表

---

## P4：多期观点对比

- [ ] 多报告选择
- [ ] 同标的观点聚合
- [ ] 观点变化时间线
- [ ] 对比报告生成