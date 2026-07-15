# TODO

本文只记录当前仍需执行的工作。已完成阶段见 `docs/ROADMAP.md` 和 `CHANGELOG.md`；明确不做的能力见 `docs/PROJECT_RULES.md`，不重复列为待办。

## Release Engineering

- [ ] 在全新 Python 3.12+ 虚拟环境完成 `pip install -e ".[dev]"`
- [x] 2013 项 pytest 全部通过（2006 非浏览器 + 7 UI smoke）
- [ ] 修复 Ruff 0.15.21 报告的 45 项问题，并统一 CI/本地版本
- [ ] 完成六条关键页面的桌面/移动端截图验收
- [ ] 修复或替换损坏的项目 `.venv`，统一开发与发布解释器
- [ ] 确认 `pyproject.toml` 版本号、release tag 与 CHANGELOG 一致
- [ ] 清理 `.pytest_tmp_phase8/`、测试截图和本地服务日志等发布外产物
- [ ] 按 `docs/RELEASE_CHECKLIST.md` 完成安全、文档和仓库门禁

## Manual Integration

- [ ] 真实 LLM 短视频与长视频 chunking 验证
- [ ] 真实 YouTube 字幕主路径与 yt-dlp 备用路径验证
- [ ] 真实文本型 PDF 的 Web/CLI 双入口验证
- [ ] 知识星球已订阅内容刷新、同步、分析验证
- [ ] Obsidian export / sync / cleanup 系列命令在真实 Vault 先 dry-run 后 apply
- [ ] MCP 统一搜索、报告详情、图谱与证据链验证

## Product Backlog

- [ ] 信息源工作台展示全文保留状态
- [ ] Web 搜索开放 `source_document` / `source_segment` 结果类型
- [ ] 观点和信号证据卡按 `source_segment_id` 定位原文片段
- [ ] Partial chunk failure recovery
- [ ] 网页正文版本记录与抽取精度继续优化
- [ ] RSS/Atom adapter
- [ ] 可插拔 OCR provider（默认仍不外传扫描件）
