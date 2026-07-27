# M3-B0：RC 用户交付准备 — 就绪报告

> 日期：2026-07-27
> 基线：9df72c9（M3-A Briefcase Spike + .gitignore）
> 阶段：M3-B0 用户交付准备
> 下一阶段：M3-B1 macOS 实机验证

## 一、RC 用户画像

| 维度 | 描述 |
|------|------|
| 身份 | 真实投资信息管理使用者 |
| 技能 | 会使用电脑，**不具备** Python/开发经验 |
| 不理解的概念 | venv、pip、config.toml、.env、Terminal、Git |
| 期望体验 | 安装 → 双击 → 浏览器打开 → 配置 AI → 开始使用 |
| 对标产品 | Excel、Notion、Obsidian — 普通桌面应用 |

## 二、用户流程分析

### 当前流程

```
双击 SignalVault.app
    ↓
Launcher 启动（5-15s 后台初始化）
    ↓
浏览器自动打开 → http://127.0.0.1:8000
    ↓
Welcome 页面（3 条核心说明 + 可选跳过）
    ↓
AI 配置（Mock 或真实 API Key）
    ↓
Obsidian 配置（明确标注可选）
    ↓
完成 → Dashboard（变化雷达）
```

### 流程评估

| 环节 | 评估 | 说明 |
|------|------|------|
| 启动反馈 | ✅ | Launcher 中文消息清晰，health poll 确保浏览器只在就绪后打开 |
| 欢迎向导 | ✅ | C3 onboarding 完整，3 步向导，支持跳过 |
| AI 配置 | ✅ | Mock/真实两种模式，Provider/Base URL/Model 有 help text，Key 不进源码 |
| Obsidian 配置 | ✅ | 明确标注可选，不阻塞核心功能，验证+预览+初始化完整 |
| Dashboard | ✅ | 新用户看到引导状态，empty state 引导导入 |

## 三、首次启动改进

### 已改进项

1. **About 页面增加"导出诊断包"按钮** — 用户在"设置 → 诊断与关于"可以直接下载诊断包，无需经过任务页面
2. **浏览器自动打开有 fallback 提示** — Launcher 已在浏览器打开失败时提示手动访问地址
3. **Launcher 中文消息** — 所有启动消息为中文、有日志路径、端口变更通知

### 留到 M3-B1 的项目

- macOS Dock 图标和菜单栏行为（需实机验证）
- 启动时的 splash screen / 进度指示（当前无 GUI，只有终端输出，.app 中用户看不到）
- Gatekeeper 警告引导（首次打开的"仍要打开"说明在 Quick Start 中覆盖）

## 四、错误提示优化

### 改进项

**Web 错误页面重写**：从仅显示 `status_code + detail` 的极简页面，改为分场景用户友好页面：

| 状态码 | 改进前 | 改进后 |
|--------|--------|--------|
| 404 | 只显示"404" + detail | 有搜索图标、导航建议、三个快捷入口（Dashboard/搜索/导入） |
| 403 | 无专门处理 | 说明安全原因、会话过期/非本地请求的可能原因、返回路径 |
| 500 | 只显示"500" + detail | 说明内部错误、3 步排查引导、日志路径提示、诊断导出入口 |
| 503 | 无 | 新增：服务启动中状态页，自动刷新提示 |
| 默认 | 只显示 status + detail | 通用错误 + 下一步引导 |

**Launcher 错误**：已有中文分级错误消息（实例冲突、运行时写入失败、服务意外停止），无需修改。

**P7-A Error Taxonomy**：20+ 错误码、中文用户消息、建议操作、恢复动作注册表 — 在 CLI 和诊断包中使用。Web 层当前未集成，留到后续阶段。

## 五、诊断能力

### 已有能力（P7-A/B/C/D）

- **9 子系统诊断**：摄入队列、审核队列、操作日志、知识星球、PDF 处理、Obsidian 知识库、统一搜索、知识图谱、系统配置
- **操作日志**：25 种操作类型，带 metadata 和错误码
- **诊断包导出**：9 文件 zip，自动脱敏（API Key → [REDACTED]，全文 → 字符数，路径 → bool）
- **恢复动作注册表**：10 个注册动作（安装 ZSXQ CLI、配置 LLM、重试摄入任务等）
- **About 页面一键导出**：新增"导出诊断包"按钮

### 诊断包文件结构

| 文件 | 内容 |
|------|------|
| `manifest.json` | 版本、redaction 策略、runtime_status、health、database_status、paths |
| `diagnostics_summary.json` | 9 子系统状态、最近失败、建议操作 |
| `operation_logs.json` | 脱敏后的最近操作记录 |
| `review_items_summary.json` | 审核队列聚合（计数、分类、样例标题） |
| `ingest_jobs_summary.json` | 摄入队列计数、最近失败摘要 |
| `config_summary.json` | 配置存在性检查（不包含值） |
| `system_info.json` | Python 版本、OS、包版本、SQLite 版本 |
| `search_graph_summary.json` | 报告/观点/信号/实体/图谱节点计数 |
| `README.txt` | 诊断包说明、redaction 声明 |

### 安全保证

- API Key 正则扫描：值中包含 `sk-*`、`Bearer *` 等模式自动 redact（防御深度）
- 路径仅返回 bool 存在性检查，不返回绝对路径
- 全文内容替换为字符数，不返回原文片段

## 六、用户文档结构

新建立三层文档体系：

```
docs/
├── user/                         # 最终用户文档（新增）
│   ├── QUICK_START.md           # 5 分钟首次使用
│   ├── FAQ.md                   # 13 个常见问题
│   └── TROUBLESHOOTING.md       # 启动/AI/Obsidian/数据故障排除
│
├── release/                      # 发布文档（新增）
│   ├── RC_CHECKLIST.md          # RC 用户交付检查清单
│   ├── FEEDBACK_TEMPLATE.md     # 非技术用户反馈模板
│   ├── KNOWN_ISSUES.md          # 已知问题与功能边界
│   └── RC_DELIVERY_STRUCTURE.md # RC 分发包目录结构定义
│
└── dev/                          # 开发文档（已有文件保持原位）
    ├── ARCHITECTURE.md
    ├── DEV_GUIDE.md
    ├── Launcher 设计
    ├── Packaging 设计
    └── Configuration 设计
    ...（44 个已有文档）
```

## 七、新增测试

**`tests/test_diagnostic_bundle_security.py`** — 24 个安全审计测试：

| 测试类别 | 数量 | 覆盖 |
|---------|------|------|
| Redaction 单元 | 11 | 深层嵌套、列表、大小写、连字符、非字符串、空值、异常消息含 key、Bearer token、Base URL、全文截断 |
| Bundle 集成 | 11 | API key 扫描、Bearer token 扫描、operation log metadata、error_detail 含 key、vault 路径、report markdown、config bool 检查、路径存在性检查、系统路径泄露、诊断摘要 key 检查、完整 zip 扫描 |
| Convenience export | 1 | 端到端导出安全性 |
| 防御深度 | 1 | `_string_contains_secret_pattern` 正则扫描 |

**全量诊断测试**：90 existing + 24 new = 114 tests，全部通过。

## 八、修改文件清单

| 文件 | 操作 | 行数变化 |
|------|------|---------|
| `src/signalvault/web/templates/settings/about.html` | 修改 | +2 行（新增导出按钮 + 帮助文字） |
| `src/signalvault/web/templates/error.html` | 重写 | 40→90 行（分场景错误页） |
| `src/signalvault/diagnostics/bundle.py` | 修改 | +72 行（manifest 增强 + 内容安全扫描） |
| `tests/test_diagnostic_bundle_security.py` | 新增 | ~380 行（24 tests） |
| `docs/user/QUICK_START.md` | 新增 | ~100 行 |
| `docs/user/FAQ.md` | 新增 | ~120 行 |
| `docs/user/TROUBLESHOOTING.md` | 新增 | ~140 行 |
| `docs/release/FEEDBACK_TEMPLATE.md` | 新增 | ~50 行 |
| `docs/release/KNOWN_ISSUES.md` | 新增 | ~130 行 |
| `docs/release/RC_CHECKLIST.md` | 新增 | ~60 行 |
| `docs/release/RC_DELIVERY_STRUCTURE.md` | 新增 | ~70 行 |
| `docs/M3B0_RC_DELIVERY_READINESS_REPORT.md` | 新增 | 本报告 |

**总计**：修改 2 个源文件，新增 1 个测试文件（24 tests），新增 8 个文档文件。

## 九、未修改的模块（按阶段边界约束）

- Launcher 状态机（`launcher.py`）
- C1/C2 配置架构
- C3 onboarding 核心逻辑
- 数据模型 / SQLite 结构
- Briefcase 配置 / pyproject.toml
- macOS 专属代码
- 已有 HTML 模板（除 error.html 和 about.html）
- 已有测试（追加不修改）

## 十、已知限制（M3-B0 范围外）

1. **Splash screen**：macOS `.app` 双击后，用户在浏览器打开前看不到任何反馈。需在 M3-B1 实机验证后评估是否需要 splash screen
2. **Web 错误页面未集成 P7-A Error Taxonomy**：error.html 现在是分场景模板，但尚未动态加载 ErrorCodeRegistry 中的结构化错误码和恢复建议
3. **非 macOS 用户启动**：Windows 用户仍需命令行，Quick Start 目前以 macOS `.app` 为假设
4. **Quick_Start.pdf**：当前为 Markdown，PDF 版本需在正式发布前用 Pandoc/浏览器打印生成
5. **Release_Notes.md**：需在正式 RC 发布前从 CHANGELOG.md 提取

## 十一、是否具备进入 M3-B1

### 进入条件检查

| 条件 | 要求 | 实际 | 判断 |
|------|------|------|------|
| 非技术用户首次流程完整 | Welcome → AI → Obsidian → Dashboard | C3 onboarding 完整，支持跳过 | ✅ |
| 启动失败有用户级反馈 | 非技术堆栈的中文错误消息 | Launcher 中文错误 + 新 error.html | ✅ |
| AI 失败可定位 | 错误提示指向 AI 设置而非 HTTP 码 | error.html 500 页 + 诊断导出入口 | ✅ |
| Obsidian 失败不阻塞 | 核心功能独立于 Obsidian | 已有贯穿所有页面的可选标注 | ✅ |
| 诊断包可导出 | Web UI 一键下载 | About 页面 + /tasks 两个入口 | ✅ |
| 诊断包无敏感信息 | API Key/路径/原文不进 zip | Redact 机制 + 24 安全测试 + 内容正则扫描 | ✅ |
| Quick Start 完成 | 非技术用户可 5 分钟完成首次使用 | docs/user/QUICK_START.md | ✅ |
| RC 反馈模板完成 | 降低非技术用户反馈成本 | docs/release/FEEDBACK_TEMPLATE.md | ✅ |
| 文档结构清晰 | 三层体系（user/release/dev） | docs/user/ + docs/release/ + 已有 docs/ | ✅ |
| 不改动阶段边界外模块 | Launcher/C1/C2/C3/数据模型/Briefcase | 零改动 | ✅ |

### 决策

**具备进入 M3-B1 macOS 实机验证的条件。**

所有 M3-B0 交付物已完成。没有阻断 M3-B1 进入的问题。

## 十二、M3-B1 下一步

M3-B1 需在 macOS 实机上执行：

1. 仓库 clone（SSH）+ Python 3.12 + Briefcase 0.4.4 安装
2. `briefcase create macOS` + `briefcase build macOS` + `briefcase package macOS`
3. `.app` 双击启动验证
4. `~/Library/Application Support/SignalVault/` 权限确认
5. 浏览器自动打开验证
6. M3-B0 新增的错误页面和诊断导出功能验证
7. Cmd+Q / SIGTERM 信号处理
8. Gatekeeper 行为记录（签名/公证暂不做）
9. 用户文档和反馈模板的实机验证
