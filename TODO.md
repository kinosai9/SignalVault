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

## P1-A：CLI 报告库查询

> P1-A 在 P0 分析闭环基础上，新增 CLI reports 子命令查看和检索已入库报告。
> 不做 FastAPI、Web UI、RAG、FTS5、向量库。

### 24. Repository 查询层

- [x] session.py 增加 reset_engine()（测试 teardown）
- [x] list_reports(limit, source_type) — 报告列表
- [x] get_report(report_id) — 报告基本信息
- [x] get_report_detail(report_id) — 报告 + 观点 + 信号
- [x] search_reports(keyword, limit) — LIKE 搜索 report_markdown + target_name + logic_chain
- [x] list_targets(limit) — 标的汇总（出现次数、最近方向）
- [x] list_sources() — 来源统计
- [x] source_type 推断（video_id → youtube / source_url 匹配 / 默认 local）

### 25. CLI reports 子命令

- [x] callback 加 ctx.invoked_subcommand 守卫（向后兼容）
- [x] reports list [--limit] [--source]
- [x] reports show <id> [--full]
- [x] reports search <keyword> [--limit]
- [x] reports targets [--limit]
- [x] reports sources

### 26. P1-A 测试

- [x] conftest.py 共享 fixtures（db_session + seeded_db）
- [x] test_reports.py — repository 查询 15 tests
- [x] test_cli_reports.py — CLI 子命令 11 tests
- [x] 原有 82 个测试不被破坏（总计 108 passed）

### 27. P1-A Hardening

- [x] DB 隔离修复：db_session fixture 在 setup 阶段先 reset_engine()，防止全局 engine 残留污染临时数据库
- [x] _extract_excerpt() markdown 格式清理（去除 `|*-#_`` 符号）
- [x] _extract_excerpt() BMP 外字符过滤（emoji 等），避免 Windows GBK 终端编码崩溃
- [x] CLAUDE.md 更新：P1-A 已完成
- [x] README.md 路线图更新：P1-A 已完成

---

## P1-B：FastAPI 只读 API

- [x] FastAPI 项目初始化
- [x] 报告列表 API（GET /api/reports）
- [x] 报告详情 API（GET /api/reports/{id}）
- [x] 核心观点 API（GET /api/reports/{id}/views）
- [x] 待验证信号 API（GET /api/reports/{id}/signals）
- [x] 实体列表 API（GET /api/entities）
- [x] 标的汇总 API（GET /api/targets）
- [x] 来源统计 API（GET /api/sources）
- [x] 搜索 API（GET /api/search）
- [x] CLI serve 命令
- [x] API 测试（test_api_health.py, test_api_reports.py, test_api_search.py）
- [x] 测试数据库隔离（复用 db_session fixture）
- [x] README / TODO / CLAUDE.md 更新

---

## P1-C：Jinja2 极简 HTML 报告页面

- [x] 创建 web/ 目录（routes.py + templates/ + static/）
- [x] 实现 HTML routes（GET / → /reports, /reports, /reports/{id}, /search）
- [x] Jinja2 模板（base.html, reports_list.html, report_detail.html, search.html, error.html）
- [x] 极简 CSS（白底、系统字体、表格可读、无前端框架）
- [x] create_app() 挂载 web routes + StaticFiles
- [x] repository.get_report_detail 扩展字段（evidence_strength, speaker_label, signals source_quote/timestamp）
- [x] API schemas 同步扩展（向后兼容，新增字段有默认值）
- [x] HTML 404 页面
- [x] 8 个 web 页面测试（test_web_pages.py）
- [x] 总计 137 tests passed
- [x] README / TODO / CLAUDE.md 更新

---

## P1-D：SQLite FTS5 搜索增强

- [x] FTS5 虚拟表 report_search_fts（11 个字段，report_id UNINDEXED）
- [x] fts.py：ensure_fts_table / rebuild_search_index / search_fts / _has_fts5
- [x] CJK 预处理：_tokenize_for_fts 在字符间插入空格
- [x] repository.search_reports 优先 FTS5，失败 fallback LIKE
- [x] LIKE fallback 保留 _search_reports_like
- [x] CLI reports rebuild-index 命令
- [x] 12 个 FTS 测试（创建/索引/搜索/auto-create/fallback/CLI/API/HTML）
- [x] 总计 149 tests passed
- [x] 文档更新（README / TODO / CLAUDE.md）

---

## P1-E：YouTube 频道关注库与视频列表获取

- [x] ORM: Channel + ChannelVideo 表
- [x] yt-dlp ChannelVideoAdapter（fetch_channel_videos）
- [x] Repository: add_channel / list_channels / upsert_videos / list_channel_videos / mark_video_status
- [x] CLI channels add / list / refresh / videos / analyze-video（--dry-run / --no-mock）
- [x] 视频去重（video_id + channel_id）
- [x] 分析状态记录（new / analyzed / skipped）
- [x] 168 tests passed（+19 channels tests）
- [x] 文档更新

---

## P1-F：Tech/AI 默认频道包 + Channel Tags

- [x] channels 表新增 tags / priority / default_focus / default_limit / default_max_analyze / notes 字段
- [x] 旧库自动迁移 ALTER TABLE（_migrate_channels_table）
- [x] add_channel 扩展支持 tags / priority / default_focus / limits
- [x] update_channel_tags（支持 --add / --remove / --set）
- [x] list_channels 支持 --tag / --priority 过滤
- [x] seed_default_channels（5 个默认 Tech/AI 频道，幂等）
- [x] CLI channels seed-tech-ai / list --tag / list --priority / tag
- [x] README / TODO / CLAUDE.md 更新
- [x] 测试：migration / seed / filter / tag CRUD / CLI（21 个新增测试）

注意：
- channels list 输出增加 Priority / Tags 列，移除新视频/Channel ID 列
- tags 存 JSON 数组字符串，不做复杂多对多 tags 表
- seed-tech-ai 幂等，重复执行 skip 已存在频道
- 不做自动批量真实 LLM、Obsidian 导出、RAG

---

## P2-A1：Tech/AI Investing Prompt v2 + Schema 增强

- [x] prompts.py 重写：投资边界规则、evidence 枚举、speaker fallback、time_horizon 必填、AI 价值链标注、实体标准化
- [x] analysis/models.py 扩展：TechIndustryInsight, InvestmentView 新增 7 个 Tech/AI 字段, ExtractionResult 新增 prompt_version/tech_industry_insights/non_focus_items
- [x] DB ORM 扩展：investment_views 表新增 6 列，自动迁移
- [x] DB repository：save_investment_views / get_report_detail 适配新字段
- [x] Mock provider v2：输出新字段，报告含 Tech/Industry Insights + Non-focus Items
- [x] Pipeline 传递 focus_areas 到 provider，输出 prompt_version
- [x] 20 个 P2-A1 测试（模型向后兼容、prompt 规则、mock v2、DB 入库）
- [x] 210 tests passed（190 原有 + 20 P2-A1）
- [x] 文档更新：README / TODO / CLAUDE.md

## P2-A2.1：Channel / Video Metadata Propagation

> channels analyze-video 生成的报告自动补齐频道名/视频标题/URL/发布时间等元数据。
> 元数据通过 source_info_override 传递到 pipeline → source_info → Markdown 报告。

- [x] channel_repository.get_channel_video_by_video_id() — 联表查询 channel + channel_video
- [x] pipeline.analyze_from_transcript(source_info_override=) — 覆盖空字段合并
- [x] cli channels_analyze_video — 查询元数据 → 构造 override → 传递到 pipeline
- [x] mock_provider render_report — 数据来源部分展示 channel/video 元数据（频道名/标题/链接/发布日期/标签）
- [x] 测试：7 个新测试（joined metadata / override merge / Markdown / normal path unaffected）
- [x] 文档更新：README / TODO / CLAUDE.md

注意：
- 不影响普通 --youtube-url 路径
- override 优先级：channel_videos.title > YouTube adapter title > video_id
- 无频道元数据时正常降级，不报错

---

## P2-A2：跨频道 Prompt v2 质量评估

- [x] evaluation.py：compute_report_stats / eval_all_reports / export_csv / generate_summary_md
- [x] Generic target 检测（Broad Market, Economy 等 10 个过泛对象）
- [x] CLI eval reports / export / summary 子命令
- [x] 14 个 eval 测试（generic detection / stats / CLI / CSV export / summary MD）
- [x] 跨频道样本验证：BG2Pod(3), Latent Space(3), Acquired(1+1), All-In(3)
- [ ] Prompt v3 微调（基于累积样本观察）

注意：
- eval 测试复用 seeded_db fixture，不污染真实 data/
- CSV/Markdown 输出到 tmp_path 在测试中隔离

---

## P2-B：长视频分块分析（Long Transcript Chunking）

- [x] TranscriptChunk 模型（chunk_id, segment range, timestamps, text, segments_text）
- [x] chunk_transcript（按 segment 边界 + char_limit + overlap 切分）
- [x] is_long_transcript 自动检测（>50K chars or >1000 segments）
- [x] Per-chunk extraction（逐块 extract_facts，带 chunk metadata）
- [x] merge_extraction_results（去重 views/entities/insights/risks/signals）
- [x] Compaction 限制（views≤12, insights≤12, entities≤40, risks≤10, signals≤10）
- [x] Pipeline 集成（auto-detect / --chunked / --no-chunking）
- [x] CLI 参数（--chunked / --no-chunking / --chunk-size / --chunk-overlap）
- [x] 31 个测试（detection / chunk creation / overlap / dedup / compaction / merge / pipeline / CLI）
- [x] 文档更新（README / TODO / CLAUDE.md）
- [ ] 手动验证：Acquired Vanguard 真实 LLM chunking
- [ ] Partial chunk failure recovery（单个 chunk 失败不中止其它）
- [ ] Semantic deduplication（embedding 去重，替代当前的 key-based）
- [ ] Chunk-level evaluation（eval 支持 per-chunk 统计）

注意：
- chunking 不改变 prompt 和 schema，只改变 pipeline 如何处理长字幕
- 暂不引入 LangChain / LlamaIndex 等外部编排框架，保持轻量
- 不分块的短字幕行为完全不变
- 任一 chunk 失败当前中止分析（后续做 partial mode）

---

## P2-C：Obsidian Export v1

> 将 SQLite 中的 YouTube 报告导出到 Obsidian Vault，形成可浏览、可双链的知识库。

- [x] Vault 路径配置（OBSIDIAN_VAULT_PATH, OBSIDIAN_EXPORT_ENABLED）
- [x] exporters/markdown_utils.py — sanitize_filename / build_frontmatter / wiki_link
- [x] exporters/obsidian.py — export_report / export_channel_card / export_to_vault
- [x] CLI obsidian export --vault --source --report-id --dry-run --overwrite --limit
- [x] Report YAML frontmatter + 结构化 Markdown 正文
- [x] Channel card 创建 + 追加 Recent Reports（不覆盖用户内容）
- [x] System index (99_System/Report Index.md) + export log
- [x] 28 个测试（filename / frontmatter / wiki links / report export / channel card / skip / overwrite / dry-run / CLI）
- [x] 文档更新（README / TODO / CLAUDE.md）
- [ ] 手动验证：真实 Vault 导出

### P2-C Hardening

- [x] Metadata backfill：export 时通过 channel_videos + channels 补齐缺失的 channel_name / video_title / published_at
- [x] 导出筛选：--channel（大小写不敏感部分匹配）、--only-with-channel（跳过 UnknownChannel）
- [x] Dry-run 增强：Rich 表格含 Action/Reason/Prompt Version 列
- [x] UnknownChannel 策略：默认仍可导出（兼容），--only-with-channel 跳过
- [x] 17 个新测试（backfill / filter / dry-run / CLI）
- [ ] 手动验证：--only-with-channel dry-run
- [ ] 手动验证：--channel "Acquired" dry-run + real export

注意：
- 默认不自动导出，需显式 CLI 命令
- 不写真实 Vault 在测试中（全部用 tmp_path）
- v1 只做 01_Reports + 05_Channels + System files
- 不做 Topic/Company/Person/Claim/Signal 卡片
- 不做 LLM-WIKI 动态维护
- 不做双向同步

### P2-C.1 收口修复

- [x] 测试 env 隔离：conftest.py + monkeypatch 隔离 OBSIDIAN_VAULT_PATH
- [x] UnknownChannel cleanup CLI：obsidian cleanup-unknown --dry-run / --apply
- [x] frontmatter 解析：_parse_yaml_frontmatter 从 Markdown 提取 video_id
- [x] DB backfill 查找：video_id → channel_videos + channels 联表
- [x] apply 安全迁移：重新导出正确 channel + 旧文件移到 99_System/UnknownChannel_Backup/
- [x] 不删除用户文件，只移动到 backup
- [x] 15 个新测试（frontmatter / find / analyze / dry-run / apply / CLI）
- [ ] 手动验证：cleanup-unknown --dry-run
- [ ] 手动验证：cleanup-unknown --apply

### P2-C.2 Channel Card Reconciliation

- [x] 扫描 01_Reports/ frontmatter → 按 channel 分组
- [x] 缺失 channel card → 自动创建
- [x] 已有 card → 只追加 Recent Reports（不覆盖用户内容）
- [x] 已存在的 report link 不重复追加
- [x] --channel 过滤（大小写不敏感部分匹配）
- [x] --overwrite 强制重写
- [x] UnknownChannel / 空 channel 自动跳过
- [x] 17 个新测试（scan / group / create / update / dry-run / filter / CLI）
- [ ] 手动验证：sync-channel-cards --dry-run
- [ ] 手动验证：sync-channel-cards 真实 Vault

### P2-D Topic / Company Card Generation v1

- [x] 扫描 01_Reports/ 提取 topic（hashtag + AI价值链列）
- [x] 扫描 01_Reports/ 提取 company（Entities 区 + 表格目标列）
- [x] Topic / Company 名称规范化（别名映射 + title case fallback）
- [x] 缺失卡片自动创建，已有卡片只追加 Source Reports
- [x] 已存在的 report link 不重复追加
- [x] --topics-only / --companies-only 分类型生成
- [x] --channel 过滤（大小写不敏感部分匹配）
- [x] --overwrite 强制重写
- [x] Topic Index / Company Index / Card Generation Log 生成
- [x] 22 个新测试（extract / normalize / create / append / dry-run / filter / index / CLI）
- [ ] 手动验证：generate-cards --dry-run
- [ ] 手动验证：generate-cards 真实 Vault

### P2-D.1 Topic / Company Card Cleanup & Classification

- [x] Company 分类规则：whitelist 保留 + topic_pattern 迁移 + manual_review
- [x] Topic alias merge：同义 topic 合并到 canonical name
- [x] Company → Topic 迁移：Source Reports 合并 + 旧文件移到 backup
- [x] 不直接删除文件
- [x] --topics-only / --companies-only 分类型清理
- [x] Index 更新（Topic Index / Company Index / Card Cleanup Log）
- [x] 21 个新测试（classify / alias / migrate / merge / backup / index / CLI）
- [ ] 手动验证：cleanup-cards --dry-run
- [ ] 手动验证：cleanup-cards --apply

### P2-D.2 Topic Taxonomy Consolidation

- [x] Core Topic taxonomy：25 个核心主题白名单
- [x] Extended alias map：50+ 同义别名映射到 canonical name
- [x] Topic status 标记：core / emerging / long_tail / manual_review
- [x] Alias merge：同义 topic 合并到 canonical，旧文件移到 backup
- [x] Topic Taxonomy.md：分层展示 Core / Emerging / Long-tail / Manual Review
- [x] Topic Index 更新
- [x] Topic Consolidation Log 生成
- [x] 18 个新测试（classify / alias / merge / status / taxonomy / CLI）
- [ ] 手动验证：consolidate-topics --dry-run
- [ ] 手动验证：consolidate-topics --apply

### P2-D.2.1 Topic Taxonomy Final Hardening

- [x] Generic topic guard：Application / Model / Enterprise / 企业级 / Capital Market 强制合并
- [x] Canonical casing：Ai For Science → AI for Science（Windows case-insensitive 兼容）
- [x] 扩展 alias map：50+ 同义别名映射
- [x] 10 个新测试（casing / generic guard / merge / backup / taxonomy）
- [ ] 手动验证：consolidate-topics --dry-run
- [ ] 手动验证：consolidate-topics --apply

### P2-E LLM-WIKI Dynamic Maintenance with Patch Review

- [x] LLM-WIKI 模块结构：`src/podcast_research/llm_wiki/`（context_builder / prompts / patch_generator）
- [x] Core topic discovery：扫描 `02_Topics/` 中 `status: core` 的 topic cards
- [x] Context building：读取 Source Reports，提取 Core Investment Views / Tech Insights / Risks / Tracking Signals / Entities / Source Quotes
- [x] LLM patch prompt：约束 LLM 不输出投资建议、不制造事实、每个 key claim 绑定 source report
- [x] Patch proposal 生成：写入 `00_Inbox/LLM_Patches/topic_{Name}_{YYYYMMDD_HHMMSS}.md`
- [x] Mock mode：生成占位 patch 用于测试，不调用真实 LLM
- [x] Real LLM mode：调用 OpenAI-compatible API 生成真实 patch
- [x] CLI 命令：`llm-wiki generate-patches --dry-run / --mock / --no-mock / --topic / --core-only / --max-reports`
- [x] Safety：不直接修改 `02_Topics/` 或 `03_Companies/`，patch 仅供人工审阅
- [x] 22 个新测试（find_core / build_context / generate_patch / write_file / CLI / error handling）
- [x] 手动验证：generate-patches --dry-run（9 core topics, 4 source reports each）
- [x] 手动验证：generate-patches --mock（"AI Agents" topic，patch 写入 00_Inbox/LLM_Patches/）
- [x] 手动验证：generate-patches --no-mock（DashScope API arrears，error handled gracefully）

### P2-E.1 Real Patch Validation & Quality Guard

- [x] Patch YAML frontmatter（type, target_type, target, target_card, provider, model, prompt_version, generated_at, source_reports, status: pending_review, auto_apply: false）
- [x] Review Checklist section（9 项人工审阅 checklist）
- [x] validate-patches CLI 命令（frontmatter 检查 / target_card 存在性 / source_reports 存在性 / 必要章节检查 / Review Checklist 检查）
- [x] validate-patches Rich 表格输出（Patch / Target / Reports / Status / Valid / Issues）
- [x] --patch 参数支持单个 patch 验证
- [x] 11 个新测试（frontmatter / checklist / validation / CLI / dry-run）
- [x] 手动验证：mock patch frontmatter + checklist 正确
- [x] 手动验证：validate-patches（4 patches: 2 valid, 2 old w/o frontmatter）
- [x] 手动验证：真实 LLM patch（DeepSeek deepseek-v4-pro）+ 质量验证通过
- [x] 452 tests passed（441 + 11 P2-E.1）

### P2-E.2 Patch Apply with Explicit Review

- [x] apply_patch() 函数：validation gate + section 解析 + marker-based append + status update + apply log
- [x] CLI apply-patch 命令：--dry-run / --apply / --confirm-reviewed / --force
- [x] 前置校验：type/target_type/status/auto_apply/target_card/source_reports/sections/checklist
- [x] Status 要求：pending_review + confirm_reviewed 可 apply，approved 可 apply，applied/rejected 拒绝
- [x] Section mapping：Proposed Current Understanding → Current Understanding 等 6 个映射
- [x] LLM-WIKI:BEGIN/END marker 包裹，防止重复 apply
- [x] 不覆盖已有内容，只追加
- [x] 不存在的 section 自动创建（如 Key Claims）
- [x] Apply 后更新 patch status → applied + applied_at + applied_to
- [x] 99_System/Patch_Apply_Log.md 记录 apply 历史
- [x] 18 个新测试（dry-run / validation gate / status / section mapping / marker / duplicate / log / safety）
- [x] 手动验证：dry-run（6 sections will apply）
- [x] 手动验证：真实 apply（DeepSeek patch → AI Agents.md）
- [x] 手动验证：target card 6 sections 更新 + 原有内容保留
- [x] 手动验证：patch status → applied
- [x] 手动验证：apply log 正确生成
- [x] 470 tests passed（452 + 18 P2-E.2）

后续任务：
- P2-E.3: Company Card patch generation
- P2-E.4: Claim / Signal Card generation
- P2-E.5: Patch rollback with markers

### P2-E.2.1 Apply Formatting Hardening

- [x] Section 插入顺序：新 section 按 SECTION_ORDER 插入正确位置，不追加到末尾
- [x] Related Topics 应用 taxonomy canonical mapping（如 "enterprise saas" → "Enterprise AI"）
- [x] Related Companies entity type guard（已知产品/框架/工具标注类型，如 [[Claude Code]] *(tool)*）
- [x] Source Reports 显示优先用 channel 名（如 "Latent Space — CSYWbbP_OkY"）
- [x] llm_wiki/taxonomy.py：共享 taxonomy 数据（SECTION_ORDER / TOPIC_CANONICAL_MAP / KNOWN_NON_COMPANY）
- [x] 6 个新测试（section order / topic normalization / entity annotation / taxonomy functions / source report context）
- [x] 476 tests passed（470 + 6 P2-E.2.1）

### P2-E.3 Company Card Patch Generation

- [x] Company discovery / CompanyContext / build_company_context()
- [x] Company patch prompts（禁止投资建议/财务预测）
- [x] generate_company_patch() mock + real LLM, target_type=company
- [x] validate-patches + apply-patch 兼容 company 类型
- [x] CLI --company 与 --topic 互斥
- [x] 10 个新测试 + manual verification（NVIDIA, 2 reports, validates clean）
- [x] 486 tests passed（476 + 10 P2-E.3）

### P2-E.3.1 Real Company Patch Validation

- [x] OpenAI: 3 source reports → real LLM patch quality 优秀
- [x] Alphabet: 3 source reports → real LLM patch 生成完成
- [x] validate-patches: 3 company patches all valid
- [x] apply-patch: OpenAI patch 成功应用（7 sections, 7 markers）
- [x] 质量要点: 无投资建议, 5 claims 绑定 source, 4 risks 来自 source, 4 evidence notes 含原文引用, 3 timeline 事件

后续任务：

---

## P2：真实 LLM + 小宇宙可选 Adapter

- [ ] 真实 LLM provider（OpenAI-compatible）完整接入与 prompt 调优
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