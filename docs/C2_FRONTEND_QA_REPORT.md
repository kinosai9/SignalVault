# C2 前端完整性 QA 报告

> QA 日期：2026-07-17  
> 封板基线：`f5b47d9cb4bd34ab987ddd0c80d24b7c34a971fd` (`main`)  
> QA 范围：`/settings`、`/settings/ai`、`/settings/obsidian`、`/settings/system`、`/settings/about`  
> 初始 QA 结论：**不满足 Release Candidate 前端门禁。1 个 P0、3 个 P1、3 个 P2。**  
> 最终前端收口后：C2-QA-002 至 C2-QA-007 已关闭；仅 C2-QA-001 真实 Provider 事件循环缺陷保留为后端 Release Blocker。

## 1. 执行摘要

- 完成 5 个页面 × 6 个指定视口，共 30 个全页截图：1920×1080、1440×900、1366×768、1280×800、390×844、430×932。
- 完成 AI 11 类状态构造；真实 Provider 的成功/鉴权失败/模型不存在等连接结果被同一个运行时缺陷阻断，无法到达预期状态。
- 完成 Obsidian 11 类状态构造与截图。
- 实际通过：AI 保存、Key 替换、Key 删除后回退环境变量、Vault validate/保存/preview/initialize/repair/test write/disable/clear path、CSRF 403、刷新、浏览器返回、重复提交。
- 未通过：AI 真实连接测试。设置页侧栏打开/关闭已在最小前端修复后通过。
- 所有指定视口均可纵向滚动到底；未检测到页面级横向滚动、按钮越界或表单控件越界。
- 合成 API Key 在 HTML、密码输入值、截图与结果文件中的泄漏数为 **0**。
- 浏览器 `pageerror` 为 0；唯一控制台 403 为主动执行的 CSRF 负向测试。

## 2. 问题清单

### C2-QA-001 — P0 / Release Blocker：真实 Provider「测试连接」在封板环境不可用

- 页面：`/settings/ai`
- 尺寸：所有尺寸；功能缺陷与视口无关。
- 现象：成功、通用失败、鉴权失败、模型不存在四类测试全部显示 `测试失败: No module named 'nest_asyncio'`，状态持续为“已配置，尚未验证”。
- 根因证据：`test_llm_connection()` 在 FastAPI 异步请求内依赖 `nest_asyncio`，但 `pyproject.toml` 的运行依赖和开发依赖均未声明该包。
- 用户影响：用户无法确认真实 LLM 配置是否可用，也无法获得鉴权失败、模型不存在等可行动提示；C2-A 的核心闭环失效。
- 建议修复：单独进入后端/运行时修复，不在本轮前端修复中处理。优先消除同步函数在异步路由内嵌套事件循环的设计；不要只为“跑通”盲目补依赖。
- 后端影响：**是**。涉及异步调用边界或依赖声明，需要专项测试。
- 证据：`output/playwright/c2-frontend-qa/run-20260717-093823/results.json`；`screenshots/ai__auth-failed__1440x900.png`。

### C2-QA-002 — P1：设置中心脱离主应用 Shell，桌面无侧栏、移动端无菜单

- 页面：全部 5 个设置页面。
- 尺寸：全部尺寸；390×844、430×932 影响最大。
- 现象：DOM 中 `.app-sidebar`、`[data-nav-toggle]` 均为 0；无法执行侧栏打开/关闭。移动端仍被全局 CSS 添加 54px 顶部留白，但没有对应移动顶栏。
- 用户影响：设置页像跳出了 SignalVault；移动端无法通过主导航切换至变化雷达、导入中心、搜索等主任务，只能依赖面包屑返回。
- 建议修复：让设置模板复用主 `base.html` 的应用 Shell、移动顶栏、侧栏与 `app.js`，设置二级导航保留在内容区。
- 后端影响：否。仅允许调整 Jinja 模板加载路径，不改变任何业务路由或服务。
- 证据：`run-20260717-093039/screenshots/matrix__settings__1920x1080.png`、`matrix__settings__390x844.png`；结果中的 `sidebar_open_close=false`。

### C2-QA-003 — P1：设置中心与既有前端设计系统明显不一致

- 页面：全部 5 个设置页面。
- 尺寸：全部尺寸。
- 现象：设置页使用硬编码 Bootstrap 蓝/绿/红、4–6px 圆角、1100px 独立容器和旧式表格；主应用使用暖色 Surface、墨绿 Accent、14–18px 圆角、1240px page shell、统一阴影与状态色。标题层级、卡片间距、按钮、badge、alert、导航均不协调。
- 用户影响：新增页面看起来像另一个产品；状态颜色含义与主站不一致，降低可信度和学习迁移。
- 建议修复：用现有 CSS token 重写设置页局部样式；不引入新设计系统、不改后端数据契约。
- 后端影响：否。
- 证据：桌面和移动端全部矩阵截图，重点为 `matrix__settings-ai__390x844.png`。

### C2-QA-004 — P1：移动端路径/属性表格可读性失败

- 页面：`/settings/system` 最严重；`/settings/ai`、`/settings/obsidian`、`/settings/about` 同类风险。
- 尺寸：390×844、430×932。
- 现象：固定 180px 首列挤压值列，长路径逐字符断行；390px 下系统页高度达到 3203px。AI 状态来源如 `(default)` 也被逐字符拆分。
- 用户影响：用户难以复制、辨认和比对路径；页面虽“没有横向滚动”，但信息不可读。
- 建议修复：移动端将 `.prop-table tr` 改为纵向 label/value 卡片行；路径使用 `overflow-wrap:anywhere`，标签单独换行；桌面保持表格扫描效率。
- 后端影响：否。
- 证据：`run-20260717-093039/screenshots/matrix__settings-system__390x844.png`、`obsidian__long-path__390x844.png`。

### C2-QA-005 — P2：概览页错误显示 Mock 模式 API Key“已配置 (default)”

- 页面：`/settings`
- 尺寸：全部尺寸。
- 现象：同一隔离配置中，概览卡显示 API Key 已配置 `(default)`，AI 详情页正确显示“未配置”。
- 原因：模板只判断 `ai_key_source` 是否非空；`default` 也被当作已配置。
- 用户影响：状态摘要与详情矛盾，可能让用户误以为系统已有 Key。
- 建议修复：概览模板将 `default` 明确视为未配置；不修改 SecretStore 或 ConfigService。
- 后端影响：否。
- 证据：`matrix__settings__1920x1080.png` 与 `matrix__settings-ai__390x844.png` 对照。

### C2-QA-006 — P2：关于页 AI badge 的 CSS class 使用中文状态文本

- 页面：`/settings/about`
- 尺寸：全部尺寸。
- 现象：模板生成类似 `status-Mock 模式` 的 class，无法匹配状态色规则，AI badge 仅有基础外观。
- 用户影响：关于页状态与 AI 页面、概览页颜色语义不一致。
- 建议修复：在模板内按已知状态文本映射到 `status-mock/incomplete/unvalidated/ok/error/overridden`；不改 view model。
- 后端影响：否。

### C2-QA-007 — P2 / 已关闭：错误页与长信息缺乏设置中心外壳和统一断行策略

- 页面：CSRF 403 响应、所有 settings alert、长路径/长错误压力态。
- 尺寸：移动端最明显。
- 初始现象：CSRF 错误返回裸 `<h1>` 页面；长错误依赖浏览器自然换行，缺少统一 `overflow-wrap`。
- 用户影响：失败时突然离开产品上下文；技术信息对非 IT 用户不可行动。
- 已修复：HTML 表单的 Origin/CSRF 失败统一返回主应用 Shell 内的 403 页面，提示“请求已失效”“请刷新页面后重新操作”，并提供白名单生成的原设置页与设置中心入口。错误页不签发或包含 CSRF 字段，不反射表单、Referer、路径、Secret 或内部错误原因。JSON API 继续返回 `application/json` 的结构化 403。
- 后端影响：仅变更 HTML 路由响应展示，不改变 token、double-submit cookie、HMAC、Origin/Referer 或 JSON API 守卫语义。
- 证据：`output/playwright/c2-frontend-qa/closeout-20260717-110656/`；三档错误页均为 403 且无横向溢出。

## 3. 状态与操作覆盖

### AI 状态

| 状态 | 构造/截图 | 结果 |
|---|---:|---|
| Mock 模式 | 是 | 正常 |
| 真实 Provider 未配置 | 是 | 显示“配置不完整” |
| 配置不完整 | 是 | 正常 |
| 已配置未验证 | 是 | 正常 |
| 验证成功 | 尝试 | 被 C2-QA-001 阻断 |
| 验证失败 | 尝试 | 被 C2-QA-001 阻断 |
| 鉴权失败 | 尝试 | 被 C2-QA-001 阻断 |
| 模型不存在 | 尝试 | 被 C2-QA-001 阻断 |
| 环境变量覆盖 | 是 | 正常显示 warning |
| SecretStore 已配置 | 是 | 来源显示 `secret_store`，未回显 Key |
| 删除 Secret 后回退环境变量 | 是 | 操作通过，来源回退 `env` |

### Obsidian 状态

已构造并截图：未启用、未配置、路径不存在、路径不可写/不可访问、有效目录但无 `.obsidian`、已识别 Obsidian Vault、待初始化、已初始化、需要修复、manifest 冲突、禁用但保留路径。状态标签均可到达。

### 操作

| 操作 | 结果 |
|---|---|
| AI 保存 | 通过 |
| AI 测试 | **失败：C2-QA-001** |
| Key 替换 | 通过 |
| Key 删除及环境变量回退 | 通过 |
| Vault 路径保存 | 通过 |
| validate | 通过 |
| preview | 通过（API 200） |
| initialize | 通过 |
| repair | 通过，缺失目录被补齐 |
| test write | 通过，临时文件已清理 |
| disable | 通过，Vault 文件保留 |
| clear path | 通过，Vault 文件保留 |
| CSRF 错误 | 通过，返回 403 |
| 页面刷新 | 通过 |
| 浏览器返回 | 通过 |
| 重复提交 | 通过，两次均 200，状态一致 |
| 侧栏打开/关闭 | 通过，移动端打开与关闭均正常 |

## 4. 设计一致性与优化建议

按用户目标排序，而不是按组件数量排序：

1. **先恢复产品上下文**：设置页复用主 Shell。用户始终知道自己在哪，也能一步返回核心任务。
2. **统一状态语言**：复用现有 `--success/--warning/--danger/--info` token，badge 和 alert 只表达状态，不再使用另一套 Bootstrap 色。
3. **让移动端信息可读**：属性表在小屏改为上下布局；长路径允许整段换行并可选择复制，而不是逐字挤压。
4. **统一操作层级**：主操作使用墨绿，次操作使用中性 Surface，危险操作只在危险区使用红色；移动端按钮堆叠，桌面端保持自然宽度。
5. **压缩首屏认知成本**：页面标题下增加一句目标说明；状态卡优先显示“当前能否使用”和下一步，来源与高级参数渐进展开。
6. **修正摘要可信度**：概览、详情、关于页必须使用同一状态语义，尤其是 Key 配置状态和 AI badge。
7. **后续增强而非本轮扩张**：为路径增加复制按钮、为验证失败增加下一步动作，可在 P0 修复后单独设计；本轮不新增后端功能。

## 5. 截图证据

- 完整尺寸矩阵：`output/playwright/c2-frontend-qa/run-20260717-093039/screenshots/`
- 完整矩阵结果：`output/playwright/c2-frontend-qa/run-20260717-093039/results.json`
- 最终操作链结果：`output/playwright/c2-frontend-qa/run-20260717-093823/results.json`
- 重点截图：
  - `matrix__settings__1920x1080.png`
  - `matrix__settings__390x844.png`
  - `matrix__settings-ai__390x844.png`
  - `matrix__settings-system__390x844.png`
  - `obsidian__long-path__390x844.png`
  - `settings__synthetic-long-error__390x844.png`

## 6. 本轮允许修改文件

最小前端修复允许：

- `src/signalvault/web/templates/base.html`：提供设置模板可复用的 head/content block。
- `src/signalvault/web/templates/settings/base.html`
- `src/signalvault/web/templates/settings/overview.html`
- `src/signalvault/web/templates/settings/ai.html`
- `src/signalvault/web/templates/settings/obsidian.html`
- `src/signalvault/web/templates/settings/system.html`
- `src/signalvault/web/templates/settings/about.html`
- `src/signalvault/web/static/style.css`
- `src/signalvault/web/routes.py`：设置模板 loader 与 HTML 403 展示 helper；不改任何 CSRF 校验语义。
- `src/signalvault/web/templates/settings/csrf_error.html`：统一、安全的 HTML 403 页面。
- `tests/test_c2a_ai_settings.py`、`tests/test_c2b_obsidian_settings.py`、`tests/test_c2c_settings_center.py`、`tests/test_web_pages.py`、`tests/test_ui_smoke.py`：仅补前端 DOM/CSS/导航回归测试。
- `docs/C2_FRONTEND_QA_REPORT.md`、`CHANGELOG.md`：记录验证事实与修复结果。

本轮禁止修改：

- `src/signalvault/settings/service.py`（ConfigService）
- `src/signalvault/settings/secret_store.py`
- `src/signalvault/settings/llm_validator.py`
- Provider 工厂及 `src/signalvault/llm/`
- `src/signalvault/services/obsidian_settings_service.py`
- Vault 初始化、repair、manifest 逻辑
- `pyproject.toml` 与 AI 异步调用逻辑（C2-QA-001 留作独立后端修复）

## 7. 预计影响

- 最小前端修复预计不改变任何后端数据契约、配置优先级、SecretStore、Provider 创建或 Vault 文件操作。
- 唯一可能触及 Python 的改动是设置模板 loader 的展示层路径解析；必须由现有页面测试和 UI smoke 验证。
- C2-QA-001 不属于前端问题，本轮不会通过重构或绕过后端逻辑修复。

## 8. 最小前端修复结果

### 已完成

- 设置中心复用主应用 Shell、侧栏、移动顶栏、footer 与 `app.js`。
- 设置二级导航、标题说明、卡片、表单、按钮、badge、alert 全部改用既有 SignalVault design token。
- 390/430px 属性表改为 label/value 纵向行；长路径与长信息可读换行。
- 概览页默认 Key 状态修正为“未配置”。
- 关于页 AI badge 映射到稳定 CSS 状态类。
- 主侧栏新增栏目名改为“配置中心”，栏目内页面名保留“系统与集成”，消除同名重复。
- HTML 设置表单 403 复用主应用 Shell；JSON API 403 保持结构化 JSON。
- 移动抽屉隐藏重复品牌并从顶栏下方开始，避免遮挡。
- 未修改 ConfigService、SecretStore、Provider 工厂、Validator、Vault 初始化/repair/manifest 逻辑。

### 修复后浏览器证据

- 完整 5 页面 × 6 尺寸矩阵：`output/playwright/c2-frontend-qa/run-20260717-095012/`
- 最终聚焦操作与侧栏证据：`output/playwright/c2-frontend-qa/run-20260717-102714/`
- CSRF 403 最终 6 页面 × 3 尺寸收口：`output/playwright/c2-frontend-qa/closeout-20260717-110656/`
- 30 个尺寸组合均无页面、按钮或表单横向溢出。
- 所有尺寸可滚动到底；移动侧栏 `opened=True, closed=True`。
- Obsidian validate/preview/save/initialize/repair/test-write/disable/clear-path 全部通过。
- AI 保存、Key 替换、Key 删除回退 env、CSRF 403、刷新、返回、重复提交通过。
- 合成 API Key 泄漏 0；浏览器 page error 0。
- AI 真实连接四类结果仍被 C2-QA-001 阻断，未伪报为通过。

### C2-QA-007 最终浏览器验收

- `/settings`、`/settings/ai`、`/settings/obsidian`、`/settings/system`、`/settings/about` 与 CSRF 403 页面，分别在 1440×900、1366×768、390×844 验收，共 18 张截图。
- 15 个正常页面响应均为 200；3 个 CSRF 页面均保持 403。
- 18 个组合的 `documentWidth == clientWidth`，页面级和元素级横向溢出均为 0。
- 错误页包含主 Shell、侧栏和移动菜单；包含刷新重试提示与安全返回入口；不包含 `_csrf_token` 字段。
- 合成 Secret、路径、无效 token、内部堆栈泄漏为 0；浏览器 `pageerror` 为 0。
- 控制台仅有 3 条预期的主导航 403 状态记录，对应三个错误页尺寸，不是 JavaScript 异常。
- JSON 负向请求保持 403、`application/json` 与 `error_type=csrf`。

### 自动化验证

- `python -m pytest --collect-only -q`：2374 tests collected。
- C2 + `test_web_pages.py`：304 passed，1 skipped。
- `test_c2c_settings_center.py`：68 passed。
- UI smoke：8 passed（新增真实移动端 CSRF 403 溢出检查）。
- `ruff check src tests`：clean。
- `git diff --check`：clean。
- 本轮最终全量非浏览器单次运行：2364 passed，1 skipped，1 setup error。错误为 `test_sync_job_page_loads` 初始化 SQLite 时遇到 `table episodes already exists`；该用例随后隔离复跑 1 passed，且包含它的 `test_web_pages.py` 已在 C2 专项中通过。此前全量运行另出现过 ScannerCache `scanned_at` 时间戳波动并在隔离复跑通过。两类错误均与本轮模板/CSS/HTML 403 改动无代码交集，按授权未修改后端测试语义。

### 仍然开放

1. **C2-QA-001 / P0**：真实 Provider 测试连接依赖/事件循环边界错误。
2. **测试可靠性**：ScannerCache 时间戳断言和 `test_web_pages.py` 全量运行中的 SQLite 重复建表均表现为仅组合运行波动、隔离通过；按授权不修改 ScannerCache、数据库生命周期或其测试语义。
