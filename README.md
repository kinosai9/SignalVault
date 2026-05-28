# 投资播客研究助手 / Podcast Investment Research Assistant

将公开播客字幕中的投资观点、标的、风险提示、待验证信号和关键原文引用结构化沉淀。

> **本项目不提供投资建议。** 所有输出仅为播客内容的结构化整理，不构成买入、卖出、持有等决策建议。

## 当前阶段：P1 报告库查询 + 本地 API

在 P0 分析闭环基础上，支持 CLI 查看和检索已入库报告，并提供本地只读 FastAPI API。

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

## 真实 LLM 使用（后续阶段）

```bash
# 1. 配置 .env（从 .env.example 复制并填入）
cp .env.example .env
# 编辑 .env，设置 LLM_PROVIDER=openai-compatible 和 LLM_API_KEY

# 2. 使用真实 LLM
python -m podcast_research --subtitle-file your_subtitle.srt --no-mock
```

> P0 阶段仅使用规则引擎 mock provider，不调用真实 LLM API。

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
  api/
    app.py               # FastAPI app 工厂
    schemas.py           # Pydantic 响应 schema
    routes/
      health.py          # GET /api/health
      reports.py         # GET /api/reports/*, /api/entities, /api/targets, /api/sources
      search.py          # GET /api/search
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

## P0 不做的内容

- 小宇宙链接解析、xyz-dl 字幕下载
- 真实 LLM API 调用（P0 仅支持手动集成验证，不进入自动化测试）
- FastAPI 后端、前端 UI
- Whisper 转写、多平台 RSS
- 向量数据库、PDF/Word 导出
- 团队协作、云端同步

## 路线图

| 阶段 | 目标 | 状态 |
|------|------|------|
| P0-A | CLI 本地字幕分析闭环（mock LLM） | **已完成** |
| P0-B | CLI YouTube 字幕 Adapter（mock LLM） | **已完成** |
| P1-A | CLI 报告库查询（list/show/search/targets/sources） | **已完成** |
| P1-B | FastAPI 只读 API（/api/reports/*, /api/search 等） | **已完成** |
| P1-C | Jinja2 极简 HTML 报告页面 | 待启动 |
| P2 | 小宇宙链接导入 + 真实 LLM | 待启动 |
| P3 | 历史报告全局查询（FTS5 + LLM 问答） | 待启动 |
| P4 | 多期观点对比 | 待启动 |

## 许可证

Private / 个人使用