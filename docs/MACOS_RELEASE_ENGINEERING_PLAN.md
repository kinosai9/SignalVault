# SignalVault macOS Release Engineering Plan

> 基线：M0 打包审计 (`docs/MACOS_PACKAGING_AUDIT.md`)
> 日期：2026-07-20
> 目标：从源码仓库到可分发的 macOS `.app`，分 M1–M4 四个阶段交付

## 一、阶段总览

```
M0 ✅  打包预审（本文档的前置）
│
├── M1    wheel / sdist 构建验证
│        clean-room 安装 + 启动 + onboarding + 配置持久化
│        预计：1-2 个 session
│
├── M2    macOS Launcher
│        双击 → 启动服务 → 打开浏览器 → 防重复 → 正常退出
│        预计：2-3 个 session
│
├── M3    .app Bundle
│        Briefcase 配置 → runtime 嵌入 → wheel → launcher → icon
│        预计：2-3 个 session
│
└── M4    分发工程
│        签名 → notarization → DMG → 安装/卸载说明
│        预计：2-3 个 session (实际执行需 Apple Developer 账号)
```

## 二、M1：wheel / sdist 构建验证

### 目标

```text
python -m build
→ 创建干净 venv
→ pip install dist/signalvault-0.1.0-py3-none-any.whl
→ signalvault serve
→ 浏览器访问 http://127.0.0.1:8000
→ 完成 onboarding 向导
→ 配置持久化到 ~/Library/Application Support/SignalVault/config/config.toml
→ 重启服务验证配置保留
```

### 文件级实施计划

#### Step 1: 修复 pyproject.toml (package_data)

**文件**: `pyproject.toml`

添加：
```toml
[tool.setuptools.package-data]
signalvault = [
    "web/templates/**/*.html",
    "web/static/*.css",
    "web/static/*.js",
    "web/static/*.svg",
]
```

#### Step 2: 创建 MANIFEST.in

**文件**: `MANIFEST.in` (新建)

```
graft src/signalvault/web/templates
graft src/signalvault/web/static
include LICENSE
include README.md
```

#### Step 3: 本地构建验证

```bash
python -m pip install build
python -m build
# 验证 .whl 内容
python -m zipfile -l dist/signalvault-0.1.0-py3-none-any.whl | grep -E "\.(html|css|js|svg)$"
```

#### Step 4: clean-room 验证

```bash
# 创建临时 venv
python3.12 -m venv /tmp/sv-test
source /tmp/sv-test/bin/activate
pip install dist/signalvault-0.1.0-py3-none-any.whl

# 验证 CLI
signalvault --help

# 启动服务（使用临时 SIGNALVAULT_HOME）
SIGNALVAULT_HOME=/tmp/sv-data signalvault serve --port 8765

# 验证：
# 1. 浏览器打开 http://127.0.0.1:8765
# 2. 走完 onboarding 向导
# 3. 检查 ~/tmp/sv-data/config/config.toml 已创建
# 4. 检查 ~/tmp/sv-data/data/signalvault.db 已创建
# 5. 重启服务验证配置持久化
```

#### Step 5: SDK 列表导出

```bash
# 确认 wheel 只包含必要文件
python -m zipfile -l dist/signalvault-0.1.0-py3-none-any.whl > docs/m1-wheel-contents.txt
```

### M1 验收标准

- [ ] `python -m build` 成功，生成 `.whl` 和 `.tar.gz`
- [ ] wheel 包含所有 45 个 HTML 模板
- [ ] wheel 包含 3 个静态文件
- [ ] clean venv 中 `signalvault serve` 启动成功
- [ ] 前端页面正常渲染（非空白页）
- [ ] Onboarding 向导可完成
- [ ] 配置写入 `config.toml` 并在重启后保留
- [ ] `signalvault --version` 或 `__version__` 正确输出
- [ ] 现有 2408 tests 全部通过

### M1 不做的

- 不修改业务代码
- 不修改 Launcher
- 不修改 .app bundle
- 不处理代码签名

## 三、M2：macOS Launcher

### 目标

实现最小可用 Launcher：双击 → 启动服务 → 打开浏览器。

### 文件级实施计划

#### Step 1: 创建 Launcher 模块

**文件**: `src/signalvault/launcher.py` (新建，约 200 行)

核心函数：
```python
def find_free_port(start=8000, max_attempts=10) -> int: ...
def check_existing_instance(pid_file: Path) -> int | None: ...  # 返回端口或 None
def write_pid_file(pid_file: Path, port: int) -> None: ...
def cleanup_pid_file(pid_file: Path) -> None: ...
def wait_for_health(url: str, timeout=10.0) -> bool: ...
def open_browser(url: str) -> None: ...
def launch() -> int: ...  # 主入口，返回 exit code
```

#### Step 2: PID 文件格式

```json
{
  "pid": 12345,
  "port": 8000,
  "started_at": "2026-07-20T12:00:00",
  "host": "127.0.0.1"
}
```

位置：`<AppPaths.runtime_dir>/signalvault.pid`

#### Step 3: 创建 CLI 入口

在 `cli.py` 添加 `launch` 命令：
```python
@app.command("launch")
def launch(
    port: int = typer.Option(8000, "--port"),
    no_browser: bool = typer.Option(False, "--no-browser"),
):
    """启动 SignalVault 服务并打开浏览器（桌面启动模式）。"""
    from signalvault.launcher import launch as do_launch
    raise typer.Exit(do_launch())
```

#### Step 4: 新增测试

**文件**: `tests/test_launcher.py` (新建)

测试用例：
- `test_find_free_port` — 端口分配逻辑
- `test_pid_file_lifecycle` — 写入/读取/清理
- `test_stale_pid_cleanup` — 失效 PID 自动清理
- `test_existing_instance_detection` — 检测已有实例
- `test_health_check_timeout` — 健康检查超时

#### Step 5: shell wrapper（macOS 双击用）

**文件**: `scripts/signalvault.sh` (新建)

```bash
#!/bin/bash
# SignalVault Launcher wrapper — 不显示终端窗口
# 用于 .app/Contents/MacOS/ 入口
cd "$(dirname "$0")/.."
./Resources/python/bin/python3 -m signalvault launch "$@"
```

### 架构约束确认

- [ ] 绑定 `127.0.0.1`（不暴露局域网）
- [ ] 不显示终端窗口
- [ ] webbrowser.open 打开默认浏览器
- [ ] 重复双击不创建第二个服务实例
- [ ] Stale PID 自动清理
- [ ] 端口占用自动递增
- [ ] 服务启动失败时友好提示

### M2 验收标准

- [ ] 单终端启动 `signalvault launch` → 服务启动 → 浏览器自动打开
- [ ] 重复执行 `signalvault launch` → 检测已有实例 → 打开浏览器（不重复启动）
- [ ] 杀掉服务进程后重新 `launch` → 自动清理 stale PID → 正常启动
- [ ] 默认端口被占用 → 自动使用 8001
- [ ] 所有 Launcher 测试通过
- [ ] 现有 2408 tests 仍然通过

## 四、M3：.app Bundle

### 目标

用 Briefcase 生成标准 macOS `.app`，包含 Python runtime、wheel、launcher、icon。

### 文件级实施计划

#### Step 1: 添加 Briefcase 配置

**文件**: `pyproject.toml` (追加)

```toml
[tool.briefcase]
project_name = "SignalVault"
bundle = "com.kino.signalvault"
version = "0.1.0"
url = "https://github.com/kinosai9/signalvault"
license = "MIT"
author = "Kinosai9"

[tool.briefcase.app.signalvault]
formal_name = "SignalVault"
description = "SignalVault — 多源投资研究助手"
icon = "src/signalvault/web/static/signalvault-icon"
sources = ["src/signalvault"]
requires = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlalchemy>=2.0",
    "jinja2>=3.1",
    "typer>=0.12",
    "pydantic>=2.6",
    "httpx>=0.27",
    "python-dotenv>=1.0",
    "rich>=13.0",
    "python-multipart>=0.0.20",
    "beautifulsoup4>=4.12",
    "lxml>=5.0",
    "pdfplumber>=0.11",
    "youtube-transcript-api>=0.6",
    "yt-dlp>=2024.0",
    "mcp>=1.0",
]

[tool.briefcase.app.signalvault.macOS]
# 后台执行，不显示 Dock 图标（可选）
# requires = ["LSUIElement=true"]
```

#### Step 2: 创建 Briefcase 入口模块

**文件**: `src/signalvault/app.py` (新建)

```python
"""Briefcase app entry point."""
import sys
from signalvault.launcher import launch

def main():
    sys.exit(launch())
```

#### Step 3: 准备 App Icon

```bash
# 从 SVG 生成 .icns
# 需要 iconutil (macOS 内置) 或在线转换服务
# 中间步骤：SVG → 1024x1024 PNG → .iconset → .icns
mkdir -p resources/signalvault.iconset
# ... 生成各种尺寸的 PNG
iconutil -c icns resources/signalvault.iconset -o src/signalvault/web/static/signalvault.icns
```

#### Step 4: Briefcase 构建

```bash
pip install briefcase
briefcase create     # 创建 .app 脚手架
briefcase build      # 编译/安装依赖
briefcase run        # 运行验证
briefcase package    # 生成可分发的 .app
```

#### Step 5: Clean-room 验证

```bash
# 在另一台干净的 macOS 上
# 1. 解压/复制 SignalVault.app 到 /Applications
# 2. 双击启动
# 3. 验证 onboarding 流程
# 4. 检查数据目录创建：~/Library/Application Support/SignalVault/
# 5. 退出再重新打开，验证配置持久化
# 6. 验证不依赖源码仓库
```

### M3 验收标准

- [ ] `briefcase create && briefcase build` 成功
- [ ] 生成的 `.app` 可双击启动
- [ ] 浏览器自动打开
- [ ] 静态文件加载正常（CSS/JS 无 404）
- [ ] 模板渲染正常
- [ ] Onboarding 完整走通
- [ ] 数据写入 `~/Library/Application Support/SignalVault/`
- [ ] 脱离源码仓库可运行
- [ ] 不依赖 `pip install -e .` 的开发模式

## 五、M4：分发工程

### 目标

对 `.app` 签名和公证，制作 DMG，提供安装说明。

### 依赖条件

- Apple Developer Program 会员（$99/年）
- Developer ID Application 证书
- App-specific password 或 API key（用于 notarization）

### 文件级实施计划

#### Step 1: 代码签名

```bash
# 签名所有二进制和 .dylib
codesign --deep --force --verify --verbose \
  --sign "Developer ID Application: Kino (XXXXXXXXXX)" \
  --options runtime \
  SignalVault.app

# 验证签名
codesign --verify --verbose SignalVault.app
```

#### Step 2: Notarization

```bash
# 创建 ZIP 提交公证
ditto -c -k --keepParent SignalVault.app SignalVault.zip
xcrun notarytool submit SignalVault.zip \
  --apple-id "xxx@xxx.com" \
  --team-id "XXXXXXXXXX" \
  --password "@keychain:AC_PASSWORD" \
  --wait

# 装订票据
xcrun stapler staple SignalVault.app
```

#### Step 3: DMG 制作

```bash
# 创建 DMG
hdiutil create -volname "SignalVault" \
  -srcfolder SignalVault.app \
  -ov -format UDZO \
  SignalVault-0.1.0.dmg

# 签名 DMG
codesign --sign "Developer ID Application: Kino (XXXXXXXXXX)" \
  SignalVault-0.1.0.dmg
```

#### Step 4: 文档

**文件**: `docs/INSTALLATION.md` (新建)

内容：
- 系统要求（macOS 13+, Apple Silicon/Intel）
- 安装步骤（下载 DMG → 拖到 Applications → 双击启动）
- 首次启动引导（onboarding 向导会自动打开）
- 数据位置（`~/Library/Application Support/SignalVault/`）
- 卸载步骤（删除 .app + 删除 Application Support 目录）
- 已知问题

**文件**: `docs/UPGRADE.md` (新建)

内容：
- 版本升级步骤
- 配置文件兼容性
- 数据库迁移说明

### M4 验收标准

- [ ] `.app` 签名验证通过
- [ ] Notarization 成功
- [ ] DMG 可正常挂载和安装
- [ ] `INSTALLATION.md` 覆盖安装和卸载
- [ ] `UPGRADE.md` 覆盖版本升级

## 六、RC Blocker 列表

| # | 描述 | 阶段 | 阻塞 |
|---|------|------|------|
| B1 | package_data 未配置 — 模板/静态不进 wheel | M1 | **M1** |
| B2 | 未在 clean venv 验证过完整启动 | M1 | **M1** |
| B3 | Launcher 不存在 | M2 | **M2** |
| B4 | 无 PID/lock 防重复实例 | M2 | **M2** |
| B5 | Daemon 线程 graceful shutdown | M2 | M2（建议） |
| B6 | SQLite WAL 未启用 | M1 | M1（建议） |
| B7 | 无 App Icon (.icns) | M3 | **M3** |
| B8 | Briefcase 配置未创建 | M3 | **M3** |
| B9 | 无 Apple Developer 账号 | M4 | **M4** |
| B10 | 未在干净 macOS 上验证过 | M3 | M3（建议） |

**标记为粗体的为必须解决才能进入该阶段。**

## 七、可延期到 rc2+ 的项目

| 项目 | 原因 |
|------|------|
| 自动更新 (Sparkle) | 需要额外基础设施，M4 可做 DMG 手动更新 |
| Keychain 集成 | SecretStore 已用文件系统加密，可用但不完美 |
| Lua/插件系统 | 不在此版本范围内 |
| 多语言支持 | 当前仅中文 |
| macOS 菜单栏图标 | Nice-to-have |
| 崩溃报告收集 | 需后端服务 |
| DMG 背景图/EULA | 体验优化 |
| 后台任务改为 asyncio | 架构变更，不在打包范围 |

## 八、文件清单（M1–M4 涉及的所有文件）

### 新建文件

| 文件 | 阶段 | 目的 |
|------|------|------|
| `MANIFEST.in` | M1 | sdist 包含非 Python 资源 |
| `src/signalvault/launcher.py` | M2 | macOS Launcher 核心逻辑 |
| `src/signalvault/app.py` | M3 | Briefcase 入口点 |
| `scripts/signalvault.sh` | M2 | Shell wrapper（不显示终端） |
| `resources/signalvault.icns` | M3 | 应用图标 |
| `tests/test_launcher.py` | M2 | Launcher 单元测试 |
| `docs/INSTALLATION.md` | M4 | 安装文档 |
| `docs/UPGRADE.md` | M4 | 升级文档 |

### 修改文件

| 文件 | 阶段 | 变更内容 |
|------|------|----------|
| `pyproject.toml` | M1 | 添加 `[tool.setuptools.package-data]` |
| `pyproject.toml` | M3 | 添加 `[tool.briefcase]` 配置 |
| `src/signalvault/cli.py` | M2 | 添加 `launch` 命令 |
| `src/signalvault/db/session.py` | M1 | 启用 SQLite WAL 模式 |
| `src/signalvault/services/job_service.py` | M2 | daemon 线程注册 + shutdown hook |
| `src/signalvault/api/app.py` | M2 | lifespan shutdown 等待后台线程 |

### 不变文件

所有业务逻辑、向导流程、设置中心、路由、模板内容均不修改。

## 九、M1 启动前检查清单

- [x] M0 审计完成，输出 `MACOS_PACKAGING_AUDIT.md`
- [ ] 阅读并确认本计划
- [ ] `git status` 干净
- [ ] 2408 tests 全部通过
- [ ] ruff check 通过
- [ ] 确认不修改业务代码

## 十、风险登记

| 风险 | 可能性 | 影响 | 缓解 |
|------|--------|------|------|
| uvicorn C 扩展在 Briefcase 中编译/链接失败 | 中 | 服务无法启动 | 回退到纯 Python uvicorn（去掉 `[standard]`） |
| Briefcase 与 setuptools package_data 不兼容 | 低 | 模板丢失 | 手动配置 Briefcase `data_files` |
| Apple notarization 因嵌入式 Python 被拒 | 中 | 无法分发 | 使用 Briefcase 的 notarization 支持，或切换到纯 Python uvicorn |
| Launcher 在 macOS 不同版本表现不一致 | 低 | 体验问题 | 扩展测试矩阵 |
| SQLite 并发写入问题在用户场景触发 | 低 | 数据丢失 | M1 启用 WAL，M2 加 graceful shutdown |
