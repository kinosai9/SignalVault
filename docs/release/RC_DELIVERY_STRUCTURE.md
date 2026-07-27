# RC 交付目录结构

> 定义 SignalVault Release Candidate 分发包的目录结构。本文件描述**目标结构**，实际 `.app` 和打包物由 Briefcase 在 M3-B 阶段生成。

---

## 目标分发包

```
SignalVault_RC_<version>/
│
├── SignalVault.app                  # macOS 应用程序包（Briefcase 生成）
│
├── Quick_Start.pdf                  # 快速开始（从 docs/user/QUICK_START.md 导出）
│
├── Release_Notes.md                 # 本版本发布说明
│
├── Troubleshooting.md               # 故障排除（从 docs/user/TROUBLESHOOTING.md 导出）
│
├── Feedback_Template.md             # 反馈模板（从 docs/release/FEEDBACK_TEMPLATE.md 导出）
│
└── Known_Issues.md                  # 已知问题（从 docs/release/KNOWN_ISSUES.md 导出）
```

---

## 分发格式

- **主分发**：`.dmg` 磁盘映像（包含以上所有文件）
- **备选**：`.zip` 压缩包

---

## 文件说明

| 文件 | 来源 | 面向 |
|------|------|------|
| `SignalVault.app` | `briefcase package macOS` | 最终用户 |
| `Quick_Start.pdf` | `docs/user/QUICK_START.md` → PDF | 最终用户 |
| `Release_Notes.md` | `CHANGELOG.md` 发布段 | 最终用户 / 测试者 |
| `Troubleshooting.md` | `docs/user/TROUBLESHOOTING.md` | 最终用户 |
| `Feedback_Template.md` | `docs/release/FEEDBACK_TEMPLATE.md` | 测试者 |
| `Known_Issues.md` | `docs/release/KNOWN_ISSUES.md` | 测试者 / 最终用户 |

---

## 不在分发包中的文件

以下文件是项目仓库中的开发文档，**不随 RC 分发包一起分发**：

- 所有 `docs/` 下的设计文档（`*_DESIGN.md`）
- Phase 验收报告（`*_ACCEPTANCE_REPORT.md`）
- 架构文档（`ARCHITECTURE.md`）
- 开发指南（`DEV_GUIDE.md`）
- 项目规则（`PROJECT_RULES.md`）
- 路线图（`ROADMAP.md`）
- 发布工程审计（`RELEASE_ENGINEERING_AUDIT.md`）
- CLAUDE.md
- tests/ 目录

---

## 生成方式

```bash
# .app
briefcase create macOS
briefcase build macOS
briefcase package macOS          # → DMG

# 文档导出（手动或用脚本）
# Quick_Start.md → Quick_Start.pdf（用 Pandoc 或浏览器打印）
# Troubleshooting.md → Troubleshooting.md（直接复制）
# Release_Notes.md → 从 CHANGELOG.md 提取当前版本段
```
