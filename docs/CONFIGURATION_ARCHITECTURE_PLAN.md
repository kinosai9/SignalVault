# Configuration Architecture Plan

> 基于 `docs/CONFIGURATION_AUDIT.md` 的事实发现  
> 规划 C1–C4 实施路径，最小化风险，最大化复用现有代码

## 实施状态（2026-07-16）

| 阶段 | 状态 | 内容 |
|------|------|------|
| C1-A | ✅ 已交付 | AppPaths — 跨平台路径解析 |
| C1-B | ✅ 已交付 | ConfigSchema、ConfigService、SecretStore |
| C1-C | ✅ 已交付 | LLM Runtime Factory、SetupStatus、LLM/Obsidian Validators、Vault Manifest |
| C2-A | ✅ 已交付 | AI 服务配置页面、CSRF/Origin 保护 |
| C2-B | ✅ 已交付 | Obsidian 集成配置页面、Vault 初始化/修复/Manifest |
| C2-C | ✅ 已交付 | 设置中心概览、系统页面、About 页面、导航、版本单一来源 |
| C3 | 🔜 计划中 | 首次使用向导 |
| C4 | 🔜 计划中 | 多 Provider、Keychain、原生目录选择器 |

### 实际架构

```
src/signalvault/
├── settings/
│   ├── app_paths.py          # AppPaths — 平台路径
│   ├── schema.py             # ConfigSchema — 运行时配置项
│   ├── service.py            # ConfigService — 5 层优先级链
│   ├── secret_store.py       # SecretStore — 密钥独立文件
│   ├── llm_runtime.py        # LLMRuntimeConfig + create_llm_provider()
│   ├── llm_validator.py      # LLM 连接验证
│   ├── obsidian_validator.py # Vault 路径验证
│   ├── vault_manifest.py     # Vault Manifest CRUD
│   ├── setup_status.py       # SetupStatus 聚合
│   └── __init__.py
├── services/
│   ├── ai_settings_service.py      # AI 页面 + JSON API 后端
│   ├── obsidian_settings_service.py # Obsidian 页面 + JSON API 后端
│   └── settings_overview_service.py # 概览/系统/About 聚合
├── web/
│   ├── csrf.py               # CSRF double-submit cookie + Origin 校验
│   ├── routes.py             # HTML 页面路由（settings + obsidian POST）
│   ├── routes_settings.py    # JSON API 路由
│   └── templates/settings/
│       ├── base.html         # 共享设置布局 + 二级导航
│       ├── overview.html     # 概览四卡片
│       ├── ai.html           # AI 配置表单
│       ├── obsidian.html     # Obsidian 配置
│       ├── system.html       # 系统状态（只读）
│       └── about.html        # 关于 / 诊断
└── __init__.py               # __version__ via importlib.metadata
```

### 测试基线

| 指标 | 值 |
|------|-----|
| 收集 | 2359 tests |
| 通过 | 2351 passed |
| 跳过 | 1 (Windows 平台限制) |
| UI smoke | 7 passed |
| Ruff | Clean |

### 已知限制

- Web 页面不支持在线修改 host/port/路径
- 无原生目录选择器（C4 规划）
- 无 Keychain 集成（C4 规划）
- 无多 Provider 支持（C4 规划）
- Build commit 在 wheel 部署时显示为空（C3/C4 构建时注入）
- 不修改 host/port 或路径的重启自动生效

## 1. 目标架构概览

```
┌─────────────────────────────────────────────────────────┐
│                    优先级链                              │
│  函数参数 > CLI 参数 > config.toml > 环境变量 > 默认值    │
└─────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   ConfigService         SecretStore           AppPaths
   (普通配置 TOML)      (敏感配置 0600)       (平台路径)
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ▼
                      SetupState
                    (启动状态机)
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   CLI 命令              Web 路由              测试 fixtures
```

## 2. 组件详细设计

### 2.1 AppPaths（新建）

**责任**：提供平台感知的统一应用路径，消除硬编码路径和 `os.getcwd()` 依赖。

**复用评估**：当前 `config.py` 有分散的路径定义，无统一抽象。**需新建**。

```python
# src/signalvault/config/app_paths.py (C1 新建)
@dataclass(frozen=True)
class AppPaths:
    app_name: str = "SignalVault"
    home_override: str | None = None  # SIGNALVAULT_HOME env

    @property
    def data_dir(self) -> Path:
        """用户数据根目录。环境变量 SIGNALVAULT_HOME 或 DATA_DIR 覆盖。"""
        ...

    @property
    def config_dir(self) -> Path:
        """配置文件目录。"""
        return self.data_dir / "config"

    @property
    def log_dir(self) -> Path: ...

    @property
    def db_path(self) -> Path: ...

    @property
    def cache_dir(self) -> Path: ...

    @property
    def backup_dir(self) -> Path: ...

    @property
    def temp_dir(self) -> Path: ...

    # 平台默认
    @staticmethod
    def _platform_data_dir() -> Path:
        """Windows: %APPDATA%/SignalVault
           macOS:   ~/Library/Application Support/SignalVault
           Linux:   $XDG_DATA_HOME/signalvault"""
```

**平台默认路径**：

| 平台 | 数据目录 | 配置目录 | 缓存目录 |
|------|---------|---------|---------|
| Windows | `%APPDATA%\SignalVault` | `%APPDATA%\SignalVault\config` | `%LOCALAPPDATA%\SignalVault\cache` |
| macOS | `~/Library/Application Support/SignalVault` | `~/Library/Application Support/SignalVault/config` | `~/Library/Caches/SignalVault` |
| Linux | `$XDG_DATA_HOME/signalvault` | `$XDG_CONFIG_HOME/signalvault` | `$XDG_CACHE_HOME/signalvault` |

**环境变量覆盖链**（全平台）：
1. `SIGNALVAULT_HOME` → 覆盖所有路径根
2. `DATA_DIR` / `LOG_DIR` / `DB_PATH` → 单独覆盖（兼容现有 .env）
3. 平台默认值

**迁移兼容**：
- 如果 `DATA_DIR` 指向仓库 `data/`（开发模式），AppPaths 应检测并保持兼容
- 如果 `SIGNALVAULT_HOME` 未设置且 `DATA_DIR` 未设置，默认使用平台路径
- 首次启动时如果检测到旧 `data/` 目录，提示迁移

**测试兼容**：
- `AppPaths` 接受构造参数覆盖，不读环境变量
- conftest.py 通过 `AppPaths(home_override=tmp_path)` 注入测试路径

**与 CLI/Web/测试的关系**：
- CLI：单例，启动时通过 `AppPaths.resolve()` 解析
- Web：单例，FastAPI lifespan 中初始化
- 测试：每个 fixture 独立实例，通过 `tmp_path` 覆盖

**预计修改文件**：
- 新建：`src/signalvault/config/app_paths.py`
- 修改：`src/signalvault/config.py`（废弃 BASE_DIR/DATA_DIR/LOG_DIR/DB_PATH/SUBTITLE_DIR/REPORT_DIR/TRANSCRIPT_CACHE_DIR，改为从 AppPaths 读取，保留别名兼容）
- 修改：`src/signalvault/config_store.py`（使用 AppPaths.config_dir 替代 os.getcwd()）
- 修改：`src/signalvault/logging_config.py`（使用 AppPaths.log_dir）
- 修改：`src/signalvault/db/session.py`（使用 AppPaths.db_path）
- 修改：`tests/conftest.py`（通过 AppPaths 注入测试路径）
- 参考实现：`src/signalvault/config.py`（路径计算逻辑）

**风险**：低。AppPaths 是纯计算组件，不影响业务逻辑。主要风险在迁移时确保现有测试继续通过。

### 2.2 ConfigSchema（新建）

**责任**：定义所有配置项的 schema、默认值、验证规则和分类。

**复用评估**：无现有实现。**需新建**。

```python
# src/signalvault/config/config_schema.py (C1 新建)
from dataclasses import dataclass, field
from enum import Enum

class ConfigCategory(Enum):
    SYSTEM = "system"
    LLM = "llm"
    OBSIDIAN = "obsidian"
    ADVANCED = "advanced"

class ConfigSensitivity(Enum):
    PUBLIC = "public"
    SENSITIVE = "sensitive"  # 不进诊断包，不在日志输出

@dataclass
class ConfigItem:
    key: str
    default: Any
    category: ConfigCategory
    sensitivity: ConfigSensitivity
    description: str
    env_var: str | None = None      # 兼容旧环境变量名
    cli_flag: str | None = None      # 如 "--host"
    web_editable: bool = False       # 是否在配置中心显示
    validator: Callable | None = None

# 完整 schema（C1 从代码迁移，C2 完善）
CONFIG_SCHEMA: dict[str, ConfigItem] = {
    "llm.provider": ConfigItem(...),
    "llm.api_key": ConfigItem(sensitivity=SENSITIVE, ...),
    "llm.model": ConfigItem(...),
    "llm.base_url": ConfigItem(...),
    "llm.timeout": ConfigItem(default=120.0, category=ADVANCED, ...),
    "llm.max_retries": ConfigItem(default=2, category=ADVANCED, ...),
    "obsidian.vault_path": ConfigItem(default="", ...),
    "obsidian.export_enabled": ConfigItem(default=False, ...),
    "obsidian.subdirectory": ConfigItem(default="", category=ADVANCED, ...),
    "web.host": ConfigItem(default="127.0.0.1", category=ADVANCED, ...),
    "web.port": ConfigItem(default=8000, category=ADVANCED, ...),
    "logging.level": ConfigItem(default="INFO", category=ADVANCED, ...),
    # ... (42 total items from audit)
}
```

**预计修改文件**：
- 新建：`src/signalvault/config/config_schema.py`
- 无现有文件需修改（新建组件）

**风险**：低。纯定义层，不影响运行时行为。

### 2.3 ConfigService（新建，核心）

**责任**：统一的配置读写接口，优先级链实现，配置变更通知。

**复用评估**：当前 `config.py`（模块变量 + env）+ `config_store.py`（JSON 文件）。**需新建，封装现有逻辑**。

```python
# src/signalvault/config/config_service.py (C1 新建)
class ConfigService:
    """统一配置服务。优先级：参数 > TOML > env > schema default"""

    def __init__(self, app_paths: AppPaths, schema: dict[str, ConfigItem]):
        self._app_paths = app_paths
        self._schema = schema
        self._overrides: dict[str, Any] = {}  # 运行时覆盖（如 CLI 参数）
        self._toml_data: dict[str, Any] = {}
        self._load_toml()

    def get(self, key: str) -> Any: ...
    def get_string(self, key: str) -> str: ...
    def get_int(self, key: str) -> int: ...
    def get_bool(self, key: str) -> bool: ...

    def set(self, key: str, value: Any) -> None:
        """写入 TOML 并通知变更。API Key 走 SecretStore。"""

    def test_llm_connection(self, ...) -> ConnectionTestResult: ...

    # 兼容现有 config.py 接口
    @property
    def llm_provider(self) -> str: ...
    @property
    def llm_api_key(self) -> str: ...

# 单例（模块级，替代现有 config.py 的模块变量）
_config_service: ConfigService | None = None

def get_config_service() -> ConfigService: ...
```

**与现有代码的关系**：
- `config.py` → 保留为兼容层，内部转发到 ConfigService
- `config_store.py` → 合并进 ConfigService（Vault 路径存为 `obsidian.vault_path` 在 TOML 中）
- `.env` → 继续支持作为环境变量覆盖（优先级低于 TOML）

**与 CLI/Web/测试的关系**：
- CLI：在命令入口处设置 `_overrides`（如 `--host`、`--port`、`--db-path`）
- Web：通过 `get_config_service()` 获取单例
- 测试：conftest.py 通过 `ConfigService(app_paths=test_paths)` 创建隔离实例

**修改配置后行为**：
- TOML 写入后立即生效（ConfigService 缓存刷新）
- 环境变量变更需重启（受限于 os.environ 特性）
- 不实现热重载通知（rc1 范围外）

**预计修改文件**：
- 新建：`src/signalvault/config/config_service.py`
- 新建：`src/signalvault/config/__init__.py`（包初始化）
- 修改：`src/signalvault/config.py`（改为兼容层）
- 修改：`src/signalvault/config_store.py`（废弃，迁移到 ConfigService）
- 修改：`src/signalvault/cli.py`（使用 ConfigService 替代 config.LLM_PROVIDER 等）
- 修改：`src/signalvault/web/routes.py`（使用 ConfigService）
- 修改：`src/signalvault/analysis/pipeline.py`（使用 ConfigService 获取 LLM 配置）
- 修改：`src/signalvault/services/analyze_service.py`（同上）
- 修改：`src/signalvault/db/session.py`（使用 ConfigService 获取 DB_PATH）
- 修改：`src/signalvault/logging_config.py`（使用 ConfigService 获取日志配置）
- 修改：`src/signalvault/diagnostics/bundle.py`（使用 ConfigService）
- 修改：`tests/conftest.py`（注入测试 ConfigService）

**风险**：**中高**。ConfigService 是 C1 最大变更，涉及 ~12 个文件的导入路径修改。需充分测试，特别是 config.py 兼容层。

### 2.4 SecretStore（新建）

**责任**：安全存储 API Key 等敏感配置。rc1 用 0600 文件；rc2 可升级到 Keychain。

**复用评估**：当前无实现。API Key 仅存于 `.env` 和环境变量。**需新建**。

```python
# src/signalvault/config/secret_store.py (C1 新建)
class SecretStore:
    """敏感配置存储。rc1: 权限 0600 的 JSON 文件。"""

    def __init__(self, app_paths: AppPaths):
        self._secrets_path = app_paths.config_dir / "secrets"
        # 创建时设置 0600 权限

    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...
    def list_keys(self) -> list[str]: ...  # 不返回值

    # 批量操作（用于诊断包排除）
    def redact_for_diagnostics(self) -> dict[str, bool]:
        """返回 {key: is_set} 不包含实际值"""
```

**密钥清单**（当前 + 未来）：
| Key | 当前存储 | rc1 方案 |
|-----|---------|---------|
| `LLM_API_KEY` | `.env` 明文 | SecretStore (0600) |
| (未来) Obsidian API Token | 无 | SecretStore (0600) |
| (未来) ZSXQ Cookie | 无 | SecretStore (0600) |

**安全原则**：
- 不进 git（.gitignore 已覆盖 config 目录）
- 不进诊断包（`redact_for_diagnostics` 只返回 key 是否存在）
- 不进日志（ConfigService 在日志中遮蔽敏感 key）
- Web 页面不回显完整值（仅显示 `****abcd` 最后 4 位）

**预计修改文件**：
- 新建：`src/signalvault/config/secret_store.py`
- 修改：`src/signalvault/diagnostics/bundle.py`（使用 SecretStore.redact_for_diagnostics）
- 修改：`src/signalvault/analysis/pipeline.py`（从 ConfigService → SecretStore 获取 API Key）

**风险**：低。SecretStore 是独立组件，仅被 ConfigService 调用。迁移时需确保现有 `.env` 中的 API Key 能被一次性导入。

### 2.5 SetupState（新建）

**责任**：管理首次启动状态，区分「未初始化/部分完成/就绪」。

**复用评估**：无现有实现。当前仅通过检查 Vault 路径是否为空推断状态。**需新建**。

```python
# src/signalvault/config/setup_state.py (C1 新建)
class SetupStep(Enum):
    DB = 1
    LLM = 2
    VAULT_PATH = 3
    VAULT_INIT = 4
    WIZARD = 5

class SetupState:
    """持久化首次启动状态到 config.toml [setup] 段。"""

    def is_completed(self, step: SetupStep) -> bool: ...
    def mark_completed(self, step: SetupStep) -> None: ...
    def get_next_step(self) -> SetupStep | None: ...
    def is_ready(self) -> bool: ...
    def reset(self, step: SetupStep) -> None: ...  # 仅用于修复
```

**Dashboard 集成**：
- `FRESH` → 重定向到 `/setup/wizard`
- `DB_INITIALIZED` → 提示配置 LLM
- `LLM_CONFIGURED` → 提示配置 Vault（可选）
- `VAULT_CONFIGURED` → 提示初始化 Vault
- `READY` → 正常 Dashboard

**预计修改文件**：
- 新建：`src/signalvault/config/setup_state.py`
- 修改：`src/signalvault/web/routes.py`（Dashboard 和 setup 路由检查 SetupState）
- 修改：`src/signalvault/cli.py`（serve 命令启动时检查状态，打印提示）

**风险**：低。SetupState 不影响现有功能，仅添加引导逻辑。

### 2.6 LLMConfigValidator（新建）

**责任**：提供 LLM 连接测试和配置验证能力。

**复用评估**：当前 `OpenAICompatibleProvider._chat()` 有基本错误处理，但无独立的连接测试。**需新建**。

```python
# src/signalvault/config/llm_config_validator.py (C1 新建)
class ConnectionTestResult:
    ok: bool
    error_type: str | None  # auth_failed, model_not_found, ...
    error_message: str | None
    latency_ms: float | None

class LLMConfigValidator:
    def test_connection(
        self, provider: str, api_key: str, base_url: str, model: str
    ) -> ConnectionTestResult:
        """发送最小 API 请求验证连接。超时 10 秒。"""
```

**Web API 端点**（C2 实现页面，C1 可实现后端）：
```
POST /api/llm/test-connection
  → 200 { ok: true, latency_ms: 234 }
  → 200 { ok: false, error_type: "auth_failed", error_message: "..." }
```

**预计修改文件**：
- 新建：`src/signalvault/config/llm_config_validator.py`
- 修改：`src/signalvault/web/routes.py`（C2 添加 API 端点）

**风险**：低。独立组件，不影响现有调用路径。

### 2.7 ObsidianConfigValidator（新建）

**责任**：Vault 路径校验、权限检查、初始化状态检查。

**复用评估**：当前 `workspace/setup.py` 有 `validate_vault()`，可直接复用。**需新建封装层**。

```python
# src/signalvault/config/obsidian_config_validator.py (C1 新建)
class VaultValidationResult:
    valid: bool
    exists: bool
    is_directory: bool
    is_writable: bool
    is_initialized: bool
    missing_dirs: list[str]
    missing_files: list[str]
    has_obsidian_config: bool  # 是否已有 .obsidian/ 目录
    error_message: str | None

class ObsidianConfigValidator:
    def validate_path(self, path: str) -> VaultValidationResult: ...
    def initialize(self, path: str) -> VaultSetupResult: ...
    def test_write(self, path: str) -> bool: ...
```

**预计修改文件**：
- 新建：`src/signalvault/config/obsidian_config_validator.py`
- 修改：`src/signalvault/web/routes.py`（`/setup/vault` 使用新 validator）

**风险**：低。封装现有 `workspace/setup.py` 逻辑，不改变行为。

## 3. 阶段拆分

### C1：统一配置基础

**目标**：建立 AppPaths、ConfigService、SecretStore、SetupState 基础设施，不改变用户可见行为。

**文件级清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| **新建** | `src/signalvault/config/__init__.py` | 配置包子包初始化 |
| **新建** | `src/signalvault/config/app_paths.py` | 平台路径管理 |
| **新建** | `src/signalvault/config/config_schema.py` | 42 项配置 schema |
| **新建** | `src/signalvault/config/config_service.py` | 统一配置读写 |
| **新建** | `src/signalvault/config/secret_store.py` | 敏感配置存储 |
| **新建** | `src/signalvault/config/setup_state.py` | 启动状态机 |
| **新建** | `src/signalvault/config/llm_config_validator.py` | LLM 连接测试 |
| **新建** | `src/signalvault/config/obsidian_config_validator.py` | Vault 校验 |
| **修改** | `src/signalvault/config.py` | 改为 ConfigService 兼容层 |
| **修改** | `src/signalvault/config_store.py` | 废弃，标记 DeprecationWarning |
| **修改** | `src/signalvault/logging_config.py` | 使用 AppPaths |
| **修改** | `src/signalvault/db/session.py` | 使用 ConfigService |
| **修改** | `src/signalvault/cli.py` | 使用 ConfigService |
| **修改** | `src/signalvault/web/routes.py` | 使用 ConfigService |
| **修改** | `src/signalvault/analysis/pipeline.py` | 使用 ConfigService 获取 LLM 配置 |
| **修改** | `src/signalvault/services/analyze_service.py` | 使用 ConfigService |
| **修改** | `src/signalvault/diagnostics/bundle.py` | 使用 ConfigService + SecretStore |
| **修改** | `src/signalvault/diagnostics/summary.py` | 使用 ConfigService |
| **修改** | `src/signalvault/sources/zsxq_cli.py` | ZSXQ_CLI_PATH 从 ConfigService |
| **修改** | `.env.example` | 补齐缺失配置项 |
| **修改** | `tests/conftest.py` | 注入测试 AppPaths + ConfigService |
| **新建** | `tests/test_config_app_paths.py` | AppPaths 单元测试 |
| **新建** | `tests/test_config_service.py` | ConfigService 单元测试 |
| **新建** | `tests/test_config_secret_store.py` | SecretStore 单元测试 |
| **新建** | `tests/test_config_setup_state.py` | SetupState 单元测试 |

**验收标准**：
- 所有现有 2013 tests 通过
- 新增配置模块测试覆盖
- `config.py` 兼容层：`LLM_PROVIDER`、`LLM_API_KEY` 等别名正常工作
- `DATA_DIR` / `LOG_DIR` / `DB_PATH` 环境变量继续生效
- `SIGNALVAULT_HOME` 环境变量可覆盖所有路径
- SecretStore 创建的文件权限为 0600（Unix）或等价（Windows ACL）
- SetupState 正确记录初始化进度

### C2：系统与集成页面

**目标**：在 Web Console 中添加「系统与集成」配置页面，让非技术用户可以在 UI 中配置。

**页面结构**：
```
/settings                    → 系统与集成首页
  /settings/ai               → AI 服务（LLM Provider/Key/Model/测试连接）
  /settings/obsidian         → Obsidian（路径/初始化/状态/打开目录）
  /settings/data             → 数据与备份（数据库位置/备份）
  /settings/advanced         → 高级设置（host/port/log level/chunk 参数）
  /settings/diagnostics      → 诊断与关于
```

**文件级清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| **新建** | `src/signalvault/web/templates/settings_base.html` | 设置页面布局基模板 |
| **新建** | `src/signalvault/web/templates/settings_ai.html` | AI 服务配置页 |
| **新建** | `src/signalvault/web/templates/settings_obsidian.html` | Obsidian 配置页 |
| **新建** | `src/signalvault/web/templates/settings_data.html` | 数据与备份页 |
| **新建** | `src/signalvault/web/templates/settings_advanced.html` | 高级设置页 |
| **新建** | `src/signalvault/web/templates/settings_diagnostics.html` | 诊断与关于页 |
| **修改** | `src/signalvault/web/routes.py` | 添加 `/settings/*` 路由 |
| **修改** | `src/signalvault/web/templates/dashboard.html` | 顶部导航添加设置入口 |
| **新建** | `tests/test_web_settings.py` | 设置页面测试 |

**验收标准**：
- 所有设置页面可正常加载
- AI 服务页面：可输入 Provider/Key/Model/Base URL 并测试连接
- Obsidian 页面：可选择目录、初始化、查看状态
- 设置保存后立即生效（无需重启，ConfigService 自动刷新缓存）
- API Key 页面显示掩码值（`****abcd`）
- 不影响 CLI 使用

### C3：首次使用向导

**目标**：新用户首次启动时引导完成必要配置。

**页面流**：
```
/ → 检测 SetupState
  → FRESH: 重定向到 /setup/wizard
    → Step 1: 欢迎与隐私提示
    → Step 2: LLM 配置 + 测试连接
    → Step 3: Obsidian 配置（可选跳过）
    → Step 4: Vault 初始化
    → Step 5: 完成 → 重定向到 /dashboard
  → READY: 正常显示 /dashboard
```

**文件级清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| **新建** | `src/signalvault/web/templates/setup_wizard.html` | 向导多步骤页面 |
| **修改** | `src/signalvault/web/routes.py` | 添加 `/setup/wizard` 路由 |
| **修改** | `src/signalvault/web/routes.py` | Dashboard 路由检查 SetupState |
| **修改** | `src/signalvault/web/templates/dashboard.html` | 部分完成状态的引导横幅 |

**验收标准**：
- 首次启动自动进入向导
- 每步可独立完成或跳过（可选步骤）
- 向导不阻塞跳过可选步骤的用户
- 已完成的步骤不在 Dashboard 重复提示
- 向导可重新进入（通过设置页面）

### C4：macOS 打包接入

**目标**：为 macOS 分发做好准备，但不完成完整 .app 打包。

**范围**：
- AppPaths 在 macOS 上使用 `~/Library/Application Support/SignalVault`
- SecretStore 在 macOS 上支持 Keychain 后端（通过 `keyring` 库，可选）
- 验证 `pip install` 非 editable 模式下的路径行为
- `.app` 启动器骨架（py2app 或等效方案评估）

**本阶段不实现**：
- 完整 .app bundle
- 代码签名
- App Store 分发
- Sparkle 自动更新

## 4. RC 必须项与延期项

### rc1 必须完成（P0）

| 项目 | 阶段 | 说明 |
|------|------|------|
| AppPaths 平台路径管理 | C1 | 消除硬编码路径 |
| ConfigService 统一配置读写 | C1 | 替代 config.py 模块变量 |
| SecretStore 敏感配置存储 | C1 | API Key 安全存储 |
| SetupState 启动状态跟踪 | C1 | 支持首次向导 |
| .env / env var 向后兼容 | C1 | 现有用户无感迁移 |
| 测试全绿 | C1 | 2013 tests + 新增测试 |
| AI 服务配置页面 | C2 | 非技术用户可配置 LLM |
| Obsidian 配置页面 | C2 | 非技术用户可配置 Vault |
| 首次使用向导 | C3 | 新用户 5 分钟可上手 |
| LLM 连接测试 | C2 | 配置页面内置测试按钮 |

### 可延期到 rc2

| 项目 | 说明 |
|------|------|
| macOS Keychain 集成 | 需 `keyring` 库，增加依赖 |
| 多 Provider 管理 | 同时配置多个 LLM Provider |
| 自动发现 Obsidian Vault | 扫描常见目录 |
| 高级配置页面 | host/port/chunk/log rotate 等 |
| 配置导入/导出 | 备份和恢复用户配置 |
| 原生目录选择器 | 替换浏览器默认文件上传控件 |
| macOS .app 打包 | py2app + 代码签名 |
| 配置变更热重载 | 修改 TOML 后无需重启 |

## 5. 迁移计划

### 5.1 现有用户迁移路径

1. **首次 C1 启动时**：
   - 检测到旧 `.env` → 自动导入到 `config.toml`
   - 检测到旧 `data/user_settings.json` → 迁移 Vault 路径到 `config.toml`
   - 检测到旧 `data/signalvault.db` → 保持不动（数据完整性）
   - 旧 `.env` 保留但不再作为主配置源（仅作为环境变量覆盖）

2. **开发者体验**：
   - `.env` 继续工作（优先级低于 config.toml，高于默认值）
   - `--mock` / `--no-mock` CLI 参数继续工作
   - `--vault` / `--db-path` CLI 覆盖继续工作

3. **回滚路径**：
   - C1 不删除任何旧文件
   - 如果 `config.toml` 损坏，回退到 `.env` + 默认值
   - `config.py` 兼容层确保现有代码不需要立即修改

### 5.2 测试迁移

- `conftest.py` 通过 `ConfigService(app_paths=test_paths)` 注入隔离配置
- 不再依赖 `monkeypatch.setenv` 设置配置值（改用 ConfigService override）
- `db_session` fixture 通过 `AppPaths` 设置临时 DB 路径

## 6. 风险评估

| 风险 | 阶段 | 缓解 |
|------|------|------|
| ConfigService 变更范围大（~12 文件） | C1 | 保留 config.py 兼容层；分步提交 |
| 现有 .env 用户配置丢失 | C1 | 自动导入；保留 .env 回退 |
| AppPaths 在不同平台行为不一致 | C1 | 3 平台 CI 测试（GitHub Actions matrix） |
| SecretStore 权限设置跨平台差异 | C1 | Windows ACL / Unix chmod 分别处理 |
| LLM 配置页面暴露 API Key | C2 | 掩码显示 + SecretStore 后端 |
| 向导过于复杂导致用户流失 | C3 | 每步可跳过；有「以后再说」按钮 |

## 7. 判定

**C0 审计已完成。42 个配置项已全部识别、分类并记录冲突和风险。**

**具备进入 C1 的条件。** C1 建议从 AppPaths 和 ConfigService 开始，这两个组件是所有后续工作的基础。

**C1 预计改动**：8 个新文件，12 个修改文件，4 个新测试文件。预计工作量 1 个完整开发会话。
