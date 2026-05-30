# 投资播客研究助手 / Podcast Investment Research Assistant

将公开播客字幕中的投资观点、标的、风险提示、待验证信号和关键原文引用结构化沉淀。

> **本项目不提供投资建议。** 所有输出仅为播客内容的结构化整理，不构成买入、卖出、持有等决策建议。

## 当前阶段：P2-E.2 LLM-WIKI Patch Apply

P0 + P1 + P2-A + P2-B + P2-C + P2-D + P2-E + P2-E.1 已完成。P2-E.2 实现了安全的、显式的单文件 patch apply 流程，LLM 生成的 patch 通过 marker 机制追加到目标 Topic Card，支持 dry-run 和人工审阅确认。

## 快速开始

```bash
# 安装
pip install -e ".[dev]"

# mock 模式分析本地字幕文件（P0-A 默认）
python -m podcast_research --subtitle-file data/subtitles/sample.srt

# mock 模式分析 YouTube 视频字幕（P0-B）
python -m podcast_research --youtube-url "https://www.youtube.com/watch?v=VIDEO_ID" --mock

# 指定字幕语言优先级
python -m podcast_research --youtube-url "https://www.youtube.com/watch?v=VIDEO_ID" --youtube-lang "zh-Hans,en" --mock

# 指定关注点和分析深度
python -m podcast_research --subtitle-file your_subtitle.srt --focus "新能源,港股,AI算力" --depth deep

# 查看报告
cat data/reports/sample_report.md

# 运行测试
python -m pytest tests/ -v
```

## 报告库查询（P1-A）

分析命令生成的报告自动入库，可通过 `reports` 子命令查询：

```bash
# 列出所有报告
python -m podcast_research reports list
python -m podcast_research reports list --source youtube --limit 10

# 查看报告详情
python -m podcast_research reports show 1
python -m podcast_research reports show 1 --full    # 输出完整 Markdown

# 搜索报告（LIKE 匹配报告内容、投资标的、逻辑链）
python -m podcast_research reports search "NVIDIA"

# 汇总投资标的
python -m podcast_research reports targets

# 来源统计
python -m podcast_research reports sources
```

## 启动本地 API 服务（P1-B）

启动本地只读 API 服务，可通过 HTTP 访问报告库：

```bash
# 启动服务
python -m podcast_research serve

# 自定义 host 和 port
python -m podcast_research serve --host 127.0.0.1 --port 8000

# 开发模式（代码变更自动重载）
python -m podcast_research serve --reload
```

启动后访问：
- API 文档 (Swagger): http://127.0.0.1:8000/docs
- 健康检查: http://127.0.0.1:8000/api/health
- 报告列表: http://127.0.0.1:8000/api/reports?limit=20
- 报告详情: http://127.0.0.1:8000/api/reports/1
- 核心观点: http://127.0.0.1:8000/api/reports/1/views
- 搜索: http://127.0.0.1:8000/api/search?q=NVIDIA

### API 端点一览

| 端点 | 说明 |
|------|------|
| `GET /api/health` | 健康检查 |
| `GET /api/reports` | 报告列表（?limit=20&source=youtube） |
| `GET /api/reports/{id}` | 报告详情（含 views/signals/markdown） |
| `GET /api/reports/{id}/views` | 报告投资观点 |
| `GET /api/reports/{id}/signals` | 报告待验证信号 |
| `GET /api/entities?type=stock&limit=100` | 实体列表 |
| `GET /api/targets?limit=100` | 投资标的汇总 |
| `GET /api/sources` | 来源统计 |
| `GET /api/search?q=NVIDIA&limit=20` | 搜索报告 |

> 注意：API 为本地只读服务，不支持分析任务提交、报告编辑或删除。默认绑定 127.0.0.1:8000。

## YouTube 频道关注（P1-E + P1-F）

```bash
# 播种默认 Tech/AI 频道包（4 个核心频道，幂等+自愈）
python -m podcast_research channels seed-tech-ai

# 按标签过滤频道
python -m podcast_research channels list --tag ai
python -m podcast_research channels list --priority core

# 管理频道标签
python -m podcast_research channels tag 1 --add "ai,tech"
python -m podcast_research channels tag 1 --remove "macro"
python -m podcast_research channels tag 1 --set "ai,tech,vc"

# 关注频道
python -m podcast_research channels add "https://www.youtube.com/@allin" --name "All-In Podcast"

# 刷新频道视频列表（获取最新 20 个视频）
python -m podcast_research channels refresh 1 --limit 20

# 查看频道视频
python -m podcast_research channels videos 1

# 分析指定视频（真实 LLM）
python -m podcast_research channels analyze-video --video-id "HGbA6ze0_3M" --focus "AI投资,美股" --no-mock

# dry-run 检查
python -m podcast_research channels analyze-video --video-id "HGbA6ze0_3M" --dry-run
```

注意：
- 默认使用 mock provider，真实 LLM 需显式 `--no-mock`
- 已分析过的视频默认跳过，避免重复
- `--dry-run` 模式只检查不分析
- `seed-tech-ai` 幂等+自愈，重复执行不会重复插入，已存在但配置缺失的频道自动补齐

### 频道视频分析自动补全元数据（P2-A2.1）

通过 `channels analyze-video` 生成的报告会自动携带频道和视频元数据：

- **来源频道**：从 channels 表获取频道名称和链接
- **视频信息**：视频标题、URL、发布日期
- **频道标签**：自动展示在报告数据来源部分
- **默认关注点**：如果未指定 `--focus`，自动使用频道的 `default_focus`

这些元数据会传递到报告 Markdown、API 响应和 HTML 页面中，提升报告可读性和来源可追溯性。

## 跨频道质量评估（P2-A2）

```bash
# 终端展示所有报告评估统计
python -m podcast_research eval reports

# 按频道过滤
python -m podcast_research eval reports --channel "BG2Pod"

# 导出 CSV（供后续分析）
python -m podcast_research eval export --output data/eval/prompt_v2_eval.csv

# 导出 Markdown 总结
python -m podcast_research eval summary --output data/eval/prompt_v2_summary.md
```

评估统计字段：
- 报告 ID、频道名、视频 ID、prompt 版本、模型
- 观点数、技术洞察数、非关注项数、实体数、风险数、待验证信号数
- 证据类型分布、相关性分布、AI 价值链分布
- 泛化标的计数（Broad Market / Economy 等过泛对象）
- 未知发言人计数、时间范围分布
- 报告状态（ok / empty / generic_targets）

泛化标的检测列表：Broad Market、Economy、Investors、Consumers、Society、AI Industry、Technology Sector、Market、Companies、Startups。

## 长视频分块分析（P2-B）

长视频（>50K 字符或 >1000 段字幕）自动启用分块分析，解决 token 超限问题：

```bash
# 长视频自动 chunking（默认行为）
python -m podcast_research --youtube-url "VIDEO_URL" --focus "AI投资,科技公司" --no-mock

# 强制启用 chunking
python -m podcast_research --youtube-url "VIDEO_URL" --focus "AI投资" --no-mock --chunked

# 自定义 chunk 参数
python -m podcast_research --youtube-url "VIDEO_URL" --no-mock --chunked \
  --chunk-size 30000 --chunk-overlap 2000

# 禁用 chunking（长视频时 WARNING）
python -m podcast_research --youtube-url "VIDEO_URL" --no-mock --no-chunking

# 频道视频 chunking
python -m podcast_research channels analyze-video VIDEO_ID \
  --focus "科技公司,商业模式" --no-mock --chunked
```

### Chunking 策略

- **触发条件**：chars > 50000 或 segments > 1000（自动）或 `--chunked`（手动）
- **分块**：按 segment 边界切分，每块 30000 字符，块间 2000 字符重叠
- **提取**：每块独立调用 LLM extract_facts
- **合并**：去重 + compaction（investment_views ≤ 12，entities ≤ 40 等）
- **渲染**：合并后只生成一份最终报告

### 注意事项

- 短视频行为完全不变，不强制 chunking
- Chunking 会增加 API 调用次数（N 块 = N 次 LLM 调用），需注意成本
- 任一 chunk 失败会中止整个分析（后续版本将支持 partial mode）
- 默认 pytest 使用 mock provider，不调用真实 LLM

## Obsidian Vault 导出（P2-C）

将 SQLite 中的 YouTube 报告导出到 Obsidian Vault，形成可浏览、可双链的知识库：

```bash
# Dry-run 预览（推荐先执行）
python -m podcast_research obsidian export \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --source youtube \
  --prompt-version tech_ai_v2 \
  --dry-run

# 正式导出
python -m podcast_research obsidian export \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --source youtube \
  --prompt-version tech_ai_v2

# 按频道导出（大小写不敏感，部分匹配）
python -m podcast_research obsidian export \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --channel "Acquired" \
  --dry-run

# 只导出有频道信息的报告（跳过 UnknownChannel）
python -m podcast_research obsidian export \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --only-with-channel \
  --dry-run

# 导出指定报告
python -m podcast_research obsidian export --report-id 150

# 覆盖已存在文件
python -m podcast_research obsidian export --overwrite --limit 5
```

### 导出内容

| 目录 | 内容 |
|------|------|
| `01_Reports/` | 单视频报告（YAML frontmatter + Markdown） |
| `05_Channels/` | 频道卡片（Recent Reports 自动追加） |
| `99_System/Report Index.md` | 报告索引表 |
| `99_System/Export Log.md` | 导出日志 |

### 文件命名

`01_Reports/YYYY-MM-DD_ChannelName_VideoId.md`

### Metadata Backfill

导出时自动补齐缺失的频道元数据（channel_name / video_title / published_at 等）：

1. `extraction_json.source_info` 中已有值（最高优先）
2. `channel_videos` + `channels` 联表查询（按 video_id 匹配）
3. fallback: `UnknownChannel` / video_id

Backfill 仅在 export runtime 生效，不修改数据库。

### 导出筛选

| 参数 | 行为 |
|------|------|
| `--channel "Name"` | 只导出频道名匹配的报告（大小写不敏感，部分匹配） |
| `--only-with-channel` | 跳过无法解析出频道信息的报告 |
| `--source youtube` | 只导出 YouTube 来源（v1 默认） |
| `--prompt-version` | 按 prompt 版本过滤 |

### Vault 配置

在 `.env` 中配置默认 Vault 路径：

```env
OBSIDIAN_VAULT_PATH=D:\KinocNote\ai-investing-vault\科技AI投资知识库
```

注意：
- 默认不自动导出，需显式执行 CLI 命令
- 已存在文件默认 skip，不覆盖用户手工编辑
- `--overwrite` 可强制覆盖
- Vault 路径必须已存在，工具不创建根目录
- v1 仅导出 YouTube 报告，不做 Topic/Company/Claim 卡片

### UnknownChannel 清理（P2-C.1）

旧的导出可能在频道元数据缺失时生成 `UnknownChannel` 文件。清理工具通过 video_id 查询 `channel_videos + channels` 表尝试补齐：

```bash
# Dry-run 预览（推荐先执行）
python -m podcast_research obsidian cleanup-unknown \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --dry-run

# 执行迁移（旧文件移到 99_System/UnknownChannel_Backup/）
python -m podcast_research obsidian cleanup-unknown \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --apply
```

行为：
- **dry-run**：只检测分析，不修改文件。输出 Rich 表格展示每个文件的 video_id、backfilled channel、建议新文件名、action
- **apply**：对可识别的文件重新导出为正确 channel 文件，旧文件**移到** `99_System/UnknownChannel_Backup/`（不删除）
- 无法识别的文件标记为 `manual_review`，保持原样
- `--overwrite` 覆盖已存在的目标文件
- 建议在 P2-D Topic / Company Card 前清理 UnknownChannel

### Channel Card 同步（P2-C.2）

根据 `01_Reports/` 中报告的 frontmatter，补齐和同步 `05_Channels/` 下的频道卡片：

```bash
# Dry-run 预览（推荐先执行）
python -m podcast_research obsidian sync-channel-cards \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --dry-run

# 正式同步（创建缺失卡片 + 追加 Recent Reports）
python -m podcast_research obsidian sync-channel-cards \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库"

# 只同步指定频道
python -m podcast_research obsidian sync-channel-cards \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --channel "Latent Space"
```

行为：
- 扫描 `01_Reports/*.md` 的 YAML frontmatter，按 channel 分组
- 如果 `05_Channels/{Channel}.md` 不存在 → 创建新卡片
- 如果卡片已存在 → 只追加新的 `## Recent Reports` 链接（不覆盖用户手工内容）
- 已存在的 report link 不重复追加
- UnknownChannel / 空 channel 的 report 自动跳过
- `--channel` 大小写不敏感部分匹配
- `--overwrite` 可强制重写整个卡片
- 不修改 `01_Reports/` 中的文件

### Topic / Company Card 生成（P2-D）

从 `01_Reports/` 中提取主题和公司实体，生成 `02_Topics/` 和 `03_Companies/` 卡片：

```bash
# Dry-run 预览（推荐先执行）
python -m podcast_research obsidian generate-cards \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --dry-run

# 正式生成
python -m podcast_research obsidian generate-cards \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库"

# 只生成 Topic Cards
python -m podcast_research obsidian generate-cards --topics-only --dry-run

# 只生成 Company Cards
python -m podcast_research obsidian generate-cards --companies-only --dry-run

# 只处理指定频道的报告
python -m podcast_research obsidian generate-cards \
  --channel "Latent Space" --dry-run
```

行为：
- 扫描 `01_Reports/*.md`，从 hashtag（`#tag`）和 Core Investment Views 表格提取 topic
- 从 Entities 区和表格目标列提取 company 实体
- 缺失卡片自动创建，已有卡片只追加 Source Reports
- 已存在的 report link 不重复追加
- 生成 `99_System/Topic Index.md`、`Company Index.md`、`Card Generation Log.md`
- 不调用 LLM，纯 deterministic 生成
- 默认不覆盖用户手工内容
- `--overwrite` 可强制重写

### Card Cleanup & Classification（P2-D.1）

清理 deterministic card generation 产生的分类噪音：

```bash
# Dry-run 预览（推荐先执行）
python -m podcast_research obsidian cleanup-cards \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --dry-run

# 正式清理
python -m podcast_research obsidian cleanup-cards \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --apply

# 只清理 Company Cards
python -m podcast_research obsidian cleanup-cards --companies-only --dry-run

# 只清理 Topic Cards
python -m podcast_research obsidian cleanup-cards --topics-only --dry-run
```

行为：
- 检测 Company Cards 中明显非公司的卡片（如 CPU Supply、Enterprise SaaS、Kubernetes）
- 将非公司卡片迁移到 `02_Topics/`，旧文件移到 `99_System/Card_Cleanup_Backup/`
- 合并同义 Topic 别名（如 Ai Agent → AI Agents）
- 更新 Topic Index / Company Index / Card Cleanup Log
- 不直接删除文件，不调用 LLM
- 不确定项标记 manual_review，apply 时不处理

### Topic Taxonomy Consolidation（P2-D.2）

将 Topic Cards 分层为 Core / Emerging / Long-tail / Manual Review，合并同义别名：

```bash
# Dry-run 预览（推荐先执行）
python -m podcast_research obsidian consolidate-topics \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --dry-run

# 正式执行（合并别名 + 标记 status + 生成 taxonomy index）
python -m podcast_research obsidian consolidate-topics \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --apply

# 只处理 core topics
python -m podcast_research obsidian consolidate-topics --core-only --dry-run

# 禁用别名合并
python -m podcast_research obsidian consolidate-topics --no-merge-aliases --apply
```

行为：
- 25 个 Core Topics（AI Infrastructure / AI Agents / Semiconductor 等）标记为 `status: core`
- 同义别名自动合并到 canonical name（如 ai-infra → AI Infrastructure）
- 多报告非核心 topic → emerging，单报告 → long_tail
- 被合并的旧 Topic Card 移到 `99_System/Topic_Consolidation_Backup/`
- 生成 `99_System/Topic Taxonomy.md`（分层展示 Core / Emerging / Long-tail / Manual Review）
- 更新 Topic Index 和 Topic Consolidation Log
- 不删除文件，不调用 LLM

### Topic Taxonomy Final Hardening（P2-D.2.1）

在进入 LLM-WIKI 动态维护前，修正 generic emerging topics 和 canonical casing：

```bash
# 复用 consolidate-topics 命令
python -m podcast_research obsidian consolidate-topics \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --dry-run

python -m podcast_research obsidian consolidate-topics \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --apply
```

行为：
- **Generic topic guard**：Application / Model / Enterprise / 企业级 / Capital Market 等 generic 名称被强制合并到对应 canonical core topic
- **Canonical casing**：Ai For Science → AI for Science（保留正确大小写）
- **扩展 alias map**：50+ 同义别名映射到 canonical name
- 被合并的旧 Topic Card 移到 `99_System/Topic_Consolidation_Backup/`
- 更新 Topic Taxonomy.md / Topic Index / Consolidation Log
- 不删除文件，不调用 LLM

### LLM-WIKI Dynamic Maintenance（P2-E）

基于 Source Reports 为 Topic/Company Cards 生成 LLM patch proposals，采用 patch review 模式，不直接修改卡片：

```bash
# Dry-run 预览（不调用 LLM，只显示将处理哪些 topics）
python -m podcast_research llm-wiki generate-patches \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --core-only \
  --dry-run

# Mock 模式（生成占位 patch，用于测试）
python -m podcast_research llm-wiki generate-patches \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --topic "AI Agents" \
  --mock

# 真实 LLM 模式（调用 OpenAI-compatible API）
python -m podcast_research llm-wiki generate-patches \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --topic "AI Agents" \
  --no-mock

# 处理所有 core topics
python -m podcast_research llm-wiki generate-patches \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --core-only \
  --no-mock
```

行为：
- **Patch review 模式**：LLM 生成 patch proposal 写入 `00_Inbox/LLM_Patches/`，不直接修改 `02_Topics/` 或 `03_Companies/`
- **Context building**：读取 topic card 的 Source Reports，提取相关 sections（Core Investment Views / Tech Insights / Risks / Tracking Signals / Entities / Source Quotes）
- **LLM constraints**：不输出投资建议，不制造事实，每个 key claim 必须绑定 source report，证据不足写入 Open Questions
- **Patch structure**：包含 Proposed Current Understanding / Key Claims / Related Companies / Related Topics / Open Questions / Timeline / Evidence Notes
- **Mock mode**：生成占位 patch 用于测试，不调用真实 LLM
- **Safety**：不修改 source cards，patch 文件仅供人工审阅
- 支持 `--topic` 指定单个 topic，`--core-only` 处理所有 core topics
- 支持 `--max-reports` 限制每个 topic 使用的 source reports 数量（默认 5）

### Real Patch Validation（P2-E.1）

生成的 patch 需要在应用前进行人工审阅和质量校验：

```bash
# 验证所有 patches
python -m podcast_research llm-wiki validate-patches \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库"

# 验证单个 patch
python -m podcast_research llm-wiki validate-patches \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --patch "00_Inbox/LLM_Patches/topic_AI_Agents_20260530_155112.md"
```

**真实 LLM 验证流程：**

```bash
# 1. 先只跑 1 个 topic（不要批量生成）
python -m podcast_research llm-wiki generate-patches \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --topic "AI Agents" \
  --no-mock

# 2. 验证 patch 结构完整性
python -m podcast_research llm-wiki validate-patches \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库"

# 3. 人工打开 patch 文件，逐项核对 Review Checklist
# 4. 确认无误后，在 P2-E.2 中执行 apply
```

**Patch 质量保障：**
- 每个 patch 包含 YAML frontmatter（含 provider/model/prompt_version/generated_at/status）
- 每个 patch 末尾包含 9 项 Review Checklist
- `validate-patches` 自动检查 frontmatter、target card、source reports、必要章节
- `auto_apply` 永远为 `false`，patch apply 必须人工确认

### Patch Apply（P2-E.2）

通过审阅的 patch 可安全应用到目标 Topic Card：

```bash
# Dry-run 预览（不写文件，展示将应用的 sections）
python -m podcast_research llm-wiki apply-patch \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --patch "00_Inbox/LLM_Patches/topic_AI_Agents_20260530_155112.md" \
  --dry-run

# 真实 apply（必须显式 --apply + --confirm-reviewed）
python -m podcast_research llm-wiki apply-patch \
  --vault "D:\KinocNote\ai-investing-vault\科技AI投资知识库" \
  --patch "00_Inbox/LLM_Patches/topic_AI_Agents_20260530_155112.md" \
  --apply \
  --confirm-reviewed
```

**Apply 行为：**
- 使用 `<!-- LLM-WIKI:BEGIN/END patch_id -->` marker 包裹追加内容（可追踪、可回滚）
- 不覆盖已有 section 内容，只追加
- 不存在的 section 自动创建
- 同一 patch 重复 apply 被拒绝（通过 marker 检测）
- 不修改 Source Reports、Company Cards、frontmatter 用户自定义字段
- 写 `99_System/Patch_Apply_Log.md` 记录 apply 历史

## 全文搜索索引（P1-D）

```bash
# 重建搜索索引（新增报告后执行）
python -m podcast_research reports rebuild-index

# 搜索
python -m podcast_research reports search "NVIDIA"
```

搜索策略：优先 FTS5 全文检索，不可用时自动 fallback 到 LIKE 搜索。搜索结果标记 `match_type`：`fts` 或 `like-fallback`。

## 启动本地报告查看页面（P1-C）

启动服务后可在浏览器中查看 HTML 报告页面：

```bash
# 启动服务（同时提供 API 和 HTML 页面）
python -m podcast_research serve

# 打开以下页面
```

浏览器访问：
- 首页: http://127.0.0.1:8000/
- 报告库: http://127.0.0.1:8000/reports
- 报告详情: http://127.0.0.1:8000/reports/1
- 搜索: http://127.0.0.1:8000/search
- API 文档: http://127.0.0.1:8000/docs

页面功能：
- 报告列表（支持 ?source=youtube&limit=50 过滤）
- 报告详情（核心观点矩阵、待验证信号、完整 Markdown 正文）
- 全文搜索（标的、逻辑链、报告内容）
- 极简 CSS，无前端框架依赖

## 真实 LLM 使用（后续阶段）

```bash
# 1. 配置 .env（从 .env.example 复制并填入）
cp .env.example .env
# 编辑 .env，设置 LLM_PROVIDER=openai-compatible 和 LLM_API_KEY

# 2. 使用真实 LLM
python -m podcast_research --subtitle-file your_subtitle.srt --no-mock
```

> P0 阶段仅使用规则引擎 mock provider，不调用真实 LLM API。

### Prompt v2（P2-A1）

Tech/AI Investing Prompt v2 相比 v1 的核心改进：

- **内容分类**：investment_views / tech_industry_insights / non_focus_items / uncertain_items 四级分层
- **evidence 强约束**：10 个 evidence_type 枚举，有具体数字不得标记为 unsupported_claim
- **speaker fallback**：unknown_speaker / podcast_participant / low 统一规则
- **time_horizon 必填**：immediate / short_term / medium_term / long_term / unknown
- **AI 价值链标注**：ai_value_chain_layer / technology_driver / business_impact 新字段
- **实体标准化**：NVIDIA / Alphabet / TSMC 等自动归一化
- **报告结构固定**：11 个标准章节，核心观点矩阵扩展为 11 列
- **P2-A1 Hardening**：泛 target 黑名单（Broad Market / Economy / AI Industry 等）、investment_relevance 严格分级（high ≤ 40%，无证据不得高于 medium）、TechIndustryInsight 增加 topic_tags

> mock 模式不反映 prompt v2 的真实语义质量。真实 LLM 验证见下方。

### Mock Provider 定位说明

mock provider 是基于中文关键词匹配的规则引擎，**仅用于工程闭环测试**：

- 验证 pipeline 串联、数据入库、报告渲染等工程链路是否正常
- 不代表真实语义抽取能力
- 英文字幕、复杂投资观点、隐含逻辑链需要使用真实 LLM provider
- 默认 `pytest` 使用 mock provider，不调用真实 API
- 真实 LLM 测试作为手动集成验证，不进入默认测试

英文视频在 mock 模式下输出 0 条观点是**预期行为**，不是 bug。

## 手动集成测试：YouTube + Real LLM

在 .env 中配置好真实 LLM 后，可对 YouTube 视频进行端到端验证：

```bash
python -m podcast_research \
  --youtube-url "https://www.youtube.com/watch?v=jJRAvZNGUvI" \
  --focus "美股,AI投资,宏观政策,科技股" \
  --depth standard \
  --no-mock
```

**注意事项**：

- 需要在 `.env` 中配置 `LLM_PROVIDER`、`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`
- 调用真实 LLM API 会产生费用
- 长视频（如 2000+ 段字幕）可能触发 token 上限，当前未实现分块处理
- 如果失败，优先检查 `logs/` 目录下的日志文件
- **绝对不要**将 API Key 打印到终端或写入日志

## 项目结构

```text
src/podcast_research/
  cli.py                 # Typer CLI 命令
  config.py              # .env 加载 + 全局配置
  logging_config.py      # 日志：console + RotatingFileHandler
  analysis/
    models.py            # Pydantic v2 数据模型（两阶段抽取 schema）
    pipeline.py          # 主分析流水线（analyze + analyze_from_transcript）
  adapters/
    base.py              # TranscriptAdapter 基类 + TranscriptResult
    youtube_transcript.py # YouTube 字幕 Adapter（youtube-transcript-api）
  subtitles/
    parser.py            # SRT/VTT/TXT 解析器
    cleaner.py           # 清洗：去空行、合并短段、去重、标记广告
  llm/
    base.py              # LLMProvider 抽象基类
    mock_provider.py     # 规则引擎 mock（基于关键词匹配）
    openai_compatible_provider.py  # 真实 LLM 预留骨架
    prompts.py           # prompt 模板
  db/
    models.py            # SQLAlchemy ORM（5 张核心表）
    session.py           # SQLite session 管理
    repository.py        # 数据写入 + 查询方法
    channel_repository.py # 频道/视频 Repository + metadata lookup
    fts.py               # FTS5 全文搜索索引
  api/
    app.py               # FastAPI app 工厂
    schemas.py           # Pydantic 响应 schema
    routes/
      health.py          # GET /api/health
      reports.py         # GET /api/reports/*, /api/entities, /api/targets, /api/sources
      search.py          # GET /api/search
  web/
    routes.py            # HTML 页面路由（/reports, /reports/{id}, /search）
    templates/           # Jinja2 模板（base, reports_list, report_detail, search, error）
    static/style.css     # 极简 CSS
  utils/
    hash.py              # 文件哈希（字幕重复检测）
    timestamp.py         # 时间戳格式化
    youtube.py           # YouTube URL 解析
tests/                    # pytest 测试
data/
  subtitles/             # 字幕文件存放
  reports/               # 报告输出
  transcripts/youtube/   # YouTube 字幕缓存
  podcast_analyst.db     # SQLite 数据库（运行时生成）
logs/                     # 日志
```

## 核心原则

1. 不输出买卖建议
2. 不把 AI 归纳伪装成嘉宾原话
3. 核心观点必须绑定原文引用和时间戳
4. 不确定信息必须显式标注
5. 所有外部依赖通过 adapter 隔离

## 当前不做

- 小宇宙链接解析、xyz-dl 字幕下载
- 真实 LLM API 调用（P0 仅支持手动集成验证，不进入自动化测试）
- React / Next.js / Vue 等前端框架
- Whisper 转写、多平台 RSS
- 向量数据库、PDF/Word 导出
- 团队协作、云端同步
- 登录鉴权、报告编辑/删除

## 路线图

| 阶段 | 目标 | 状态 |
|------|------|------|
| P0-A | CLI 本地字幕分析闭环（mock LLM） | **已完成** |
| P0-B | CLI YouTube 字幕 Adapter（mock LLM） | **已完成** |
| P1-A | CLI 报告库查询（list/show/search/targets/sources） | **已完成** |
| P1-B | FastAPI 只读 API（/api/reports/*, /api/search 等） | **已完成** |
| P1-C | Jinja2 极简 HTML 报告页面 | **已完成** |
| P1-D | SQLite FTS5 搜索增强 | **已完成** |
| P1-E | YouTube 频道关注库与视频列表获取 | **已完成** |
| P1-F | Tech/AI 默认频道包 + Channel Tags | **已完成** |
| P2-A1 | Tech/AI Investing Prompt v2 + Schema 增强 | **已完成** |
| P2-A2.1 | Channel/Video Metadata Propagation | **已完成** |
| P2-A2 | 跨频道 Prompt v2 质量评估 | **已完成** |
| P2-B | 长视频分块分析（Long Transcript Chunking） | **已完成** |
| P2-C | Obsidian Vault 导出 v1 | **已完成** |
| P2 | 小宇宙链接导入 + 其他增强 | 待启动 |
| P3 | 历史报告全局查询（FTS5 + LLM 问答） | 待启动 |
| P4 | 多期观点对比 | 待启动 |

## 许可证

Private / 个人使用