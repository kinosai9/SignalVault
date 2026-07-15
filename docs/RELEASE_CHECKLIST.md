# Release Checklist

本清单是 SignalVault 的发布门禁。只有“发布候选验证”全部通过，才能标记 Release Candidate；真实 LLM 和外部连接器属于人工验收，不进入默认 CI。

## 1. Release Baseline

- [x] P0-P7 后端/CLI 验收完成
- [x] 四条前端主用户动线完成，Phase 8 已验证
- [x] SourceDocument / SourceSegment 第一阶段落地
- [x] MIT `LICENSE` 存在
- [x] 用户手册、README、ROADMAP、架构与来源文档已统一
- [x] `python -m pytest --collect-only -q` 收集 2013 tests（2026-07-15）

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

- [x] 全部 2013 tests 通过：2006 项非浏览器测试分四组运行，7 项 UI smoke 单独运行
- [ ] Ruff clean（Ruff 0.15.21 当前有 45 项存量问题）
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

## 6. Manual Integration Gate

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
