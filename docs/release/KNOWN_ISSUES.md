# 已知问题与限制

> 本文档记录当前 RC 版本中已知的问题和功能边界。这些问题不影响核心使用，但你在使用时应当了解。

---

## 功能边界

### 扫描型 PDF 不自动 OCR

**影响**：扫描版 PDF（图片型）无法提取文字，分析会失败。

**当前行为**：提取失败后，PDF 会被加入待处理审核队列，显示"需要 OCR"。

**计划**：未来版本考虑集成 OCR 能力。

### 无登录鉴权

**影响**：SignalVault 没有用户名/密码登录。服务默认只绑定 `127.0.0.1`（本机地址）。

**安全性**：其他设备无法通过网络访问你的 SignalVault。但同一台电脑上的其他用户可以访问（如果他们有浏览器权限）。

**建议**：不要将 SignalVault 暴露到公网。不要在共享电脑上存储敏感 API Key。

### 普通网页和文本默认归档

**影响**：普通网页和文本文件导入后默认只归档原文，不自动生成投资分析报告。

**当前行为**：归档后可在知识搜索中查找。如需分析，需要通过 CLI 工具手动触发。

**原因**：并非所有网页都包含投资相关内容，自动分析会浪费 AI 调用成本。

### Web 搜索不支持按原文筛选

**影响**：Web 页面的知识搜索目前按报告、观点、信号、实体筛选，暂不支持按 SourceDocument / SourceSegment（原始资料片段）筛选。

**CLI 可用**：CLI 搜索命令支持更细粒度的筛选。

### 无定时抓取

**影响**：SignalVault 不会自动定时抓取 YouTube 频道更新或网页变化。

**当前行为**：需要手动触发导入。

### 无团队协作

**影响**：SignalVault 是单用户本地应用。不支持多人共享数据或协同编辑。

### 无云同步

**影响**：数据仅存储在本地。如果你在多台电脑上使用，需要手动备份和迁移数据。

### 不支持 RAG / 向量库

**影响**：SignalVault 的搜索基于 SQLite FTS5 全文搜索，不使用向量数据库或 RAG（检索增强生成）。

**当前行为**：搜索按关键词匹配，结合实体和观点关联进行排序。

---

## macOS 特定

### Gatekeeper 警告

**影响**：首次打开 `.app` 时，macOS Gatekeeper 可能提示"无法验证开发者"。

**解决方法**：系统设置 → 隐私与安全性 → 仍要打开。

**原因**：当前版本未经过 Apple 开发者签名和公证。签名计划在正式发布前完成。

### 首次启动较慢

**影响**：首次双击应用到浏览器打开，可能需要 10-20 秒。

**原因**：首次启动需要初始化 SQLite 数据库和默认配置。

---

## Windows 特定

### Windows 桌面应用打包 (M3-B2 Spike)

**影响**：Windows 原生桌面启动（`.exe`）的 MSI 安装包已可生成（Briefcase 0.4.4），但 GUI stub 在 Python 3.14.4 嵌入式环境下存在间歇性启动失败。

**当前状态**：
- `briefcase create / build / package` — 通过 ✅
- MSI 安装 — 通过 ✅ (45.92 MB, 安装至 `%LOCALAPPDATA%\Programs\Kinosai\SignalVault\`)
- 应用代码 Windows 兼容 — 通过 ✅ (系统 Python + 已安装包验证)
- Briefcase GUI stub 启动 — 不稳定 ❌ (`GUI-Stub-3.14-amd64-b11`, 退出码 1, 无日志)

**技术细节**：
- Briefcase 版本: 0.4.4
- 嵌入式 Python: 3.14.4
- Stub 二进制: `GUI-Stub-3.14-amd64-b11`
- 应用层已验证: `signalvault.launcher.launch()` 通过系统 Python 正常运行，health check OK
- 参考: [`docs/M3-B2_WINDOWS_SPIKE_REPORT.md`](../M3-B2_WINDOWS_SPIKE_REPORT.md)

**临时运行方式**（需要系统 Python 3.14）：
```powershell
$env:PYTHONPATH = "$env:LOCALAPPDATA\Programs\Kinosai\SignalVault\app;$env:LOCALAPPDATA\Programs\Kinosai\SignalVault\app_packages"
python -c "from signalvault.launcher import launch; launch()"
```

**计划**：调查 Briefcase stub 兼容性，或切换为自定义 Console 子系统启动器。

---

## 投资分析相关

### 不是投资建议工具

SignalVault 用于**结构化整理公开投资信息**。所有分析结果基于 AI 模型对公开内容的提取：

- 不提供买入/卖出/持有建议
- 不保证分析结果的准确性或完整性
- 不构成投资建议

### Mock 模式不代表真实 AI 质量

Mock 模式（默认）基于中文关键词匹配规则引擎，仅用于工程闭环测试和功能体验。

---

## 性能边界

### 长视频分析成本

超过 15 分钟的视频会自动分段处理，每段调用一次 AI。**长视频（1 小时+）可能产生较高的 API 调用成本。**

### 大量信息源

当前版本未针对大量（100+）频道/信息源的高频更新做过优化。
