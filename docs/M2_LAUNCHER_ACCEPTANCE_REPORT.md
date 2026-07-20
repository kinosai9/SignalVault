# M2 Launcher Core Lifecycle & Graceful Shutdown Acceptance Report

> 日期：2026-07-20
> 基线：eff10b6 (M1) → M2 implementation
> 阶段：M2 — Launcher 核心生命周期与优雅退出

## 一、M1 基线修正

M1 验收结论已修正为：**"M1 专项与 clean-room 门禁通过；仓库级仍有既有测试失败，未发现 M1 新增回归。"**

既有失败测试（5 个）：

| # | 完整名称 | 失败原因 | 稳定性 | 归属 |
|---|---------|---------|--------|------|
| 1 | `tests/test_c2c_settings_center.py::TestMainNav::test_main_nav_has_settings_link` | C3 onboarding guard 重定向 | 稳定 | C3 存量 |
| 2 | `tests/test_sources_channels.py::TestDashboardIntegration::test_dashboard_shows_sources_link` | C3 onboarding guard 重定向 | 稳定 | C3 存量 |
| 3 | (偶发 flaky) | 未在重跑中复现 | 不稳定 | 待观察 |
| 4 | `tests/test_ui_smoke.py::test_channels_page_loads` | channels 页面加载 | 稳定 | UI smoke 存量 |
| 5 | `tests/test_ui_smoke.py::test_channels_page_css_loaded` | channels CSS 检查 | 稳定 | UI smoke 存量 |

HTML 模板：源目录 46 个，wheel 46 个，一致。

## 二、Launcher 架构

### 模块

`src/signalvault/launcher.py` — 约 430 行，纯生命周期编排，不实现业务逻辑。

### 数据结构

```
LauncherConfig(host, preferred_port, max_port_attempts, health_timeout, 
               health_interval, open_browser)
  - host 强制 127.0.0.1（__post_init__ 覆盖任何非 localhost 值）

InstanceRecord(pid, host, port, started_at, instance_id)
  - JSON 序列化到 PID 文件
```

### 注入点

所有 I/O 操作通过模块级可注入函数调用，测试不依赖 monkey-patching：

- `_pid_file_path()` → PID 文件路径
- `_process_exists(pid)` → OS 进程检查
- `_port_in_use(host, port)` → socket 端口探测
- `_health_check(host, port, timeout)` → HTTP health 请求
- `_open_browser(url)` → webbrowser.open
- `_now_iso()` → UTC 时间戳
- `_sleep(seconds)` → 轮询间隔

## 三、PID 文件

位置：`<AppPaths.runtime_dir>/signalvault.pid`

格式：
```json
{
  "pid": 12345,
  "host": "127.0.0.1",
  "port": 8000,
  "started_at": "2026-07-20T12:00:00Z",
  "instance_id": "uuid"
}
```

写入采用 write-then-rename 原子操作。不包含：API Key、config 内容、SecretStore 内容、Vault 文档内容。

## 四、实例检测

`detect_existing_instance(pid_path)` 四步验证：

1. PID 文件可解析（损坏 JSON → None）
2. PID 进程存在（`os.kill(pid, 0)`）
3. Health endpoint 可达（HTTP 200）
4. Health 返回 `app=signalvault`（identity 验证）

行为表：

| 场景 | 行为 |
|------|------|
| 无 PID 文件 | 正常启动 |
| PID 文件损坏 | 删除（log warning），正常启动 |
| PID 进程不存在 | 删除 stale 文件，正常启动 |
| PID 存活但 health 失败 | 记录冲突（log warning），不杀进程 |
| PID 存活 + health 正常 + 身份正确 | 复用已有实例，打开浏览器 |

## 五、端口策略

1. 先检测已有实例
2. 已有实例有效 → 不复用端口选择
3. 无有效实例 → 从 `preferred_port` 开始递增
4. 最多尝试 `max_port_attempts`(10)
5. 全部占用 → 退出码 1

端口选择与 bind 之间保留竞态容错（启动失败重试下一个端口）。

## 六、Health Identity

`GET /api/health` 增强为返回 `version` 字段：

```json
{"status": "ok", "app": "signalvault", "version": "0.1.0", "database": "ok"}
```

Launcher 验证：HTTP 200 + `status=ok` + `app=signalvault`。

健康轮询：默认 15s 超时，200ms 间隔（可配置），不使用固定长 sleep。

## 七、Uvicorn 生命周期

采用**同进程受控方案**：

```python
class _UvicornRunner:
    def __init__(self, host, port):
        app = create_app()
        self._server = uvicorn.Server(uvicorn.Config(app, host=host, port=port))
    
    def start_in_thread(self)   # daemon 线程启动
    def request_shutdown(self)   # 设置 should_exit
    def wait(self, timeout)      # join 线程
```

优势：
- 无子进程管理
- 无孤儿进程
- 信号在同一进程内传播
- PID 文件与进程 PID 一致

## 八、浏览器行为

- 健康检查通过后调用 `webbrowser.open(url)`
- `--no-browser` 不打开浏览器
- 浏览器打开失败不终止服务，打印手动访问 URL
- 重复启动已有实例时重新打开浏览器
- 浏览器关闭不停止服务

## 九、后台线程 Shutdown

在 `job_service.py` 中新增：

```python
_shutdown_event = threading.Event()
_active_threads: list[threading.Thread] = []

def is_shutdown_requested() -> bool
def shutdown_background_jobs(timeout=5.0) -> None
def _register_thread(t) -> None
```

三个后台任务创建点（analysis, sync, channel_refresh）均已加入 `_register_thread(t)`。

FastAPI lifespan shutdown 阶段调用 `shutdown_background_jobs(timeout=5.0)`。

Launcher 退出路径也调用 `_shutdown_background_tasks()`。

约束：
- 不修改业务逻辑
- 不重构为 asyncio
- 不通过 sleep 掩盖问题
- 线程未完成时记录 WARNING 日志

## 十、信号处理

支持 `SIGINT` 和 `SIGTERM`：

```
收到信号
→ 设置 shutdown_requested
→ runner.request_shutdown()
→ 退出 keep-alive 循环
→ _shutdown_background_tasks()
→ runner.wait(timeout=10.0)
→ finally: _remove_pid_file()
```

PID 文件清理在 `finally` 中，异常启动失败也会清理本次创建的 PID。

## 十一、日志

Launcher 日志：`<AppPaths.log_dir>/launcher.log`

记录内容：启动时间、版本、已有实例检测、端口选择、健康检查结果、浏览器打开、信号接收、后台 shutdown、退出码、异常。

不记录：API Key、config.toml 内容、SecretStore 内容、Vault 文档内容。

## 十二、新增测试

`tests/test_launcher.py` — 35 个测试，通过依赖注入覆盖：

| 测试类别 | 测试数 | 场景 |
|---------|--------|------|
| LauncherConfig | 4 | 默认 localhost, 拒绝非 localhost, 自定义端口, no-browser |
| 端口选择 | 3 | 首选可用, 占用递增, 无可用端口 |
| PID 文件 I/O | 6 | 读写往返, 不存在, 空文件, 损坏 JSON, 删除不存在, 删除存在 |
| 实例检测 | 6 | 无 PID, stale, health 失败, 错误 app, 有效实例, 复用打开浏览器 |
| Health 轮询 | 3 | 首次成功, 超时, 错误身份 |
| 启动失败 | 1 | health 超时返回 1 + PID 清理 |
| 浏览器行为 | 1 | --no-browser 不调用 webbrowser |
| 信号处理 | 2 | 线程正常退出 + PID cleanup, 异常崩溃 + PID cleanup |
| 日志安全 | 2 | InstanceRecord 无敏感字段, PID 文件无 secret |
| 后台 shutdown | 2 | event 注册, 状态重置 |
| 重复启动 | 1 | 二启复用已有实例 |
| 非 localhost | 1 | 配置强制 127.0.0.1 |
| InstanceRecord | 3 | 往返序列化, 无效 JSON, 缺失字段 |

测试特征：
- 无真实 sleep（`_sleep` 注入为 no-op）
- 无真实 socket（`_port_in_use` 注入）
- 无真实 HTTP（`_health_check` 注入）
- 无真实浏览器（`_open_browser` 注入）
- 无真实进程 kill（`_process_exists` 注入）

## 十三、全量门禁

### ruff

```
All checks passed.
```

### 关键测试组

```
tests/test_api_health.py:     1 passed
tests/test_launcher.py:      35 passed
tests/test_packaging.py:     23 passed
Total (key groups):          59 passed, 0 failed
```

### 全量测试（不含 UI smoke）

```
2452 passed, 2 failed, 1 skipped, 785 warnings (17m 22s)
```

**2 个失败均为存量 C3 onboarding guard 问题**：

| # | 完整名称 | 归属 |
|---|---------|------|
| 1 | `tests/test_c2c_settings_center.py::TestMainNav::test_main_nav_has_settings_link` | C3 存量 |
| 2 | `tests/test_sources_channels.py::TestDashboardIntegration::test_dashboard_shows_sources_link` | C3 存量 |

**M2 新增回归：0 个。**

测试数量变化：M1 2420 → M2 2455 (+35 launcher tests)

### UI smoke

```
9 passed, 2 failed
```

2 个失败均为存量 channels 页面问题，非 M2 引入。

## 十四、macOS 实机验证

**当前环境为 Windows (Python 3.14)，macOS 验证待执行。**

计划验证清单：

- [ ] clean wheel install on macOS
- [ ] `signalvault launch` → 浏览器自动打开
- [ ] 首次 onboarding
- [ ] 第二次 `signalvault launch` → 只打开已有实例
- [ ] 端口 8000 占用后使用 8001
- [ ] 终止进程后 stale PID 自动恢复
- [ ] Cmd+C / SIGTERM 正常退出
- [ ] 数据路径：`~/Library/Application Support/SignalVault/`
- [ ] 日志路径：`~/Library/Application Support/SignalVault/logs/launcher.log`

## 十五、已知限制

1. **macOS 实机未执行** — 当前为 Windows 开发环境，macOS 上需独立验证
2. **Ctrl+C 在 Windows 终端的信号传播** — uvicorn daemon 线程中的 SIGINT 传播有待在 Windows 上进一步测试
3. **后台线程 shutdown_event 的检查点** — 当前后台线程在 LLM/网络调用期间为阻塞式，退出信号只能在线程循环边界被检查。shutdown 最多等 5s，超时后记录 WARNING 但不阻塞退出
4. **webbrowser.open 在无 GUI 环境的行为** — macOS .app 启动时默认有 GUI，纯 SSH 环境会失败（记录日志并打印手动 URL）

## 十六、M3 进入条件

| 条件 | 状态 |
|------|------|
| Launcher 核心生命周期实现 | ✅ |
| launch CLI 命令可用 | ✅ |
| 实例检测（PID + health + identity） | ✅ |
| 端口选择 + 递增 | ✅ |
| Health 检查返回 version | ✅ |
| Uvicorn 同进程受控 | ✅ |
| 浏览器行为（open / no-browser / fail-safe） | ✅ |
| 后台线程 gracefule shutdown | ✅ |
| SIGINT / SIGTERM 信号处理 | ✅ |
| PID finally 清理 | ✅ |
| Launcher 日志不泄露 secret | ✅ |
| 35 launcher 测试通过 | ✅ |
| ruff 通过 | ✅ |
| macOS 实机验证 | ⏳ (Windows 环境，待执行) |

**macOS 实机验证完成后即可进入 M3 Briefcase spike。**
