# M3-C 工作流产品化重构 — 影响分析报告

> 状态：影响分析（待确认修改范围）
> 日期：2026-08-02
> 基线：M3-B0/M3-B1 首轮 macOS 实机测试完成，核心功能可用
> 范围：用户工作流产品化重构，不改变核心数据模型与业务能力

---

## 0. 执行摘要（结论先行）

用户反馈的四个问题（多入口 / 人工刷新 / 首配与长期混淆 / 数据升级保护缺失）**同根**：当前系统是「功能驱动 + 历史迭代叠加」的架构，**缺少一个状态驱动的产品编排层**。入口路由、来源处理、应用模式、数据生命周期这四类「选择逻辑」散落在路由与服务里，且部分状态机（onboarding gate、schema_version）已经存在，但要么没被一致强制执行，要么只是装饰性数据。

**M3-C 的本质不是重写核心能力，而是补齐编排层**，把散落的「用户做技术性选择」上提为「系统按状态自动判断」。这与 M3-C 原则「用户提供信息 → 系统自动判断处理」完全一致。

四条核心约束（已有数据兼容 / 不破坏已有报告 / 不改变核心 pipeline / 增量重构）**全部可满足**，原因在 §6 逐条核对。重构可按风险分 **4 个独立交付层**，从零耦合的「数据保护」开始，到风险最高的「自动化编排」收尾，每一层都能独立验证、独立上线。

**对用户的影响**：用户不再需要在每个环节做技术性判断（选哪个入口、要不要点确认、是不是该走向导、升级会不会丢数据），而是「给系统信息，系统自动处理」。这是从「工具」到「助手」的产品形态跃迁。

---

## 1. 验证过的现状基线

以下事实均已通过精读代码 + 文件:行号交叉印证，非推测。

| 维度 | 事实 | 证据 |
|---|---|---|
| 测试规模 | 2542 tests 可收集 | README |
| Python 模块 | 140 个 | Glob |
| 数据表 | 19 张 ORM 表，**无任何 ForeignKey 约束**（逻辑外键靠命名约定） | `db/models.py` |
| Web 路由 | 90+ 个，`routes.py` 单文件 5663 行 | `web/routes.py` |
| CLI 命令 | 16 命令组 + 7 顶层命令 ≈ 86 个 | `cli.py` |
| 来源处理路径 | **6 条独立路径，无统一编排器** | `services/` + `sources/` |
| 进入产品路径 | 桌面双击 / `launch` / `serve` / CLI 命令树 / `mcp-serve` | `__main__.py:7-16` |
| 核心分析 pipeline | `_run_pipeline()` 只接收 `segments`，**与来源完全解耦** | `analysis/pipeline.py:208` |

---

## 2. 四个问题的根因定位

### 问题 1：多入口导致用户不知道如何选择

**现象**：用户面对一个来源，不知道用哪个入口。

**代码根因**：入口按「功能」和「历史迭代阶段」叠加生长，没有收敛到一个统一心智模型。

- **YouTube 是最分散的一类**：同一件事「把视频变成报告」有 4+ 个入口 —
  - CLI `--youtube-url`（`cli.py:59,109`）
  - CLI `channels analyze-video`（`cli.py:709`）
  - Web legacy `/content/new` + POST `/content/analyze`（`routes.py:1810,1833`）— **P2-K.1 旧入口，P2-S.3.4 的 `/sources/import/new` 出现后未下线**
  - Web `/sources/channels/{id}/videos/{vid}/import`（`routes.py:3966`）
- **报告生成入口碎片化**：8 个入口（4 CLI + 4 Web）指向同一个 `_run_pipeline`。
- **来源能力分布割裂**：
  - Web URL / 文件 / Tracked 三类**只在 Web 有入口**，CLI 无对应
  - PDF / ZSXQ 是 **CLI/Web 双轨且能力不等**（Web 上 PDF 分析能力是 CLI 子集，`routes.py:3058` 文案明示「PDF 主要通过 CLI」）
- **Legacy 堆积**：6 个 301 重定向（`/content/jobs/{id}`、`/sync/jobs/{id}`、`/setup/vault` 等）仍在路由表。
- **MCP 描述漂移**：`cli.py:4377` 硬编码「8 个工具」，但 `mcp_server/tools.py` 实际有 12 个（缺统一搜索、图谱、证据链相关工具），Agent 集成者会被误导。

**对用户的影响**：非技术用户面对「我要导入一个视频」时要先猜入口，猜错就走错流程；技术文档化也无法消除「为什么这里有 4 个长得一样的入口」的困惑。

**与 M3-C 原则契合度**：高。「用户提供信息（一个 URL/文件）→ 系统自动路由到正确入口」正是编排层的职责。改造落在 Web 路由层与入口收敛，不碰数据契约。

---

### 问题 2：信息源刷新需要人工确认，无法体现 AI 自动化价值

**现象**：固定信息源刷新后，用户要手动逐条勾选确认，且确认后只是「归档」，永远不进 AI 分析。

**代码根因（这是 M3-C 最关键的架构发现）**：

> **系统对「归档 vs 分析」没有统一判定。判定是按入口模块的物理边界硬编码的：进了 `sources/` 模块的来源永远不会到 LLM；进了 `services/analyze_service.py` 的直接到 LLM。两者之间没有桥。**

- 6 条来源路径里，只有 **YouTube（路径 A）和 PDF（路径 D）会触发 LLM**，且都不需要预览确认。
- **网页（路径 B）、文件（路径 C）、Tracked（路径 E）、ZSXQ（路径 F）强制 preview-confirm，且确认函数体内根本不 import pipeline** — 即「确认」只做归档，永不分析：
  - `import_preview.execute_import_action()`（`import_preview.py:260`）只写归档 markdown
  - `file_import_preview.confirm_file_import()`（`file_import_preview.py:213`）只写归档
  - `tracked_source_service.import_tracked_source_entries()`（`tracked_source_service.py:248`）只做归档
- **Tracked source 刷新完全手动**：无任何后台调度（全仓无 cron / APScheduler / periodic）。刷新后状态强制置 `preview_ready`（`tracked_source_service.py:195`），用户必须到 entries 页面手动勾选。且当前只有 All-In Podcast 一种 tracked source 能刷新（`source_kind == "allin_notes_index"` 闸门，`tracked_source_service.py:78-86`）。
- **`analyze_from_transcript()` 全仓唯一调用方是 `analyze_service.py:127`（YouTube 专用）** — 任何「让网页/文件/tracked 也跑分析」的需求，目前都无路径可达。
- **ingest_jobs 状态机缺分析态**：9 个状态（`ingest_jobs.py:28-38`）全是「归档类」，没有 `pending_analysis` / `analyzing` / `analyzed`。
- **无队列消费者**：所有 confirm 都由 Web 路由同步触发，没有 worker 自动消费 ingest_jobs。`resume_pending()`（`ingest_jobs.py:377`）只是统计函数，不自动执行。

**对用户的影响**：用户花时间设了固定信息源、点了刷新、还要逐条勾选、最后发现只是存了个 markdown 档——AI 的价值完全没体现。这是「工具」而非「助手」体验的直接来源。

**与 M3-C 原则契合度**：最高。这正是「用户提供信息 → 系统自动判断处理」的核心战场。

**关键好消息（约束验证）**：**核心 pipeline 不需要动**。`_run_pipeline()`（`pipeline.py:208`）只接收 `segments`，与来源解耦。改造落在 `sources/` 编排层 + 新增统一编排器 + ingest_jobs 状态机扩展，完全不碰 `analysis/`。

**自动化边界（哪些能自动化、哪些必须保留人工）**：

| 环节 | 当前 | 性质 | M3-C 判断 |
|---|---|---|---|
| YouTube / PDF → LLM | 不需确认 | 用户主动提交 = 意愿 | **保持** |
| 网页/文件/Tracked 条目 → 归档 | 强制逐条确认 | 实现偷懒 | **可自动化**（无冲突 + 解析良好时按 `recommended_action` 自动归档） |
| Tracked 刷新触发 | 完全手动 | 实现偷懒 | **可自动化**（加后台调度） |
| 归档后是否升级到 LLM 分析 | 能力缺失 | — | **新增**（配置开关 + 成本预算 opt-in） |
| 批量 LLM 分析（花真钱） | 不存在 | 产品原则（成本） | **必须用户 opt-in + 预算上限**，绝不默认自动 |
| content_hash 重复 | 硬阻止 | 数据完整性 | **保持**（`import_preview.py:193`） |
| `parse_quality == "minimal"` | 硬阻止 | 拒绝垃圾输入 | **保持** |
| 覆盖已存在 Deep Notes | 强制确认 | 破坏性 | **保持** |

---

### 问题 3：首次配置流程和长期使用逻辑混淆

**现象**：已配置好的日常用户会误入首配向导，分不清「一次性首配」和「日常修改」。

**代码根因**：不是缺状态机，是**状态机已存在但没被一致强制执行**。

- onboarding 4 步向导（欢迎→AI→Obsidian→完成），完成标志是 `onboarding_service.should_enter_onboarding()` 单一布尔位（`onboarding_service.py:44-46`），底层 `_internal.onboarding.completed`（`schema.py:248-254`），唯一写入点 `complete_onboarding()` / `skip_onboarding()`（`onboarding_service.py:61-74`）。**这套机制本身是干净的。**
- **致命缺口 1 — `/setup/*` 路由没有反向守卫**：`/setup/welcome`、`/setup/ai`、`/setup/obsidian`、`/setup/complete` 的 GET 处理函数（`routes.py:974, 1004, 1088, 1249`）**全部不检查 `should_enter_onboarding()`**。已配好用户直接访问 `/setup/welcome` 仍能完整重走 4 步向导，文案与首配完全一致。
- **致命缺口 2 — 设置中心主动邀请用户回去重走向导**：`settings/overview.html:81-87` 常年挂着「✨ 首次使用向导 / 重新打开向导 →」卡片。
- **致命缺口 3 — 文案明确鼓励混淆**：`setup/complete.html:31`「以后可随时从'配置中心'重新打开向导或修改单项配置」。
- **状态机 bug — SetupStatus 有死字段**：`wizard_completed`（`setup_status.py:28`）从未被任何 setter 赋值，导致 `needs_onboarding`（`setup_status.py:74-76`）**恒为 True**，经 `/api/settings/status`（`routes_settings.py:116`）暴露给 MCP / 诊断包，外部消费者拿到错误的「需要首配」信号。真实 gate（`OnboardingState.completed`）和这个死字段是双源真相。
- **错误恢复路径误弹向导**：`_redirect_vault_required()`（`routes.py:35-41`）在 vault 缺失时硬编码跳 `/setup/obsidian` — 把「日常使用中 vault 被移走」这种小故障弹回首配第 3 步，而不是去设置中心改路径。
- **双套模板冗余**：`setup/ai.html` 与 `settings/ai.html` 功能完全重叠，却用两套模板、两套路由、两套 CSRF helper（`_render_setup`/`_render_settings`、`_check_setup_origin`/`_check_settings_origin`），维护成本翻倍且行为漂移风险高。

**对用户的影响**：日常用户点「系统与集成」就看到「重新打开向导」，点了之后没有任何「你早已配置过」的提示，会以为配置丢了或需要重来。

**与 M3-C 原则契合度**：高。这层改造几乎全是「修复 + 守卫 + 文案」，不动数据契约，风险极低。

**重要结论**：**不需要引入新的「应用模式」枚举**。现有 `should_enter_onboarding()` 已经是事实上的二元模式（首配 vs 日常），且写入点、状态来源、消费者都清晰。要做的不是「加新模式」，而是「让现有模式判断在所有相关路由上被一致强制」。

---

### 问题 4：缺少明确的数据升级保护机制

**现象**：用户升级版本时不知道数据安不安全。

**代码根因（这是风险最高的一项，但好消息是改造成本低）**：

> **SignalVault 有「向前加列式」的渐进升级能力，能保证旧报告/原文不被升级破坏；但完全没有版本化迁移框架、没有 DB 自动备份、没有真实 schema 版本探测、没有回滚。`SchemaVersion` 表和 UI 上的版本号都是装饰性假数据。**

- **无迁移框架**：全仓无 alembic、无 migrations 目录（Glob 确认）。建表靠 `Base.metadata.create_all()` + **11 个手写 `_migrate_*_table` 函数**（`session.py:23-468`），模式是「inspect 列名 → 不存在就 ADD COLUMN」。只能加列，不能改/删/重命名列。
- **SchemaVersion 表是装饰性的**：
  - `_track_schema_version()`（`session.py:489`）**永远硬编码 `target_version=1`**，异常被 `except: pass` 吞掉（`session.py:509-510`）。
  - `_get_db_status()`（`settings_overview_service.py:341`）**硬编码 `return ("正常", 1)`**，根本不查 `schema_version` 表。
  - UI `settings/system.html:100` 显示的 `db_schema_version` 因此永远是 1。
- **升级前自动备份 DB：未实现**（Grep `backup.*\.db` / `shutil.*copy.*db` 全仓 0 匹配）。`backup_dir`（`app_paths.py:143`）存在，但**只服务 Obsidian 文件整理备份**，从未用于 DB。
- **无回滚 / downgrade / 损坏检测**：config.toml 有 corrupt→rename 兜底（`service.py:319-337`），DB 没有同等保护。
- **现有保护机制（唯一存在的一条）**：向前加列式兼容。`CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN`（绝不 DROP/RENAME），保证旧报告/原文/观点不丢。这是已多次验证的成熟模式（P0-B / P2-A1 / P4-B / P2-M.1 等都安全扩过列）。
- **真实升级风险**：任何 `_migrate_*` 中途抛异常（磁盘满等），DB 可能处于部分迁移状态，且**无备份可恢复、无回滚路径** = 一次性失败即数据全毁。配置文件有备份而 DB 没有，是显著的优先级倒挂。

**对用户的影响**：用户不敢升级，因为「升级会不会丢我攒了半年的报告」这个问题没有明确答案。这直接阻碍产品的长期使用心智。

**与 M3-C 原则契合度**：高。这一层与其他三个问题**完全解耦**，可以独立、最先交付。Agent 给出两条「最小代价最高价值」改造：DB 自动备份（约 15 行）+ 真实 schema 版本探测（约 10 行）。

---

## 3. 核心洞察：四问题同根 = 缺编排层

把四个根因摆在一起，模式清晰：

| 问题 | 散落在哪 | 缺失的编排 |
|---|---|---|
| 1 多入口 | Web 路由 + CLI 命令树 + legacy | 「信息 → 正确入口」的统一入口编排 |
| 2 人工确认 | `sources/` 与 `services/` 的物理隔离 | 「来源 → 归档/分析判定」的处理编排 |
| 3 首配混淆 | onboarding 状态机未被一致执行 | 「应用状态 → 正确体验」的模式强制 |
| 4 数据保护 | schema_version 是装饰性数据 | 「版本升级 → 安全迁移」的生命周期编排 |

**共同解法**：补齐一个状态驱动的产品编排层。这与 M3-C 原则「用户提供信息 → 系统自动判断处理」是同一件事——编排层的职责就是把「用户做技术性选择」上提为「系统按状态自动判断」。

注意问题 3 和 4 的特殊性：它们的「编排基础设施」其实已经存在（onboarding 状态机、SchemaVersion 表），只是没接通或没被强制。所以这两层改造**成本远低于另两层**，本质是「修复 + 接通」，而非「新建」。

---

## 4. 重构范围分层（按风险递增，每层独立可交付）

### Layer 0 — 数据升级保护（独立 · 零耦合 · 最高性价比）

**对应问题 4。** 与其他三层完全解耦，建议最先做、独立上线。

| 改造 | 文件 | 性质 | 对用户影响 |
|---|---|---|---|
| DB 自动备份（升级前 copy 到 `backups/`，保留 N 份） | `db/session.py:471`（`init_db` 顶部，`create_all` 之前） | 新增 ~15 行 | 升级失败有「后悔药」，消除丢数据恐惧 |
| 真实 schema 版本探测 | `services/settings_overview_service.py:332-343` 改为真查表 | 改 ~10 行 | UI 版本号变可信，可观测 |
| `init_db` 后 `PRAGMA integrity_check` + 失败提示从备份恢复 | `db/session.py:13`（`init_engine`） | 新增兜底 | DB 损坏可自愈引导 |
| `_track_schema_version` 接真实版本号（为后续真迁移铺路） | `db/session.py:489-510` | 修复 | 迁移可追踪 |

**不动**：表结构、`_migrate_*` 函数（它们是已装机用户升级的唯一桥梁，绝不清理）。

**验证**：备份文件生成、integrity_check、UI 版本号真实。`tests/test_db.py` 补备份测试。

---

### Layer 1 — 首配与长期使用分离（低风险 · 守卫 + 文案 + bug 修复）

**对应问题 3。** 纯路由守卫 + 文案 + 死字段清理，不动数据契约。

| 改造 | 文件 | 性质 | 对用户影响 |
|---|---|---|---|
| `/setup/*` GET 加反向守卫（已配好用户重定向到 `/settings`） | `routes.py:974, 1004, 1088, 1249` | 新增守卫 | 日常用户不再误入向导 |
| `_redirect_vault_required` 目标改为 `/settings/obsidian` | `routes.py:35-41` | 1 行改 | vault 丢失走设置中心而非向导 |
| 删除/重定义 `settings/overview.html:81-87` 的「重新打开向导」卡片 | `settings/overview.html` | 模板 | 消除最大混淆入口 |
| 修复 SetupStatus 死字段（删 `wizard_completed` / `needs_onboarding` 或接通真实状态） | `setup_status.py:28, 74-76` + `routes_settings.py:116` | bug 修复 | `/api/settings/status` 不再误报 |
| 文案：`setup/complete.html:31` 删「重新打开向导」引导 | `setup/complete.html` | 文案 | 心智一致 |
| （可选长期）合并 `setup/ai.html` ↔ `settings/ai.html` 双套模板 | `templates/setup/`, `templates/settings/` | 消除冗余 | 维护成本减半 |

**验证**：已配好用户访问 `/setup/*` 被重定向；`/api/settings/status` 的 `needs_onboarding` 真实。`tests/test_c3_onboarding.py` + `test_c2c_settings_center.py` 补守卫用例。

---

### Layer 2 — 入口收敛（中等风险 · UX 重构，需保留书签兼容）

**对应问题 1。** Web 路由与导航重构。

| 改造 | 文件 | 性质 | 对用户影响 |
|---|---|---|---|
| 下线 legacy `/content/new`（保留 301 重定向到 `/sources/import/new` 一段兼容期） | `routes.py:1810, 1833` | 收敛 | YouTube 不再有 4 个入口 |
| 清理 6 个 301 legacy 重定向（评估能否安全移除） | `routes.py:1349, 1892, 1961` 等 | 清理 | 路由表减负 |
| 统一「提供信息」入口：一个 URL/文件输入框 → 系统判定类型 → 路由到正确处理路径 | `sources/import/new` 强化或新增 | 编排 | 用户只管贴链接，系统自动分流 |
| 修正 MCP 工具描述（12 个，同步 `cli.py:4377` 硬编码） | `cli.py:4377`, `mcp_server/tools.py` | 修复 | Agent 集成不再被误导 |

**风险点**：legacy 入口下线要保留 301 兼容期，用户书签不能直接 404。

**验证**：`tests/test_web_pages.py` 更新路由断言；`tests/test_mcp_server.py` 验证 12 个工具描述；UI smoke。

---

### Layer 3 — 自动化编排层（最高价值 · 严格不碰 pipeline）

**对应问题 2。** M3-C 的核心价值所在，但通过编排层而非 pipeline 实现。

| 改造 | 文件 | 性质 | 对用户影响 |
|---|---|---|---|
| 新增统一来源编排器（判定：归档 / 分析 / 链式 / 跳过） | 新建 `services/ingest_orchestrator.py` | 新增 | 「系统自动判断处理」落地 |
| ingest_jobs 状态机扩展（加 `pending_analysis` / `analyzing` / `analyzed`） | `sources/ingest_jobs.py:28-38` + 对应 `_migrate_*` | 加列加状态 | 支持自动分析链路 |
| 自动归档：无冲突 + 解析良好时按 `recommended_action` 自动归档（保留 `auto_proceed=false` 回退） | `sources/import_preview.py`, `file_import_preview.py`, `tracked_source_service.py` | 编排 | 刷新后不用逐条点 |
| 自动分析判定：配置驱动的「自动分析白名单」+ 成本预算 opt-in（绝不默认自动花真钱） | 编排器 + 设置项 | 新增能力 | 归档后可升级到 AI 分析 |
| Tracked source 自动刷新调度（后台线程或独立触发，不引入重型 cron） | `tracked_source_service.py` + `launcher` 生命周期 | 新增 | 真正体现「固定信息源」价值 |
| 队列消费者（让 ingest_jobs 的分析任务能异步执行，而非 Web 路由同步触发） | `services/job_service.py`（抽象 job 执行体） | 扩展 | 批量分析不阻塞 UI |

**严格边界**：
- ❌ **不动 `analysis/pipeline.py`**（`_run_pipeline` 保持接收 segments 的解耦设计）
- ❌ **不动 `adapters/`**（数据抓取归一化层）
- ❌ **LLM 调用永远受成本预算 opt-in 约束**，绝不默认自动
- ✅ 自动归档（不花钱）可默认开启；自动分析（花钱）必须用户显式开启 + 设上限

**验证**：`tests/test_ingest_jobs.py`（状态机）、`tests/test_sources_tracked.py`（自动刷新）、新增编排器单测、自动归档/自动分析判定单测。

---

## 5. DB 层增量重构安全边界

M3-C 会新增状态字段与配置项。安全边界（已验证）：

**✅ 安全动作（历史已多次做过）**：
1. 加新列：`models.py` 加 `Mapped[...]` + 对应 `_migrate_*_table` 的 `migrations` 追加 `(col, type)`，type 含 `DEFAULT` 或列 nullable。
2. 加新表：定义新 ORM 类 + `CREATE TABLE IF NOT EXISTS`（或靠 `create_all`）。
3. 加 status/state 枚举字段：`String(N) DEFAULT '<known_value>'`，旧行自动填默认值。

**❌ 禁止动作（动了破坏兼容）**：改列类型 / 重命名列 / 删除列 / 加 NOT NULL 或 UNIQUE 约束 / 改主键 / 改 `source_doc_id` `segment_id` 业务键格式 / 「顺便」清理 11 个 `_migrate_*` 函数。

**绝对不能动结构的核心表列**：`episodes`、`reports`、`investment_views`、`tracking_signals`、`entities`、`source_documents`、`source_segments` 的主键与证据链列（详见 Agent 报告 §6.1）。

---

## 6. 四条核心约束逐条核对

| 约束 | 是否满足 | 依据 |
|---|---|---|
| 已有数据兼容 | ✅ | Layer 0 加自动备份兜底；所有新字段用 ADD COLUMN + DEFAULT；绝不 DROP/RENAME（§5） |
| 不破坏已有报告 | ✅ | 不动 reports/investment_views 等核心表结构；不动 11 个 `_migrate_*` 桥梁函数 |
| 不改变核心 pipeline | ✅ | `_run_pipeline()` 与来源解耦（`pipeline.py:208`）；Layer 3 全部落在 `sources/` + 新建编排器，`analyze_from_transcript()` 入口签名不变 |
| 增量重构 | ✅ | 四层独立交付，每层可独立验证上线；全是「加」（加编排器/状态/守卫/备份/判定），不是「改/删」核心 |

---

## 7. 分阶段交付计划（建议顺序）

| 阶段 | 内容 | 风险 | 可独立上线 | 依赖 |
|---|---|---|---|---|
| **M3-C-0** | Layer 0 数据保护（备份 + 真实版本号 + integrity_check） | 极低 | ✅ | 无 |
| **M3-C-1** | Layer 1 首配/长期分离（守卫 + bug 修复 + 文案） | 低 | ✅ | 无 |
| **M3-C-2** | Layer 2 入口收敛（legacy 下线 + 统一入口 + MCP 描述） | 中 | ✅ | 无（但建议在 C-1 后） |
| **M3-C-3a** | Layer 3a 自动归档 + ingest_jobs 状态扩展 + 编排器骨架 | 中 | ✅ | 无 |
| **M3-C-3b** | Layer 3b 自动分析判定（配置 + 成本预算 opt-in） | 中高 | ✅ | M3-C-3a |
| **M3-C-3c** | Layer 3c Tracked 自动刷新调度 + 队列消费者 | 中高 | ✅ | M3-C-3a |

建议先做 M3-C-0 和 M3-C-1（零耦合、低风险、立即可见的用户价值：升级安心 + 不再误入向导），再做 M3-C-2，最后做 M3-C-3 系列核心价值。

---

## 8. 编码前必须复核的锚点

以下是改造的精确落点，编码开始前需逐一复核当前行号（代码可能在分析期间变动）：

1. `routes.py:1810, 1833` — 确认 `/content/new`（GET）当前是 301 重定向还是活跃表单；POST `/content/analyze` 是否仍是活跃 YouTube 入口。**这决定 legacy 下线的具体方式。**
2. `routes.py:35-41` — grep 全仓 `_redirect_vault_required` 所有调用点，确认改指向 `/settings/obsidian` 的影响面。
3. `routes.py:974, 1004, 1088, 1249` — 确认 `/setup/*` GET 当前确无 `should_enter_onboarding()` 守卫。
4. `db/session.py:471-510` — 确认 `init_db` 顺序与 `_track_schema_version` 硬编码版本号。
5. `services/settings_overview_service.py:332-343` — 确认 `_get_db_status` 硬编码。
6. `sources/ingest_jobs.py:28-38` — 确认状态机无分析态。
7. `tracked_source_service.py:78-86, 195` — 确认 eligibility 闸门与 `preview_ready` 强制点。
8. `cli.py:4377` — 确认 MCP 工具数硬编码 8 vs 实际 12。

---

## 9. 明确不做的事（M3-C 边界）

- ❌ 不引入 alembic（保留手写 `_migrate_*` + 加 DB 备份兜底，够用；alembic 迁移留作长期项）
- ❌ 不动 `analysis/pipeline.py`、`adapters/`、LLM prompts
- ❌ 不改 / 删任何现有表列与业务键格式
- ❌ 不引入新的「应用模式」枚举（复用 `should_enter_onboarding()` 二元状态）
- ❌ 不默认自动花真钱做 LLM 分析（永远 opt-in + 预算上限）
- ❌ 不引入 React/Vue/Next.js、不改产品形态
- ❌ 不清理 11 个 `_migrate_*` 函数（它们是已装机用户的升级桥梁）

---

## 10. 决策请求

请确认以下三点，确认后即开始按 §7 顺序编码：

1. **分层与顺序**是否认可（M3-C-0 数据保护 → M3-C-1 首配分离 → M3-C-2 入口收敛 → M3-C-3 自动化编排）？
2. **自动化的成本红线**是否认可：自动归档（不花钱）默认开启，自动 LLM 分析（花钱）必须用户显式 opt-in + 预算上限？
3. **legacy 入口下线策略**是否认可：保留 301 重定向兼容期，不直接 404？

> 本报告所有事实基于 2026-08-02 的代码精读 + 文件:行号交叉印证。`§8` 锚点在编码开始时会逐一复核。
