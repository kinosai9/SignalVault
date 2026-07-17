# C3 首次使用向导验收报告

日期：2026-07-17（更新于同日）
分支：`main`
范围：C2 前端收口回顾、C3 首次使用向导、响应式与安全验收、5 项复核收口、旧 `/setup/vault` 迁移

## 结论

C3 首次使用向导已实现，5 项复核收口 + 旧 `/setup/vault` 6 阶段迁移全部完成。
C3 定向测试、C2 设置中心回归、UI smoke、Ruff 与 diff 检查均通过。

仓库级非浏览器全量组合运行仍存在既有并发稳定性限制，C3 未引入新回归。

### 复核与迁移总结

| 类别 | 内容 | 状态 |
|---|---|---|
| P0 修复 | `/dashboard` 加 onboarding 守卫，阻止向导旁路 | ✅ |
| P1 加固 | ConfigService `_normalise_toml` 递归展平，防止手动编辑丢数据 | ✅ |
| 审计确认 | Wizard route 只编排 services，无违规 | ✅ |
| 独立遗留 | 后台线程测试竞态，C3 未触及 | 📋 |
| 旧路由迁移 | 6 阶段全部完成，旧 `/setup/vault` → 301 → `/setup/obsidian` | ✅ |
| 增强 | `/api/browse-folder` 文件夹选择器移植到 C3 Obsidian 页面 | ✅ |

## C2 QA 问题与修复回顾

| 编号 | 严重度 | 结果 |
|---|---:|---|
| C2-QA-001 真实 Provider 异步/同步边界 | P0 | 已由后端改为 async/await，移除嵌套事件循环绕过 |
| C2-QA-002 设置页脱离主 Shell | P1 | 已统一主侧栏、移动抽屉与应用上下文 |
| C2-QA-003 新页面与原设计系统不协调 | P1 | 已统一宽度、标题、卡片、表单、按钮、badge、提示和二级导航 |
| C2-QA-004 移动端路径与属性可读性 | P1 | 已增加断行、堆叠与横向溢出保护 |
| C2-QA-005 概览 Key 状态误报 | P2 | 已区分默认值、环境变量与 SecretStore 来源 |
| C2-QA-006 About badge class 错误 | P2 | 已改为稳定语义 class |
| C2-QA-007 CSRF 裸 403 | P2 | HTML 使用统一友好错误页；JSON API 保持结构化 JSON |

详细证据见 `docs/C2_FRONTEND_QA_REPORT.md`。

## 用户流程与页面结构

1. `/`：当 onboarding 未完成时进入 `/setup/welcome`；完成或全局跳过后进入 `/dashboard`。
2. `/setup/welcome`：解释产品用途、本地 SQLite、用户自配 AI、Obsidian 可选和非投资建议边界。
3. `/setup/ai`：选择 Mock 或 OpenAI Compatible；真实连接只在点击“保存并测试”后发生，也可保存继续或稍后配置。
4. `/setup/obsidian`：说明 SQLite 是主数据源；支持路径验证、初始化预览、初始化或稍后配置。
5. `/setup/complete`：只展示安全摘要，不展示 API Key 或 Vault 路径；提交完成后进入变化雷达。
6. `/settings`：可重新打开向导；不会清空配置或自动发起真实 AI 请求。

向导使用聚焦布局，不显示完整主侧栏；四步进度始终可见。桌面真实 AI 表单在 1366×768 使用双列压缩，主操作按钮留在首屏；移动端恢复单列并纵向堆叠按钮。

## 状态模型

状态由 `onboarding_service` 独立维护：

| Key | 默认值 | 语义 |
|---|---:|---|
| `_internal.onboarding.version` | `0` | 已完成的向导结构版本 |
| `_internal.onboarding.completed` | `false` | 用户已完成或明确全局跳过 |
| `_internal.onboarding.completed_at` | `""` | UTC 完成时间 |
| `_internal.onboarding.skipped_ai` | `false` | 本次明确跳过 AI |
| `_internal.onboarding.skipped_obsidian` | `false` | 本次明确跳过 Obsidian |

AI Key 失效、模型失效或 Vault 路径失效不会把 `completed` 改回 false。测试覆盖完成后健康变化不重新触发向导，以及 ConfigService reload 后状态仍存在。

为支持三段式 schema key，ConfigService 的 TOML writer 仅增加了“段内键名含点时使用引号”的序列化兼容；配置优先级、读取层次、SecretStore 和业务语义均未改变。

## Service 复用证明

| 向导动作 | 调用的既有 service |
|---|---|
| AI 保存 | `update_ai_settings()` |
| Key 保存/替换 | `replace_llm_secret()` |
| AI 保存并测试 | async `test_llm_connection()` |
| AI 当前状态 | `get_ai_settings_view()` |
| Vault 当前状态 | `get_obsidian_settings_view()` |
| 路径验证 | `validate_obsidian_path()` |
| 初始化预览 | `preview_vault_initialization()` |
| Vault 初始化 | `initialize_obsidian_vault()` |
| Vault 路径保存 | `update_obsidian_settings()` |

Wizard route 不直接写 `config.toml`、SecretStore、Vault 目录或 manifest，不直接调用 LLM HTTP，也不自行计算 AI/Obsidian 健康状态。

## CSRF、Origin 与泄漏检查

- 8 个 C3 POST 路由均验证现有 Origin/Referer 和 double-submit CSRF token。
- 无 token、无效 token 和非本地 Origin 均返回 HTTP 403 聚焦错误页。
- 错误页不包含 CSRF 字段/token、API Key、Vault 路径、请求体或内部堆栈。
- API Key input 永远 `value=""`；验证失败只保留 Provider、Base URL、Model 等普通字段。
- 完成摘要只显示“已保存 Vault 路径”，不显示路径内容。
- 未改 CSRF 算法、HMAC、cookie 或 Origin 规则。

## 修改文件

### C3 初始实现

- `src/signalvault/services/onboarding_service.py`
- `src/signalvault/settings/schema.py`
- `src/signalvault/settings/service.py`
- `src/signalvault/services/ai_settings_service.py`（仅修正已有错误分支变量名）
- `src/signalvault/web/routes.py`
- `src/signalvault/web/static/style.css`
- `src/signalvault/web/templates/setup/base.html`
- `src/signalvault/web/templates/setup/welcome.html`
- `src/signalvault/web/templates/setup/ai.html`
- `src/signalvault/web/templates/setup/obsidian.html`
- `src/signalvault/web/templates/setup/complete.html`
- `src/signalvault/web/templates/setup/csrf_error.html`
- `src/signalvault/web/templates/dashboard.html`
- `src/signalvault/web/templates/settings/overview.html`

### 2026-07-17 复核修复与迁移

- `src/signalvault/web/routes.py` — `page_dashboard()` 加 onboarding 守卫；37 处守卫重定向 → `_redirect_vault_required()`；新增 `/setup/obsidian/repair` + `/api/browse-folder`；旧路由改为 301
- `src/signalvault/settings/service.py` — `_normalise_toml` 递归展平；config.toml 头部加引号警告
- `src/signalvault/services/sync_service.py` — 错误消息 URL 更新
- `src/signalvault/web/static/style.css` — `.input-with-button` 并排布局
- `src/signalvault/web/templates/setup/obsidian.html` — 浏览文件夹按钮 + JS
- `src/signalvault/web/templates/setup_vault.html` — **已删除**（死代码）

### 测试与文档

- `tests/test_c3_onboarding.py`
- `tests/test_ui_smoke.py`
- `tests/test_web_pages.py` — dashboard 测试加 `complete_onboarding()`；`TestVaultSetup` 重写为 301 验证
- `docs/C3_FIRST_RUN_ONBOARDING_PLAN.md`
- `docs/C3_ACCEPTANCE_REPORT.md`
- `docs/C3_VAULT_SETUP_MIGRATION_PLAN.md` — **新增**
- `docs/CONFIGURATION_AUDIT.md` — 5.1 节重写，7 处 URL 更新
- `docs/USER_GUIDE.md` — URL 更新
- `docs/FRONTEND_EXPERIENCE_EXECUTION_PLAN.md` — 路由清单更新
- `docs/CONFIGURATION_ARCHITECTURE_PLAN.md` — 引用更新
- `README.md` — 路由表更新
- `CHANGELOG.md`

## 新增测试

- C3 定向：33 passed。
- 覆盖：新用户自动进入、完成/全局跳过后不再进入、设置中心重开、Welcome、AI Mock/真实保存/保存并测试/失败继续、Key 不泄漏、Obsidian 跳过/validate/initialize/manifest conflict、完成摘要、状态重载、健康变化不重开、全部 POST CSRF、非本地 Origin、C2 页面回归。
- UI smoke 从 8 增至 11：新增 1366×768 欢迎页主按钮可见、390×844 AI 按钮堆叠/无 Key/无溢出、390×844 完成摘要/无溢出。
- 未新增 skip；唯一 skip 是既有 Windows 只读目录测试。

## 全量门禁

### 初始 C3 提交时

| 门禁 | 结果 |
|---|---|
| `ruff check src/ tests/` | passed |
| `pytest --collect-only -q` | 2416 collected |
| C2 + C3 定向 | 206 passed, 1 existing Windows skip |
| C3 + ConfigService | 72 passed |
| `pytest tests/test_ui_smoke.py -q` | 11 passed |
| `git diff --check` | passed |

### 复核修复后（2026-07-17）

| 门禁 | 结果 |
|---|---|
| `ruff check` (routes.py, service.py, sync_service.py, test_web_pages.py) | passed |
| C3 + web pages + ConfigService 组合 | 195 passed |
| `git diff --check` | passed |

## 截图与尺寸

目录：`output/playwright/c3-onboarding/`

| 页面/状态 | 尺寸 | 文件 |
|---|---:|---|
| 欢迎页 | 1440×900 | `welcome-1440x900.png` |
| 欢迎页 | 390×844 | `welcome-390x844.png` |
| AI 默认 | 1440×900 | `ai-default-1440x900.png` |
| AI 错误（普通字段保留、Key 为空） | 1366×768 | `ai-error-1366x768.png` |
| AI Mock 成功 | 390×844 | `ai-success-390x844.png` |
| Obsidian 未配置 | 1366×768 | `obsidian-unconfigured-1366x768.png` |
| Obsidian 已初始化 | 390×844 | `obsidian-initialized-390x844.png` |
| 完成页 | 1440×900 | `complete-1440x900.png` |
| 完成页 | 390×844 | `complete-390x844.png` |

所有截图由隔离的 `SIGNALVAULT_HOME`、Mock AI 和临时 Vault 生成；页面宽度检查均为 0 px 横向溢出。没有使用或写入真实 Key、真实 Vault 或用户配置。

## 已知限制（更新于 2026-07-17）

1. 仓库级组合运行仍有既有后台线程固定 sleep 时序抖动；隔离重跑通过，但全量一次性稳定性未解决。
2. 既有 SQLite engine/fixture 组合运行偶发重复建表；C2 报告已有同类记录，本轮未修改数据库初始化语义。
3. C3 不包含真实 Provider 自动化网络请求；这是产品安全要求。真实 Provider 仍由用户点击后手工验证。

## 2026-07-17 复核结论（原"建议交回 Claude Code 复核"）

5 项建议复核已全部处理，涉及 2 处代码修复 + 1 份 6 阶段迁移计划（已全部执行完成）：

| # | 问题 | 结论 | 行动 |
|---|---|---|---|
| 1 | Wizard route 编排审计 | ✅ 合规 | 12 个路由均只编排既有 services，无违规 |
| 2 | ConfigService dotted key 兼容 | ✅ 已加固 | `_normalise_toml` 递归展平；TOML 头部加引号警告 |
| 3 | 根入口 onboarding 守卫 | ✅ 已修复 | `/dashboard` 加 `should_enter_onboarding()` 守卫 |
| 4 | 后台线程测试竞态 | 📋 独立遗留 | C3 未触及相关代码，独立处理 |
| 5 | 旧 `/setup/vault` 迁移 | ✅ 已完成 | `docs/C3_VAULT_SETUP_MIGRATION_PLAN.md`，6/6 阶段完成 |

## 旧 `/setup/vault` 迁移完成清单

6 阶段全部于 2026-07-17 执行完毕：

| 阶段 | 内容 | 结果 |
|---|---|---|
| A | 37 处守卫重定向统一 → `/setup/obsidian` | ✅ |
| B | 新增 `POST /setup/obsidian/repair` | ✅ |
| C | 旧路由 301 重定向 + dashboard 按钮 + sync_service 消息 | ✅ |
| D | 文件夹选择器移植到 C3 Obsidian 页面 | ✅ |
| E | 测试迁移：301 验证 + C3 深度覆盖 | ✅ |
| F | 5 份文档更新 + 死模板删除 | ✅ |

用户现在只有一条 Obsidian 配置路径：C3 向导 `/setup/obsidian`。旧 `/setup/vault` 返回 301 永久重定向。
详细记录见 `docs/C3_VAULT_SETUP_MIGRATION_PLAN.md`。
