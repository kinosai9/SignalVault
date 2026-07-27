# RC 交付检查清单

> 本清单用于 RC 版本交付前的最终验证。与 `RELEASE_CHECKLIST.md` 的分工：本清单聚焦**用户交付体验**，原 `RELEASE_CHECKLIST.md` 覆盖完整工程质量门禁。

---

## 1. 用户首次体验

- [ ] 双击 `.app` 可以启动
- [ ] 启动后浏览器自动打开
- [ ] 首次访问进入欢迎向导
- [ ] 欢迎向导可正常跳过（直接进入 Dashboard）
- [ ] 欢迎向导可完整走通（AI 配置 → Obsidian 配置 → 完成）
- [ ] 跳过 Obsidian 不影响核心功能

## 2. AI 配置

- [ ] Mock 模式可正常选择和使用
- [ ] OpenAI-compatible 模式下可填写 Provider/Base URL/Model/API Key
- [ ] 保存并测试连接正常
- [ ] 测试失败时错误提示可理解（非技术术语）
- [ ] API Key 不回显、不进页面源码

## 3. Obsidian 配置

- [ ] 明确标注为"可选"
- [ ] 跳过 Obsidian 后 Dashboard 可正常使用
- [ ] 路径验证正确（拒绝相对路径和系统根目录）
- [ ] 初始化 Vault 正常
- [ ] 禁用/清除路径不删除 Vault 文件

## 4. 核心用户动线

- [ ] **变化雷达**：可正常显示，新用户看到引导状态
- [ ] **导入中心**：YouTube/网页/文件/PDF 入口可达
- [ ] **知识搜索**：搜索功能正常
- [ ] **报告库**：报告列表可显示，详情页正常

## 5. 错误处理

- [ ] 启动失败显示用户可理解的错误信息（非技术堆栈）
- [ ] AI 连接失败指向"检查 AI 设置"而非"HTTP 401"
- [ ] Obsidian 失败不阻塞主流程
- [ ] 错误页面包含下一步引导（非纯错误码）

## 6. 诊断能力

- [ ] 设置 → 诊断与关于 → 导出诊断包 可正常下载 zip
- [ ] 诊断包不包含 API Key
- [ ] 诊断包不包含原文内容
- [ ] 诊断包不包含用户文件路径

## 7. 用户文档

- [ ] `docs/user/QUICK_START.md` 可供非技术用户 5 分钟完成首次使用
- [ ] `docs/user/FAQ.md` 覆盖常见疑问
- [ ] `docs/user/TROUBLESHOOTING.md` 覆盖主要故障场景
- [ ] `docs/release/FEEDBACK_TEMPLATE.md` 可降低反馈成本
- [ ] `docs/release/KNOWN_ISSUES.md` 准确记录当前限制

## 8. 质量门禁

- [ ] 全量 pytest 通过
- [ ] 诊断包安全审计测试通过（24 tests）
- [ ] 无新增 lint 问题
- [ ] Web 页面测试通过
