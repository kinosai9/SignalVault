# 投资播客研究助手 / Podcast Investment Research Assistant

将公开播客字幕中的投资观点、标的、风险提示、待验证信号和关键原文引用结构化沉淀，输出 Markdown 报告、SQLite 数据库和 Obsidian 知识库。

> **本项目不提供投资建议。** 所有输出仅为播客内容的结构化整理，不构成买入、卖出、持有等决策建议。

## 当前阶段：P3-A/B/C/D 已完成

P0 + P1 + P2（A 到 S）已完成，P3-A/B/C/D 已交付，1563 个测试，83 个 Python 模块，12 个 CLI 命令组，约 20 个 Web 页面。

**P3 已完成**（详见 `docs/P3_PLAN.md`）：
- ✅ P3-A 持久化摄入队列 — SQLite `ingest_jobs` 替代内存预览存储
- ✅ P3-B Vault Lint — 5 条 lint rule 检查 Obsidian vault 健康
- ✅ P3-C Review Queue — 统一 `review_items` 审核队列
- ✅ P3-D MCP Server — 只读 MCP server，8 个 tool，让 AI Agent 查询知识库

## P3: Agent-ready knowledge backend

P3 将 podcast_research 升级为**可恢复、可审计、可被 AI Agent 查询**的知识库后端。四个子系统独立运行、可串联协作：

| 系统 | CLI | 作用 |
|------|------|------|
| 摄入队列 | `ingest list/show/retry/resume` | 所有摄入任务持久化到 SQLite，重启不丢失 |
| Vault 健康检查 | `vault-lint --vault <path>` | 5 条 lint rule 检查 Obsidian vault 质量 |
| 审核队列 | `review list/show/accept/skip/resolve` | 统一 triage lint issues / patch / entity merge |
| MCP Server | `mcp-serve` | 8 个只读 tool，Claude Code/Codex 直接查知识库 |

**MCP Tools（Claude Code/Codex 可用）：**

| Tool | 查询什么 |
|------|----------|
| `search_reports` | 搜索报告（关键词 + source 过滤） |
| `get_report` | 报告详情（含 views/signals/markdown） |
| `list_channels` | YouTube 频道及视频统计 |
| `search_entities` | 实体（公司/产品/技术/人物） |
| `get_entity_profile` | 实体详情 + 关联投资观点 |
| `list_investment_views` | 投资观点（target/direction/ai_layer） |
| `list_tracking_signals` | 跟踪信号（target/status） |
| `list_review_items` | 审核事项（type/status/severity） |

```bash
# Vault 健康检查 → 问题写入审核队列
python -m podcast_research vault-lint --vault /path/to/vault --write-review

# 审核队列 triage
python -m podcast_research review list --status open
python -m podcast_research review accept 1 --note "已修复"

# 启动 MCP Server（Claude Code 自动发现）
python -m podcast_research mcp-serve
```

详见 `docs/P3_ACCEPTANCE_REPORT.md` 和 `docs/P3_PLAN.md`。

核心能力：
- 单视频分析（本地字幕 / YouTube URL）→ Markdown 报告 + SQLite 入库
- 频道关注 + 批量视频管理 + 后台分析任务队列
- 本地 API 服务（FastAPI）+ Web Console（Jinja2）
- Obsidian Vault 导出 + Topic/Company/Claim/Signal 卡片生态
- LLM-WIKI Patch Review 模式：LLM 生成 → 人工审阅 → 安全 apply
- 长视频自动分块（Map-Reduce）
- 跨频道报告质量评估 + Watchlist Brief
- 信息源摄入管道：网页导入 / 文件上传 / 固定源跟踪 / 冲突检测 + 统一管理面板

## 快速开始

```bash
# 安装
pip install -e ".[dev]"

# mock 模式分析本地字幕文件
python -m podcast_research --subtitle-file data/subtitles/sample.srt

# mock 模式分析 YouTube 视频
python -m podcast_research --youtube-url "https://www.youtube.com/watch?v=VIDEO_ID" --mock

# 指定关注点和分析深度
python -m podcast_research --subtitle-file your_subtitle.srt --focus "新能源,港股,AI算力" --depth deep

# 启动本地 Web Console
python -m podcast_research serve

# 运行测试
python -m pytest tests/ -v
```

## 报告库查询

分析命令生成的报告自动入库，通过 `reports` 子命令查询：

```bash
python -m podcast_research reports list                    # 列出所有报告
python -m podcast_research reports list --source youtube --limit 10
python -m podcast_research reports show 1                  # 报告详情
python -m podcast_research reports show 1 --full           # 完整 Markdown
python -m podcast_research reports search "NVIDIA"         # 搜索
python -m podcast_research reports targets                 # 投资标的汇总
python -m podcast_research reports sources                 # 来源统计
python -m podcast_research reports rebuild-index           # 重建 FTS5 搜索索引
```

## 本地 API 服务

启动本地只读 API + HTML Web Console：

```bash
python -m podcast_research serve                           # 默认 127.0.0.1:8000
python -m podcast_research serve --host 127.0.0.1 --port 8000
python -m podcast_research serve --reload                  # 开发模式
```

### API 端点

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

API 为本地只读服务，不做鉴权，默认绑定 127.0.0.1:8000。

## 摄入队列管理（P3-A）

```bash
python -m podcast_research ingest list                        # 列出摄入任务
python -m podcast_research ingest list --status pending_preview
python -m podcast_research ingest show 1                      # 查看任务详情
python -m podcast_research ingest retry 1                     # 重试失败任务
python -m podcast_research ingest resume                      # 查看待处理摘要
```

## Vault 健康检查（P3-B）

```bash
python -m podcast_research vault-lint --vault /path/to/vault  # 运行全部检查
python -m podcast_research vault-lint --vault /path/to/vault --rules dead_wikilink
python -m podcast_research vault-lint --vault /path/to/vault --json
python -m podcast_research vault-lint --vault /path/to/vault --write-review  # 问题写入审核队列
```

## 审核队列管理（P3-C）

```bash
python -m podcast_research review list                        # 列出审核项
python -m podcast_research review list --status open --type lint_dead_wikilink
python -m podcast_research review show 1                      # 查看详情
python -m podcast_research review accept 1 --note "已修复"    # 接受
python -m podcast_research review skip 1 --note "暂不处理"    # 跳过
python -m podcast_research review resolve 1                   # 解决
```

## MCP Server（P3-D）— 只读知识库查询

启动 stdio MCP server，让 Claude Code / Codex / Claude Desktop 查询知识库。

```bash
python -m podcast_research mcp-serve                        # 使用默认数据库
python -m podcast_research mcp-serve --db-path /path/to/db  # 指定数据库
```

**Claude Desktop 配置：**

```json
{
    "mcpServers": {
        "podcast-research": {
            "command": "python",
            "args": ["-m", "podcast_research", "mcp-serve"]
        }
    }
}
```

**8 个只读 tool：**

| Tool | 功能 |
|------|------|
| `search_reports` | 搜索报告（关键词 + source 过滤） |
| `get_report` | 获取报告详情（含 views/signals/markdown） |
| `list_channels` | 列出 YouTube 频道及视频统计 |
| `search_entities` | 搜索实体（按类型/名称过滤） |
| `get_entity_profile` | 获取实体详情 + 关联投资观点 |
| `list_investment_views` | 列出投资观点（target/direction/ai_layer） |
| `list_tracking_signals` | 列出跟踪信号（target/status） |
| `list_review_items` | 列出审核事项（type/status/severity） |

详见 `docs/MCP_SERVER_DESIGN.md`。

## Web Console

启动 `serve` 后，浏览器可访问的页面：

| 页面 | 路由 | 说明 |
|------|------|------|
| Dashboard | `/dashboard` | Vault 健康概览、统计卡片、快捷操作 |
| 报告库 | `/reports` | 报告列表、筛选 |
| 报告详情 | `/reports/{id}` | 观点矩阵、信号、原文、全文 |
| Research Brief | `/briefs/latest` | 最新分析简报 |
| Watchlist | `/watchlist` | 关注清单简报（证据分级） |
| Watchlist 设置 | `/watchlist/settings` | 管理关注标的 |
| 搜索 | `/search` | 全文搜索报告 |
| 添加内容 | `/content/new` | 提交 YouTube URL 分析 |
| 任务列表 | `/tasks` | 统一任务队列（分析/同步） |
| 任务详情 | `/tasks/{id}` | 任务进度、日志、失败诊断 |
| Patches 列表 | `/patches` | LLM-WIKI Patch 管理 |
| Patch 详情 | `/patches/{id}` | Patch 审阅 |
| 频道管理 | `/sources/channels` | 关注频道列表、筛选（8 种过滤） |
| 频道视频 | `/sources/channels/{id}/videos` | 视频候选池、状态管理 |
| Vault 初始化 | `/setup/vault` | 首次使用引导、Vault 修复 |

## YouTube 频道管理

```bash
# 关注频道
python -m podcast_research channels add "https://www.youtube.com/@allin" --name "All-In Podcast"

# 播种默认 Tech/AI 频道包（幂等+自愈）
python -m podcast_research channels seed-tech-ai

# 频道列表与筛选
python -m podcast_research channels list
python -m podcast_research channels list --tag ai
python -m podcast_research channels list --priority core

# 管理频道标签
python -m podcast_research channels tag 1 --add "ai,tech"
python -m podcast_research channels tag 1 --remove "macro"

# 刷新频道视频列表
python -m podcast_research channels refresh 1 --limit 20

# 查看频道视频
python -m podcast_research channels videos 1

# 分析指定视频
python -m podcast_research channels analyze-video --video-id "HGbA6ze0_3M" --focus "AI投资,美股" --no-mock
python -m podcast_research channels analyze-video --video-id "HGbA6ze0_3M" --dry-run
```

通过 `channels analyze-video` 生成的报告会自动携带频道和视频元数据（频道名、视频标题、发布日期、标签等）。

## 跨频道质量评估

```bash
python -m podcast_research eval reports                          # 终端评估统计
python -m podcast_research eval reports --channel "BG2Pod"       # 按频道过滤
python -m podcast_research eval export --output eval.csv         # 导出 CSV
python -m podcast_research eval summary --output summary.md      # 导出 Markdown 总结
```

评估维度：观点数、技术洞察数、实体数、证据类型分布、相关性分级、泛化标的检测、未知发言人计数等。

## 长视频分块分析

长视频（>50K 字符或 >1000 段字幕）自动启用 Map-Reduce 分块，解决 token 超限问题：

```bash
# 自动 chunking（默认行为）
python -m podcast_research --youtube-url "VIDEO_URL" --focus "AI投资" --no-mock

# 手动控制
python -m podcast_research --youtube-url "VIDEO_URL" --no-mock --chunked
python -m podcast_research --youtube-url "VIDEO_URL" --no-mock --chunk-size 30000 --chunk-overlap 2000
python -m podcast_research --youtube-url "VIDEO_URL" --no-mock --no-chunking   # 禁用

# 频道视频 chunking
python -m podcast_research channels analyze-video VIDEO_ID --focus "科技公司" --no-mock --chunked
```

策略：按 segment 边界切分 → 逐块 extract_facts → 去重 + compaction → 单次 render_report。任一 chunk 失败中止全部分析。

## Obsidian Vault 导出

将分析报告导出为 Obsidian 知识库，含 YAML frontmatter 和双向链接：

```bash
# 基础导出
python -m podcast_research obsidian export \
  --vault "<your-vault-path>" --source youtube --dry-run
python -m podcast_research obsidian export \
  --vault "<your-vault-path>" --source youtube

# 按频道过滤
python -m podcast_research obsidian export \
  --vault "<your-vault-path>" --channel "Acquired" --dry-run

# UnknownChannel 清理（从 DB 补齐频道元数据）
python -m podcast_research obsidian cleanup-unknown \
  --vault "<your-vault-path>" --dry-run
python -m podcast_research obsidian cleanup-unknown \
  --vault "<your-vault-path>" --apply

# Channel Card 同步
python -m podcast_research obsidian sync-channel-cards \
  --vault "<your-vault-path>" --dry-run
```

导出内容：`01_Reports/`（报告）、`05_Channels/`（频道卡片）、`99_System/`（索引和日志）。已存在文件默认 skip，`--overwrite` 可覆盖。

## Topic / Company Card 生态

从报告正文 deterministic 提取 Topic 和 Company，生成 Obsidian 卡片，支持分类清理和分层管理：

```bash
# 生成卡片
python -m podcast_research obsidian generate-cards \
  --vault "<your-vault-path>" --dry-run
python -m podcast_research obsidian generate-cards --topics-only
python -m podcast_research obsidian generate-cards --companies-only

# 清理分类（非公司实体 → Topic，同义合并）
python -m podcast_research obsidian cleanup-cards \
  --vault "<your-vault-path>" --dry-run
python -m podcast_research obsidian cleanup-cards \
  --vault "<your-vault-path>" --apply

# Topic 分层管理（Core / Emerging / Long-tail）
python -m podcast_research obsidian consolidate-topics \
  --vault "<your-vault-path>" --dry-run
python -m podcast_research obsidian consolidate-topics \
  --vault "<your-vault-path>" --apply
```

## Claim & Signal 系统

从报告和 LLM-WIKI Patches 中提取 Claim 和 Signal，生成独立卡片，支持状态管理、相似度检测和追踪更新：

```bash
# 生成 Claim & Signal 卡片
python -m podcast_research obsidian generate-claims-signals \
  --vault "<your-vault-path>" --dry-run

# Claim 管理
python -m podcast_research claims list
python -m podcast_research claims show <claim_id>
python -m podcast_research claims update-status <claim_id> --status validated
python -m podcast_research claims find-similar                    # 相似 Claim 检测
python -m podcast_research claims backlog                         # 审阅队列

# Signal 管理
python -m podcast_research signals list
python -m podcast_research signals show <signal_id>
python -m podcast_research signals update-status <signal_id> --status triggered
python -m podcast_research signals update-tracking <signal_id>    # 设置追踪元数据
python -m podcast_research signals add-update <signal_id>         # 手动添加更新记录
python -m podcast_research signals tracking-backlog               # 追踪队列
```

## LLM-WIKI 动态维护

Patch Review 模式：LLM 基于 Source Reports 生成 Patch Proposal，人工审阅后安全 Apply，全程可追踪、可回滚：

```bash
# 生成 Patch（mock 测试）
python -m podcast_research llm-wiki generate-patches \
  --vault "<your-vault-path>" --topic "AI Agents" --mock

# 生成 Patch（真实 LLM）
python -m podcast_research llm-wiki generate-patches \
  --vault "<your-vault-path>" --topic "AI Agents" --no-mock
python -m podcast_research llm-wiki generate-patches \
  --vault "<your-vault-path>" --core-only --no-mock

# 验证 Patch 结构
python -m podcast_research llm-wiki validate-patches \
  --vault "<your-vault-path>"

# Apply Patch（必须显式 --apply + --confirm-reviewed）
python -m podcast_research llm-wiki apply-patch \
  --vault "<your-vault-path>" \
  --patch "00_Inbox/LLM_Patches/topic_AI_Agents_xxx.md" \
  --apply --confirm-reviewed

# 回滚 / 拒绝
python -m podcast_research llm-wiki rollback-patch \
  --patch "00_Inbox/LLM_Patches/topic_AI_Agents_xxx.md"
python -m podcast_research llm-wiki reject-patch \
  --patch "00_Inbox/LLM_Patches/topic_AI_Agents_xxx.md" --reason "证据不足"
```

安全机制：Patch YAML frontmatter 含 `auto_apply: false`，每个 Patch 末尾有 9 项 Review Checklist，Apply 使用 `LLM-WIKI:BEGIN/END` marker 包裹可追踪内容，重复 Apply 被自动拒绝。

## Workspace 管理

```bash
# 刷新 Dashboard（扫描 Vault + 重新生成摘要）
python -m podcast_research obsidian workspace refresh \
  --vault "<your-vault-path>"

# 回填关系数据（Claim/Signal related_topics/related_companies）
python -m podcast_research obsidian workspace backfill-relations \
  --vault "<your-vault-path>"

# 刷新卡片 curation 状态
python -m podcast_research obsidian workspace refresh-curation-status \
  --vault "<your-vault-path>"

# 修正报告元数据（标题、发布日期等）
python -m podcast_research obsidian workspace polish-report-metadata \
  --vault "<your-vault-path>"

# 清理长尾 Topic（标准化 + 去重）
python -m podcast_research obsidian workspace cleanup-long-tail-topics \
  --vault "<your-vault-path>"

# 生成 Watchlist Brief
python -m podcast_research obsidian workspace watchlist-brief \
  --vault "<your-vault-path>"
```

## 真实 LLM 使用

项目默认使用 mock provider（关键词规则引擎），真实 LLM 需显式 `--no-mock`：

```bash
# 1. 配置 .env（从 .env.example 复制）
cp .env.example .env
# 编辑 .env：
#   LLM_PROVIDER=openai-compatible
#   LLM_API_KEY=your-key
#   LLM_BASE_URL=https://your-api-endpoint/v1
#   LLM_MODEL=your-model

# 2. 真实 LLM 分析
python -m podcast_research --youtube-url "VIDEO_URL" --focus "AI投资,美股" --no-mock
```

**Mock Provider 定位：**
- 基于中文关键词匹配的规则引擎，**仅用于工程闭环测试**
- 不代表真实语义抽取能力
- 英文字幕在 mock 模式下输出 0 条观点是预期行为
- 默认 pytest 使用 mock provider，不调用真实 API
- 真实 LLM 测试仅作为手动集成验证

## 项目结构

```
src/podcast_research/
  cli.py                  # Typer CLI（12 个命令组，~50 个子命令）
  config.py               # .env 加载 + 全局配置
  config_store.py         # 用户设置持久化
  evaluation.py           # 跨频道质量评估
  logging_config.py       # 日志配置
  adapters/               # 数据源适配层
    base.py               # TranscriptAdapter 基类
    youtube_transcript.py # YouTube 字幕（youtube-transcript-api）
    channel_video_adapter.py  # 频道视频元数据（yt-dlp）
  analysis/               # 分析引擎
    models.py             # Pydantic v2 数据模型
    pipeline.py           # 主分析流水线
    chunking.py           # 长视频 Map-Reduce 分块
  subtitles/              # 字幕处理
    parser.py             # SRT/VTT/TXT 解析
    cleaner.py            # 清洗、去重、广告标记
  llm/                    # LLM Provider 层
    base.py               # LLMProvider 抽象基类
    mock_provider.py      # 规则引擎 mock
    openai_compatible_provider.py  # OpenAI-compatible API
    prompts.py            # Prompt 模板
  db/                     # 数据层
    models.py             # SQLAlchemy ORM（6 张核心表）
    session.py            # SQLite session 管理
    repository.py         # 数据查询/写入
    channel_repository.py # 频道/视频 Repository
    fts.py                # FTS5 全文搜索
  api/                    # API 层（FastAPI）
    app.py                # App 工厂
    schemas.py            # Pydantic 响应 schema
    routes/               # health / reports / search
  web/                    # Web Console 层
    routes.py             # ~33 个页面路由
    templates/            # 20 个 Jinja2 模板
    static/style.css      # CSS
  services/               # 业务服务层
    analyze_service.py    # 视频分析编排
    job_service.py        # 任务队列管理
    sync_service.py       # 知识同步
    watchlist_matcher.py  # Watchlist 匹配引擎
  exporters/              # 导出层
    obsidian.py           # Obsidian Vault 导出
    markdown_utils.py     # Markdown 工具
  llm_wiki/               # LLM-WIKI 动态维护
    context_builder.py    # Source Report context 构建
    patch_generator.py    # Patch 生成（mock/real）
    validator.py          # Patch 结构验证
    applier.py            # Patch Apply
    rollback.py           # Rollback / Reject
    taxonomy.py           # Topic 分类工具
    prompts.py            # LLM prompt
  claim_signal/           # Claim & Signal 系统
    extractor.py          # Deterministic 提取
    generator.py          # 卡片生成
    review.py             # 审阅操作
  workspace/              # Vault 工作区管理
    setup.py              # Vault 初始化/修复
    scanner.py            # Vault 扫描器
    generators.py         # Dashboard 生成器
    curation.py           # Curation 状态管理
    backfill.py           # 关系回填
    longtail.py           # 长尾清理
    metadata.py           # 报告元数据修正
    research_brief.py     # Research Brief 生成
    watchlist.py          # Watchlist Brief 生成
    managed_block.py      # 托管块工具
  utils/                  # 工具函数
  mcp_server/             # MCP Server（P3-D）：8 个只读 tool
tests/                    # 1563 个 pytest 测试
```

## 核心原则

1. 不输出买卖建议
2. 不把 AI 归纳伪装成嘉宾原话
3. 核心观点必须绑定原文引用和时间戳
4. 不确定信息必须显式标注
5. 所有外部依赖通过 adapter 隔离

## 当前不做

- 小宇宙链接解析、xyz-dl 字幕下载
- React / Next.js / Vue 等前端框架
- Whisper 本地转写、多平台 RSS
- RAG、向量数据库、AI 问答
- PDF/Word 导出
- 团队协作、云端同步
- 登录鉴权
- 自动定时抓取
- Deep Research（多轮 LLM 编排）
- 写入型 MCP tool（保持 MCP 只读安全边界）
- 复杂知识图谱（实体关系图、因果链）
- Vault 文件系统 MCP tool（当前只查 DB）

## 路线图

| 阶段 | 目标 | 状态 |
|------|------|------|
| P0-A | CLI 本地字幕分析闭环（mock LLM） | ✅ 已完成 |
| P0-B | CLI YouTube 字幕 Adapter（mock LLM） | ✅ 已完成 |
| P1-A | CLI 报告库查询 | ✅ 已完成 |
| P1-B | FastAPI 只读 API | ✅ 已完成 |
| P1-C | Jinja2 HTML Web Console | ✅ 已完成 |
| P1-D | SQLite FTS5 搜索增强 | ✅ 已完成 |
| P1-E | YouTube 频道关注 + 视频管理 | ✅ 已完成 |
| P1-F | Tech/AI 频道包 + Tags 系统 | ✅ 已完成 |
| P2-A | Prompt v2 + Schema 增强 + 跨频道评估 | ✅ 已完成 |
| P2-B | 长视频 Map-Reduce 分块分析 | ✅ 已完成 |
| P2-C | Obsidian Vault 导出 + Channel Card 同步 | ✅ 已完成 |
| P2-D | Topic/Company Card 生态 + 分类清理 + 分层管理 | ✅ 已完成 |
| P2-E | LLM-WIKI Patch Review → Apply → Rollback 完整生命周期 | ✅ 已完成 |
| P2-F | Claim & Signal 卡片系统 | ✅ 已完成 |
| P2-H | Workspace 管理（Dashboard/Brief/Backfill/Curation/Longtail） | ✅ 已完成 |
| P2-K | Watchlist + 后台任务队列 + 失败诊断 | ✅ 已完成 |
| P2-L | 首次使用引导 + Vault 初始化/修复 | ✅ 已完成 |
| P2-M | 频道筛选 + Source Pages + 视觉优化 | ✅ 已完成 |
| P2-N | Research Brief 质量调优 + 内容积累 | ✅ 已完成 |
| P3 | 知识库后端化（ingest_jobs + vault_lint + review_items + mcp_server） | ✅ 已完成 |
| P4 | 多期观点对比、Claim/Signal MCP tool 扩展 | 待启动 |

## 许可证

MIT License

Copyright (c) 2026 Kinoc

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## 致谢 / Acknowledgments

本项目基于以下开源项目构建，感谢所有维护者：

### 核心依赖

| 项目 | 用途 | 许可证 |
|------|------|--------|
| [FastAPI](https://github.com/fastapi/fastapi) | Web API 框架 | MIT |
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) | ORM / 数据库访问 | MIT |
| [Typer](https://github.com/fastapi/typer) | CLI 框架 | MIT |
| [Pydantic](https://github.com/pydantic/pydantic) | 数据校验 / Schema | MIT |
| [Jinja2](https://github.com/pallets/jinja) | HTML 模板引擎 | BSD-3-Clause |
| [Rich](https://github.com/Textualize/rich) | 终端格式化输出 | MIT |
| [uvicorn](https://github.com/encode/uvicorn) | ASGI 服务器 | BSD-3-Clause |

### 数据源

| 项目 | 用途 | 许可证 |
|------|------|--------|
| [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) | YouTube 字幕获取 | MIT |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | YouTube 频道/视频元数据 | Unlicense |

### 工具链

| 项目 | 用途 | 许可证 |
|------|------|--------|
| [pytest](https://github.com/pytest-dev/pytest) | 测试框架 | MIT |
| [httpx](https://github.com/encode/httpx) | HTTP 客户端（LLM API 调用） | BSD-3-Clause |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | 环境变量加载 | BSD-3-Clause |

### 灵感与集成

- [Obsidian](https://obsidian.md) — 本项目的知识库载体，导出的 Vault 文件为 Obsidian 优化的 Markdown 格式。Obsidian 本身不是开源软件，但我们感谢 Obsidian 团队创造的优秀知识管理工具和开放的文件格式生态。

---

> 本项目诞生于将重复性播客研究任务 AI 化的工作哲学。所有代码在 Claude Code 辅助下完成。
