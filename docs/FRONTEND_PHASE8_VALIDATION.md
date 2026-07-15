# Frontend Phase 8 Validation

## 结论

> **2026-07-15 封板复核：** Phase 8 之后，PDF Web 上传分析、知识星球 Web 工作台、SourceDocument/SourceSegment 原文层、报告完整原文中英对照和翻译服务已经落地。本文保留 Phase 8 当时的验证证据；下文标为“后续”的事项应以本说明和 `SOURCE_PROVENANCE_PERSISTENCE_DESIGN.md` 当前状态为准。

阶段 8 以“验证与收口”为主，不继续扩展前端能力。

当前前端主路径已经形成闭环：

```text
变化雷达 → 信息源工作台 → 导入中心 → 统一知识搜索 → 报告证据链/完整原文 → 任务与诊断
```

页面结构、左侧导航、SignalVault 命名、导入中心入口、搜索页、报告详情证据链、诊断中心与操作日志聚合页已经可以支撑非技术用户的日常使用路径。

本阶段发现的主要收口点是：诊断中心与操作日志的实际入口是 `/tasks`，不是 `/diagnostics` 或 `/operations`。当前模板内文案已经明确为“诊断中心与操作日志”，但后续文档、测试和讨论中应统一使用 `/tasks` 作为 Web 路径。

## 验证范围

### 自动化验证

已运行前端相关测试：

```bash
python -m pytest tests\test_web_pages.py tests\test_ui_smoke.py tests\test_diagnostics_summary.py tests\test_operation_log.py -q
```

结果：

```text
186 passed, 2 warnings
```

警告来自 `websockets`/`uvicorn` 的弃用提醒，不是本轮前端回归。

### 环境复核

使用 `D:\miniconda3\python.exe` 重跑同一组测试时，测试环境不完整：

- `typer` 缺失，导致 CLI 相关测试失败。
- `youtube_transcript_api` 缺失，导致 YouTube 分析服务导入失败。
- Playwright headless 启动被系统权限拦截，报 `spawn EPERM`。
- 默认 pytest 临时目录 `C:\Users\Huawei\AppData\Local\Temp\pytest-of-Huawei` 无权限，需要显式 `--basetemp`。

这些属于本机解释器/依赖环境问题，不直接代表当前前端模板回归。项目实际验证应优先使用已配置好的项目环境或修复 `.venv` 启动器。

## 页面快照

已通过 FastAPI `TestClient` 渲染关键页面为静态 HTML 快照，并内联当前 CSS，便于离线复核：

| 页面 | 路径 | 快照 |
| --- | --- | --- |
| 变化雷达 | `/dashboard` | `docs/ui_prototypes/screenshots/implementation/phase8-dashboard.html` |
| 信息源工作台 | `/sources` | `docs/ui_prototypes/screenshots/implementation/phase8-sources-workbench.html` |
| 导入中心 | `/sources/import/new` | `docs/ui_prototypes/screenshots/implementation/phase8-import-center.html` |
| Unified Knowledge Search | `/search?q=AI` | `docs/ui_prototypes/screenshots/implementation/phase8-knowledge-search.html` |
| 报告证据链 | `/reports/{id}` | `docs/ui_prototypes/screenshots/implementation/phase8-report-evidence-chain.html` |
| 诊断中心与操作日志 | `/tasks` | `docs/ui_prototypes/screenshots/implementation/phase8-diagnostics-center.html` |

内置浏览器安全策略禁止直接访问 `file://`，当前沙箱也无法保活本地静态服务器，因此本阶段未能生成新的 PNG 截图。HTML 快照已经是实际 Jinja 模板渲染结果，不是手写原型。

## 页面核对结果

### 1. 变化雷达

通过点：

- 首屏从“项目功能入口”调整为“今日研究动作”。
- 用户先看到关注点变化、待处理信息源、诊断状态，而不是后端功能列表。
- 左侧导航保持稳定，降低非技术用户迷路概率。

收口建议：

- 后续可以把“关注点变化”接入真实的 watchlist delta 数据，而不是只展示聚合状态。

### 2. 信息源工作台

通过点：

- 页面承担“信息源状态总览”职责，不再把所有导入入口混在一个表单里。
- 已突出 YouTube、网页、固定信息源、文件/PDF、知识星球几类来源。
- 保留“诊断来源”入口，符合导入失败后的用户动线。

收口建议：

- Source Document / Source Segment 已落地；“已保留全文 / 仅保留元数据 / 解析失败”的来源保留状态仍未进入工作台。

### 3. 导入中心

通过点：

- 导入入口按用户心智拆分：视频、知识星球、网页、固定源、文件/PDF。
- 能力描述更偏“我应该选哪个入口”，而不是技术模块名。
- 路径统一为 `/sources/import/new`，适合作为所有导入 CTA 的落点。

收口建议：

- PDF 上传分析和知识星球只读导入/同步/分析已经具备 Web 入口。
- 导入预览页后续应显示“将保留哪些可追溯材料”。

### 4. Unified Knowledge Search

通过点：

- 页面定位从报告搜索升级为知识库统一搜索。
- 结果可承接报告、观点、信号、实体等不同层级。
- 对投资研究场景，搜索页已经更接近“查证据链”而不是“问答入口”。

收口建议：

- Source Provenance 底层查询已支持 `source_document` 和 `source_segment`，Web 搜索筛选仍待开放。
- 搜索结果卡片应显示来源片段的时间戳、页码、段落号和原文/译文状态。

### 5. 报告详情页证据链

通过点：

- 报告页已经强化“证据链”而不是只显示 Markdown 正文。
- 观点、信号、证据引用有更清晰的视觉分层。
- 当前字段仍兼容后端已有 `source_quote`、timestamp、PDF page 等契约。

收口建议：

- 报告已可打开完整原文；观点/信号证据卡按 `source_segment_id` 精确跳转仍待完成。

### 6. 诊断中心与操作日志

通过点：

- `/tasks` 已承担诊断中心与操作日志聚合页职责。
- 页面把系统健康、建议动作、最近操作日志、任务列表放在一个排障动线里。
- 文案更接近“下一步该做什么”，不是只显示错误码。

收口建议：

- 不建议新增 `/diagnostics` 和 `/operations` 两个并列入口，避免导航复杂化。
- 如果后续确实需要独立日志页，应从 `/tasks` 下钻，不要在一级导航增加新的技术页面。

## 当前待收口问题

1. 项目 `.venv` 启动器损坏  
   `.venv\Scripts\python.exe` 仍无法启动；`.codex-venv\Scripts\python.exe` 可以启动 Web 应用。Release Engineering 需要确定唯一交付环境，并通过干净安装验证替代本机偶然可用状态。

2. Python 解释器路径容易漂移  
   `C:\Python314\python.exe`、`D:\miniconda3\python.exe`、`.venv` 同时存在，依赖集不一致。阶段验证应明确使用项目环境。

3. PNG 截图未完成  
   HTML 快照是实际 Jinja 模板渲染结果。2026-07-15 复核时应用可在 `127.0.0.1:8765` 启动，但本机 `npx` 安装损坏且项目环境未安装 Python Playwright，新的浏览器 PNG 仍未生成。修复统一环境后运行：

   ```bash
   python -m http.server 18768 --bind 127.0.0.1 --directory docs/ui_prototypes/screenshots/implementation
   ```

   然后访问：

   ```text
   http://127.0.0.1:18768/phase8-dashboard.html
   http://127.0.0.1:18768/phase8-sources-workbench.html
   http://127.0.0.1:18768/phase8-import-center.html
   http://127.0.0.1:18768/phase8-knowledge-search.html
   http://127.0.0.1:18768/phase8-report-evidence-chain.html
   http://127.0.0.1:18768/phase8-diagnostics-center.html
   ```

## 阶段 8 判断

前端体验优化可以进入收口状态，但不建议立即做大规模新页面。

下一步更有价值的是两件事：

1. 修复项目运行环境，确保测试、serve、截图验证都使用同一套 Python 环境。
2. 按 `SOURCE_PROVENANCE_PERSISTENCE_DESIGN.md` 落地原文层后，再回到搜索页和报告详情页补“可打开原文片段”的真实交互。
