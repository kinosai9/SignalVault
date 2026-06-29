# TODO

## 已完成（P2-O · P2-S）

- [x] P2-O.1: Engineering Stabilization（CI, lint, docs, UI smoke tests）
- [x] P2-O.2/O.2.1: Runtime Observability & Task Failure UX
- [x] P2-S.1: External Derived Source Adapter（allin_zh_notes, generic web）
- [x] P2-S.2: Deep Notes Export & Episode Linking
- [x] P2-S.2.2: External Fetch Reliability（retry engine + error classification）
- [x] P2-S.3.1: Generic Web URL Import Preview（adapter, conflict detector, UI）
- [x] 1261 tests, ruff clean

## 待完成

### P0-B 遗留

- [ ] YouTube 视频元数据获取（标题、时长、频道名）— 需 YouTube Data API 或 HTML 解析
- [ ] YtDlpAdapter（yt-dlp 字幕下载备用方案）
- [ ] 真实 YouTube 投资访谈视频链接集成验证

### P2-B 遗留

- [ ] Partial chunk failure recovery（单个 chunk 失败不中止其它）
- [ ] Semantic deduplication（embedding 去重，替代 key-based）
- [ ] Chunk-level evaluation（eval 支持 per-chunk 统计）

### P2-S 遗留

- [ ] P2-S.2.1: validate_deep_notes_import 第 5 个 episode 导入失败的跟进（4/5 成功）
- [ ] External adapter 扩展（除 All-In Podcast 外的其他中文资讯站点）
- [ ] GenericWebPageAdapter 正文提取精度优化（当前 best-effort）
- [ ] Source Import 预测览页面错误状态覆盖（network failure, parse error 等）

### 手动验证项

- [ ] P2-C: cleanup-unknown --dry-run + --apply 真实 Vault
- [ ] P2-C.2: sync-channel-cards --dry-run + 真实 Vault
- [ ] P2-D: generate-cards --dry-run + 真实 Vault
- [ ] P2-D.1: cleanup-cards --dry-run + --apply
- [ ] P2-D.2: consolidate-topics --dry-run + --apply
- [ ] P2-S.2: Deep Notes 真实 export 验证

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
