# LLM Wiki 参考项目分析报告

> 分析日期：2026-07-01
> 参考项目：[nashsu/llm_wiki](https://github.com/nashsu/llm_wiki) v0.5.4
> 当前项目：[signalvault](https://github.com/kinosai9/signalvault)

## 一、许可协议分析

| | llm_wiki | signalvault |
|---|---|---|
| **许可证** | GPL v3 | 未声明（默认保留所有权利） |
| **版权方** | Yong Su (2024–2026) | Kinoc |
| **传染性** | 强 copyleft — 任何衍生作品必须同样以 GPL v3 发布 | N/A |

**结论：不能直接合并代码。** GPL v3 要求任何包含 GPL 代码的派生项目也以 GPL v3 开源。如果 signalvault 保持闭源或商业用途，不能直接引入 llm_wiki 的代码。但**设计理念、架构模式、算法思路**不受版权保护，可以借鉴。

**安全做法：**
- 架构和设计可以借鉴（不受 GPL 约束）
- 算法思路可以重新实现（独立开发，不参考源码）
- 不要复制粘贴任何代码文件或代码片段
- 如果未来考虑整合，需先决定项目是否愿意 GPL v3 开源

---

## 二、项目对比

### 2.1 基本定位

| 维度 | llm_wiki | signalvault |
|------|----------|------------------|
| **目标** | 通用个人知识库自动构建 | 投资播客/视频结构化分析 |
| **用户** | 知识工作者、研究者、任何人 | 投资研究者 |
| **形态** | Tauri 2 桌面应用 | Python CLI + Web Console |
| **核心循环** | Ingest → Query → Lint | 分析 → 报告 → 导出 |
| **知识组织** | 三层架构（Raw → Wiki → Schema） | 报告库 + 观点/信号/实体卡片 |
| **版本** | v0.5.4 | P2-S 完成 |

### 2.2 技术栈

| 维度 | llm_wiki | signalvault |
|------|----------|------------------|
| **语言** | TypeScript + Rust | Python |
| **前端** | React 19 + Tailwind CSS 4 + shadcn/ui | Jinja2 模板 + 手写 CSS |
| **桌面** | Tauri 2（Rust 后端） | 无（Web server 模式） |
| **数据库** | LanceDB（向量）+ 文件系统 | SQLite + FTS5 |
| **LLM** | 9 家供应商统一接口（流式） | OpenAI-compatible（httpx） |
| **搜索** | 混合搜索（关键词 BM25 + 向量 RRF） | FTS5 全文搜索 |
| **图** | Sigma.js 知识图谱可视化 | 无 |
| **包管理** | npm | pip |
| **测试** | Vitest + fast-check | pytest |

### 2.3 核心功能对比

| 功能 | llm_wiki | signalvault |
|------|----------|------------------|
| **信息摄入** | ✓ 文件系统监听 + 计划导入 | ✓ 四类入口（频道/URL/跟踪源/文件上传） |
| **摄入队列** | ✓ 持久化队列 + 崩溃恢复 | ✗ 内存 `_preview_store`（重启丢失） |
| **LLM 分析** | ✓ 两步 CoT 摄入管道 | ✓ 两阶段抽取（事实→报告） |
| **内容分块** | ✓ text-chunker | ✓ Map-Reduce 长视频分块 |
| **冲突/去重** | ✓ SHA256 + embedding 去重系统 | ✓ content_hash + URL + title 冲突检测 |
| **知识图谱** | ✓ 4 信号评分 + Louvain 社区检测 + 可视化 | ✗ |
| **Wiki 链接** | ✓ `[[wikilink]]` 自动发现和补全 | ✗ |
| **健康检查** | ✓ Lint 系统 + 修复建议 | ✗ |
| **Review 系统** | ✓ 矛盾/建议/差距审查队列 | ✗（有 Patch Review 但不同） |
| **MCP Server** | ✓ 8 tools 暴露给 AI Agent | ✗ |
| **Web Clipper** | ✓ Chrome 扩展 | ✗ |
| **多语言** | ✓ i18next（中/英/日/韩） | ✗（仅中文） |
| **模板** | ✓ 场景模板选择器 | ✗ |
| **向量搜索** | ✓ LanceDB + RRF | ✗ |
| **Desktop 系统托盘** | ✓ Tray + 开机启动 | ✗ |

---

## 三、可借鉴的设计与架构

### 3.1 高优先级 —— 直接可落地的改进

#### A. 持久化摄入队列（替换 `_preview_store`）

**llm_wiki 做法：** `ingest-queue.ts` 实现持久化队列，支持崩溃恢复、重试、状态追踪。

**当前问题：** signalvault 的 `_preview_store` 和 `_file_preview_store` 是进程内 dict，重启丢失，不支持多 worker。

**借鉴方案：**
- 在 SQLite 中新增 `ingest_queue` 表（status, preview_data, created_at, confirmed_at）
- 预览生成时写入 DB，确认后标记完成，过期自动清理
- 不需要 Rust/Tauri，直接用现有 SQLAlchemy + SQLite 即可

```
ingest_queue
  id, preview_id, source_type (url/file/tracked_entry),
  status (pending/confirmed/skipped/expired),
  preview_data (JSON), created_at, confirmed_at
```

#### B. Wiki Lint → Report Health Check

**llm_wiki 做法：** `lint.ts` 定期检查 wiki 健康状态：死链、孤立页、过期内容、frontmatter 格式错误。`lint-fixes.ts` 生成修复建议。

**当前问题：** signalvault 没有报告质量/一致性的自动检查。

**借鉴方案：**
- `workspace/lint.py` — 扫描 vault 检查：
  - 死链（`[[wikilink]]` 指向不存在的文件）
  - 孤立报告（没有关联 channel/source）
  - 过期内容（超过 N 天未更新）
  - frontmatter 格式错误
  - 重复报告检测
- 集成到 dashboard 作为一个面板

#### C. 知识图谱精简版

**llm_wiki 做法：** 4 信号评分（直接链接、source overlap、Adamic-Adar、type affinity）+ Louvain 社区检测，Sigma.js 可视化。

**当前问题：** signalvault 有 topic/company/claim/signal 卡片但缺少可视化关联。

**借鉴方案（简化版）：**
- `workspace/graph.py` — 构建报告→观点→标的→信号的关联图
- 两种输出：
  1. **Markdown 图谱卡片**（已有方向，可增强为 Mermaid graph）
  2. **JSON 图谱数据**供前端消费
- 不引入 Sigma.js / 全量前端图渲染，保持 Jinja2 技术栈
- Mermaid 语法渲染知识图谱（在 Markdown 中可用）

#### D. Review Queue → 替代当前 TODO 追踪

**llm_wiki 做法：** `review-store.ts` 管理矛盾发现、建议采纳、知识差距等审查项。

**当前问题：** signalvault 的 Patch Review 系统只覆盖 LLM-WIKI 卡片修改，没有通用审查机制。

**借鉴方案：**
- 复用现有 `patches` 表或新建 `reviews` 表
- 支持类型：contradiction（观点矛盾）、gap（知识缺口）、suggestion（AI 建议）、stale（过期内容）
- 在 dashboard 增加 "待审查" 面板
- 这实际上是我们现有 Patch Review 的泛化和扩展

### 3.2 中优先级 —— 值得规划的能力

#### E. [[wikilink]] 自动发现

**llm_wiki 做法：** `enrich-wikilinks.ts` 扫描内容，自动发现可链接的 term，生成 `[[wikilink]]`。

**借鉴方案：**
- 在 Obsidian export 时，自动为已知 topic/company 生成 wikilink
- `exporters/wikilink_enricher.py` — 扫描报告正文，匹配已有的 topic/company card，插入 `[[wikilink]]`
- 这在 Obsidian 中会创建双向链接，大幅增强知识库导航

#### F. 混合搜索（关键词 + 向量）

**llm_wiki 做法：** 关键词 BM25 + 向量搜索 + Reciprocal Rank Fusion (RRF)。

**当前问题：** signalvault 只有 FTS5 关键词搜索。

**借鉴方案：**
- 短期：增强 FTS5 搜索（权重调整、中文分词优化）
- 中期：引入 embedding 搜索（使用现有 OpenAI-compatible provider 的 embedding endpoint）
- 不需要 LanceDB，SQLite 可以存储向量（或使用 sqlite-vec 扩展）

#### G. MCP Server

**llm_wiki 做法：** `mcp-server/` 提供 8 个 tool 暴露给 Claude Desktop / Cursor 等 AI Agent。

**借鉴方案：**
- `mcp_server/` — FastMCP server 暴露 signalvault 能力给 Claude：
  - `search_reports` — 搜索报告
  - `get_report` — 获取报告详情
  - `list_channels` — 列出频道
  - `get_claims` / `get_signals` — 查询观点/信号
- 让 Claude 可以直接查询 signalvault 的知识库
- Python 原生支持，用 `mcp` 包即可

### 3.3 低优先级 —— 远期参考

#### H. Web Clipper

llm_wiki 的 Chrome 扩展通过 Readability.js + Turndown.js 提取网页内容并直接发送到桌面应用。我们可以借鉴其 Readability + Turndown 管道来增强 `GenericWebPageAdapter` 的正文提取质量。

#### I. Scenario Templates

llm_wiki 有 `templates.ts` 提供场景模板选择器（研究项目、学习笔记、写作项目等）。我们可以为 signalvault 提供类似的分析模板（深度分析、快速扫描、技术尽调等）。

#### J. 多语言支持

llm_wiki 使用 i18next 支持中/英/日/韩。signalvault 目前只有中文，可以规划英文 UI。

---

## 四、架构层面的关键差异与启示

### 4.1 前端架构：我们需要升级吗？

| | llm_wiki | signalvault |
|---|---|---|
| **框架** | React 19 + Vite | Jinja2 服务端渲染 |
| **UI 组件** | shadcn/ui + Tailwind | 手写 CSS |
| **交互** | SPA（三栏布局，拖拽面板） | MPA（每次刷新页面） |
| **状态** | Zustand（客户端状态管理） | 无（服务端状态，每次请求重建） |

**判断：不需要升级前端框架。** 原因：
1. signalvault 是本地研究工具，不是面向大众消费者的产品。Jinja2 模板足够。
2. React 迁移成本极高（80 个模块、20 个模板全部需要重写）
3. 当前约束明确说"不做 React/Vue"
4. 但可以考虑渐进式增强：在关键交互页面（如 dashboard）使用 HTMX 或 Alpine.js 实现局部刷新，不引入构建工具链

### 4.2 Desktop 化：Tauri 对我们的价值

llm_wiki 使用 Tauri 2 打包成桌面应用。signalvault 是 `python -m signalvault serve` 启动本地 server。

**判断：当前不需要。** signalvault 的 serve 模式已经足够好。Tauri 引入 Rust 工具链会增加构建复杂度。可以等用户规模扩大后再考虑。

### 4.3 LLM Provider 抽象层

llm_wiki 的 `llm-client.ts` + `llm-providers.ts` 统一了 9 家供应商的流式调用接口。signalvault 目前只有 `OpenAICompatibleProvider`。

**判断：值得借鉴，简化实现。** 不需要支持 9 家，但统一 provider 接口设计可以参考：
- 所有 provider 实现同一个 `stream_chat(messages, options) -> AsyncIterator[Chunk]` 接口
- 每个 provider 负责自己的 wire format 转换
- `MockLLMProvider` 也走同一接口

---

## 五、融合借鉴路线图建议

```
P3（当前阶段可规划）：
├── P3-A: 持久化摄入队列（SQLite ingest_queue 表）
├── P3-B: Vault Health Lint（死链/孤立/过期检测）
├── P3-C: 精简知识图谱（Mermaid graph 生成）
└── P3-D: Review Queue 泛化（扩展现有 Patch Review）

P4（中期规划）：
├── P4-A: [[wikilink]] 自动 enrich
├── P4-B: 混合搜索（FTS5 + embedding RRF）
└── P4-C: MCP Server（暴露给 AI Agent）

P5（远期参考）：
├── P5-A: Web Clipper（Chrome 扩展）
├── P5-B: 多语言 UI（i18n）
└── P5-C: 分析模板选择器
```

---

## 六、许可证行动建议

1. **当前状态：** signalvault 无开源许可证声明。GitHub 默认条款下其他人无权使用、复制、修改。
2. **如果计划开源：** 建议 MIT 或 Apache 2.0（允许商业使用，不强制下游开源），与 GPL v3 的 llm_wiki 保持距离。
3. **如果计划闭源/商业使用：** 保持当前 unlicensed 状态即可，但注明 copyright。
4. **如果考虑整合 llm_wiki 代码：** 必须先决定以 GPL v3 发布 signalvault，并接受 copyleft 义务。

---

## 七、总结

llm_wiki 是一个工程化程度很高的项目（比 signalvault 大一个数量级：React + Rust + MCP + Extension + Desktop），但它解决的问题域更通用（通用知识库），signalvault 更垂直（投资音视频分析）。

**最有价值的三个借鉴方向：**
1. **持久化摄入队列** — 直接填补当前最大架构短板（内存存储丢失问题）
2. **Vault Health Lint + Review Queue** — 提升知识库质量和可维护性
3. **MCP Server** — 让 AI Agent 直接访问 signalvault 的知识库，打开新的使用场景

**不需要做的事情：**
- 迁移到 React/Tauri
- 引入向量数据库
- 支持 9 家 LLM provider
- 做 Chrome 扩展

设计理念可以借鉴，但代码不混用，许可证边界清晰。
