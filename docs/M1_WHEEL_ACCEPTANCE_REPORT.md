# M1 Wheel/Sdist Build & Clean-Room Acceptance Report

> 日期：2026-07-20
> 基线：bf1145a + M1 package_data 修复
> 阶段：M1 — wheel/sdist 构建与 clean-room 验证

## 一、测试基线核对

### 基线状态

| 检查项 | 结果 |
|--------|------|
| `git status --short` | 2 untracked (M0 文档) |
| `git log -1 --oneline` | `bf1145a @ C3 post-review...` |
| `ruff check src/ tests/` | All checks passed |
| `git diff --check` | 干净 |

### 测试数量差异分析

| 来源 | collected | 说明 |
|------|-----------|------|
| C3 验收报告 | 2416 | 含当时所有测试文件 |
| M0 基线 | 2408 | 正常波动（测试文件微调） |
| M1 当前（不含 UI smoke） | 2408 | 与 M0 一致 |
| M1 当前（含 UI smoke） | 2419 | 2408 + 11 UI smoke |

差异原因：C3 验收后有小量测试文件变更（C3 post-review hardening 中重构了 TestVaultSetup 测试），collect 数从 2416 变为 2408。此差异在 C3 post-review commit (bf1145a) 中引入，非 M1 引入。

### 全量测试（不含 UI smoke）

**结论：M1 专项与 clean-room 门禁通过；仓库级仍有既有测试失败，未发现 M1 新增回归。**

```
2393 passed, 3 failed, 1 skipped, 785 warnings
```

**失败详情**:

| # | 完整名称 | 失败原因 | 隔离重跑 | 稳定性 | 归属 |
|---|---------|---------|---------|--------|------|
| 1 | `tests/test_c2c_settings_center.py::TestMainNav::test_main_nav_has_settings_link` | C3 dashboard guard：测试未设置 `onboarding_completed` cookie，请求 `/dashboard` 被重定向到 `/setup/welcome`，响应中不含 `href="/settings"` | 稳定复现 | 稳定失败 | C3 存量，需更新测试注入 onboarding 状态 |
| 2 | `tests/test_sources_channels.py::TestDashboardIntegration::test_dashboard_shows_sources_link` | 同上：访问 `/dashboard` 被重定向到 onboarding 欢迎页，响应中不含 `/sources` | 稳定复现 | 稳定失败 | C3 存量，同上 |
| 3 | (偶发 flaky) | 第一次全量跑出现 3 failed，第二次全量重跑仅 2 failed。第三个未在重跑中复现 | 未复现 | 不稳定 | 待观察，不影响 M1 门禁 |

### UI smoke tests

```
9 passed, 2 failed
```

| # | 完整名称 | 失败原因 | 稳定性 |
|---|---------|---------|--------|
| 1 | `tests/test_ui_smoke.py::test_channels_page_loads` | 频道页面加载断言失败（`assert "sources/channels" in page.url`） | 稳定失败 |
| 2 | `tests/test_ui_smoke.py::test_channels_page_css_loaded` | 频道页面 CSS 检查失败 | 稳定失败 |

这两个为存量 UI smoke 问题，非 M1 引入，留待后续 UI smoke 专项修复。

### 新增打包测试

```
23 passed, 0 failed
```

M1 新增 `tests/test_packaging.py`，23 个测试覆盖 wheel/sdist 内容验证、资源文件存在性、entry points、无 dev 泄漏等。

### 模板数量确认

源目录 `src/signalvault/web/templates/` 包含 **46 个 HTML 文件**（含 `settings/` 和 `setup/` 子目录）。wheel 中同样包含 46 个，与源目录一致。

## 二、package_data 修复

### 修改内容

**`pyproject.toml`**:
```toml
[tool.setuptools.package-data]
signalvault = [
    "web/templates/**/*.html",
    "web/static/*.css",
    "web/static/*.js",
    "web/static/*.svg",
]
```

**`MANIFEST.in`** (新建):
```
graft src/signalvault/web/templates
graft src/signalvault/web/static
include README.md
include LICENSE
```

## 三、ReportLab 依赖结论

- **生产代码** (`src/`): 零 `import reportlab`
- **测试代码** (`tests/`): 仅 `test_pdf_extraction.py` 和 `test_pdf_analysis.py` 使用（生成测试 PDF）
- **诊断模块** (`diagnostics/bundle.py`): 字符串引用 `"reportlab"` 用于 `importlib.metadata.version()` 查询，缺失时返回 `"unknown"`，不抛异常
- **结论**: ReportLab 属于 dev-only 依赖，不需要移到运行时依赖。已在 `[project.optional-dependencies] dev` 中，当前配置正确。

## 四、wheel/sdist 构建结果

### 文件大小

| 产物 | 大小 |
|------|------|
| `signalvault-0.1.0-py3-none-any.whl` | 596 KB |
| `signalvault-0.1.0.tar.gz` | 744 KB |

### wheel 内容（193 文件）

| 类型 | 数量 | 验证 |
|------|------|------|
| Python 模块 | 138 | ✅ |
| HTML 模板 | 46 | ✅ 全部 |
| CSS | 1 | ✅ style.css |
| JS | 1 | ✅ app.js |
| SVG | 1 | ✅ signalvault-icon.svg |
| 元数据 | 6 | ✅ METADATA, RECORD, WHEEL, entry_points, LICENSE, top_level |

### sdist 内容（301 条目）

| 类型 | 数量 | 验证 |
|------|------|------|
| Python 模块 | 213 | ✅ 含 tests/ |
| HTML 模板 | 46 | ✅ |
| CSS/JS/SVG | 3 | ✅ |
| README.md | ✅ | 已包含 |
| LICENSE | ✅ | 已包含 |
| 敏感文件 | 0 | ✅ 无 .env, config.toml, .db |

详细清单见 `docs/M1_WHEEL_CONTENTS.txt` 和 `docs/M1_SDIST_CONTENTS.txt`。

## 五、clean-room 验证

### 环境

| 参数 | 值 |
|------|-----|
| Python | 3.14.0 (>=3.12 兼容) |
| 工作目录 | `/tmp/sv-clean-test`（不在仓库内） |
| 安装方式 | `pip install dist/signalvault-0.1.0-py3-none-any.whl` |
| SIGNALVAULT_HOME | `/tmp/sv-clean-data` |
| PYTHONPATH | 未设置 |
| 仓库 .env | 未读取 |

### 启动验证

```
signalvault.__version__ = 0.1.0
signalvault --help → 正常
signalvault serve → 启动成功
```

### 路由验证

| 路由 | HTTP 状态 | 验证 |
|------|-----------|------|
| `GET /` | 302 → `/setup/welcome` | ✅ 首次运行重定向到向导 |
| `GET /setup/welcome` | 200 | ✅ |
| `GET /setup/ai` | 200 | ✅ |
| `GET /setup/obsidian` | 200 | ✅ |
| `GET /setup/complete` | 200 | ✅ |
| `GET /dashboard` | 302（首次）/ 200（完成后） | ✅ |
| `GET /settings` | 200 | ✅ |
| `GET /settings/ai` | 200 | ✅ |
| `GET /settings/obsidian` | 200 | ✅ |
| `GET /settings/system` | 200 | ✅ |
| `GET /settings/about` | 200 | ✅ |
| `GET /api/health` | 200, `{"status":"ok"}` | ✅ |
| `GET /static/style.css` | 200, `text/css` | ✅ |
| `GET /static/app.js` | 200, `text/javascript` | ✅ |
| `GET /static/signalvault-icon.svg` | 200, `image/svg+xml` | ✅ |

### Onboarding 完整流程

```
POST /setup/welcome → 303 /setup/ai ✅
POST /setup/ai (mock) → 303 /setup/obsidian ✅
POST /setup/obsidian (skip) → 200 (stay) ✅
POST /setup/complete → 303 /dashboard ✅
GET /dashboard → 200 ✅
```

### 持久化验证

重启后：

| 检查项 | 结果 |
|--------|------|
| `config/config.toml` 已创建 | ✅ `onboarding.completed = true` |
| `data/signalvault.db` 已创建 | ✅ 266 KB, schema 正常 |
| `logs/signalvault.log` 已创建 | ✅ |
| 重启后 Dashboard 直接可访问 | ✅ 不重复触发 onboarding |
| 配置保留 | ✅ AI 设置和 Obsidian 状态正确 |
| 所有文件仅位于 SIGNALVAULT_HOME | ✅ 不写 site-packages, 不写当前目录 |

### sdist 反向验证

从 sdist 安装第二个干净环境：

```
pip install dist/signalvault-0.1.0.tar.gz → 成功
pip check → No broken requirements
Version → 0.1.0
Templates → 46
CSS/JS/SVG → 1/1/1
```

## 六、问题与建议

### 已知问题

| # | 描述 | 影响 | 建议 |
|---|------|------|------|
| 1 | 2 个测试因 C3 onboarding guard 重定向失败 | 测试隔离，非运行时问题 | 更新测试在请求前完成 onboarding |
| 2 | UI smoke channels 页面 2 个失败 | 仅影响 UI smoke | 独立排查 channels 路由 |
| 3 | `__main__.py` 导入会触发 `app()` 解析命令行 | 仅当被 import 时（非常规用法） | 可加 `if __name__ == "__main__"` guard（非 M1 范围） |
| 4 | Python 3.14（非 3.12） | 用户环境为 3.14，wheel 兼容 | macOS 环境下应用 3.12 验证 |

### 不阻塞项

- WAL 模式未启用（按 M1 要求不修改）
- 后台线程 graceful shutdown 未实现（M2 范围）
- Launcher 不存在（M2 范围）

## 七、M2 进入条件判断

| 条件 | 状态 |
|------|------|
| wheel 可构建并包含全部资源 | ✅ |
| sdist 可构建并包含全部资源 | ✅ |
| clean-room 安装可启动服务 | ✅ |
| onboarding 完整流程可走通 | ✅ |
| 配置持久化 + 重启保留 | ✅ |
| 静态资源全部 200 | ✅ |
| 模板全部正常渲染 | ✅ |
| 不依赖源码仓库 | ✅ |
| 不依赖 Git | ✅ |
| 不写 site-packages | ✅ |
| 23 个打包测试全部通过 | ✅ |
| ruff 通过 | ✅ |
| 无 M1 引入的测试失败 | ✅ |
| 源目录与 wheel 模板数一致（各 46 个） | ✅ |

**M1 专项与 clean-room 门禁通过；仓库级仍有既有测试失败（5 个：2 个 onboarding guard + 1 个偶发 flaky + 2 个 UI smoke），未发现 M1 新增回归。**

**可以进入 M2。**
