# CLAUDE.md

## 项目

投资音视频研究助手。从 YouTube/播客字幕中结构化提取投资观点、标的、风险、信号和原文引用。
不是投资建议工具。

## 当前阶段

**P2-S External Sources + Deep Notes Export。** P0–P2 (A–S) 已交付，1261 tests（含 26 job persistence + 7 Playwright UI smoke），58 个 Python 模块，9 个 CLI 命令组。

CI：GitHub Actions 自动 pytest + ruff lint。详细路线见 `docs/ROADMAP.md`，变更记录见 `CHANGELOG.md`。

## 架构边界

```
adapters/  → 数据源适配（字幕 → TranscriptSegment）
llm/       → 模型供应商适配（prompt → JSON/Markdown）
analysis/  → 分析流水线（解析 → 清洗 → 抽取 → 渲染 → 入库）
db/        → SQLAlchemy + SQLite（6 表）
api/       → FastAPI 只读 JSON API
web/       → Jinja2 HTML 页面（20 模板）
services/  → 业务编排（analyze/job/sync/watchlist）
exporters/ → Obsidian Vault 导出
llm_wiki/  → LLM-WIKI Patch Review 生命周期
workspace/ → Vault 管理（dashboard/curation/backfill）
```

**adapters 和 llm 不互相跨越。** adapters 适配数据，llm 适配模型。

## 禁止事项

- 不输出投资建议，不把 AI 推断伪装成嘉宾原话
- 核心观点必须有 source_quote + timestamp
- API Key 不进代码、不进日志、不进 git
- `.env` 不提交，`.env.example` 只用占位值
- 不做：React/Vue/Next.js、Whisper、RAG、向量库、PDF/Word 导出、登录鉴权、自动定时抓取、团队协作

## 测试规则

```bash
python -m pytest tests/ -v    # 1261 tests（含 7 UI smoke），全部使用 mock provider
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
| `CLAUDE.md` | AI | 当前规则、边界、约束 |
| `docs/ARCHITECTURE.md` | 开发者 | 分层架构、模块边界 |
| `docs/ROADMAP.md` | 规划 | 已完成/计划中阶段 |
| `docs/DEV_GUIDE.md` | 开发者 | 环境、测试、命令速查 |
| `CHANGELOG.md` | 记录 | 阶段完成日志 |
| `TODO.md` | 追踪 | 待办项 |
