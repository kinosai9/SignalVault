# C2 Acceptance Report — Configuration & Settings Center

> 日期：2026-07-16  
> 版本：SignalVault 0.1.0 RC  
> 门禁基线：2359 collected / 2351 passed / 1 skipped / 7 UI smoke / Ruff clean

## 1. 交付范围

| 子系统 | 说明 | 状态 |
|--------|------|------|
| AppPaths | 跨平台路径解析（Windows/macOS/Linux） | C1-A |
| ConfigService | 5 层优先级链 + source tracking + config.toml 持久化 | C1-B |
| SecretStore | 密钥独立文件存储（0600），不进 config.toml/日志/诊断 | C1-B |
| LLM Runtime Factory | 单一 `create_llm_provider()` 入口 | C1-C |
| SetupStatus | 复合系统健康模型（mock-aware llm_ready） | C1-C |
| LLM Validator | 10 类连接错误分类 | C1-C |
| Obsidian Validator | Vault 路径验证（path_valid / has_obsidian_metadata / is_initialized） | C1-C |
| Vault Manifest | 原子 JSON 写入、幂等 init、conflict 保护、repair | C1-C |
| AI 设置页面 | Provider/Model/Base URL/API Key 配置、连接测试、验证持久化 | C2-A |
| CSRF/Origin | double-submit cookie HMAC、Origin URL host 比较 | C2-A |
| Obsidian 设置页面 | 8 状态模型、路径验证、初始化预览、init/repair、写入测试 | C2-B |
| Secret Revision | Key 替换/删除后旧验证自动失效 | C2-B |
| 设置中心概览 | AI/Obsidian/系统/诊断四卡片 | C2-C |
| 数据与系统 | 只读应用/路径/数据库/服务信息 | C2-C |
| 诊断与关于 | 版本/隐私/免责/许可、诊断入口到 /tasks | C2-C |
| 导航 | 主导航"系统与集成"入口 + 设置二级导航 | C2-C |
| 版本来源 | `importlib.metadata` 从 pyproject.toml 读取 | C2-S |

## 2. 测试基线

```bash
$ python -m pytest --collect-only -q
2359 tests collected

$ python -m pytest tests/ --ignore=tests/test_ui_smoke.py -q
2351 passed, 1 skipped

$ python -m pytest tests/test_ui_smoke.py -q
7 passed

$ python -m ruff check src/ tests/
All checks passed!
```

跳过的测试：`test_write_test_readonly_dir` — Windows 平台限制（`pytest.skip`），macOS CI 会执行。

## 3. 新增测试明细

| 文件 | 测试数 | 覆盖范围 |
|------|--------|----------|
| `test_c2a_ai_settings.py` | 24 | AI 视图、保存、密钥操作、验证持久化、secret revision、Origin 边界、CSRF、Web 页面 |
| `test_c2b_obsidian_settings.py` | 74 | Obsidian 视图、更新、验证、预览、初始化、修复、写入测试、禁用清除、页面、API、状态模型、路径安全、clean-room |
| `test_c2c_settings_center.py` | 54 | CSRF 边界、概览页、系统页、About 页、子导航、主导航、版本一致性、表单回归、路径缩略、DB 计数 |

## 4. 关键设计决策

### 密钥永远不进入 config.toml
API Key 只存储于 SecretStore（`secrets` 文件），`config.toml` 不保留任何 Key 值或哈希。页面的 `api_key` input 使用 `type=password` + `autocomplete=off`，value 始终为空字符串。

### Origin 校验使用 URL host 比较
`check_origin()` 从字符串包含改为 `urlparse` → `.hostname` 精确比较。拒绝 `127.0.0.1.attacker.com` 和 `null` Origin。

### 配置变更自动失效旧验证
secret_revision 单调计数器确保替换 Key A 为 Key B 后旧验证状态自动变为 stale。ConfigService 的 get_with_source 支持区分"用户保存的值"和"被更高优先级覆盖的值"。

### Obsidian 是可选集成
未配置/禁用时不影响任何核心功能。SQLite 是主数据源。页面明确声明这一点。

## 5. Clean-Room 验证

端到端流程已在自动化测试中验证（`test_full_clean_room_flow`）：
全新 SIGNALVAULT_HOME → AI Mock → 创建临时 Vault 目录 → 保存路径 → 验证无 .obsidian → 初始化 → Manifest 正确 → 修复幂等 → 禁用保留文件 → 重启状态保持

## 6. 已知限制

- host/port/路径在线修改不支持（rc1 设计决策）
- 无原生目录选择器（C4）
- 无 Keychain（C4）
- 无多 Provider（C4）
- Build commit 在 wheel 部署时为空（C3/C4 构建注入）
- macOS `.app` 打包未开始（C4）

## 7. 向后兼容

- `config_store.py` 自动迁移旧 `user_settings.json` 的 vault_path 到 ConfigService
- `.env` 中的环境变量仍然读取并作为覆盖层（source=env）
- CLI `--vault` 参数通过 runtime override 优先生效
- 现有 config.py 继续工作但新增模块不再直接读取

## 8. 就绪状态

C2 配置体系已封板。所有配置通过 Web Console 完成。普通用户无需编辑 `.env`。具备进入 C3（首次使用向导）的条件。
