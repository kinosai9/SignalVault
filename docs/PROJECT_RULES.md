# Project Rules

> 本文档定义 signalvault 项目的工程规范、约束和边界。
> 所有阶段（P0–P7 及后续前端体验改造）的开发和设计必须遵守这些规则。
> 与 CLAUDE.md（AI 助手指令）互补：CLAUDE.md 面向 AI 编码助手，本文档面向人类开发者。

## 架构边界

```
adapters/  → 数据源适配（字幕 → TranscriptSegment）。不调用 LLM。
llm/       → LLM 供应商适配。不处理数据源逻辑。
analysis/  → 分析流水线。不直接访问 DB（通过 repository）。
db/        → SQLAlchemy + SQLite。不包含业务逻辑。
api/       → FastAPI 只读 JSON API。不返回 HTML。
web/       → Jinja2 HTML。不直接写 DB（通过 repository）。
services/  → 业务编排。协调多个层，不持有状态。
sources/   → 信息源摄入管道。普通网页/文本默认写 SourceArchive/DeepNotes；PDF/ZSXQ 可通过专用 analysis workflow 生成 Report。
exporters/ → Obsidian Vault 导出。只写文件，不修改 DB。
llm_wiki/  → Patch Review 生命周期。只操作卡片文件，不修改 DB。
workspace/ → Vault 管理。只扫描/生成 Markdown，不调用 LLM。
diagnostics/ → 错误分类、操作日志、诊断中心、诊断包导出。
mcp_server/ → MCP Server（P3/P5）。只读查询，不修改任何内容。
```

## 禁止事项

- 不输出投资建议，不把 AI 推断伪装成嘉宾原话
- 核心观点必须有 source_quote；视频证据必须保留 timestamp，PDF 证据必须保留 evidence_page，ZSXQ 证据必须保留 group/topic/source_url 追溯
- API Key 不进代码、不进日志、不进 git
- `.env` 不提交，`.env.example` 只用占位值
- 不做：React/Vue/Next.js、Whisper、RAG、向量库、PDF/Word 导出、登录鉴权、自动定时抓取、团队协作、ZSXQ 写入型客户端
- 不做桌面 UI（Tauri/Electron）
- 不新增 LLM Provider（保持 OpenAI-compatible + mock）

## 测试规则

```bash
python -m pytest tests/ -v    # full suite（mock provider）
python -m pytest --collect-only -q  # 当前可收集 1993 tests
python -m pytest tests/ -q    # 快速模式
```

- 默认 pytest 使用 mock provider，不调用真实 API
- 测试用 `db_session`/`seeded_db` fixture 隔离，不污染 `data/`
- Obsidian 测试用 `tmp_path`，不写真实 Vault
- 新增核心功能必须补测试
- UI smoke tests 验证关键页面，不需要 Playwright 全量覆盖

## 命名约定

- 文件名：snake_case（Python）、kebab-case（Markdown/template）
- 类名：PascalCase
- 函数/变量：snake_case
- 常量：UPPER_SNAKE_CASE
- 数据库表：snake_case 复数（reports, channels, ingest_jobs）
- 状态值：snake_case 字符串（preview_ready, pending_review）
- 枚举值：与状态值一致
- Vault 目录：`XX_CategoryName/`（两位数字前缀 + PascalCase）
- Vault 文件：`YYYY-MM-DD_descriptive_name.md` 或 `entity_name.md`

## DB 迁移规则

- 只新增表/列，不删除、不重命名现有列
- 所有新表使用 `CREATE TABLE IF NOT EXISTS`
- 不引入 Alembic/迁移框架（保持简单）
- DB schema 变更必须在 commit message 中说明

## Vault 写入规则

- 所有 vault 写入必须通过 exporters/ 或 sources/ 模块
- 写入前检查目标文件是否已存在（避免覆盖）
- 覆盖操作必须显式 `--overwrite` 参数
- `dry-run` 模式是默认行为（CLI）；Web 端确认后才写入
- 写入后记录到对应的 System Log

## P3 新增规则

- `ingest_jobs` 表独立于现有表，仅通过 ingest_jobs 模块访问
- Vault lint 结果通过 `review_items` 写入统一审核队列
- `review_items` 表仅通过 `sources.review_items` 模块写入
- MCP server 只读，不持有数据库连接（每次 tool 调用新建 session）
- MCP server 不引入新的环境变量（复用 OBSIDIAN_VAULT_PATH）

## P4–P7 新增规则

- PDF 只默认处理文本型 PDF；扫描件进入 Review Queue，不自动外传 OCR。
- ZSXQ 只做已订阅内容的只读导入，不做订阅、发布、评论、点赞、删除或运营管理。
- Unified Search 和 Knowledge Graph 保持 SQLite 自包含，不引入向量库或图数据库。
- `operation_logs` 只记录脱敏后的操作摘要、错误码和元数据，不记录密钥、cookie、完整原文、报告全文。
- Diagnostic Bundle 必须脱敏，不包含 API Key、Token、密码、完整付费内容或隐私字段。
- 前端体验改造保持后端数据契约不变；必要适配放在 Web route context builder，不改核心服务返回结构。

## Git

- commit message 用英文，简洁描述变更意图
- Push 仅用于跨设备同步，等用户确认
- GitHub 仓库用 SSH

## 许可证

- 当前未声明开源许可证（保留所有权利）
- 参考项目（nashsu/llm_wiki）使用 GPL v3，代码不混用
- 设计模式、架构思路可借鉴，但需要独立实现
