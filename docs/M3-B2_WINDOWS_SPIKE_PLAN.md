# M3-B2 Windows Packaging Spike — Plan

**Date**: 2026-07-31
**Status**: Phase 1 完成
**Tag**: v0.1.0rc1 (at commit 9a779b1)

---

## Phase 1: 当前环境与工程状态检查

### 1. Git 状态

| 项目 | 值 |
|------|-----|
| Working tree | **clean** (no uncommitted changes) |
| Branch | `main` |
| HEAD | `5951fe8` (Refactor README for product launch) |
| Latest tag | `v0.1.0rc1` (at `9a779b1`) |
| Tag at HEAD | None |

HEAD is 2 commits ahead of v0.1.0rc1 tag. The RC tag was cut at the M3-B0 completion commit.

### 2. Python 环境

| 项目 | 值 |
|------|-----|
| Python | 3.14.0 |
| pip | 26.1.2 |
| Briefcase | 0.4.4 |
| setuptools | 82.0.1 |
| build | 1.5.0 |
| wheel | 0.47.0 |
| Runtime version | 0.1.0 (confirmed via `import signalvault`) |

### 3. Briefcase 配置分析 (pyproject.toml)

#### 已存在配置

```toml
[tool.briefcase]
project_name = "SignalVault"
bundle = "com.kinosai.signalvault"
version = "0.1.0"

[tool.briefcase.app.signalvault]
formal_name = "SignalVault"
description = "多源投资研究助手"
entry_point = "signalvault.app:main"
sources = ["src/signalvault"]
requires = []   # reads from [project.dependencies]

[tool.briefcase.app.signalvault.macOS]
requires = []
universal_build = false
arch = "arm64"
min_os_version = "12.0"
```

#### 缺失配置

- **`[tool.briefcase.app.signalvault.Windows]` — 不存在**
- 仅 macOS target 已定义

#### 应用入口点

- `entry_point = "signalvault.app:main"` → 调用 `signalvault.launcher.launch()`
- Launcher 已有 Win32 进程检测（`ctypes` + `OpenProcess`/`GetExitCodeProcess`）
- Launcher 已有平台感知路径（`AppPaths` → `%APPDATA%/SignalVault`）
- Windows 上 `signal.SIGINT`/`signal.SIGTERM` 均可正常使用

#### 资源打包

- `sources = ["src/signalvault"]` — Briefcase 将 `src/signalvault/` 作为 Python package
- `[tool.setuptools.package-data]` 包含 web templates 和 static 文件
- 静态文件基于 `__file__` 相对路径解析 (`api/app.py:51`)
- 模板通过 Jinja2 `PackageLoader` 或文件系统路径加载

### 4. 关键架构发现

#### 已就绪的 Windows 适配

| 模块 | Windows 兼容性 |
|------|---------------|
| `launcher.py` | Win32 进程检测、PID 管理、信号处理 ✅ |
| `app_paths.py` | `%APPDATA%/SignalVault`、`%LOCALAPPDATA%` 路径 ✅ |
| `config.py` | `BASE_DIR = Path(__file__).resolve().parent.parent.parent` — 在 Briefcase bundle 中路径不同 ⚠️ |
| `api/app.py` | `static_dir = Path(__file__).parent.parent / "web" / "static"` — 相对路径 ✅ |

#### 潜在风险点

1. **`config.py:BASE_DIR`** — 在 Briefcase bundle 中 `Path(__file__).resolve().parent.parent.parent` 指向 Briefcase 创建的虚拟环境内部而非项目根目录
2. **`BASE_DIR` 的消费方** — 需确认是否有代码依赖 `BASE_DIR` 访问项目根目录文件
3. **Jinja2 模板加载** — 需确认是否通过文件系统路径加载（将受 Briefcase bundle 影响）
4. **`ensure_dirs()` 调用** — CLI 入口调用 `config.ensure_dirs()`，app 入口走 `lifespan` → `init_db()`

### 5. 下一步

Phase 2: Windows Briefcase Build Spike
1. 添加 `[tool.briefcase.app.signalvault.Windows]` 配置
2. 执行 `briefcase create windows`
3. 执行 `briefcase build windows`
4. 记录所有问题和修复
