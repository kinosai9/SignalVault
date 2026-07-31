# SignalVault

**本地优先的多源投资研究助手。**

SignalVault 将 YouTube / 播客字幕、网页资料、本地文本与 PDF、知识星球只读主题等来源，整理为可追溯的投资观点、标的、风险、待验证信号和原文证据。它提供浏览器中的研究工作台，同时保留 CLI、只读 API、只读 MCP Server 和可选的 Obsidian 导出能力。

> **免责声明：SignalVault 不提供投资建议。** 所有输出都是对输入资料的结构化整理，不构成买入、卖出或持有建议。AI 生成内容可能不准确，关键判断应回到原文、时间戳或 PDF 页码复核。

## Project Overview

投资研究的难点通常不是“再生成一份摘要”，而是持续回答这些问题：

- 今天关注的对象出现了什么新变化？
- 某个观点最早来自哪里，原话是什么？
- 哪些判断已经被新证据支持、削弱或推翻？
- 哪些条件仍然需要跟踪，而不是被误写成既成事实？

SignalVault 围绕这条研究链路工作：

```text
外部资料
  → 预览、去重与确认
  → 归档或 AI 分析
  → 报告、观点、风险、信号与实体
  → 时间戳 / PDF 页码 / 原文片段
  → 搜索、关注与后续复核
```

产品默认在本机运行，SQLite 是主数据源；Obsidian 是可选的知识库浏览和人工维护层。界面以中文为主，适合个人、单机、长期积累型的研究工作。

## Core Features

### 多源资料摄入

- YouTube 字幕与本地 `.srt` / `.vtt` / `.txt` 字幕
- 网页链接与固定信息源
- `.md` / `.txt` / `.html` / `.htm` 文件
- 可提取文本的 PDF，保留页级证据
- 知识星球已订阅内容的只读导入，依赖外部 ZSXQ CLI
- 导入前预览、内容质量提示、重复与冲突检测

普通网页和文本文件默认归档，不会自动消耗 LLM 调用生成研究报告。扫描型 PDF 当前不包含 OCR 能力。

### 结构化研究输出

- 投资观点、相关标的、逻辑链与风险提示
- 待验证的跟踪信号及状态
- 公司、产品、技术、人物等实体
- Markdown 报告与 SQLite 结构化数据
- 长字幕自动分块分析
- 来源证据链：核心观点必须保留 `source_quote`；视频保留时间戳，PDF 保留页码，知识星球保留星球、主题和来源链接

### 四条主要用户动线

| 用户目标 | 产品入口 |
|---|---|
| 查看关注对象和待处理变化 | 变化雷达 / 我的关注 |
| 导入或管理新资料 | 导入中心 / 信息源工作台 |
| 查找历史观点、信号和实体 | 知识搜索 |
| 复核结论与原文证据 | 报告库 / 报告详情 / 完整原文 |

### 搜索、关系与知识库

- SQLite FTS5 全文搜索，环境不支持时降级为 `LIKE`
- 跨报告、观点、信号和实体的统一搜索
- 轻量知识图谱与证据链查询
- 可选导出到 Obsidian Vault
- Topic / Company / Claim / Signal 卡片与人工审核工作流

### 可恢复与可诊断

- 持久化摄入队列，进程重启后任务状态不丢失
- 审核队列与 Vault 质量检查
- 任务进度、操作日志、系统健康检查和恢复建议
- 一键导出脱敏诊断包；诊断包不应包含 API Key、完整原文或用户文件绝对路径

### 面向工具与 Agent 的接口

- Typer CLI
- FastAPI 本地只读 JSON API
- 12 个只读 MCP tools
- Jinja2 Web Console

MCP 和 API 不提供写入型远程控制能力。

## Architecture

SignalVault 使用单体、分层、本地优先架构。Web Console 和 CLI 共享同一业务层、分析流水线与 SQLite 数据库。

```text
CLI ───────────────┐
Web Console ───────┼── services/ ── analysis/ ── db/ ── SQLite
Read-only API ─────┤        │            │
Read-only MCP ─────┘        │            ├── llm/
                            │            └── adapters/
                            ├── sources/
                            ├── exporters/
                            ├── diagnostics/
                            ├── llm_wiki/
                            └── workspace/
```

| 模块 | 职责 |
|---|---|
| `adapters/` | 将字幕等来源适配为统一的 `TranscriptSegment` |
| `llm/` | Mock 与 OpenAI-compatible 模型供应商适配 |
| `analysis/` | 清洗、事实抽取、长文本分块、报告生成与入库 |
| `sources/` | URL、文件、PDF、固定源和知识星球的摄入流程 |
| `services/` | 分析任务、同步、关注列表等业务编排 |
| `db/` | SQLAlchemy、SQLite、FTS5、原文与业务实体 |
| `api/` | 本地只读 JSON API |
| `web/` | Jinja2 Web Console |
| `exporters/` | Markdown 与 Obsidian Vault 导出 |
| `diagnostics/` | 错误分类、操作日志、健康检查和诊断包 |
| `mcp_server/` | 面向 AI 工具的只读知识库查询 |

架构的核心边界是：`adapters` 只负责数据适配，`llm` 只负责模型适配；本地字幕与 YouTube 模式共用同一条分析流水线。

更多设计细节见 [Architecture](docs/ARCHITECTURE.md)。

## Installation

### 当前可用：从源码安装

要求：

- Python 3.12+
- Git
- 可选：Obsidian
- 可选：真实分析所需的 OpenAI-compatible API

```bash
git clone ssh://git@github.com/kinosai9/signalvault.git
cd signalvault

python -m venv .venv
```

激活虚拟环境：

```bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

安装并启动：

```bash
python -m pip install -e .
python -m signalvault launch
```

`launch` 会始终绑定本机地址，自动选择可用端口，等待服务就绪后打开默认浏览器。默认地址是 `http://127.0.0.1:8000/`。

开发环境使用：

```bash
python -m pip install -e ".[dev]"
```

### 桌面应用打包

SignalVault 基于 [Briefcase](https://beeware.org/) 实验性地支持桌面应用打包：

| 平台 | 打包状态 | 说明 |
|------|----------|------|
| **macOS** (.app) | 配置就绪，待实机验证 | arm64 / macOS 12+. 需真实 Mac 环境构建与测试。 |
| **Windows** (.msi) | Spike 已完成，Runtime 待修复 | x86_64 / Windows 10+. `briefcase create/build/package` 全部通过，MSI 安装成功；运行时因嵌入式 Python 3.14.4 与系统 Python 3.14 的 `libffi` DLL 版本冲突，GUI stub 启动失败。详见 [`docs/M3-B2_WINDOWS_SPIKE_REPORT.md`](docs/M3-B2_WINDOWS_SPIKE_REPORT.md)。 |

**当前唯一的生产安装方式仍是源码安装。** 不要把仓库中的打包配置视为已发布的桌面安装包。

## First Run Guide

首次启动会进入欢迎向导：

1. 阅读本地数据与 AI 调用边界。
2. 选择 Mock 模式，或配置 OpenAI-compatible AI 服务。
3. 可选配置 Obsidian Vault；跳过不会影响导入、分析、搜索和报告功能。
4. 完成设置后进入“变化雷达”。

建议用下面的顺序完成第一次体验：

1. 在“导入中心”选择 YouTube、网页、文件或 PDF。
2. 查看预览、解析质量和重复提示。
3. 确认归档或分析。
4. 在“报告库”阅读结构化结果。
5. 打开报告详情，核对原文引用、时间戳或 PDF 页码。
6. 用“知识搜索”再次查找刚生成的报告、观点、信号或实体。

Mock 模式仅用于验证产品流程。它是中文关键词规则引擎，不代表真实模型的语义分析质量；英文资料在 Mock 模式下可能提取不到观点。

更完整的用户说明：

- [5 分钟快速开始](docs/user/QUICK_START.md)
- [用户使用手册](docs/USER_GUIDE.md)
- [常见问题](docs/user/FAQ.md)
- [故障排除](docs/user/TROUBLESHOOTING.md)

## Configuration

普通用户优先通过 Web Console 的“系统与集成”完成配置，不需要手工编辑 `.env`。

### AI 服务

| 配置 | 说明 |
|---|---|
| Provider | `mock` 或 `openai-compatible` |
| Base URL | 模型服务的 OpenAI-compatible API 地址 |
| Model | 服务商提供的模型名称 |
| API Key | 单独保存在本机 SecretStore，不写入 `config.toml` |

保存配置后使用页面中的连接测试确认服务可用。真实 LLM 会产生服务商费用；长资料分块后通常会触发多次调用。

### Obsidian

Obsidian 是可选集成。配置已有 Vault 的绝对路径后，SignalVault 会先验证路径，再提供初始化预览、初始化、修复和写入测试。SQLite 始终是主数据源。

### 环境变量

开发者和高级用户可以使用环境变量覆盖配置：

```bash
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=https://your-api-endpoint/v1
LLM_MODEL=your-model
LLM_API_KEY=your-key
OBSIDIAN_VAULT_PATH=/absolute/path/to/vault
SIGNALVAULT_HOME=/absolute/path/to/signalvault-data
```

不要提交 `.env`，也不要把 API Key 粘贴到日志、Issue 或诊断描述中。

## Privacy Model

SignalVault 的隐私模型是“本地存储，显式外发”：

- 数据库、报告、原文、配置、日志和诊断资料默认保存在用户电脑上。
- Web 服务默认只绑定 `127.0.0.1`，没有登录鉴权，不应暴露到公网。
- 使用真实 LLM 时，只有完成分析所需的文本会发送给用户配置的模型服务；数据处理规则取决于该服务商。
- Mock 模式不调用真实 LLM API。
- API Key 与普通配置分开存储；Unix 系统使用仅当前用户可读写的文件权限，Windows 依赖用户目录 ACL。当前 SecretStore 不是操作系统钥匙串。
- 诊断包会脱敏密钥、原文和路径，但分享前仍建议人工检查。
- 知识星球能力只读取用户已获授权的内容，不提供写入操作。
- Obsidian 同步是可选的本地文件写入。

本项目是单用户本地应用，不提供云同步、团队协作或登录鉴权。

## Current Status

当前版本为 `0.1.0`，项目处于 **Release Candidate 工程阶段**。

当前仓库可通过 `python -m pytest --collect-only -q` 收集 **2542 tests**；该数字表示测试发现成功，不等同于本次 README 重构重新执行了全部测试。

已完成：

- 多源摄入、结构化分析、报告与 SQLite 入库
- PDF 页级证据与知识星球只读导入
- 统一搜索、轻量知识图谱与只读 MCP Server
- SourceDocument / SourceSegment 原文层
- 变化雷达、信息源工作台、导入向导、知识搜索和报告证据链
- 首次启动向导、跨平台用户数据目录、AI / Obsidian 设置中心
- 操作日志、诊断中心、恢复建议与脱敏诊断包
- M3-B0 RC 用户交付准备

尚未完成：

- macOS `.app` 的实机创建、构建、打包和完整生命周期验证
- Apple 代码签名、公证和正式分发
- 真实用户 RC 测试与反馈闭环

详细状态与证据：

- [M3-B0 RC Delivery Readiness Report](docs/M3B0_RC_DELIVERY_READINESS_REPORT.md)
- [Release Engineering Audit](docs/RELEASE_ENGINEERING_AUDIT.md)
- [Known Issues](docs/release/KNOWN_ISSUES.md)
- [Changelog](CHANGELOG.md)

## Roadmap

当前路线聚焦交付质量，而不是继续扩展功能范围：

1. 在 macOS arm64 实机执行 Briefcase create / build / package。
2. 验证双击启动、浏览器唤起、应用数据目录、端口与单实例、退出和异常恢复。
3. 完成真实 LLM、YouTube、PDF、知识星球、Obsidian 与 MCP 的人工集成验收。
4. 完成 RC 分发、真实用户测试和问题修复。
5. 在正式发布前处理签名、公证、版本与发布说明。

当前明确不做：

- 投资建议或自动交易
- React / Vue / Next.js 前端重写
- Whisper 本地转录
- RAG、向量数据库或 AI 问答
- 自动定时抓取
- 团队协作、云同步和登录鉴权
- 知识星球写入型客户端
- 写入型 MCP tools
- 扫描型 PDF 自动 OCR

完整路线见 [Roadmap](docs/ROADMAP.md)。

## Development Documentation Links

| 文档 | 用途 |
|---|---|
| [Developer Guide](docs/DEV_GUIDE.md) | 环境、测试与常用命令 |
| [Architecture](docs/ARCHITECTURE.md) | 分层架构与模块边界 |
| [Project Rules](docs/PROJECT_RULES.md) | 工程约束、命名与数据库规则 |
| [Source Ingestion](docs/SOURCE_INGESTION.md) | 多来源摄入流程与边界 |
| [Frontend Experience Plan](docs/FRONTEND_EXPERIENCE_EXECUTION_PLAN.md) | 四条用户动线与前端契约 |
| [MCP Server Design](docs/MCP_SERVER_DESIGN.md) | 只读 MCP Server |
| [Release Checklist](docs/RELEASE_CHECKLIST.md) | 工程发布门禁 |
| [RC Checklist](docs/release/RC_CHECKLIST.md) | 用户交付体验门禁 |

贡献前请先阅读 [AGENTS.md](AGENTS.md)、[Architecture](docs/ARCHITECTURE.md) 和 [Project Rules](docs/PROJECT_RULES.md)。核心功能变更需要补充测试；修改 HTML 或 CSS 时还必须执行 Web 页面断言与 UI smoke tests。

```bash
python -m pytest tests/ -q
python -m pytest tests/test_ui_smoke.py -v
ruff check src/ tests/
```

默认测试使用 Mock Provider，不调用真实 API，也不应写入真实 `data/` 或 Obsidian Vault。

## License

[MIT License](LICENSE)
