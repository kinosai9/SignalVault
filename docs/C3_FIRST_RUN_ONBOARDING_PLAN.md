# C3 首次使用向导实施规则

## 目标

让无 IT 背景的新用户在不编辑 `.env` 的前提下完成：了解产品、配置或跳过 AI、配置或跳过 Obsidian、确认摘要、进入变化雷达。

## 用户流程

1. `/` 根据独立 onboarding 元数据决定进入 `/setup/welcome` 或 `/dashboard`。
2. Welcome 说明本地数据、用户自带 AI 服务、Obsidian 可选和非投资建议边界。
3. AI 步骤只调用 `ai_settings_service`；真实连接只在用户点击“保存并测试”后发生。
4. Obsidian 步骤只调用 `obsidian_settings_service`；验证和预览不写文件，初始化只由既有初始化 service 执行。
5. 完成页从既有 service 读取当前状态；用户确认后写 onboarding 完成元数据并进入 Dashboard。
6. 用户可从设置中心重新打开向导。系统健康变化不得重置完成状态。

## 状态模型

独立持久化以下非敏感元数据：

- `_internal.onboarding.version`
- `_internal.onboarding.completed`
- `_internal.onboarding.completed_at`
- `_internal.onboarding.skipped_ai`
- `_internal.onboarding.skipped_obsidian`

`completed` 只表示用户已走完或明确跳过首次设置，不表示 AI、Obsidian、数据库或系统健康。

## 分层边界

- `services/onboarding_service.py`：唯一 onboarding 状态读写入口，内部通过 `ConfigService` 持久化。
- Wizard route：只负责编排、CSRF/Origin、重定向和模板上下文；不得直接写配置文件、Secret、Vault 或 manifest。
- AI 写入与连接：复用 `update_ai_settings`、`replace_llm_secret`、`test_llm_connection`。
- Obsidian 读取、验证、预览、初始化：复用 `get_obsidian_settings_view`、`validate_obsidian_path`、`preview_vault_initialization`、`initialize_obsidian_vault`、`update_obsidian_settings`。
- 模板只接收安全 view model；API Key 永不进入返回上下文。

## 路由与安全

- GET `/setup/welcome`
- POST `/setup/welcome`
- GET/POST `/setup/ai`
- POST `/setup/ai/test`
- GET/POST `/setup/obsidian`
- POST `/setup/obsidian/validate`
- POST `/setup/obsidian/initialize`
- GET/POST `/setup/complete`
- POST `/setup/skip`

所有 POST 使用现有 double-submit cookie、HMAC token 和 Origin/Referer 校验，不改变算法。

## 兼容性

- 旧 `/setup/vault` 路由暂时保留，供历史入口兼容；C3 不调用它。
- Dashboard 无 Obsidian 时必须可进入，并明确 SQLite 是主数据源。
- C2 设置页面继续复用主应用 Shell；C3 使用更聚焦的独立 Shell，但共享颜色、表单、按钮和状态语义。

## 验收门禁

- 新用户、完成、全局跳过、分步跳过、重新打开、持久化、健康变化不重触发。
- AI Mock、真实配置、保存并测试、失败继续、Key 不泄漏。
- Obsidian 验证、预览、初始化、manifest 冲突、跳过。
- 所有 POST CSRF 与非本地 Origin 拒绝。
- 1440×900、1366×768、390×844 浏览器验收与指定状态截图。
- 全量 pytest、UI smoke、Ruff、`git diff --check`。
