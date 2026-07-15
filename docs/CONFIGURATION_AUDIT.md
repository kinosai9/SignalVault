# Configuration Audit

> 审计日期：2026-07-15  
> 范围：SignalVault 0.1.0 全量配置来源、优先级、分类与风险  
> 基准：R0-2 clean install 验证通过后的代码基线

## 1. 审计范围

已检查以下文件与代码路径：

- `pyproject.toml` / `.env.example` / `.gitignore`
- `src/signalvault/config.py` — 全局配置（import-time load_dotenv）
- `src/signalvault/config_store.py` — 用户设置持久化（JSON）
- `src/signalvault/logging_config.py` — 日志路径与级别
- `src/signalvault/cli.py` — 全部 Typer commands & options
- `src/signalvault/web/routes.py` — 全部 Web 路由与表单
- `src/signalvault/llm/openai_compatible_provider.py` — Provider 实现
- `src/signalvault/analysis/pipeline.py` — Provider 选择逻辑
- `src/signalvault/services/analyze_service.py` — 服务层 LLM 调用
- `src/signalvault/exporters/obsidian.py` — Vault 路径与子目录结构
- `src/signalvault/workspace/setup.py` — Vault 初始化
- `src/signalvault/diagnostics/bundle.py` — 诊断包配置收集
- `src/signalvault/diagnostics/errors.py` — 错误分类与建议
- `src/signalvault/diagnostics/summary.py` — 系统健康摘要
- `src/signalvault/sources/zsxq_cli.py` — 知识星球 CLI 发现
- `src/signalvault/db/session.py` — DB 路径与引擎初始化
- `tests/conftest.py` — 测试环境变量隔离
- `.github/workflows/test.yml` — CI 配置
- `README.md` — 用户文档中的配置说明
- `.env.example` — 示例环境变量

搜索关键词：`os.getenv`, `os.environ`, `load_dotenv`, `.env`, `LLM_`, `OPENAI_`, `OBSIDIAN_`, `VAULT`, `DATA_DIR`, `LOG_DIR`, `DB_PATH`, `HOST`, `PORT`, `CACHE`, `ZSXQ_CLI_PATH`

## 2. 配置项全矩阵

### 2.1 LLM / AI Provider 配置

| # | 配置项 | 当前名称 | 当前来源 | 默认值 | 读取位置 | 写入位置 | CLI 覆盖 | Web 配置 | 敏感 | 用户级别 | RC 建议来源 |
|---|--------|---------|---------|--------|---------|---------|---------|---------|------|---------|------------|
| 1 | LLM Provider 类型 | `LLM_PROVIDER` | env / .env | `"mock"` | `config.py:18` | 无 | `--mock` flag | 无 | 否 | B-必填 | ConfigService → env 兜底 |
| 2 | LLM API Key | `LLM_API_KEY` | env / .env | `""` | `config.py:21` | 无 | 无 | 无 | **是** | B-必填 | SecretStore |
| 3 | LLM Model | `LLM_MODEL` | env / .env | `"mock-v1"` | `config.py:19` | 无 | 无 | 无 | 否 | B-必填 | ConfigService |
| 4 | LLM Base URL | `LLM_BASE_URL` | env / .env | `""` | `config.py:20` | 无 | 无 | 无 | 否 | C-可选 | ConfigService |
| 5 | OpenAI 默认 model | — | 硬编码 | `"gpt-4o-mini"` | `openai_compatible_provider.py:41` | 无 | 无 | 无 | 否 | C-可选 | `LLM_MODEL` 统一 |
| 6 | LLM timeout | — | 硬编码 | `120.0` | `openai_compatible_provider.py:43` | 无 | 无 | 无 | 否 | D-高级 | ConfigService |
| 7 | LLM max_retries | — | 硬编码 | `2` | `openai_compatible_provider.py:42` | 无 | 无 | 无 | 否 | D-高级 | ConfigService |
| 8 | LLM temperature | — | 硬编码 | `0.1` | `openai_compatible_provider.py:63` | 无 | 无 | 无 | 否 | D-高级 | ConfigService |

### 2.2 Obsidian Vault 配置

| # | 配置项 | 当前名称 | 当前来源 | 默认值 | 读取位置 | 写入位置 | CLI 覆盖 | Web 配置 | 敏感 | 用户级别 | RC 建议来源 |
|---|--------|---------|---------|--------|---------|---------|---------|---------|------|---------|------------|
| 9 | Vault 路径 | `OBSIDIAN_VAULT_PATH` | user_settings.json → env / .env | `""` | `config_store.py:59-62` | `/setup/vault` POST → `config_store.save_user_vault_path()` | `--vault` (所有 obsidian 子命令) | `/setup/vault` 表单 | 否 | C-可选 | ConfigService |
| 10 | Vault 导出开关 | `OBSIDIAN_EXPORT_ENABLED` | env / .env | `"false"` | `config.py:27` | 无 | 无 | 无 | 否 | C-可选 | ConfigService |
| 11 | Vault 子目录名 | — | 硬编码 | `"SignalVault"` (未使用) / 直接写 Vault 根 | 见下方说明 | 无 | 无 | 无 | 否 | D-高级 | ConfigService |

**Vault 子目录说明**：当前 exporters 和 workspace 直接向 Vault 根目录写入 `01_Reports/`、`05_Channels/`、`99_System/`、`00_Inbox/` 等子目录，没有在 Vault 根下创建 SignalVault 专属子目录。这与 Obsidian 的惯例一致（一个 Vault 一个根），但用户将无法区分 SignalVault 文件和自有文件。

### 2.3 系统路径配置

| # | 配置项 | 当前名称 | 当前来源 | 默认值 | 读取位置 | 写入位置 | CLI 覆盖 | Web 配置 | 敏感 | 用户级别 | RC 建议来源 |
|---|--------|---------|---------|--------|---------|---------|---------|---------|------|---------|------------|
| 12 | 应用根目录 | `BASE_DIR` | 自动计算 | `Path(config.py).parent.parent.parent` | `config.py:8` | 无 | 无 | 无 | 否 | A-系统 | AppPaths.app_root |
| 13 | 数据目录 | `DATA_DIR` | env / .env | `<BASE_DIR>/data` | `config.py:10` | 无 | 无 | 无 | 否 | A-系统 | AppPaths.data_dir |
| 14 | 日志目录 | `LOG_DIR` | env / .env | `<BASE_DIR>/logs` | `config.py:11` | 无 | 无 | 无 | 否 | A-系统 | AppPaths.log_dir |
| 15 | SQLite 路径 | `DB_PATH` | env / .env | `<DATA_DIR>/signalvault.db` | `config.py:12` → `db/session.py:13` | `init_db(db_path)` | `--db-path` (部分 CLI 命令) | 无 | 否 | A-系统 | AppPaths.db_path |
| 16 | 字幕缓存 | `SUBTITLE_DIR` | 派生 | `<DATA_DIR>/subtitles` | `config.py:14` | 无 | 无 | 无 | 否 | A-系统 | AppPaths |
| 17 | 报告目录 | `REPORT_DIR` | 派生 | `<DATA_DIR>/reports` | `config.py:15` | 无 | 无 | 无 | 否 | A-系统 | AppPaths |
| 18 | Transcript 缓存 | `TRANSCRIPT_CACHE_DIR` | 派生 | `<DATA_DIR>/transcripts/youtube` | `config.py:16` | 无 | 无 | 无 | 否 | A-系统 | AppPaths |
| 19 | 用户设置文件 | — | 硬编码 | `<cwd>/data/user_settings.json` | `config_store.py:23` | `config_store.py:_save()` | 无 (测试用 `_override_settings_path`) | 通过 `/setup/vault` | 否 | A-系统 | AppPaths.config_dir |
| 20 | 诊断包临时目录 | — | 按需创建 | `tempfile.mkdtemp(prefix="sv_diag_")` | `routes.py:1636` | 无 | 无 | 无 | 否 | A-系统 | AppPaths.temp_dir |
| 21 | 备份目录 | — | 仓库 `.gitignore` 引用 | `<project_root>/backup/` | `.gitignore:30` | 无 | 无 | 无 | 否 | A-系统 | AppPaths.backup_dir |

### 2.4 Web 服务配置

| # | 配置项 | 当前名称 | 当前来源 | 默认值 | 读取位置 | 写入位置 | CLI 覆盖 | Web 配置 | 敏感 | 用户级别 | RC 建议来源 |
|---|--------|---------|---------|--------|---------|---------|---------|---------|------|---------|------------|
| 22 | 绑定地址 | `--host` | CLI 参数 | `"127.0.0.1"` | `cli.py:4178` | 无 | `serve --host` | 无 | 否 | D-高级 | ConfigService |
| 23 | 监听端口 | `--port` | CLI 参数 | `8000` | `cli.py:4179` | 无 | `serve --port` | 无 | 否 | D-高级 | ConfigService |
| 24 | 热重载 | `--reload` | CLI 参数 | `False` | `cli.py:4180` | 无 | `serve --reload` | 无 | 否 | D-高级 | ConfigService |

### 2.5 日志配置

| # | 配置项 | 当前名称 | 当前来源 | 默认值 | 读取位置 | 写入位置 | CLI 覆盖 | Web 配置 | 敏感 | 用户级别 | RC 建议来源 |
|---|--------|---------|---------|--------|---------|---------|---------|---------|------|---------|------------|
| 25 | 日志级别 | `LOG_LEVEL` | env / .env | `"INFO"` | `config.py:23` → `logging_config.py:8` | 无 | `-v` flag (仅 verbose) | 无 | 否 | D-高级 | ConfigService |
| 26 | 日志文件 | — | 硬编码 | `<LOG_DIR>/signalvault.log` | `logging_config.py:29` | RotatingFileHandler | 无 | 无 | 否 | A-系统 | AppPaths |
| 27 | 日志大小上限 | — | 硬编码 | `5_000_000` (5 MB) | `logging_config.py:30` | 无 | 无 | 无 | 否 | D-高级 | ConfigService |
| 28 | 日志备份数 | — | 硬编码 | `3` | `logging_config.py:31` | 无 | 无 | 无 | 否 | D-高级 | ConfigService |

### 2.6 知识星球 (ZSXQ) 配置

| # | 配置项 | 当前名称 | 当前来源 | 默认值 | 读取位置 | 写入位置 | CLI 覆盖 | Web 配置 | 敏感 | 用户级别 | RC 建议来源 |
|---|--------|---------|---------|--------|---------|---------|---------|---------|------|---------|------------|
| 29 | ZSXQ CLI 路径 | `ZSXQ_CLI_PATH` | env（未在 .env.example） | 自动搜索 PATH | `zsxq_cli.py:71` | 无 | 无 | 无 | 否 | D-高级 | 自动发现 + ConfigService 覆盖 |
| 30 | ZSXQ CLI 候选名 | — | 硬编码 | `("zsxq", "zsxq-cli")` | `zsxq_cli.py:20` | 无 | 无 | 无 | 否 | A-系统 | 常量 |

### 2.7 分析参数

| # | 配置项 | 当前名称 | 当前来源 | 默认值 | 读取位置 | 写入位置 | CLI 覆盖 | Web 配置 | 敏感 | 用户级别 | RC 建议来源 |
|---|--------|---------|---------|--------|---------|---------|---------|---------|------|---------|------------|
| 31 | 分析深度 | `--depth` | CLI 参数 | `"standard"` | `cli.py:63` | 无 | `--depth` | 无 | 否 | D-高级 | ConfigService |
| 32 | 关注领域 | `--focus` | CLI 参数 | 无默认 | `cli.py:62` | 无 | `--focus` | 部分 Web 表单 | 否 | C-可选 | ConfigService |
| 33 | Chunk size | `--chunk-size` | CLI 参数 | `30000` | `cli.py:69` | 无 | `--chunk-size` | 无 | 否 | D-高级 | ConfigService |
| 34 | Chunk overlap | `--chunk-overlap` | CLI 参数 | `2000` | `cli.py:70` | 无 | `--chunk-overlap` | 无 | 否 | D-高级 | ConfigService |
| 35 | YouTube 语言 | `--youtube-lang` | CLI 参数 | 无默认 | `cli.py:60` | 无 | `--youtube-lang` | 无 | 否 | D-高级 | ConfigService |

### 2.8 CI 配置

| # | 配置项 | 当前名称 | 当前来源 | 默认值 | 敏感 | 用户级别 |
|---|--------|---------|---------|--------|------|---------|
| 36 | Python 版本 | `matrix.python-version` | GitHub Actions | `["3.12"]` | 否 | F-部署 |
| 37 | 测试命令 | — | GitHub Actions | `pytest tests/ -v --tb=short` | 否 | F-部署 |
| 38 | Lint 命令 | — | GitHub Actions | `ruff check src/ tests/` | 否 | F-部署 |
| 39 | Playwright 浏览器 | — | GitHub Actions | `playwright install chromium --with-deps` | 否 | F-部署 |
| 40 | Ruff 版本 | `ruff==0.15.21` | pyproject.toml dev deps | 锁定 | 否 | F-部署 |

### 2.9 废弃或重复配置

| # | 问题 | 详情 |
|---|------|------|
| D1 | `config.py` 与 `config_store.py` 双重 OBSIDIAN_VAULT_PATH | `config.py:26` 从 env 读取；`config_store.py:59-62` 从 user_settings.json → env 回退读取。`_get_vault_path()` (routes.py:30) 只走 config_store；`config.py` 的 `OBSIDIAN_VAULT_PATH` 只在 diagnostics bundle 中使用。**存在两条路径不同步的风险。** |
| D2 | `LLM_PROVIDER` 命名不一致 | `config.py` 存储为 `"openai-compatible"`；`pipeline.py:134` 同时接受 `"openai-compatible"` 和 `"openai_compatible"`（下划线变体）；`patch_generator.py` 使用 `"openai_compatible"`（下划线）。 |
| D3 | Mock 逻辑分散 | `--mock` flag → `--no-mock` flag 在 cli.py 多处重复判断；`analyze_service.py:83` 硬编码 `provider = "mock" if mock else "openai-compatible"`；Web 路由 `routes.py:3141` 同样逻辑。 |
| D4 | `.env.example` 不完整 | 缺少 `OBSIDIAN_VAULT_PATH`、`OBSIDIAN_EXPORT_ENABLED`、`ZSXQ_CLI_PATH`。 |
| D5 | 硬编码 provider model 默认值 | `openai_compatible_provider.py:41` 硬编码 `model="gpt-4o-mini"`，但 `LLM_MODEL` env var 也存在。初始化时并未传递 `LLM_MODEL`（pipeline.py:139-142 未读取 `LLM_MODEL`）。 |
| D6 | `config_store.py` 使用 `os.getcwd()` | `_get_settings_path()` 基于当前工作目录而非 `DATA_DIR`，在不同启动方式下可能指向不同位置。 |

## 3. 配置优先级（当前事实）

```
当前优先级（import-time）:

1. conftest.py 强制 os.environ（仅测试）
2. os.environ 已有值（load_dotenv 不覆盖）
3. .env 文件（load_dotenv 在 config.py:6 import 时执行）
4. 代码硬编码默认值
```

**关键发现：**

- **load_dotenv 在 import 时加载**：`config.py:6` 在模块第一次 import 时执行 `load_dotenv()`。这意味着 `.env` 在 import 时就被读取，后续 `os.environ` 修改不会反映到已读取的模块级变量。
- **config_store.py 优先级例外**：`get_user_vault_path()` 独立维护三层优先级：`user_settings.json` → `os.getenv("OBSIDIAN_VAULT_PATH")` → `""`。**Web 路由使用此函数，CLI 使用 config.py 模块变量，两者可能读到不同值。**
- **测试通过 conftest.py 预先设置 `os.environ`**：在 `import signalvault` 之前设置 `LLM_PROVIDER=mock` 等，利用 `load_dotenv` 不覆盖已有 env var 的特性。
- **修改配置后必须重启**：所有模块级变量在 import 时固化。CLI 每次启动重新 import；Web 服务在 uvicorn 进程生命周期内不变。
- **Provider 一次性实例化**：`_run_pipeline()` 每次调用时创建新的 Provider 实例，不缓存。但 `LLM_API_KEY` 等从模块变量读取。

**建议未来优先级：**

```
1. 显式函数参数 / 测试 fixture 覆盖
2. CLI 参数
3. 用户配置文件（JSON/TOML）
4. 环境变量（含 .env）
5. 系统默认值
```

## 4. LLM 配置专项审计

### 4.1 Provider 类型

| Provider | 内部名称 | 激活条件 | 状态 |
|----------|---------|---------|------|
| Mock | `"mock"` | 默认 / `--mock` flag | 已实现，用于测试 |
| OpenAI Compatible | `"openai-compatible"` (也接受 `"openai_compatible"`) | `LLM_PROVIDER=openai-compatible` + `--no-mock` | 已实现骨架，未充分测试 |

### 4.2 必填项 vs 可选项

**Mock Provider:**
- 必填：无
- 可选：`LLM_MODEL`（不影响行为）

**OpenAI Compatible Provider:**
- 必填：`LLM_API_KEY`（pipeline.py:140 校验非空，否则报 ValueError）
- 必填（但有默认值）：`LLM_BASE_URL`（无默认，但报错时在 openai_compatible_provider 中拼接）
- 可选：`LLM_MODEL`（Provider `__init__` 默认 `"gpt-4o-mini"`，但 pipeline.py 创建时未传递此值，导致实际使用硬编码默认值）

### 4.3 Provider 实例化链路

```
CLI analyze 命令
  → cli.py:92-96 根据 --mock/--no-mock/LLM_PROVIDER 决定 provider 字符串
  → analyze_from_transcript(provider_name="mock" 或 "openai-compatible")
    → pipeline.py:132-146 _run_pipeline()
      → 如果是 "mock": MockLLMProvider()
      → 如果是 "openai-compatible": OpenAICompatibleProvider(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            model=LLM_MODEL,           ← pipeline.py:144 代码确实传了
            max_retries=2,             ← 硬编码
            timeout=120.0,             ← 硬编码
        )
```

**注意**：pipeline.py:139-145 实际上**传递了** `LLM_MODEL`、`max_retries`（硬编码 2）、`timeout`（硬编码 120.0）。所以 `LLM_MODEL` 会被使用，但 `max_retries` 和 `timeout` 没有对应的 env var。

### 4.4 错误分类

当前 `analyze_service.py:141-158` 分类：
- `"api key" / "unauthorized" / "authentication"` → `llm_config` 错误
- `"token" / "too long" / "maximum context"` → `token_limit` 错误
- 其他 → `unknown` 错误

**缺失错误类型**：Base URL 不可达、超时、限流（429）、配额不足、SSL 错误、模型不存在（404）、返回格式无法解析。

### 4.5 Mock 强制路径

| 路径 | 是否强制 Mock | 原因 |
|------|-------------|------|
| 所有测试 | 是 | conftest.py 预设 `LLM_PROVIDER=mock` |
| Web PDF 分析 | 是 | `routes.py:4554` 硬编码 `provider_name="mock"` |
| Web 文件导入分析 | 取决于 `provider_mode` 参数 | `routes.py:3141` 从请求读取 |
| CLI 默认 | 是 | 未指定 `--no-mock` 时使用 mock |
| CLI `--no-mock` | 否（使用真实 LLM） | 需要 `.env` 中有 `LLM_API_KEY` |

### 4.6 建议的测试连接接口

```
POST /api/llm/test-connection
  Body: { provider, api_key, base_url, model }
  → 尝试最小 API 调用（如 list models 或简单 completion）
  → 返回诊断结果：{ ok, error_type, error_message, latency_ms }

错误类型枚举：
  - auth_failed (401)
  - model_not_found (404)
  - base_url_unreachable (connection error)
  - timeout
  - rate_limited (429)
  - quota_exceeded
  - ssl_error
  - protocol_incompatible
  - parse_error
```

## 5. Obsidian 配置专项审计

### 5.1 `/setup/vault` 当前行为

1. **GET** `/setup/vault` — 显示 Vault 配置页面
   - 读取 `config_store.get_user_vault_path()` 获取已保存路径
   - 若路径存在则显示「已配置」状态
   - 若路径不存在则引导用户输入

2. **POST** `/setup/vault` — 保存 Vault 路径
   - 验证路径非空、非相对路径
   - 调用 `initialize_vault()` 创建目录结构和模板文件
   - 调用 `config_store.save_user_vault_path()` 持久化到 `data/user_settings.json`
   - **幂等**：initialize_vault 只创建缺失项，不覆盖已有文件

3. **POST** `/setup/vault/repair` — 修复 Vault
   - 重新调用 `initialize_vault()` 补齐缺失项

### 5.2 Vault 路径读取优先级

```
config_store.get_user_vault_path():
  1. data/user_settings.json → "obsidian_vault_path"
  2. os.environ["OBSIDIAN_VAULT_PATH"]
  3. ""（视为未配置）
```

### 5.3 CLI `--vault` 覆盖

所有 Obsidian 子命令（`obsidian export`, `obsidian lint`, `obsidian sync` 等）均接受 `--vault` 参数。当提供 `--vault` 时，CLI 直接使用该路径；未提供时读取 `OSBIDIAN_VAULT_PATH` 环境变量（cli.py 中直接读 `config.py` 的模块变量，**不走 config_store**）。

**风险**：CLI 读 `config.py:OBSIDIAN_VAULT_PATH`（仅 env），Web 读 `config_store.get_user_vault_path()`（user_settings.json → env），**Web 保存的路径 CLI 看不到。**

### 5.4 Vault 初始化清单

```
REQUIRED_DIRS:
  00_Inbox/LLM_Patches, 01_Reports, 02_Topics, 03_Companies,
  04_People, 05_Channels, 06_Claims, 07_Signals,
  90_Templates, 99_System, attachments

REQUIRED_FILES:
  Home.md, 99_System/Watchlist.yaml, 99_System/Research Brief.md,
  99_System/Watchlist Brief.md, 99_System/Knowledge Map.md,
  99_System/Review Queue.md, 99_System/Report Index.md,
  99_System/Topic Taxonomy.md, 99_System/Getting Started.md
```

- 初始化只创建缺失项，永不覆盖已有文件 ✅
- 没有 manifest 文件记录 Vault 版本或初始化状态
- 不区分 "SignalVault 专属 Vault" 和 "用户现有 Vault"
- 所有文件直接写在 Vault 根目录下的子目录中
- 通过 `<!-- signalvault:BEGIN/END -->` 注释标记托管内容块

### 5.5 后续架构建议

**配置分区**：`系统与集成 → Obsidian`
- 路径选择（目录选择器 / 手动输入）
- 路径校验（是否存在、是否可写、是否已有 .obsidian/）
- 一键初始化
- 测试写入
- 打开目录（调用系统文件管理器）
- 禁用集成
- 重新选择
- 当前状态（已初始化/待初始化/路径失效）
- 最近同步时间
- 集成说明（Vault 与 DB 的主从关系）

**子目录建议**：当前实现直接在 Vault 根写入，无法区分 SignalVault 文件和用户自有文件。建议未来提供选择：
1. **Vault 根模式**（当前行为，兼容现有用户）
2. **子目录模式**（在 Vault 中创建 `SignalVault/` 子目录，所有内容写入其下）

## 6. 系统路径专项审计

### 6.1 当前行为（R0-2 已验证）

| 目录 | 默认路径 | 环境变量覆盖 | 自动创建 | 统一抽象 |
|------|---------|-------------|---------|---------|
| DATA_DIR | `<repo>/data` | `DATA_DIR` | ✅ `ensure_dirs()` | ❌ |
| LOG_DIR | `<repo>/logs` | `LOG_DIR` | ✅ `ensure_dirs()` | ❌ |
| DB_PATH | `<DATA_DIR>/signalvault.db` | `DB_PATH` | ❌ (lazy via init_db) | ❌ |
| SUBTITLE_DIR | `<DATA_DIR>/subtitles` | 无独立变量 | ✅ | ❌ |
| REPORT_DIR | `<DATA_DIR>/reports` | 无独立变量 | ✅ | ❌ |
| TRANSCRIPT_CACHE_DIR | `<DATA_DIR>/transcripts/youtube` | 无独立变量 | ✅ | ❌ |
| user_settings.json | `<cwd>/data/user_settings.json` | 无（测试用 monkeypatch） | ❌ | ❌ |
| 诊断包临时目录 | `tempfile.mkdtemp("sv_diag_")` | 无 | ✅（按需） | ❌ |

**当前无统一路径抽象**。每个模块独立计算或从 config 模块变量读取路径。

### 6.2 关键问题

1. **config_store.py 使用 `os.getcwd()`**：当从不同目录启动 Web 服务时，`user_settings.json` 位置不同。R0-2 已验证通过 `DATA_DIR` 环境变量可解耦，但 `config_store.py` 未使用 `DATA_DIR`。

2. **BASE_DIR 基于 config.py 物理位置**：在 editable install（`pip install -e .`）中指向仓库根目录。打包为 wheel 安装后指向 site-packages 中的安装位置——此时 `data/` 和 `logs/` 会出现在 site-packages 内，**这是不可接受的行为**。

3. **无跨平台标准化**：已支持的平台特性：
   - Windows: pathlib（自动处理反斜杠）
   - macOS/Linux: pathlib（自动处理正斜杠）
   - 缺少：XDG 目录规范（Linux）、Application Support 目录（macOS）、AppData/Local 目录（Windows）

### 6.3 AppPaths 规划（C1 实施，本阶段不实现）

```python
@dataclass
class AppPaths:
    """平台感知的应用路径管理器。"""
    app_name: str = "SignalVault"

    # 自动检测（优先级：env var > 平台默认）
    @property
    def data_dir(self) -> Path: ...
    @property
    def config_dir(self) -> Path: ...
    @property
    def log_dir(self) -> Path: ...
    @property
    def cache_dir(self) -> Path: ...
    @property
    def db_path(self) -> Path: ...
    @property
    def backup_dir(self) -> Path: ...

    # 平台默认
    @staticmethod
    def _default_data_dir() -> Path:
        if sys.platform == "win32":
            return Path(os.getenv("APPDATA", "")) / "SignalVault"
        elif sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "SignalVault"
        else:
            # XDG
            return Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local/share")) / "signalvault"
```

**兼容性要求**：
- `SIGNALVAULT_HOME` 环境变量 → 覆盖所有路径的根
- 现有 `DATA_DIR` / `LOG_DIR` / `DB_PATH` 环境变量 → 继续支持（兼容迁移）
- 测试通过 `tmp_path` fixture → 不写入真实用户目录

## 7. 配置持久化与密钥方案

### 7.1 评估矩阵

| 方案 | 安全性 | 跨平台 | 用户配置 | 敏感配置 | rc1 可用 | 备注 |
|------|--------|--------|---------|---------|---------|------|
| `.env` 文件 | 低（明文） | ✅ | ✅ | ⚠️ | ✅ | 当前方案；不进 git |
| `data/user_settings.json` | 低（明文） | ✅ | ✅ | ❌ | ✅ | 当前方案；仅 Vault 路径 |
| `config/config.toml` | 低（明文） | ✅ | ✅ | ❌ | ✅ | 推荐普通配置方案 |
| `secrets` 文件 (0600) | 中 | ✅ | ❌ | ⚠️ | ✅ | 比 .env 略有改进 |
| macOS Keychain | 高 | ❌ macOS only | ❌ | ✅ | rc2 | 安全但平台锁定 |
| `keyring` 库 | 中-高 | ✅ | ❌ | ✅ | rc2 | 跨平台，但引入新依赖 |
| 数据库存储 | 低（明文） | ✅ | ⚠️ | ❌ | ❌ | 不推荐 |

### 7.2 推荐方案

**rc1（最小可用）：**
- **普通配置**：`<AppPaths.config_dir>/config.toml`
  - 格式：TOML（人类可读写，比 JSON 更友好）
  - 由 `ConfigService` 统一管理读写
  - 启动时自动创建默认值
- **敏感配置（API Key）**：`<AppPaths.config_dir>/secrets`（权限 0600）
  - 单文件存储敏感值（JSON 格式，仅含 key=value）
  - 不在诊断包中收集
  - 不在日志中输出
  - Web 页面不回显完整值

**rc2（增强安全）：**
- macOS：迁移至 Keychain（通过 `keyring` 库，macOS 后端为 Keychain）
- Windows：迁移至 Credential Manager（通过 `keyring` 库）
- Linux：迁移至 Secret Service / `keyring` 文件后端

**迁移兼容**：继续支持 `.env` 作为覆盖层（优先级低于 `config.toml`，高于系统默认值），让高级用户和开发者保留 `.env` 使用习惯。

## 8. Setup State 规划

### 8.1 当前状态

当前 `setup_completed` 概念隐含在以下检查中：
- `OBSIDIAN_VAULT_PATH` 是否非空 → Vault 是否配置
- `/setup/vault` 页面检查 Vault 路径是否存在 → Vault 是否初始化
- Dashboard 在无 Vault 时显示「尚未配置知识库」

**没有统一的状态机或枚举。**

### 8.2 建议状态模型（C1 实施）

```python
class SetupState(enum.IntEnum):
    FRESH = 0           # 首次启动，未完成任何设置
    DB_INITIALIZED = 1  # SQLite 已创建，schema 已建
    LLM_CONFIGURED = 2  # LLM API Key 已配置且测试通过
    VAULT_CONFIGURED = 3 # Vault 路径已设置
    VAULT_INITIALIZED = 4 # Vault 目录结构已创建
    WIZARD_COMPLETED = 5 # 首次向导已完成
    READY = 6           # 所有核心功能可用

# 存储位置：<config_dir>/setup_state.json 或 config.toml 中的 [setup] 段
```

**原则**：
- 状态可部分完成（用户可跳过可选步骤）
- 支持增量升级（从状态 2 到状态 3 不要求重做状态 1）
- 状态不可回退（防止意外重置）
- Dashboard 根据当前状态显示不同的引导

## 9. 分类统计汇总

| 分类 | 数量 | 配置项 |
|------|------|--------|
| A-系统自动 | 11 | BASE_DIR, DATA_DIR, LOG_DIR, DB_PATH, SUBTITLE_DIR, REPORT_DIR, TRANSCRIPT_CACHE_DIR, user_settings 路径, 诊断包临时目录, 备份目录, ZSXQ CLI 候选名 |
| B-用户必填 | 3 | LLM_PROVIDER, LLM_API_KEY, LLM_MODEL |
| C-用户可选 | 5 | LLM_BASE_URL, OBSIDIAN_VAULT_PATH, OBSIDIAN_EXPORT_ENABLED, OpenAI 默认 model, --focus |
| D-高级设置 | 11 | LLM timeout, LLM max_retries, LLM temperature, Vault 子目录名, host, port, reload, LOG_LEVEL, 日志大小/备份数, ZSXQ_CLI_PATH, chunk 参数, YouTube 语言 |
| E-敏感 | 1 | LLM_API_KEY |
| F-部署/CI | 5 | Python 版本, 测试命令, Lint 命令, Playwright, Ruff 版本 |
| G-废弃/重复 | 6 | 双重 OBSIDIAN_VAULT_PATH, LLM_PROVIDER 命名不一致, Mock 逻辑分散, .env.example 不完整, 硬编码 model 默认值, config_store 使用 cwd |
| **合计** | **42** | — |

## 10. 配置来源图

```
                    ┌──────────────────────────────────┐
                    │         .env 文件 (可选)          │
                    │  LLM_PROVIDER / LLM_API_KEY / ... │
                    └──────────┬───────────────────────┘
                               │ load_dotenv (不覆盖已有 env)
                               ▼
┌──────────┐    import    ┌──────────┐    读取    ┌──────────────┐
│ conftest │ ──强制──►   │ config   │ ◄────────  │ os.environ   │
│ (测试)   │  os.environ │  .py     │            │ (环境变量)    │
└──────────┘             │          │            └──────────────┘
                         │ 模块级变量 │
                         │ LLM_PROVIDER│◄──── CLI --mock/--no-mock
                         │ LLM_API_KEY │         覆盖（部分命令）
                         │ DATA_DIR   │
                         │ DB_PATH    │◄──── CLI --db-path
                         │ ...        │         覆盖（部分命令）
                         └─────┬──────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
       ┌──────────┐    ┌────────────┐   ┌──────────────┐
       │ pipeline │    │ services/  │   │ diagnostics/ │
       │  .py     │    │ analyze_   │   │ bundle.py    │
       │          │    │ service.py │   │ summary.py   │
       └──────────┘    └────────────┘   └──────────────┘

       ┌──────────────────────────────────────────────┐
       │           config_store.py                    │
       │                                              │
       │  get_user_vault_path():                      │
       │    1. user_settings.json (磁盘)               │
       │    2. os.getenv("OBSIDIAN_VAULT_PATH")       │
       │    3. "" (默认)                               │
       │                                              │
       │  仅用于 OBSIDIAN_VAULT_PATH（Web 端）         │
       │  CLI 直接读 config.py 模块变量（不走此路径） │
       └──────────────────────────────────────────────┘
```

## 11. 关键冲突与风险

| # | 风险 | 严重度 | 影响 |
|---|------|--------|------|
| R1 | config.py OBSIDIAN_VAULT_PATH 与 config_store 不同步 | 中 | Web 保存的 Vault 路径 CLI 看不到；operator 可能困惑 |
| R2 | config_store 使用 os.getcwd() | 中 | 不同启动方式可能导致 user_settings.json 位置不同 |
| R3 | import-time load_dotenv | 中 | 修改 .env 后必须重启，无法运行时重载 |
| R4 | LLM_API_KEY 可能进入诊断包 | **高** | `bundle.py:309` 检查了 key 是否存在但未完全防止泄露（通过 `redact_dict` 保护，但需验证） |
| R5 | 打包后 BASE_DIR 指向 site-packages | **高** | `pip install` 非 editable 模式时 data/ 和 logs/ 会出现在 site-packages 内 |
| R6 | Web PDF 固定 mock | 低 | 用户无法在 Web 上使用真实 LLM 分析 PDF |
| R7 | .env.example 不完整 | 低 | 新用户缺少部分可选配置的文档 |
| R8 | LLM_PROVIDER 命名不一致 | 低 | "openai-compatible" vs "openai_compatible" 可能在某些路径失效 |

## 12. 后续阶段建议

本审计为 C0 交付物。后续 C1–C4 规划见 `docs/CONFIGURATION_ARCHITECTURE_PLAN.md`。

**C0 判定**：配置项已全部识别（42 项），优先级、冲突和风险已记录。LLM、Obsidian、系统路径三个专项审计已完成。**具备进入 C1（统一配置基础）的条件。**
