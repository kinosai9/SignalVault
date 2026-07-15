# Release Engineering Audit

> 审计日期：2026-07-15  
> 结论：功能实现与主文档已基本统一，可以进入 Release Candidate 修复阶段；当前不建议直接标记正式发布。

## 1. Executive Conclusion

本轮从代码、路由、CLI、数据库模型、测试、Jinja 模板、Phase 8 实际渲染快照和本地运行页面反推实现事实。审计前的主要问题不是功能缺失，而是文档时间线落后：README、来源文档、P7 计划、TODO 和许可证描述仍停留在前端改造或原文层落地前。

本轮已完成：

- 统一项目阶段为 Release Engineering 封板。
- 补齐用户使用手册，并按日常用户动线组织。
- 统一 PDF/知识星球 Web 能力、诊断入口和原文层状态。
- 统一 2013 tests、19 张 ORM 表、73 个 Web 路由、33 个模板等可验证数字。
- 将历史计划文档与当前 as-implemented 边界分开表述。
- 将发布清单改造成可执行门禁，而不是静态勾选表。

当前正式发布阻断项：

1. Ruff 0.15.21 对 `src/` 与 `tests/` 报 45 项问题，CI 若安装最新 Ruff 将无法通过。
2. 项目 `.venv` 启动器损坏，尚未完成全新虚拟环境的 clean install 验证。
3. 最新页面缺少新的桌面/移动端 PNG 验收；Phase 8 HTML 快照有效，但不替代最终视觉回归。
4. 真实 LLM、YouTube 备用路径、真实 PDF、ZSXQ、Obsidian 和 MCP 仍需人工集成验收。

## 2. Verified Implementation Baseline

| 项目 | 当前事实 | 验证方式 |
|---|---:|---|
| pytest | 2013 tests | `python -m pytest --collect-only -q` |
| Python modules | 122 | `src/signalvault/**/*.py` 文件计数 |
| ORM tables | 19 | `db/models.py` 的 `__tablename__` 计数 |
| Web routes | 73 | `web/routes.py` 的 GET/POST route 计数 |
| Jinja templates | 33 | `web/templates/` 文件计数 |
| MCP tools | 12，只读 | README、MCP server 与 P5 验收交叉核对 |
| Frontend main flows | 4 | 变化雷达、信息源工作台/导入中心、统一知识搜索、报告证据链 |
| Diagnostics Web path | `/tasks` | 当前 route 与模板 |
| License | MIT | 仓库根目录 `LICENSE` |

## 3. Actual Frontend Review

| 页面 | 实际职责 | 当前判断 | 剩余边界 |
|---|---|---|---|
| `/dashboard` | 变化雷达与今日动作 | 主入口成立，不再是技术功能目录 | 关注变化仍以聚合状态为主 |
| `/sources` | 来源状态、待确认、失败项 | 信息源工作台职责清楚 | 未显示全文保留状态 |
| `/sources/import/new` | 按资料类型分流 | 五类来源入口完整 | 本轮修正了 PDF “仅后端支持”的过时文案 |
| `/sources/files/import` | 文本归档、PDF 上传分析 | Web PDF 闭环已实现 | Web PDF 当前固定 mock provider |
| `/sources/zsxq` | 授权状态、星球同步、主题导入/分析 | 只读安全边界清楚 | 依赖外部 CLI 安装与登录 |
| `/search` | 报告、观点、信号、实体搜索 | 结论层搜索可用 | 原文材料/片段底层已支持，Web 未开放 |
| `/reports/{id}` | 观点、风险、信号、证据链 | 证据优先于摘要 | 证据卡尚未按 segment 精确跳转 |
| `/reports/{id}/transcript` | 完整原文与可选翻译 | 原文层用户入口已形成 | 仅对已关联 SourceDocument 的报告可见 |
| `/tasks` | 诊断、恢复建议、日志、任务 | 一个入口完成排障动线 | 不应再新增一级 `/diagnostics` 导航 |

## 4. Documentation Changes

| 文档 | 本轮处理 |
|---|---|
| `README.md` | 更新阶段、数字、Web 页面表、项目结构与用户手册入口 |
| `docs/USER_GUIDE.md` | 新增非技术用户手册，覆盖首次使用、日常循环、各来源导入、证据阅读和排障 |
| `docs/ROADMAP.md` | 将 Active track 改为 Release Engineering，补充 provenance 第一阶段 |
| `docs/SOURCE_INGESTION.md` | 更新 PDF/ZSXQ Web 状态和原文层实际边界 |
| `docs/SOURCE_PROVENANCE_PERSISTENCE_DESIGN.md` | 区分底层已实现、Web 已开放和剩余产品化工作 |
| `docs/P7_RELIABILITY_DIAGNOSTICS_PLAN.md` | 将 P7-F 更新为 CLI + Web 已交付，统一 `/tasks` |
| `docs/FRONTEND_PHASE8_VALIDATION.md` | 增加 Phase 8 之后的封板复核说明 |
| `docs/PROJECT_RULES.md` | 修正 MIT 许可证、测试数字与阶段范围 |
| `docs/RELEASE_CHECKLIST.md` | 重写为 clean install、自动化、主动线、安全、人工集成、仓库门禁 |
| `TODO.md` | 删除历史完成项，只保留 Release Engineering、人工验收和真实 backlog |
| `CHANGELOG.md` | 记录本轮文档封板与验证基线 |

## 5. Validation Evidence

### Passed

- Markdown 相对链接：全部可解析。
- 过期状态扫描：核心文档无“前端准备中、P7 Web 待承接、PDF/ZSXQ 仅 CLI、未声明许可证”等残留。
- 定向回归：225 passed，覆盖 Web 页面、文件/PDF、SourceDocument/SourceSegment 和翻译服务。
- UI smoke：7 passed，2 个依赖弃用 warning。
- 非浏览器全量：四组 602 + 379 + 450 + 575 = 2006 passed。
- 总计：2013/2013 tests passed；分组运行用于规避单进程 15 分钟工具上限。
- 本地 Web：使用 `.codex-venv` 启动，`GET /dashboard` 返回 200。
- `git diff --check`：无 whitespace error。

### Not Passed Or Not Completed

- Ruff 0.15.21：45 errors。39 项可自动修复，主要为 import 排序、未使用 import；另有 SIM102、SIM105、E741、F841 等需人工判断。
- 单进程 `python -m pytest tests/ -q`：15 分钟工具上限超时，无失败输出；分组执行已覆盖并通过全部 2013 tests。
- `.venv`：启动器损坏；`.codex-venv` 可运行，但不是 clean install 证据。
- 新 PNG：本机 `npx` 损坏；新装 Playwright 与已有浏览器版本不匹配。Phase 8 实际 Jinja HTML 快照仍可用于结构复核。
- 真实外部集成：未执行，避免真实 API 费用和私有数据访问。

## 6. Release Decision

建议将当前状态标为 **RC preparation**，不要标为正式 Release。

Release Candidate 前必须完成：

1. 修复 45 个 Ruff 问题，并固定 Ruff 版本或确保 CI 与本地一致。
2. 在全新 Python 3.12+ 环境执行安装、全量测试、ruff 和 serve。
3. 生成六条关键页面的桌面/移动端截图并人工检查。
4. 更新版本号与 CHANGELOG，清理临时目录和日志。

正式 Release 前再完成真实 LLM 与外部连接器人工验收，并把结果附在发布记录中。
