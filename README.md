# 投资播客研究助手 / Podcast Investment Research Assistant

将公开播客字幕中的投资观点、标的、风险提示、待验证信号和关键原文引用结构化沉淀。

> **本项目不提供投资建议。** 所有输出仅为播客内容的结构化整理，不构成买入、卖出、持有等决策建议。

## 当前阶段：P2-A2.1 Channel Metadata + P2-A2 Cross-channel Evaluation

P0 分析 + P1-A/B/C/D/E/F 已完成 + P2-A1 Hardening 已完成。P2-A2.1 实现频道/视频元数据传递，channels analyze-video 自动补齐频道名和视频标题到报告。P2-A2 实现跨频道 Prompt v2 质量评估工具。

## 快速开始

```bash
# 安装
pip install -e ".[dev]"

# mock 模式分析本地字幕文件（P0-A 默认）
python -m podcast_research --subtitle-file data/subtitles/sample.srt

# mock 模式分析 YouTube 视频字幕（P0-B）
python -m podcast_research --youtube-url "https://www.youtube.com/watch?v=VIDEO_ID" --mock

# 指定字幕语言优先级
python -m podcast_research --youtube-url "https://www.youtube.com/watch?v=VIDEO_ID" --youtube-lang "zh-Hans,en" --mock

# 指定关注点和分析深度
python -m podcast_research --subtitle-file your_subtitle.srt --focus "新能源,港股,AI算力" --depth deep

# 查看报告
cat data/reports/sample_report.md

# 运行测试
python -m pytest tests/ -v
```

## 报告库查询（P1-A）

分析命令生成的报告自动入库，可通过 `reports` 子命令查询：

```bash
# 列出所有报告
python -m podcast_research reports list
python -m podcast_research reports list --source youtube --limit 10

# 查看报告详情
python -m podcast_research reports show 1
python -m podcast_research reports show 1 --full    # 输出完整 Markdown

# 搜索报告（LIKE 匹配报告内容、投资标的、逻辑链）
python -m podcast_research reports search "NVIDIA"

# 汇总投资标的
python -m podcast_research reports targets

# 来源统计
python -m podcast_research reports sources
```

## 启动本地 API 服务（P1-B）

启动本地只读 API 服务，可通过 HTTP 访问报告库：

```bash
# 启动服务
python -m podcast_research serve

# 自定义 host 和 port
python -m podcast_research serve --host 127.0.0.1 --port 8000

# 开发模式（代码变更自动重载）
python -m podcast_research serve --reload
```

启动后访问：
- API 文档 (Swagger): http://127.0.0.1:8000/docs
- 健康检查: http://127.0.0.1:8000/api/health
- 报告列表: http://127.0.0.1:8000/api/reports?limit=20
- 报告详情: http://127.0.0.1:8000/api/reports/1
- 核心观点: http://127.0.0.1:8000/api/reports/1/views
- 搜索: http://127.0.0.1:8000/api/search?q=NVIDIA

### API 端点一览

| 端点 | 说明 |
|------|------|
| `GET /api/health` | 健康检查 |
| `GET /api/reports` | 报告列表（?limit=20&source=youtube） |
| `GET /api/reports/{id}` | 报告详情（含 views/signals/markdown） |
| `GET /api/reports/{id}/views` | 报告投资观点 |
| `GET /api/reports/{id}/signals` | 报告待验证信号 |
| `GET /api/entities?type=stock&limit=100` | 实体列表 |
| `GET /api/targets?limit=100` | 投资标的汇总 |
| `GET /api/sources` | 来源统计 |
| `GET /api/search?q=NVIDIA&limit=20` | 搜索报告 |

> 注意：API 为本地只读服务，不支持分析任务提交、报告编辑或删除。默认绑定 127.0.0.1:8000。

## YouTube 频道关注（P1-E + P1-F）

```bash
# 播种默认 Tech/AI 频道包（4 个核心频道，幂等+自愈）
python -m podcast_research channels seed-tech-ai

# 按标签过滤频道
python -m podcast_research channels list --tag ai
python -m podcast_research channels list --priority core

# 管理频道标签
python -m podcast_research channels tag 1 --add "ai,tech"
python -m podcast_research channels tag 1 --remove "macro"
python -m podcast_research channels tag 1 --set "ai,tech,vc"

# 关注频道
python -m podcast_research channels add "https://www.youtube.com/@allin" --name "All-In Podcast"

# 刷新频道视频列表（获取最新 20 个视频）
python -m podcast_research channels refresh 1 --limit 20

# 查看频道视频
python -m podcast_research channels videos 1

# 分析指定视频（真实 LLM）
python -m podcast_research channels analyze-video --video-id "HGbA6ze0_3M" --focus "AI投资,美股" --no-mock

# dry-run 检查
python -m podcast_research channels analyze-video --video-id "HGbA6ze0_3M" --dry-run
```

注意：
- 默认使用 mock provider，真实 LLM 需显式 `--no-mock`
- 已分析过的视频默认跳过，避免重复
- `--dry-run` 模式只检查不分析
- `seed-tech-ai` 幂等+自愈，重复执行不会重复插入，已存在但配置缺失的频道自动补齐

### 频道视频分析自动补全元数据（P2-A2.1）

通过 `channels analyze-video` 生成的报告会自动携带频道和视频元数据：

- **来源频道**：从 channels 表获取频道名称和链接
- **视频信息**：视频标题、URL、发布日期
- **频道标签**：自动展示在报告数据来源部分
- **默认关注点**：如果未指定 `--focus`，自动使用频道的 `default_focus`

这些元数据会传递到报告 Markdown、API 响应和 HTML 页面中，提升报告可读性和来源可追溯性。

## 跨频道质量评估（P2-A2）

```bash
# 终端展示所有报告评估统计
python -m podcast_research eval reports

# 按频道过滤
python -m podcast_research eval reports --channel "BG2Pod"

# 导出 CSV（供后续分析）
python -m podcast_research eval export --output data/eval/prompt_v2_eval.csv

# 导出 Markdown 总结
python -m podcast_research eval summary --output data/eval/prompt_v2_summary.md
```

评估统计字段：
- 报告 ID、频道名、视频 ID、prompt 版本、模型
- 观点数、技术洞察数、非关注项数、实体数、风险数、待验证信号数
- 证据类型分布、相关性分布、AI 价值链分布
- 泛化标的计数（Broad Market / Economy 等过泛对象）
- 未知发言人计数、时间范围分布
- 报告状态（ok / empty / generic_targets）

泛化标的检测列表：Broad Market、Economy、Investors、Consumers、Society、AI Industry、Technology Sector、Market、Companies、Startups。

## 全文搜索索引（P1-D）

```bash
# 重建搜索索引（新增报告后执行）
python -m podcast_research reports rebuild-index

# 搜索
python -m podcast_research reports search "NVIDIA"
```

搜索策略：优先 FTS5 全文检索，不可用时自动 fallback 到 LIKE 搜索。搜索结果标记 `match_type`：`fts` 或 `like-fallback`。

## 启动本地报告查看页面（P1-C）

启动服务后可在浏览器中查看 HTML 报告页面：

```bash
# 启动服务（同时提供 API 和 HTML 页面）
python -m podcast_research serve

# 打开以下页面
```

浏览器访问：
- 首页: http://127.0.0.1:8000/
- 报告库: http://127.0.0.1:8000/reports
- 报告详情: http://127.0.0.1:8000/reports/1
- 搜索: http://127.0.0.1:8000/search
- API 文档: http://127.0.0.1:8000/docs

页面功能：
- 报告列表（支持 ?source=youtube&limit=50 过滤）
- 报告详情（核心观点矩阵、待验证信号、完整 Markdown 正文）
- 全文搜索（标的、逻辑链、报告内容）
- 极简 CSS，无前端框架依赖

## 真实 LLM 使用（后续阶段）

```bash
# 1. 配置 .env（从 .env.example 复制并填入）
cp .env.example .env
# 编辑 .env，设置 LLM_PROVIDER=openai-compatible 和 LLM_API_KEY

# 2. 使用真实 LLM
python -m podcast_research --subtitle-file your_subtitle.srt --no-mock
```

> P0 阶段仅使用规则引擎 mock provider，不调用真实 LLM API。

### Prompt v2（P2-A1）

Tech/AI Investing Prompt v2 相比 v1 的核心改进：

- **内容分类**：investment_views / tech_industry_insights / non_focus_items / uncertain_items 四级分层
- **evidence 强约束**：10 个 evidence_type 枚举，有具体数字不得标记为 unsupported_claim
- **speaker fallback**：unknown_speaker / podcast_participant / low 统一规则
- **time_horizon 必填**：immediate / short_term / medium_term / long_term / unknown
- **AI 价值链标注**：ai_value_chain_layer / technology_driver / business_impact 新字段
- **实体标准化**：NVIDIA / Alphabet / TSMC 等自动归一化
- **报告结构固定**：11 个标准章节，核心观点矩阵扩展为 11 列
- **P2-A1 Hardening**：泛 target 黑名单（Broad Market / Economy / AI Industry 等）、investment_relevance 严格分级（high ≤ 40%，无证据不得高于 medium）、TechIndustryInsight 增加 topic_tags

> mock 模式不反映 prompt v2 的真实语义质量。真实 LLM 验证见下方。

### Mock Provider 定位说明

mock provider 是基于中文关键词匹配的规则引擎，**仅用于工程闭环测试**：

- 验证 pipeline 串联、数据入库、报告渲染等工程链路是否正常
- 不代表真实语义抽取能力
- 英文字幕、复杂投资观点、隐含逻辑链需要使用真实 LLM provider
- 默认 `pytest` 使用 mock provider，不调用真实 API
- 真实 LLM 测试作为手动集成验证，不进入默认测试

英文视频在 mock 模式下输出 0 条观点是**预期行为**，不是 bug。

## 手动集成测试：YouTube + Real LLM

在 .env 中配置好真实 LLM 后，可对 YouTube 视频进行端到端验证：

```bash
python -m podcast_research \
  --youtube-url "https://www.youtube.com/watch?v=jJRAvZNGUvI" \
  --focus "美股,AI投资,宏观政策,科技股" \
  --depth standard \
  --no-mock
```

**注意事项**：

- 需要在 `.env` 中配置 `LLM_PROVIDER`、`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`
- 调用真实 LLM API 会产生费用
- 长视频（如 2000+ 段字幕）可能触发 token 上限，当前未实现分块处理
- 如果失败，优先检查 `logs/` 目录下的日志文件
- **绝对不要**将 API Key 打印到终端或写入日志

## 项目结构

```text
src/podcast_research/
  cli.py                 # Typer CLI 命令
  config.py              # .env 加载 + 全局配置
  logging_config.py      # 日志：console + RotatingFileHandler
  analysis/
    models.py            # Pydantic v2 数据模型（两阶段抽取 schema）
    pipeline.py          # 主分析流水线（analyze + analyze_from_transcript）
  adapters/
    base.py              # TranscriptAdapter 基类 + TranscriptResult
    youtube_transcript.py # YouTube 字幕 Adapter（youtube-transcript-api）
  subtitles/
    parser.py            # SRT/VTT/TXT 解析器
    cleaner.py           # 清洗：去空行、合并短段、去重、标记广告
  llm/
    base.py              # LLMProvider 抽象基类
    mock_provider.py     # 规则引擎 mock（基于关键词匹配）
    openai_compatible_provider.py  # 真实 LLM 预留骨架
    prompts.py           # prompt 模板
  db/
    models.py            # SQLAlchemy ORM（5 张核心表）
    session.py           # SQLite session 管理
    repository.py        # 数据写入 + 查询方法
    channel_repository.py # 频道/视频 Repository + metadata lookup
    fts.py               # FTS5 全文搜索索引
  api/
    app.py               # FastAPI app 工厂
    schemas.py           # Pydantic 响应 schema
    routes/
      health.py          # GET /api/health
      reports.py         # GET /api/reports/*, /api/entities, /api/targets, /api/sources
      search.py          # GET /api/search
  web/
    routes.py            # HTML 页面路由（/reports, /reports/{id}, /search）
    templates/           # Jinja2 模板（base, reports_list, report_detail, search, error）
    static/style.css     # 极简 CSS
  utils/
    hash.py              # 文件哈希（字幕重复检测）
    timestamp.py         # 时间戳格式化
    youtube.py           # YouTube URL 解析
tests/                    # pytest 测试
data/
  subtitles/             # 字幕文件存放
  reports/               # 报告输出
  transcripts/youtube/   # YouTube 字幕缓存
  podcast_analyst.db     # SQLite 数据库（运行时生成）
logs/                     # 日志
```

## 核心原则

1. 不输出买卖建议
2. 不把 AI 归纳伪装成嘉宾原话
3. 核心观点必须绑定原文引用和时间戳
4. 不确定信息必须显式标注
5. 所有外部依赖通过 adapter 隔离

## 当前不做

- 小宇宙链接解析、xyz-dl 字幕下载
- 真实 LLM API 调用（P0 仅支持手动集成验证，不进入自动化测试）
- React / Next.js / Vue 等前端框架
- Whisper 转写、多平台 RSS
- 向量数据库、PDF/Word 导出
- 团队协作、云端同步
- 登录鉴权、报告编辑/删除

## 路线图

| 阶段 | 目标 | 状态 |
|------|------|------|
| P0-A | CLI 本地字幕分析闭环（mock LLM） | **已完成** |
| P0-B | CLI YouTube 字幕 Adapter（mock LLM） | **已完成** |
| P1-A | CLI 报告库查询（list/show/search/targets/sources） | **已完成** |
| P1-B | FastAPI 只读 API（/api/reports/*, /api/search 等） | **已完成** |
| P1-C | Jinja2 极简 HTML 报告页面 | **已完成** |
| P1-D | SQLite FTS5 搜索增强 | **已完成** |
| P1-E | YouTube 频道关注库与视频列表获取 | **已完成** |
| P1-F | Tech/AI 默认频道包 + Channel Tags | **已完成** |
| P2-A1 | Tech/AI Investing Prompt v2 + Schema 增强 | **已完成** |
| P2-A2.1 | Channel/Video Metadata Propagation | **已完成** |
| P2-A2 | 跨频道 Prompt v2 质量评估 | **已完成** |
| P2-B | 长视频分块分析（Long Transcript Chunking） | 待启动 |
| P2 | 小宇宙链接导入 + 其他增强 | 待启动 |
| P3 | 历史报告全局查询（FTS5 + LLM 问答） | 待启动 |
| P4 | 多期观点对比 | 待启动 |

## 许可证

Private / 个人使用