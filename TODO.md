# TODO

## P2-O.1 Engineering Stabilization

- [x] CLAUDE.md / README / TODO 阶段一致性
- [x] GitHub Actions CI（push/PR 自动 pytest + ruff）
- [x] ruff 配置 + 基础 lint（76 项例外 via per-file-ignores）
- [x] data/logs/.env 安全检查（无敏感数据进入 git）
- [x] CSS cache busting（content hash: 2d2ef5f5）
- [x] UI smoke test（7 Playwright tests for source pages + dashboard/reports/search）
- [x] docs/ARCHITECTURE.md
- [x] docs/RELEASE_CHECKLIST.md

## 待完成

### P0-B 遗留

- [ ] YouTube 视频元数据获取（标题、时长、频道名）— 需 YouTube Data API 或 HTML 解析
- [ ] YtDlpAdapter（yt-dlp 字幕下载备用方案）
- [ ] 真实 YouTube 投资访谈视频链接集成验证

### P2-B 遗留

- [ ] Partial chunk failure recovery（单个 chunk 失败不中止其它）
- [ ] Semantic deduplication（embedding 去重，替代 key-based）
- [ ] Chunk-level evaluation（eval 支持 per-chunk 统计）

### 手动验证项

- [ ] P2-C: cleanup-unknown --dry-run + --apply 真实 Vault
- [ ] P2-C.2: sync-channel-cards --dry-run + 真实 Vault
- [ ] P2-D: generate-cards --dry-run + 真实 Vault
- [ ] P2-D.1: cleanup-cards --dry-run + --apply
- [ ] P2-D.2: consolidate-topics --dry-run + --apply

### P3：小宇宙 + 其他增强

- [ ] 真实 LLM provider 完整接入与 prompt 调优
- [ ] 小宇宙单集链接解析（可选 Adapter）
- [ ] xyz-dl 字幕下载 Adapter（可选）
- [ ] 说话人推断逻辑
- [ ] 元数据获取（podcasts 表）

### P4：多期观点对比

- [ ] 多报告选择
- [ ] 同标的观点聚合
- [ ] 观点变化时间线
- [ ] 对比报告生成
