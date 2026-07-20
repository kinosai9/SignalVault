# M2-W Windows Launcher 用户体验 QA 报告

> 日期：2026-07-20
>
> 平台：Microsoft Windows 10.0.26200.8875 / Python 3.14
>
> 结论：**Windows 平台无关行为 QA 未通过 M3-A 门禁；本报告不是 macOS 实机验收。**

## 1. 测试环境

- 仓库：`D:\claude\xyz_analysis`
- 最终有效隔离根目录：系统临时目录下的独立 `SIGNALVAULT_HOME`
- AI：`LLM_PROVIDER=mock`
- Vault：独立临时目录；未初始化、未写入
- `.env`：最终有效测试显式设置 `PYTHON_DOTENV_DISABLED=1`
- 浏览器：Playwright 1.61 + Chromium headless
- 视口：1440×900、1366×768、390×844
- 测试运行时：依据 `uv.lock` 创建在临时目录的 Python 3.14 虚拟环境

隔离审计发现首轮 `uv --project` 会把工作目录切回仓库，使 `python-dotenv` 读取仓库 `.env`。该轮证据已全部作废；没有执行 Vault 初始化或写入。随后新建全新 home，禁用 dotenv，并显式使用临时 Vault 重跑完整旅程。最终配置文件只包含 onboarding 状态，不包含 Vault 路径或 API Key。

Playwright CLI 的 `npx` 入口存在但 npm 安装损坏（缺少 `npx-cli.js`），因此按项目既有 UI smoke 技术栈改用 Python Playwright。第一次浏览器启动受沙箱 `spawn EPERM` 阻止，授权启动隔离无头 Chromium 后完成验证。

## 2. 首次启动

结果：**核心启动通过，终端反馈已改善。**

| 项目 | 结果 |
|---|---|
| 命令 | 隔离环境执行 `python -m signalvault launch --no-browser`；另单独执行默认浏览器打开验证 |
| 启动反馈 | 显示“正在启动”、日志位置、启动成功、访问地址、Ctrl+C/关闭浏览器说明 |
| 最终端口 | 8000 |
| PID 文件 | `<SIGNALVAULT_HOME>/runtime/signalvault.pid`，字段完整，端口为 8000 |
| health | `status=ok, app=signalvault, version=0.1.0, database=ok` |
| 自动打开地址 | `http://127.0.0.1:8000`；日志记录 `Browser opened at` |
| onboarding | 首次进入 `/setup/welcome` |
| 启动耗时 | clean-room 4.579 秒；默认浏览器验证 2.241 秒 |
| launcher.log | 位于隔离 home 的 `logs/launcher.log`，未发现 secret/API Key 关键词 |

重定向 stdout 文件在当前 PowerShell/子进程编码组合下显示中文乱码；交互式输出及 pytest `capsys` 中文断言正常。该问题不影响浏览器，但正式 Windows 打包后应再检查控制台编码。

## 3. 重复启动

结果：**真实 Windows 进程测试未通过；单元注入通过。**

- 单元测试中，有效 PID + health + identity 会复用原实例、保持 PID/端口并重新调用浏览器。
- 真实 Windows 稳定虚拟环境中，第二次 launch 将仍健康的 PID 判为 stale。
- 第二次 launch 随后发现 8000 被占用，在 8001 创建第二实例，并覆盖 PID 文件。
- `launcher.log` 明确出现 `Stale PID file detected`，没有出现 `Existing healthy instance found`。
- 因第二命令进入 keep-alive，重复启动不能快速返回，也无法完成“再次打开现有页面”。

这不是端口 identity 误判：原 8000 的 `/api/health` 在第二次启动前可返回 `app=signalvault`。风险集中在 Windows 跨进程 `_process_exists()` 路径（当前基于 `os.kill(pid, 0)`）。在修复并重跑前，不得宣称重复启动通过。

## 4. 端口占用

结果：**通过。**测试使用 Python 普通 HTTP 服务占位，SignalVault identity 检查不会把它识别为自身。

| 场景 | 结果 |
|---|---|
| 8000 被普通 HTTP 占用 | 选择 8001；PID、health、访问地址均使用 8001 |
| 8000–8002 被占用 | 选择 8003；PID、health、访问地址均使用 8003 |
| 8000–8009 全被占用 | exit 1；不创建 PID；提示关闭占用程序或使用 `--port` |
| 浏览器端口 | 自动化测试确认浏览器使用实际选中端口（8003） |

实际启动耗时分别为 2.486 秒和 2.431 秒。全部端口占用时，错误包含端口范围和日志路径。

## 5. PID 异常

| 场景 | 结果 | 判断 |
|---|---|---|
| PID 文件不存在 | 正常启动 | 通过 |
| stale PID | 删除旧记录并重启；日志明确 | 通过 |
| 损坏 JSON | 检测返回无实例，但文件被静默保留，后续启动会覆盖 | UX 缺陷 |
| 缺少字段 | 同损坏 JSON | UX 缺陷 |
| PID 存活、health 不可达 | 不杀进程，检测阶段保留 PID | 安全边界通过；启动后覆盖风险待修 |
| health 200、app 非 signalvault | 不识别为实例、不杀进程 | identity 通过；启动后覆盖风险待修 |
| 有效已有实例 | 注入测试通过；真实 Windows 重复启动失败 | 阻断项 |

异常退出后的 stale PID 恢复实测通过：旧 PID 被记录并清理，新实例在 1.388 秒内恢复到 8000，health 正常。

## 6. 启动失败

| 场景 | 结果 |
|---|---|
| health 超时 | exit 1；提示重试和日志位置；请求 shutdown；清理 PID |
| 服务提前退出 | 当前返回 exit 0，并显示成功；**未通过** |
| 服务初始化异常 | 异常发生在主 `try/finally` 前；抛出 `RuntimeError`，PID 残留；**未通过** |
| runtime 目录不可写 | 最终表现为 PID 写入异常，不能保证可行动提示；**未通过** |
| PID 写入失败 | 抛出 `PermissionError`；无 PID，但缺少 Launcher 级友好错误；**未通过** |
| 主循环内异常 | exit 1；显示数据目录/日志提示；finally 清理 PID |

服务初始化失败和 PID 写入失败仍可能让 CLI 顶层输出 traceback；当前新增文案只能覆盖进入 Launcher 主 `try` 后的异常，不能覆盖上述两条前置路径。

## 7. 浏览器失败

结果：**通过（受控注入）**。

- `webbrowser.open()` 返回 `False`：服务继续，显示手工 URL，日志记录失败。
- `webbrowser.open()` 抛异常：stdlib 适配层转换为 `False`，不传播异常。
- 已有实例的浏览器失败：保留 PID，不清理健康实例，显示手工 URL。
- 新实例的浏览器失败：服务保持到收到受控退出信号。
- 正常路径实测：Windows 默认浏览器打开 8000，日志记录成功。

## 8. 退出与恢复

| 项目 | 结果 |
|---|---|
| SIGINT 注入（单元） | exit 0、request shutdown、PID 清理 |
| SIGTERM 注入（单元） | exit 0、request shutdown、PID 清理 |
| 后台任务为空 | shutdown event 正常设置并返回 |
| 存在短任务 | 使用 Event 协作结束，线程 join，活动列表清空 |
| 真实 Windows CTRL_C_EVENT 自动注入 | 15 秒内未退出，最终受控强制清理；PID 未清理；不能算 Ctrl+C 通过 |
| 强制退出后恢复 | stale PID 清理，新 PID 启动，8000 释放后复用，health 正常 |

自动化的 `CTRL_C_EVENT` 与用户在前台终端按 Ctrl+C 不完全等价，因此本轮结论是“真实 Ctrl+C 未验收”，不是断言人工 Ctrl+C 必然失败。没有使用固定长 sleep 判断退出，均使用进程、PID、health 或 Event 条件轮询/等待。

## 9. 浏览器用户旅程

结果：**通过。**最终有效 clean-room 流程：

`launch → welcome → AI Mock → Obsidian 跳过 → complete → dashboard → 关闭浏览器 → health 仍正常 → 新浏览器访问 / → dashboard`

- 首次根路径进入 onboarding。
- AI provider 为 `mock`；API Key 输入值为空。
- Obsidian 页面观测到的路径与临时 Vault 完全一致；随后选择跳过。
- complete 正确显示 Mock、Obsidian 未配置和 SQLite 主数据源。
- 完成后根路径不再重开 onboarding，直接进入 dashboard。
- 关闭浏览器后 health 仍为 `ok`。
- console error：0；HTTP 500：0。
- 20 个观测到的静态资源响应全部为 200。
- 横向溢出：welcome 1440×900 为 0；dashboard 三个视口均为 0。

截图证据位于 `output/playwright/m2-windows-ux/`（本地 QA 产物，不作为 macOS 证据）。

## 10. 日志和文案问题

本轮已改善：

- 启动立即显示“正在启动”和日志位置。
- 成功显示访问地址和关闭浏览器不停止服务。
- 端口变化明确显示首选端口与实际端口。
- 端口耗尽给出 `--port` 下一步。
- 已有实例给出明确提示和现有 URL。
- 浏览器失败给出手工 URL。
- health 失败给出重试建议和日志位置。
- 主循环异常给出数据目录可写性与日志建议。

仍需修复：

1. 服务初始化/PID 写入失败在友好错误边界之外。
2. 服务提前退出被显示为成功并返回 0。
3. 损坏/缺字段 PID 没有用户或日志提示。
4. Windows 重复启动会错误判 stale，随后创建第二实例。
5. 重定向输出的中文编码需在正式 Windows 安装物中复核。

## 11. 修改内容

- `src/signalvault/launcher.py`
  - 增加启动中、日志位置、成功 URL、退出方式反馈。
  - 增加已有实例与已有实例浏览器失败提示。
  - 增加端口变化和端口耗尽的可行动提示。
  - 改善 health 超时与主循环异常文案。
- `tests/test_launcher.py`
  - 新增已有/新实例浏览器失败、浏览器异常、实际端口 URL 测试。
  - 新增端口变化/耗尽文案测试。
  - 新增 SIGINT/SIGTERM 受控退出测试。
  - 新增短后台任务 shutdown/join 测试。
- `docs/M2_WINDOWS_UX_QA_REPORT.md`
  - 新增本报告。

未修改 ConfigService、SecretStore、C1/C2/C3、页面视觉、Provider、Vault、数据库模式、Briefcase 或 `.app`。

## 12. 自动化结果

| 命令/测试 | 结果 |
|---|---|
| `pytest --collect-only -q` | 2475 tests collected |
| Launcher 专项 | 44 passed |
| Launcher + health + onboarding | 77 passed，2 warnings |
| ruff（Launcher 与测试） | All checks passed |
| Playwright clean-room 用户旅程 | 通过；3 视口 overflow=0；console/500=0 |
| UI smoke | 9 passed，2 failed；两项均为已知 channels 失败；18766 同时存在预先运行的 SignalVault，出现 bind warning |
| 全量非 UI（隔离 venv） | 2448 passed，14 failed，1 skipped，786 warnings |
| 额外失败复跑 | packaging 23 passed；file import 1 passed |
| 两项存量失败复跑 | 2 failed，名称与基线一致 |

全量隔离 venv 的 14 failures 中，12 项属于打包临时目录权限/运行时差异并在系统环境定向复跑通过；稳定保留的 2 项是：

1. `tests/test_c2c_settings_center.py::TestMainNav::test_main_nav_has_settings_link`
2. `tests/test_sources_channels.py::TestDashboardIntegration::test_dashboard_shows_sources_link`

UI smoke 的 2 项保持原样：

1. `tests/test_ui_smoke.py::test_channels_page_loads`
2. `tests/test_ui_smoke.py::test_channels_page_css_loaded`

没有通过修改 Launcher 或前端绕过上述存量失败。

## 13. 仍需 macOS 实机验证

以下项目本轮均未验证，不得视为通过：

- `.app` 双击启动、Dock/Finder 行为和默认浏览器。
- `~/Library/Application Support/SignalVault/` 路径与权限。
- macOS PID/进程存活探测语义。
- Cmd+C、SIGTERM、系统退出/注销时的优雅关闭。
- macOS 默认浏览器失败和无 GUI 会话行为。
- app bundle 内 runtime、wheel、静态资源与模板。
- Gatekeeper、签名、公证、首次启动安全提示。
- 正式打包物中的日志位置、编码和异常恢复。

## 14. 是否具备进入 M3-A Briefcase spike 的条件

**否。**先修复并重测以下阻断项：

1. Windows 重复启动必须可靠识别健康已有实例，禁止创建第二服务和覆盖 PID。
2. 服务初始化异常与 PID/runtime 写入失败必须进入统一错误边界，提供日志路径并清理本次 PID。
3. 服务线程无信号提前退出必须返回非零并显示可行动错误。
4. 至少完成一次真实前台终端 Ctrl+C 验收，确认 PID 清理、端口释放和再次启动。

上述问题属于 Launcher 生命周期，不应通过前端、延长 sleep 或忽略存量测试来绕过。修复后应先重跑本 Windows QA，再进入 M3-A；macOS 实机验收仍是后续独立门禁。
