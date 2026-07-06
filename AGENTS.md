# AGENTS.md

## 项目

SignalVault 多源投资研究助手。从 YouTube/播客字幕、网页资料、文本/PDF 文件、知识星球只读主题等信息源中结构化提取投资观点、标的、风险、信号和原文引用。
不是投资建议工具。

## 当前阶段

**P7 后端/CLI 能力已基本完成，前端体验专项改造准备中。** P0–P7 已交付到多源摄入、PDF 分析、ZSXQ 只读导入、统一搜索、轻量图谱、诊断中心与诊断包导出。当前 `python -m pytest --collect-only -q` 可收集 1908 tests。

当前前端主线：依据 `docs/FRONTEND_EXPERIENCE_EXECUTION_PLAN.md`，在不改变后端数据契约的前提下，将现有 Web Console 改造成 SignalVault 的四条主用户动线：变化雷达、信息源工作台、导入向导、知识库搜索。

后端能力状态详见 `README.md`、`CHANGELOG.md`、各阶段验收报告；前端执行计划见 `docs/FRONTEND_EXPERIENCE_EXECUTION_PLAN.md`。

CI：GitHub Actions 自动 pytest + ruff lint。详细路线见 `docs/ROADMAP.md`，变更记录见 `CHANGELOG.md`。

## 架构边界

```
adapters/  → 数据源适配（字幕 → TranscriptSegment）
llm/       → 模型供应商适配（prompt → JSON/Markdown）
analysis/  → 分析流水线（解析 → 清洗 → 抽取 → 渲染 → 入库）
db/        → SQLAlchemy + SQLite（核心表 + ingest/review/graph/operation 扩展）
api/       → FastAPI 只读 JSON API
web/       → Jinja2 HTML 页面（20+ 模板）
services/  → 业务编排（analyze/job/sync/watchlist）
sources/   → 信息源摄入管道（导入预览/跟踪源/文件上传/PDF/ZSXQ/冲突检测）
exporters/ → Obsidian Vault 导出
llm_wiki/  → LLM-WIKI Patch Review 生命周期
workspace/ → Vault 管理（dashboard/curation/backfill）
diagnostics/ → 错误分类、操作日志、诊断中心、诊断包
mcp_server/ → 只读 MCP Server（报告/实体/观点/信号/搜索/图谱/证据链）
```

**adapters 和 llm 不互相跨越。** adapters 适配数据，llm 适配模型。

## 禁止事项

- 不输出投资建议，不把 AI 推断伪装成嘉宾原话
- 核心观点必须有 source_quote；视频来源必须有 timestamp，PDF 来源必须保留 evidence_page，ZSXQ 来源必须保留 group/topic/source_url 追溯
- API Key 不进代码、不进日志、不进 git
- `.env` 不提交，`.env.example` 只用占位值
- 不做：React/Vue/Next.js、Whisper、RAG、向量库、PDF/Word 导出、登录鉴权、自动定时抓取、团队协作、知识星球写入型客户端

## 测试规则

```bash
python -m pytest tests/ -v    # 当前可收集 1908 tests，全部使用 mock provider
python -m pytest tests/ -q    # 快速模式
python -m pytest tests/test_ui_smoke.py -v  # UI smoke tests（需要 playwright）
```

- 默认 pytest 使用 mock provider，不调用真实 API
- YouTube adapter 测试必须 mock `YouTubeTranscriptApi`
- 测试用 `db_session`/`seeded_db` fixture 隔离，不污染 `data/`
- Obsidian 测试用 `tmp_path`，不写真实 Vault
- 新增核心功能必须补测试
- 英文视频 mock 模式 0 观点是预期行为，不扩展英文关键词规则
- UI smoke tests（`test_ui_smoke.py`）验证关键页面 CSS 加载和 DOM 结构

## Mock Provider

基于中文关键词匹配的规则引擎，**仅用于工程闭环测试**。不代表真实语义抽取能力。复杂投资观点、隐含逻辑链需要真实 LLM。

## 真实 LLM 手动验证

```bash
python -m podcast_research --youtube-url "URL" --focus "AI投资" --no-mock
```

- 需 `.env` 配置：`LLM_PROVIDER` / `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`
- 不进自动化测试。失败先查 `logs/`。不打印 API Key。
- 长视频自动 chunking（N 块 = N 次调用），注意成本

## Pipeline 规则

- `analyze()` 和 `analyze_from_transcript()` 共用 `_run_pipeline()`，不要重写
- YouTube 模式走 `analyze_from_transcript()`，不修改 `analyze()` 签名
- LLM 分两阶段：1) 事实抽取 JSON → 2) 报告 Markdown 生成

## UI 修改验收规则

修改 HTML 模板或 CSS 后必须：
1. `python -m pytest tests/ -v` 全部通过
2. 模板 DOM 变化时同步更新 `test_web_pages.py` 中的选择器断言
3. CSS 变化时确认 `test_web_pages.py` 中的样式验证测试仍然有效
4. 非 IT 用户视角：错误提示易懂、操作路径直观、不需要查文档就能用

## 每次修改后

说明改动内容、测试结果、下一步建议。不虚构命令输出。不声称"通过"除非有验证证据。

## Git

- commit message 用英文。Push 仅用于跨设备同步，等用户说。
- GitHub 仓库用 SSH：`ssh://git@github.com/kinosai9/podcast_research.git`

## 项目文档

| 文件 | 面向 | 内容 |
|------|------|------|
| `README.md` | 用户 | 功能说明、快速开始、CLI 参考 |
| `AGENTS.md` | AI | 当前规则、边界、约束 |
| `docs/ARCHITECTURE.md` | 开发者 | 分层架构、模块边界 |
| `docs/ROADMAP.md` | 规划 | 已完成/计划中阶段 |
| `docs/DEV_GUIDE.md` | 开发者 | 环境、测试、命令速查 |
| `docs/SOURCE_INGESTION.md` | 开发者 | Sources 模块目标、入口、流程、边界 |
| `docs/PROJECT_RULES.md` | 开发者 | 工程规范、命名约定、DB 迁移规则 |
| `docs/FRONTEND_EXPERIENCE_EXECUTION_PLAN.md` | 前端 | SignalVault 前端体验改造计划 |
| `docs/P3_PLAN.md` | 规划 | P3 阶段计划与验收标准 |
| `docs/INGEST_QUEUE_DESIGN.md` | 设计 | P3-A 持久化摄入队列表设计 |
| `docs/VAULT_LINT_REVIEW_QUEUE_DESIGN.md` | 设计 | P3-B/C Lint + Review Queue 设计 |
| `docs/MCP_SERVER_DESIGN.md` | 设计 | P3-D MCP Server 设计 |
| `docs/P4_ACCEPTANCE_REPORT.md` | 验收 | PDF 入库与分析闭环 |
| `docs/P5_ACCEPTANCE_REPORT.md` | 验收 | 统一搜索与轻量图谱 |
| `docs/P6_ACCEPTANCE_REPORT.md` | 验收 | ZSXQ 只读导入与分析 |
| `docs/P7_RELIABILITY_DIAGNOSTICS_PLAN.md` | 设计/状态 | 诊断与可靠性能力 |
| `CHANGELOG.md` | 记录 | 阶段完成日志 |
| `TODO.md` | 追踪 | 待办项 |
