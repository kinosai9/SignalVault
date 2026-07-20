# SignalVault macOS 打包审计报告 (M0)

> 日期：2026-07-20
> 基线：bf1145a (C3 post-review: dashboard guard, TOML hardening, vault route migration)
> 收集：2408 tests, ruff 全过, 工作区干净

## 一、仓库基线核对

| 检查项 | 结果 |
|--------|------|
| `git status --short` | 干净（无输出） |
| `git log -1 --oneline` | `bf1145a @ C3 post-review...` |
| `ruff check src/ tests/` | All checks passed |
| `pytest --collect-only -q` | 2408 tests collected |
| `git diff --check` | 干净 |
| 本地 secrets | 无 |
| 真实 config.toml | 无 |
| 真实 Vault | 无 |
| 测试截图/临时打包产物 | 无 |

C3 验收文档已提交，基线符合 M0 入口条件。

## 二、wheel/sdist 审计

### 2.1 pyproject.toml 现状

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

**关键缺口：没有 `[tool.setuptools.package-data]` 配置，没有 `MANIFEST.in`。**

### 2.2 package discovery

- `setuptools` automatic discovery from `src/`
- `signalvault` 包包含 138 个 `.py` 模块
- `signalvault.web.templates` 下有 45 个 `.html` 模板
- `signalvault.web.static` 下有 3 个静态文件 (style.css, app.js, signalvault-icon.svg)

### 2.3 非 Python 资源清单

| 资源类型 | 路径 | 数量 | 在 wheel 中？ |
|----------|------|------|----------------|
| Jinja2 HTML 模板 | `src/signalvault/web/templates/**/*.html` | 45 | ❌ 不会包含 |
| CSS | `src/signalvault/web/static/style.css` | 1 | ❌ 不会包含 |
| JS | `src/signalvault/web/static/app.js` | 1 | ❌ 不会包含 |
| SVG icon | `src/signalvault/web/static/signalvault-icon.svg` | 1 | ❌ 不会包含 |

**当前 wheel 构建不会包含任何非 `.py` 文件。** 安装后 `signalvault serve` 可以启动，但：

1. 所有 HTML 模板找不到 → 500 错误
2. 静态文件 404
3. 前端页面完全不可用

### 2.4 文件加载方式

所有模板和静态文件都通过 `Path(__file__).parent / ...` 相对路径加载：

- **Templates**: `web/routes.py` 使用 `FileSystemLoader(Path(__file__).parent / "templates")`
- **Static**: `api/app.py` 使用 `StaticFiles(directory=str(Path(__file__).parent.parent / "web" / "static"))`
- **Settings templates**: `web/routes.py` 使用 `Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"))`

在 wheel 中 `__file__` 指向 `site-packages/signalvault/web/routes.py`，所以相对路径 `parent / "templates"` → `site-packages/signalvault/web/templates/`。**路径逻辑本身是正确的，前提是这些文件被包含进 wheel。**

### 2.5 BASE_DIR 问题

`config.py:23`: `BASE_DIR = Path(__file__).resolve().parent.parent.parent`

在源码环境中这指向仓库根目录。在 wheel 安装后，`config.py` 在 `site-packages/signalvault/config.py`，`parent.parent.parent` 指向 Python 安装根目录（如 `/Library/Frameworks/Python.framework/...`）。

**影响范围**：`BASE_DIR` 仅在 `config_store.py:41-42` 中作为**遗留迁移回退路径**使用：
```python
from signalvault.config import BASE_DIR
candidate = BASE_DIR / "data" / "user_settings.json"
```
该路径仅在该文件实际存在时被读取。对于新安装用户，此路径不存在，代码路径不会触发。**对新安装无影响，是良性遗留。**

### 2.6 其他检查项

| 检查项 | 状态 |
|--------|------|
| `importlib.resources` 使用 | 未使用 |
| 依赖 Git 仓库 | 否 |
| `signalvault.__version__` | 通过 `importlib.metadata` 动态获取 ✅ |
| AppPaths 平台路径 | 已正确实现 macOS Application Support ✅ |
| CLI entry points | `[project.scripts] signalvault = "signalvault.cli:app"` ✅ |
| `__main__.py` | 存在，`from signalvault.cli import app; app()` ✅ |
| 动态 imports | 大量使用（延迟导入避免循环依赖），但都在包内 ✅ |
| Alembic 迁移 | 不使用 Alembic；使用 `Base.metadata.create_all()` + 手动 `ALTER TABLE` ✅ |

### 2.7 修复方案

在 `pyproject.toml` 中添加：

```toml
[tool.setuptools.package-data]
signalvault = [
    "web/templates/**/*.html",
    "web/static/*.css",
    "web/static/*.js",
    "web/static/*.svg",
]
```

或创建 `MANIFEST.in`：

```
graft src/signalvault/web/templates
graft src/signalvault/web/static
```

推荐同时配置两者，确保 sdist 和 wheel 都包含资源。

## 三、运行时依赖审计

### 3.1 核心依赖（必须随包提供）

| 依赖 | 用途 | 打包风险 |
|------|------|----------|
| `fastapi>=0.115` | Web 框架 | 纯 Python，无风险 |
| `uvicorn[standard]>=0.30` | ASGI server | 含 `uvloop`(C ext)、`httptools`(C ext)，需平台 wheel |
| `sqlalchemy>=2.0` | ORM + SQLite | 纯 Python（SQLite 驱动内置于 Python stdlib）✅ |
| `jinja2>=3.1` | 模板引擎 | 纯 Python ✅ |
| `typer>=0.12` | CLI 框架 | 纯 Python ✅ |
| `pydantic>=2.6` | 数据验证 | 含 `pydantic-core`(Rust)，需平台 wheel |
| `httpx>=0.27` | HTTP 客户端 | 纯 Python ✅ |
| `python-dotenv>=1.0` | .env 加载 | 纯 Python ✅ |
| `rich>=13.0` | 终端格式化 | 纯 Python ✅ |
| `python-multipart>=0.0.20` | 文件上传 | 纯 Python ✅ |
| `beautifulsoup4>=4.12` | HTML 解析 | 纯 Python ✅ |
| `lxml>=5.0` | XML/HTML 解析 | C 扩展，需平台 wheel |
| `pdfplumber>=0.11` | PDF 文本提取 | 纯 Python ✅ |
| `youtube-transcript-api>=0.6` | YouTube 字幕 | 纯 Python ✅ |
| `yt-dlp>=2024.0` | YouTube 元数据 | 纯 Python ✅ |
| `mcp>=1.0` | MCP Server | 纯 Python ✅ |
| `tomllib` | TOML 解析 | Python 3.11+ stdlib ✅ |

**带 C/Rust 扩展的依赖**：`uvicorn[standard]` (uvloop, httptools), `pydantic` (pydantic-core), `lxml`。这些需要在打包时确保平台的 pre-built wheel 可用。

### 3.2 可选集成（不打包，用户按需配置）

| 功能 | 依赖 | 策略 |
|------|------|------|
| Obsidian Vault | 外部 Obsidian 安装 | 不打包，用户自行安装 |
| ZSXQ 导入 | `signalvault zsxq ...` CLI | 打包，但需用户提供 ZSXQ cookie |
| OCR | 无内置 OCR | 不涉及 |
| 外部字幕工具 | yt-dlp 内置 | 已打包 |

### 3.3 开发/测试专用（不进入正式包）

| 依赖 | 说明 |
|------|------|
| `pytest>=8.0` | 测试框架 |
| `pytest-cov>=5.0` | 覆盖率 |
| `pytest-asyncio>=0.24` | 异步测试 |
| `playwright>=1.50` | 浏览器自动化测试 |
| `ruff==0.15.21` | Linter |
| `reportlab>=4.0` | PDF 生成（diagnostics 用） |

这些在 `[project.optional-dependencies] dev` 中，不会在 `pip install signalvault` 时安装。

### 3.4 Playwright 专项确认

| 问题 | 回答 |
|------|------|
| 普通用户是否需要 Playwright？ | **不需要。** Playwright 仅用于 UI smoke tests。 |
| `.app` 是否携带 Chromium？ | **不携带。** 用户不需要浏览器自动化。 |
| 文件夹选择器是否依赖浏览器？ | 不依赖。P3 已实现原生 OS 文件夹选择器（`/api/system/browse-folder`）。 |
| 外部命令缺失降级 | `yt-dlp` 网络错误已有 try/except 降级处理。 |

### 3.5 结论

- **正式包不含 dev dependencies**（通过 optional-dependencies 隔离）✅
- **正式包不含 Playwright/Chromium** ✅
- **核心运行时依赖均为纯 Python 或已有 pre-built wheel** ✅
- **uvicorn[standard] 的 uvloop/httptools 在 macOS arm64 有预编译 wheel** ✅

## 四、macOS Launcher 设计

### 4.1 生命周期

```
用户双击 SignalVault.app
    │
    ▼
┌─────────────────────────────────┐
│ 1. 确定 Application Support 路径 │  ← AppPaths.resolve()
│    ~/Library/Application         │
│    Support/SignalVault/          │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ 2. 建立 runtime/log 目录         │  ← AppPaths.ensure_dirs()
│    config/ data/ logs/ runtime/  │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ 3. 检测已有实例                  │  ← PID file + lock file
│    - 读 runtime/signalvault.pid  │
│    - 检查进程是否存活             │
│    - 存活 → 直接打开浏览器        │
│    - stale lock → 清理继续       │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ 4. 选择或确认端口                │
│    默认 8000，被占则 +1 递增     │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ 5. 启动 SignalVault 服务         │
│    uvicorn.run(app,              │
│      host="127.0.0.1",          │
│      port=<selected>)            │
│    写入 PID 文件                 │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ 6. 轮询 /api/health              │
│    最多等 10s，间隔 200ms        │
│    成功 → 下一步                 │
│    超时 → 弹错误对话框           │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ 7. 打开默认浏览器                 │
│    webbrowser.open(              │
│      f"http://127.0.0.1:{port}")│
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ 8. 保持服务进程运行               │
│    等待 uvicorn 进程或信号        │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ 9. 用户退出 (Cmd+Q / SIGTERM)   │
│    → 发送 SIGTERM 给 uvicorn    │
│    → 等待 graceful shutdown     │
│    → 清理 PID 文件               │
│    → 退出                        │
└─────────────────────────────────┘
```

### 4.2 多实例与端口策略

| 场景 | 行为 |
|------|------|
| 首次启动 | 创建 `runtime/signalvault.pid`，启动服务 |
| 重复双击（服务运行中） | 检测到已有 PID 且进程存活 → 直接 `webbrowser.open()`，不重复启动 |
| 重复双击（服务已停止） | PID 存在但进程不存在（stale lock） → 清理 PID 文件，重新启动 |
| 端口 8000 被占用 | 尝试 8001, 8002... 最多 10 次，写入实际端口到 `runtime/port.txt` |
| 服务启动失败 | 弹对话框报告错误，写入日志，退出 |
| 异常退出 | 下次启动时检测 stale PID → 自动清理 |

### 4.3 关键约束

- 绑定 `127.0.0.1`，**不暴露局域网**
- 不显示终端窗口（macOS `.app` 的 LSUIElement 或后台进程）
- PID 文件包含进程 ID 和端口号，JSON 格式
- 日志写入 `~/Library/Application Support/SignalVault/logs/launcher.log`

### 4.4 实现建议

Launcher 用纯 Python 脚本（约 200 行），不引入新依赖。打包时嵌入 `.app/Contents/Resources/`，由 `.app` 的入口点调用。

```
.app/Contents/
├── Info.plist
├── MacOS/
│   └── SignalVault        # 编译的启动器（或 shell wrapper）
├── Resources/
│   ├── signalvault.icns   # 应用图标
│   ├── launcher.py        # Python launcher 脚本
│   └── ...                # embedded Python + wheel
```

## 五、DB 与后台线程风险分析

### 5.1 当前 DB 初始化路径

```
FastAPI lifespan (create_app) → init_db()
    ├── init_engine()         # 全局单例，_engine is None 防护
    ├── Base.metadata.create_all()
    ├── _migrate_*_table()    # 9 个迁移函数
    └── _track_schema_version()

CLI 命令 → init_db()          # 直接调用（reports, channels 等）
```

### 5.2 识别风险

| 风险 | 严重度 | 详情 |
|------|--------|------|
| **`create_all` 非幂等调用** | 低 | `Base.metadata.create_all()` 内部有 `checkfirst` 逻辑，但调用方无锁保护。在多进程场景下可能竞态（SQLite busy）。单进程内 FastAPI lifespan 只运行一次。 |
| **lifespan 与 CLI 双重初始化** | 无 | CLI 命令和 `serve` 是互斥的入口，不会同时运行。 |
| **健康检查过早触发 DB** | 低 | `/api/health` 路由（health.py）不访问 DB，只返回 `{"status": "ok"}`。健康检查不会过早触发 DB。 |
| **后台 daemon 线程退出不可控** | **中** | 三个后台任务（analysis, knowledge_sync, channel_refresh）使用 `threading.Thread(daemon=True)`。daemon 线程在进程退出时被强制终止，可能导致：1) 未完成的 DB 写入 2) 日志截断。 |
| **daemon 线程无 join** | **中** | `job_service.py` 启动 daemon 线程后不保存引用，不调用 `join()`。uvicorn 关闭时这些线程被直接杀死。 |
| **SQLite 并发写** | 低 | 单个 uvicorn worker + daemon 线程共享同一个 `_engine`。SQLite 的 WAL 模式可处理读-写并发，但写-写并发仍会触发 "database is locked"。当前代码未启用 WAL。 |
| **固定 sleep 时序抖动** | 低 | C3 报告提到的"后台线程固定 sleep 时序抖动"影响测试可靠性，生产环境中 daemon 线程的 sleep 在 analysis 流程中用于轮询，时序偏差不影响正确性。 |

### 5.3 对 Launcher 的影响评估

| 影响 | 评估 |
|------|------|
| 多次初始化竞争 | **几乎不会发生。** Launcher 是单进程启动 uvicorn，lifespan 只触发一次。 |
| 健康检查安全 | ✅ 不访问 DB |
| `.app` 退出 | **有风险。** daemon 线程可能被 SIGTERM 杀死时正在写 DB。用户可能看到不完整的分析结果。 |
| 正常退出 | 用户通过 Web UI 发起的后台任务完成后自然结束；`Ctrl+C` / SIGTERM 会中断进行中的任务。 |

### 5.4 最小修复方案

**优先级排序**：

1. **P0 (M1 前必须)** — 启用 SQLite WAL 模式：
   ```python
   # session.py init_engine()
   _engine = create_engine(f"sqlite:///{path}", echo=False)
   with _engine.connect() as conn:
       conn.execute(text("PRAGMA journal_mode=WAL"))
       conn.commit()
   ```
   消除读-写冲突，提升并发安全。

2. **P1 (M2 前推荐)** — daemon 线程注册 + graceful shutdown：
   ```python
   # job_service.py
   _active_threads: list[threading.Thread] = []
   
   def start_background_job(target, *args):
       t = threading.Thread(target=target, args=args, daemon=True)
       _active_threads.append(t)
       t.start()
   
   def shutdown_background_jobs(timeout=5.0):
       for t in _active_threads:
           t.join(timeout=timeout)
       _active_threads.clear()
   ```
   在 FastAPI lifespan 的 shutdown 阶段等待后台线程完成。

3. **P2 (M3 前考虑)** — 使用 `signal` 处理 SIGTERM/SIGINT，确保 Launcher 主动关闭 uvicorn 时给 daemon 线程几秒缓冲时间。

4. **P3 (可延期)** — 重构后台任务为 `asyncio` 任务或 `concurrent.futures.ProcessPoolExecutor`，但这属于架构变更，不在打包范围内。

### 5.5 Sleep vs 事件

当前后台线程使用 `time.sleep()` 轮询 LLM 完成状态。这是长轮询模式，**不是竞态条件**。不要通过增加 sleep 来"修复"问题——正确的路径是保持当前轮询逻辑，但在 shutdown 时通过 Event/flag 通知线程提前退出。

## 六、打包方案比较

### 6.1 方案矩阵

| 维度 | py2app | Briefcase | PyInstaller | 自定义 Bundle (Launcher + wheel) |
|------|--------|-----------|-------------|----------------------------------|
| **Apple Silicon** | ✅ native | ✅ native | ✅ native | ✅ native |
| **Python 3.12** | ✅ | ✅ | ✅ | ✅ |
| **FastAPI/Uvicorn** | ⚠️ 需手动 include C ext | ✅ 自动 | ✅ 自动 | ✅ wheel 安装 |
| **Jinja2/Static** | ⚠️ 需配置 data_files | ✅ 自动 | ⚠️ 需 `--add-data` | ✅ 修复后 wheel 自带 |
| **SQLAlchemy** | ✅ | ✅ | ✅ | ✅ |
| **启动速度（冷）** | 1-3s | 2-5s (有 splash) | 3-10s (解压) | 1-2s ✅ |
| **包体积** | ~80 MB | ~100 MB | ~90 MB | ~60 MB (embedded) |
| **调试能力** | ⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐ (标准 Python) |
| **代码签名** | ✅ 标准 .app | ✅ 标准 .app | ⚠️ 需额外工作 | ✅ 标准 .app |
| **Notarization** | ✅ | ✅ | ⚠️ 困难 | ✅ |
| **自动更新** | 需自建 | Briefcase 内置 | 需自建 | 需自建 |
| **维护成本** | 中 | 低 | 高 | 中 |
| **社区活跃度** | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | N/A |
| **项目适配复杂度** | 低-中 | 低 | 高 | 中 |
| **macOS 原生体验** | ✅✅ | ✅✅ | ✅ | ✅✅ |
| **数据目录继承** | ✅ AppPaths 自动 | ✅ AppPaths 自动 | ⚠️ 路径可能错乱 | ✅ AppPaths 自动 |

### 6.2 rc1 推荐方案：Launcher + wheel + Briefcase

**推荐 Briefcase (BeeWare)** 作为 rc1 打包方案。

**理由**：

1. **最低概念侵入**：Briefcase 通过 `pyproject.toml` 声明式配置，不改业务代码
2. **标准 `.app` 输出**：生成标准 macOS `.app` bundle，代码签名和 notarization 路径成熟
3. **Python 生态原生**：基于 pip + venv，wheel 正常安装，importlib 路径不变
4. **AppPaths 兼容**：Briefcase 的 `.app` 内 Python 的 `sys.executable` 和 `__file__` 路径保持标准，AppPaths 平台检测（`sys.platform == "darwin"`）正常运作
5. **模板/静态文件自动包含**：配置 `package_data` 后，Briefcase 尊重 setuptools 配置
6. **开发模式支持**：`briefcase dev` 可直接跑源码，调试便利
7. **社区维护**：Briefcase 是 BeeWare 项目的一部分，有专职团队维护

**不推荐 PyInstaller 的原因**：
- 将 Python 脚本编译进单个可执行文件，`__file__` 路径和 `Path(__file__).parent` 语义会变
- `sys._MEIPASS` 临时目录对 AppPaths 和模板加载不友好
- Notarization 困难：签名需覆盖内部所有二进制，PyInstaller 的单文件模式不适用
- 调试困难：报错栈追踪不直观

**不推荐 py2app 的原因**：
- 社区活跃度低于 Briefcase
- 对 pydantic-core (Rust)、uvloop (C) 的处理不如 Briefcase 稳定
- 文档和 macOS 版本更新节奏较慢

### 6.3 方案架构

```
SignalVault.app/
├── Contents/
│   ├── Info.plist
│   ├── MacOS/
│   │   └── SignalVault          # Briefcase 生成的 stub
│   ├── Resources/
│   │   ├── signalvault.icns
│   │   └── ... (Python runtime)
│   └── app/
│       ├── app_packages/        # pip install 的依赖
│       │   ├── signalvault/     # 我们的包（含 templates, static）
│       │   ├── fastapi/
│       │   ├── uvicorn/
│       │   └── ...
│       └── signalvault/         # 应用入口
│           └── __main__.py
```

用户数据独立存放在：
```
~/Library/Application Support/SignalVault/
├── config/
│   └── config.toml
├── data/
│   └── signalvault.db
├── logs/
│   └── signalvault.log
├── runtime/
│   └── signalvault.pid
└── cache/
```

## 七、结论

### 7.1 wheel 可行性

**可行，但需要修复 package_data 配置。** 当前 `pyproject.toml` 缺少非 Python 资源的声明，导致 HTML 模板和静态文件不会被打包。修复后 wheel 可完整包含所有运行资源。

### 7.2 关键发现汇总

| # | 发现 | 严重度 | 修复时机 |
|---|------|--------|----------|
| 1 | 缺少 `[tool.setuptools.package-data]` — 模板/静态不进 wheel | **P0** | M1 前 |
| 2 | `BASE_DIR` 在 wheel 中指向错误位置（仅用于遗留迁移） | 信息 | 不阻塞 |
| 3 | Playwright 不会进入正式包 | ✅ | 无需操作 |
| 4 | 健康检查不访问 DB | ✅ | 无需操作 |
| 5 | Daemon 线程无 graceful shutdown | **P1** | M2 前 |
| 6 | SQLite 未启用 WAL 模式 | **P1** | M1 |
| 7 | AppPaths 平台路径在 wheel 中正确 | ✅ | 无需操作 |
| 8 | CLI entry points 配置正确 | ✅ | 无需操作 |
| 9 | `signalvault.__version__` 通过 importlib.metadata | ✅ | 无需操作 |

### 7.3 可进入 M1 的判断

**可以进入 M1**（wheel 构建验证），前提是：
1. 先修复 `pyproject.toml` 的 package_data
2. M1 在干净 venv 中验证完整启动链路

### 7.4 不应立即做的事情（M0 禁止项确认）

- ❌ 不制作完整 `.app`
- ❌ 不加 py2app/PyInstaller/Briefcase 配置
- ❌ 不修改业务功能、向导、设置中心
- ❌ 不加 Keychain / 自动更新 / 代码签名 / notarization / DMG
- ❌ 不通过 sleep 掩盖竞态
