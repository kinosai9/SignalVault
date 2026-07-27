# 常见问题

## 基本概念

### Mock 模式是什么？

Mock 模式是一个**不需要真实 AI 服务**的体验模式。它用规则匹配来模拟分析过程，让你在不花钱、不需要 API Key 的情况下完整走通 SignalVault 的导入→分析→报告流程。

**Mock 模式的分析结果不代表真实 AI 分析质量。** 正式使用时建议配置真实 AI 服务。

### API Key 从哪里获取？

取决于你用的 AI 服务商：

- **OpenAI**：在 [platform.openai.com/api-keys](https://platform.openai.com/api-keys) 创建
- **DeepSeek**：在 [platform.deepseek.com](https://platform.deepseek.com) 获取
- **智谱 AI**：在 [open.bigmodel.cn](https://open.bigmodel.cn) 获取
- **其他 OpenAI-compatible 服务**：查看对应服务商的文档

任何 OpenAI-compatible 的服务都可以用，只需要填写正确的 Base URL、Model 和 API Key。

### Obsidian 是不是必须的？

**不是。** Obsidian 是可选的集成功能。

不配置 Obsidian：
- ✅ 导入资料 → 正常
- ✅ AI 分析 → 正常
- ✅ 查看报告 → 正常
- ✅ 知识搜索 → 正常
- ✅ 变化雷达 → 正常
- ❌ 将报告同步到 Obsidian → 不可用

SignalVault 的主数据存储是本机 SQLite 数据库，不依赖 Obsidian。

### 数据存在哪里？

所有数据存储在本机。具体位置取决于操作系统：

- **macOS**：`~/Library/Application Support/SignalVault/`
- **Windows**：`%APPDATA%/SignalVault/`

数据目录包含：
- SQLite 数据库（`signalvault.db`）
- 配置文件
- 日志文件
- 诊断包导出

AI API Key 单独加密存储，与普通配置文件分开。

## 使用问题

### 浏览器没有自动打开怎么办？

手动在浏览器地址栏输入：**http://127.0.0.1:8000**

如果打不开：
1. 确认 SignalVault 应用正在运行（检查菜单栏是否有 SignalVault 图标）
2. 确认端口是否正确（默认 8000，如果被占用会自动换到 8001、8002…）
3. 查看日志文件（在数据目录的 `logs/` 文件夹中）

### 端口被占用怎么办？

SignalVault 会自动检测端口占用情况。如果 8000 端口被占用，会自动尝试 8001、8002…直到找到可用端口。

如果你需要指定端口，目前需要通过命令行启动：`signalvault launch --port 9000`

### 如何升级？

macOS 上：下载新版本的 `.app`，替换旧版本即可。数据文件独立存储，升级不会丢失数据。

### 如何备份数据？

备份数据目录即可。macOS 上数据目录在 `~/Library/Application Support/SignalVault/`。把整个文件夹复制到安全位置。恢复时复制回原位置。

备份内容包含：
- SQLite 数据库（所有分析报告、观点、信号）
- 配置文件
- 操作日志

### 分析一个视频需要多长时间？

取决于：
- 视频字幕长度
- AI 服务响应速度
- 是否使用真实 AI（Mock 模式几乎是即时的）

一般 15 分钟以内的视频（中文字幕），用真实 AI 分析大约需要 30 秒到 2 分钟。长视频会自动分段处理，可能需要更长时间。

### 支持哪些语言？

SignalVault 的界面是中文。分析方面：
- **中文资料**：完全支持，Mock 模式和真实 AI 均可
- **英文资料**：真实 AI 模式下支持，Mock 模式分析能力有限
- **其他语言**：取决于 AI 模型的多语言能力

### 导入的资料会泄漏吗？

不会。SignalVault：
- 不上传数据到 SignalVault 服务器（根本没有这样的服务器）
- 只在你使用真实 AI 时，将分析所需的文本内容发送给你配置的 AI 服务
- AI API Key 加密存储，不进日志、不进诊断包
- 诊断包自动脱敏，不含密钥和原文

### 可以多人使用吗？

当前版本不支持多人协作。SignalVault 是单用户本地应用。每个用户在自己的电脑上有独立的数据和配置。
