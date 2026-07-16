# Release Checklist

本清单是 SignalVault 的发布门禁。只有“发布候选验证”全部通过，才能标记 Release Candidate；真实 LLM 和外部连接器属于人工验收，不进入默认 CI。

## 1. Release Baseline

- [x] P0-P7 后端/CLI 验收完成
- [x] 四条前端主用户动线完成，Phase 8 已验证
- [x] SourceDocument / SourceSegment 第一阶段落地
- [x] C1-C2 配置体系封板（AppPaths、ConfigService、SecretStore、AI/Obsidian 设置页、CSRF、Manifest）
- [x] MIT `LICENSE` 存在
- [x] 用户手册、README、ROADMAP、架构与来源文档已统一
- [x] `python -m pytest --collect-only -q` 收集 2359 tests（2026-07-16）

## 2. Clean Install Gate

在全新虚拟环境执行，不使用本机已有 `.venv` 作为通过依据：

```bash
python -m venv .release-venv
.release-venv/Scripts/python -m pip install -e ".[dev]"
.release-venv/Scripts/python -m signalvault --help
```

- [ ] Python 版本满足 `>=3.12`
- [ ] 安装无依赖冲突
- [ ] CLI help 可正常显示
- [ ] `python -m signalvault serve` 可启动
- [ ] 首次访问能完成 Vault 目录配置
- [ ] SQLite 新库可自动创建全部 19 张 ORM 表并记录 schema version

> 当前本机 `.venv` 启动器已知损坏；发布验收必须新建环境，不能把 `.codex-venv` 可运行等同于干净安装通过。

## 3. Automated Quality Gate

```bash
python -m pytest tests/ -q
ruff check src/ tests/
python -m pytest tests/test_web_pages.py tests/test_ui_smoke.py -q
```

- [x] 全部 2359 tests 通过：2351 项非浏览器测试，7 项 UI smoke，1 项 Windows 平台 skip
- [x] Ruff clean — 全量 `src/` 和 `tests/` 零 lint 问题
- [x] Web 页面与 UI smoke tests 通过
- [x] 默认测试只使用 mock provider，不产生真实 API 费用
- [x] 测试使用隔离 fixture 和工作区 `--basetemp`，未写入真实 `data/` 或 Obsidian Vault

## 4. Main User Flow Gate

启动 `python -m signalvault serve` 后，在桌面和移动宽度各检查一次：

- [ ] `/dashboard`：变化雷达无重叠，今日动作可进入对应页面
- [ ] `/sources`：信息源状态、待处理项和导入能力一致
- [ ] `/sources/import/new`：YouTube、知识星球、网页、固定源、文件/PDF 五类入口可达
- [ ] `/sources/files/import`：文本文件可预览归档；PDF 可预览并进入分析
- [ ] `/sources/zsxq`：CLI/登录状态、星球列表、同步与分析入口反馈清晰
- [ ] `/search`：报告、观点、信号、实体筛选和来源筛选可用
- [ ] `/reports/{id}`：观点、信号、风险、证据引用显示正确
- [ ] `/reports/{id}/transcript`：完整原文可读，翻译按钮状态正确
- [ ] `/tasks`：诊断状态、恢复建议、操作日志、任务列表可理解
- [ ] 移动端侧栏可打开/关闭，内容和按钮不溢出

## 5. Data And Safety Gate

- [x] `.env` 未被 git 跟踪，`.env.example` 仅含占位值
- [ ] 发布 diff 中无 API Key、token、cookie、密码、私有 URL 或个人绝对路径
- [ ] `data/signalvault.db`、`data/user_settings.json`、字幕缓存、真实报告、日志和诊断包未暂存
- [ ] 诊断包不含密钥、完整付费内容或隐私字段
- [ ] 核心观点保留 `source_quote`
- [ ] 视频证据保留 timestamp；PDF 保留页码；ZSXQ 保留 group/topic/source_url
- [ ] UI 与文档均保留“不是投资建议”边界
- [ ] MCP Server 仍为只读，不存在写入型 tool

## 6. Configuration Center Gate (C2)

Web Console 配置页面验证（`python -m signalvault serve` 后）：

### AI 服务页面 (`/settings/ai`)
- [x] Provider 下拉选择（mock / openai-compatible）
- [x] Base URL / Model 字段随 Provider 切换显隐
- [x] API Key 通过 type=password 输入，不回显，不在页面源码中
- [x] 保存配置持久化到 config.toml
- [x] API Key 存储到 SecretStore（不进 config.toml）
- [x] 测试连接（Mock 模式即时通过）
- [x] 验证状态持久化，配置变更后自动失效
- [x] 环境变量覆盖警告

### Obsidian 页面 (`/settings/obsidian`)
- [x] 启用/禁用开关
- [x] 路径保存、验证（拒绝相对路径和系统根目录）
- [x] 初始化预览（将创建的目录/文件清单）
- [x] 初始化 Vault（幂等，不覆盖已有文件）
- [x] Manifest 创建和 conflict 保护
- [x] 修复（只补齐缺失，不覆盖）
- [x] 写入测试（创建临时文件并清理）
- [x] 禁用保留路径，不删除文件
- [x] 清除路径不删除 Vault
- [x] SQLite 独立于 Obsidian

### 设置中心概览 (`/settings`)
- [x] AI 卡片（Provider、Model、Key 来源、验证时间）
- [x] Obsidian 卡片（状态、缩略路径、.obsidian 检测）
- [x] 系统卡片（版本、DB 状态、数据目录、平台、服务地址）
- [x] 诊断卡片（健康状态、问题计数、入口链接）
- [x] 不含 API Key

### 系统页面 (`/settings/system`)
- [x] 只读展示应用/路径/数据库/服务信息
- [x] 路径分类标签（必须备份/可重建/可清理）
- [x] ORM 和 FTS 表数量

### About 页面 (`/settings/about`)
- [x] 版本、RC 标识、系统环境
- [x] 隐私说明、免责声明、开源许可
- [x] `/tasks` 诊断入口
- [x] 不含 API Key

### CSRF 与 Origin
- [x] 所有 POST 端点 CSRF 保护（double-submit cookie）
- [x] Origin/Referer 校验（URL host 比较，拒绝 127.0.0.1.attacker.com）
- [x] 无 Origin 无 Referer 无 CSRF → 403
- [x] 无 Origin 无 Referer 有效 CSRF → 允许（JSON API）

### SecretStore
- [x] `secrets` 文件独立存储，不进 config.toml
- [x] 替换 Key 后旧验证失效（secret_revision 计数器）
- [x] 删除 Key 后回退 env 值，验证仍失效

### 普通用户路径
- [x] 普通用户无需编辑 `.env`
- [x] README 不把编辑 `.env` 作为首要配置步骤

## 7. Manual Integration Gate

以下检查需要用户自己的凭证或真实资料，结果记录在发布验收记录中，不进入 CI：

- [ ] 真实 LLM：短视频分析成功，报告/观点/信号可追溯
- [ ] 真实 LLM：长视频自动 chunking 成功，并核对调用成本
- [ ] YouTube：主字幕适配器失败时，yt-dlp 备用路径行为符合预期
- [ ] PDF：真实文本型研报通过 Web 和 CLI 各验证一次
- [ ] ZSXQ：已订阅星球刷新、同步、单主题分析各验证一次
- [ ] Obsidian：导出、同步与 Vault refresh 先 dry-run 再 apply
- [ ] MCP：至少验证统一搜索、报告详情和证据链查询

## 7. Documentation And Packaging Gate

- [ ] `README.md` 当前状态、安装命令、页面入口准确
- [ ] `docs/USER_GUIDE.md` 与实际页面按钮/路由一致
- [ ] `docs/ROADMAP.md` 只保留真实 Active track
- [ ] `TODO.md` 不包含已完成事项，不把 Not Planned 混入待办
- [ ] `CHANGELOG.md` 记录本次发布范围、迁移和已知限制
- [ ] `pyproject.toml` 版本号与 release tag 一致
- [ ] CSS cache bust version 已更新
- [ ] 用户可从 README 到达用户手册、开发指南、验收记录和发布清单

## 8. Repository Gate

```bash
git status --short
git diff --check
git diff --stat
```

- [ ] 只包含本次发布需要的源码、测试和文档
- [ ] 无临时截图、pytest 临时目录、服务日志或诊断包
- [ ] GitHub remote 使用 SSH：`ssh://git@github.com/kinosai9/signalvault.git`
- [ ] CI 工作流与本地质量门禁一致
- [ ] commit message 使用简洁英文
- [ ] 不自动 push；跨设备同步时再由用户明确执行

## 9. Known Release Boundaries

以下不是封板阻断项，但必须在用户手册和发布说明中保持透明：

- 扫描型 PDF 不自动 OCR
- 普通网页和普通文本默认归档，不自动生成投资报告
- Web PDF 分析当前使用 mock provider；真实 LLM 和关注点控制使用 CLI
- Web 搜索尚未开放 SourceDocument / SourceSegment 结果筛选
- 无登录鉴权，服务默认只绑定 `127.0.0.1`
- 无定时抓取、团队协作、云同步、RAG/向量库或投资建议
