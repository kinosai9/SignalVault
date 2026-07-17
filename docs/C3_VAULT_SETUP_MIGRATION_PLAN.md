# C3 旧 `/setup/vault` 迁移计划

日期：2026-07-17
状态：执行中（P2）
依赖：C3 首次使用向导已交付（`/setup/obsidian` 上线）

## 执行进度

| 阶段 | 状态 | 日期 |
|---|---|---|
| A — 统一守卫重定向 | ✅ 完成 | 2026-07-17 |
| B — 补齐 repair 端点 | ✅ 完成 | 2026-07-17 |
| C — 兼容重定向 + 按钮 | ✅ 完成 | 2026-07-17 |
| D — 文件夹选择器评估与移植 | ✅ 完成 | 2026-07-17 |
| E — 测试迁移 | ✅ 完成 | 2026-07-17 |
| F — 文档更新 + 旧代码下线 | ✅ 完成 | 2026-07-17 |

## 背景

C3 首次使用向导引入了新的 `/setup/obsidian` 端点，在功能上完全覆盖了旧的 `/setup/vault`：
路径验证、Vault 初始化、幂等创建、配置持久化。新端点还增加了旧端点没有的
CSRF 保护、预览、Manifest 冲突检测和跳过机制。

旧 `/setup/vault` 及其配套端点（`/setup/browse-folder`、`/setup/vault/repair`）仍保留在
代码库中供历史入口兼容，但当前存在**两套首次设置入口**，增加了维护负担和用户困惑。

## 当前状态盘点

### 旧路由端点（routes.py，3 个）

| 端点 | 行号 | 功能 |
|---|---|---|
| `GET /setup/vault` | 1238 | Vault 配置页面 |
| `POST /setup/vault` | 1317 | 初始化 Vault 目录结构 |
| `POST /setup/vault/repair` | 1356 | 修复不完整的 Vault |

外加一个配套端点 `GET /setup/browse-folder`（1248 行），用于打开 OS 原生文件夹选择器。

### 路由守卫重定向（37 处）

分布在 `routes.py` 中，所有 `_get_vault_path()` 返回空或 Vault 路径不存在的页面守卫
都把用户踢到 `/setup/vault`。按消息分为两组：

**"请先配置知识库目录"（14 处）**：用于功能页面入口守卫
| 行号范围 | 涉及路由 |
|---|---|
| 3353, 3367, 3381, 3394, 3441, 3482, 3524 | `/sources/*` 系列 |
| 4267, 4287, 4351 | `/obsidian/*` 系列 |
| 4985, 5006, 5130 | 报告相关 |

**"请先配置知识库"（22 处）**：用于报告/分析页面守卫
| 行号范围 | 涉及路由 |
|---|---|
| 3726, 3746, 3780, 3864, 3904, 3938 | 报告生成/列表/详情 |
| 4131, 4186 | 分析任务 |
| 4435, 4473, 4493, 4549, 4608, 4637, 4675, 4730, 4806 | 频道/视频/搜索等 |

**"知识库目录不存在"（1 处）**：4637 行，Vault 路径已配置但目录被删除。

### 模板文件

| 文件 | 备注 |
|---|---|
| `templates/setup_vault.html` | 旧版独立 Vault 初始化页面，使用 `base.html`，含 JS 文件夹选择器 |
| `templates/dashboard.html:93` | Dashboard 修复按钮，POST 到 `/setup/vault/repair` |

### 服务层

| 文件 | 行号 | 内容 |
|---|---|---|
| `services/sync_service.py` | 80 | 错误消息：`"知识库路径尚未配置，请通过 /setup/vault 初始化。"` |

### 测试

| 文件 | 范围 | 说明 |
|---|---|---|
| `tests/test_web_pages.py` | `TestVaultSetup` 类 (11 个方法) | 全部直接调用旧 `/setup/vault` |
| `tests/test_source_profiling.py` | 12 行 | fixture 注释提到 "避免重定向到 `/setup/vault`" |

### 文档

| 文件 | 引用数 | 说明 |
|---|---|---|
| `README.md` | 1 | 路由表 |
| `CHANGELOG.md` | 1 | P2-L 历史记录 |
| `docs/USER_GUIDE.md` | 1 | 故障排查提示 |
| `docs/CONFIGURATION_AUDIT.md` | 6 | 配置表 + 5.1 专门章节 |
| `docs/FRONTEND_EXPERIENCE_EXECUTION_PLAN.md` | 1 | 路由清单 |
| `docs/CONFIGURATION_ARCHITECTURE_PLAN.md` | 1 | 计划修改引用 |
| `docs/C3_FIRST_RUN_ONBOARDING_PLAN.md` | 1 | 声明保留 |
| `docs/C3_ACCEPTANCE_REPORT.md` | 2 | 已知限制 + 建议复核 |

### 新旧功能差距

| 能力 | 旧 `/setup/vault` | 新 `/setup/obsidian` |
|---|---|---|
| 路径验证 | 简单（非空+绝对路径） | 结构化 `validate_obsidian_path()` |
| 初始化预览 | 无 | `preview_vault_initialization()` |
| 幂等创建 | 有 | 有（复用同一底层 `initialize_vault`） |
| Manifest 冲突检测 | 无 | 有 |
| 跳过/稍后配置 | 无 | `set_obsidian_skipped` |
| CSRF 保护 | 无 | 有（double-submit + Origin/Referer） |
| **修复（repair）** | **有** | **无** |
| **文件夹选择器** | **有** | **无** |
| 多步向导集成 | 无 | 有（欢迎 → AI → Obsidian → 完成） |

## 迁移策略：6 阶段

### 阶段 A：统一守卫重定向（影响范围最大）

将所有 37 处 `RedirectResponse(url="/setup/vault?...")` 替换为统一帮助函数，
指向新 `/setup/obsidian`。

```python
# routes.py 顶部新增
def _redirect_vault_required(message: str) -> RedirectResponse:
    """Redirect to Obsidian setup when vault is not configured."""
    from urllib.parse import quote
    return RedirectResponse(
        url=f"/setup/obsidian?msg=error:{quote(message)}",
        status_code=303,
    )
```

然后逐类替换：
- `"请先配置知识库目录"` → `_redirect_vault_required("请先配置知识库目录")`
- `"请先配置知识库"` → `_redirect_vault_required("请先配置知识库")`
- `"知识库目录不存在"` → `_redirect_vault_required("知识库目录不存在")`

**风险**：低。纯搜索替换，不改变控制流语义。
**测试**：运行 `test_web_pages.py` 确认受影响的页面守卫测试仍然通过。
**改动量**：routes.py 约 40 行变更。

### 阶段 B：补齐 repair 端点

新 `/setup/obsidian` 缺少 repair 能力。方案有两种：

**方案 B1（推荐）**：在 `/setup/obsidian` 页面复用 `initialize` — `initialize_obsidian_vault()`
已经调用 `initialize_vault()`，后者本身是幂等的（不覆盖已有文件）。增加 `repair: bool = False`
参数，传 `repair=True` 时调用 `repair_vault()` 而非 `initialize_vault()`。

**方案 B2**：新增独立端点 `/setup/obsidian/repair`，与旧 `/setup/vault/repair` 对等。

推荐 B1，因为：
- 用户不需要区分"初始化"和"修复"——两者都是"让 Vault 完整"
- 减少端点数量
- 底层 `initialize_vault` 和 `repair_vault` 可以统一为一个 "ensure" 语义

**风险**：中。涉及 Obsidian settings service 和 workspace.setup 的接口调整。
**测试**：将 `TestVaultSetup` 中的 repair 测试迁移为对新端点的测试。
**改动量**：`obsidian_settings_service.py` + `workspace/setup.py` + `routes.py` + 测试。

### 阶段 C：添加兼容重定向 + 更新 dashboard 修复按钮

1. 旧 3 个端点改为 301 永久重定向：
   - `GET /setup/vault` → `GET /setup/obsidian`
   - `POST /setup/vault` → `POST /setup/obsidian`
   - `POST /setup/vault/repair` → `POST /setup/obsidian/repair`（或 `POST /setup/obsidian?repair=1`）

2. `dashboard.html:93` 的修复按钮 action 改为新端点。

3. `sync_service.py:80` 的错误消息更新 URL。

**风险**：低。301 重定向对浏览器透明。
**测试**：确认旧 URL 返回 301，新 URL 功能正常。

### 阶段 D：文件夹选择器评估

旧 `/setup/browse-folder` 提供 OS 原生文件夹选择器（Windows PowerShell + 跨平台 tkinter）。
C3 的 `setup/obsidian.html` 只有文本输入框。

**评估结论**：文件夹选择器对首次用户体验有显著提升——用户不需要手动复制粘贴路径。
但：
- PowerShell FolderBrowserDialog 有已知兼容性问题（部分 Windows 11 版本不显示）
- tkinter fallback 在无 GUI 环境（WSL、headless）会失败
- 新 C3 页面使用聚焦布局，加入 JS 选择器需要异步改造

**建议**：作为独立增强任务（P3），不阻塞本次迁移。短期用文本输入 + placeholder 示例路径替代。

### 阶段 E：迁移测试

1. **`TestVaultSetup` 类**（`test_web_pages.py`）：
   - 将 11 个测试方法中对 `/setup/vault` 的调用改为 `/setup/obsidian`
   - 确认底层行为覆盖（目录创建、文件生成、幂等性）在 `test_c3_onboarding.py` 中已有等价覆盖
   - 当旧路由改为 301 重定向后，可增加重定向验证测试

2. **`test_source_profiling.py:12`**：
   - 更新 fixture 注释，将 `/setup/vault` 改为 `/setup/obsidian`

3. **回归验证**：
   ```bash
   python -m pytest tests/test_c3_onboarding.py tests/test_web_pages.py -v
   python -m pytest tests/test_settings_setup_status.py -v
   ```

### 阶段 F：文档更新 + 旧代码下线

**文档同步**：

| 文件 | 操作 |
|---|---|
| `README.md:429` | `/setup/vault` → `/setup/obsidian` |
| `docs/USER_GUIDE.md:370` | 更新故障排查 URL |
| `docs/CONFIGURATION_AUDIT.md` | 更新 5.1 节 + 配置表引用 |
| `docs/FRONTEND_EXPERIENCE_EXECUTION_PLAN.md:35` | 更新路由清单 |
| `docs/CONFIGURATION_ARCHITECTURE_PLAN.md:453` | 更新引用 |
| `CHANGELOG.md` | 新增迁移条目（不动历史 P2-L 记录） |

**旧代码下线**（在所有消费者迁移完成后）：

| 目标 | 位置 |
|---|---|
| 3 个旧路由 + browse-folder | `routes.py` 1238-1374 |
| 旧页面模板 | `templates/setup_vault.html` |
| 旧测试类 | `TestVaultSetup`（确认等价覆盖后删除） |

301 重定向保留一个版本周期（C3→C4）后再删除，给书签用户过渡时间。

## 执行顺序与依赖

```
阶段 A（守卫重定向）  ──→  阶段 B（repair 端点）
                                │
                                ↓
                          阶段 C（兼容重定向 + 按钮）
                                │
                                ↓
                          阶段 D（文件夹选择器评估）
                                │
                                ↓
                     阶段 E（测试迁移）──→ 阶段 F（文档 + 下线）
```

- 阶段 A 独立，可立即执行
- 阶段 B 和 C 依赖 A（守卫已指向新端点后才有意义）
- 阶段 D 可并行评估，不阻塞 B/C
- 阶段 E 依赖 B/C 完成
- 阶段 F 依赖 E 通过

## 回滚计划

每个阶段独立提交。任一阶段出问题时：
1. 回滚该阶段 commit
2. 旧 `/setup/vault` 始终可用（直到阶段 F 才删除路由定义）
3. 阶段 C 的 301 重定向不破坏旧行为——只是多加了一层跳转

## 验收标准

1. 所有 37 处守卫重定向指向 `/setup/obsidian`
2. Dashboard 修复按钮正常工作
3. 旧 `/setup/vault` URL 返回 301 重定向到 `/setup/obsidian`
4. `sync_service.py` 错误消息指向新 URL
5. `test_c3_onboarding.py` + `test_web_pages.py` 全部通过
6. 5 份文档引用已更新
7. Ruff 零告警
8. 用户不会看到两套不同的首次设置页面

## 已执行阶段实现记录

### 阶段 A（2026-07-17）

- `routes.py` 新增 `_redirect_vault_required(message)` helper 函数
- 37 处守卫重定向全部从 `/setup/vault?msg=error:...` 替换为 `_redirect_vault_required("...")`
- 覆盖三类消息：`请先配置知识库目录`（14 处）、`请先配置知识库`（22 处）、`知识库目录不存在`（1 处）

### 阶段 B（2026-07-17）

- `routes.py` 新增 `POST /setup/obsidian/repair` 端点，调用既有 `repair_obsidian_vault()` service
- 端点含 CSRF + Origin 校验，与 C3 其他 setup 端点一致
- 返回 `_render_setup_obsidian()` 模板，展示修复结果

### 阶段 C（2026-07-17）

- 旧 3 个路由改为 301 永久重定向：
  - `GET /setup/vault` → 301 → `/setup/obsidian`
  - `POST /setup/vault` → 301 → `/setup/obsidian`
  - `POST /setup/vault/repair` → 301 → `/setup/obsidian/repair`
- `/setup/browse-folder`（文件夹选择器）随旧页面一起移除（仅被旧模板引用）
- `dashboard.html:93` 修复按钮 action 改为 `/setup/obsidian/repair`
- `sync_service.py:80` 错误消息 URL 改为 `/setup/obsidian`

### 阶段 E（2026-07-17）

- `TestVaultSetup` 类重写：旧行为测试 → 301 重定向验证测试（3 个 redirect 测试 + 3 个保留测试）
- Vault 初始化/修复的深度行为覆盖由 `test_c3_onboarding.py` 保证
- 测试数从 ~13 个精简约 6 个，消除冗余覆盖

### 阶段 D（2026-07-17）

- 评估结论：文件夹选择器对非技术用户首次配置体验有显著价值
- `routes.py` 恢复 `/api/browse-folder` 端点（原 `/setup/browse-folder`，移至 `/api/` 命名空间）
- `setup/obsidian.html` 增加「浏览文件夹」按钮 + JavaScript fetch 调用
- `style.css` 增加 `.input-with-button` 样式（输入框+按钮并排布局）
- 失败降级：对话框不可用时提示用户手动输入路径

### 阶段 F（2026-07-17）

- `README.md:429` — 路由表 `/setup/vault` → `/setup/obsidian`
- `docs/USER_GUIDE.md:370` — 故障排查 URL 更新
- `docs/CONFIGURATION_AUDIT.md` — 7 处引用更新（配置表 + 5.1 节重写为 C3 行为说明）
- `docs/FRONTEND_EXPERIENCE_EXECUTION_PLAN.md:35` — 路由清单更新
- `docs/CONFIGURATION_ARCHITECTURE_PLAN.md:453` — 引用更新
- `CHANGELOG.md:629` — 保留历史记录，不修改
- 删除死模板 `src/signalvault/web/templates/setup_vault.html`
- 旧 301 重定向保留至 C4，届时可完全移除旧路由定义

## 迁移完成总结

6 个阶段全部完成。用户现在只有一条 Obsidian 设置路径：C3 向导第 3 步 `/setup/obsidian`。
所有旧入口（守卫重定向、书签、按钮）均自动到达新端点。

## 不纳入本次迁移

- **文件夹选择器增强**：独立评估，待 P3 处理
- **频道后台线程测试固定 sleep**：独立遗留问题
- **SQLite engine fixture 竞态**：独立遗留问题
- **C3 不包含真实 Provider 自动化网络请求**：产品安全要求
