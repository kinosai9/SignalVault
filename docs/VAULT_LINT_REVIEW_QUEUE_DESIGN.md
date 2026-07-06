# P3-B + P3-C: Vault Lint & Review Queue 设计

> 状态：P3-B/C 已实现 | 2026-07-01
> 实现：`workspace/vault_lint.py`, `sources/review_items.py`, `db/models.py` (ReviewItem)

## 第一部分：P3-B Vault Lint（已实现）

### 已实现的 5 条 Lint Rules

| # | Rule | Severity | 检测内容 | Auto-fix |
|---|------|----------|----------|----------|
| 1 | `frontmatter_invalid` | error | YAML 解析失败或缺少闭合 `---` | 否 |
| 2 | `frontmatter_missing` | warning | 必填字段缺失（按文件目录判定类型） | 否 |
| 3 | `dead_wikilink` | warning | `[[wikilink]]` 指向不存在的文件 | 否 |
| 4 | `duplicate_report` | warning | 相同 video_id 或 content_hash | 否 |
| 5 | `orphan_card` | info | Topic/Company/Claim/Signal 无报告引用 | 否 |

必填字段按目录映射：
- `01_Reports/` → type, source_type, channel, video_id, analyzed_at
- `02_Topics/` → type, status
- `03_Companies/` → type, status
- `06_Claims/` → type, claim_id, status
- `07_Signals/` → type, signal_id, status

扫描时排除 `90_`、`99_`、`.trash`、`.obsidian` 目录。

### CLI 使用示例

```bash
# 运行全部 lint 规则
python -m signalvault vault-lint --vault /path/to/vault

# 仅运行指定规则
python -m signalvault vault-lint --vault /path/to/vault --rules dead_wikilink,orphan_card

# 排除某些规则
python -m signalvault vault-lint --vault /path/to/vault --exclude frontmatter_invalid

# JSON 输出
python -m signalvault vault-lint --vault /path/to/vault --json

# Lint 发现写入 review_items
python -m signalvault vault-lint --vault /path/to/vault --write-review
```

### Lint Finding 数据结构

每条 finding 为 dict：
```python
{
    "rule": "dead_wikilink",
    "severity": "warning",
    "file_path": "01_Reports/test.md",
    "message": "[01_Reports/test.md] [[Ghost]] 指向不存在的文件",
    "detail": "wikilink: Ghost",
    "item_type": "lint_dead_wikilink",
}
```

### Runner API

```python
from signalvault.workspace.vault_lint import run_vault_lint, write_lint_to_review

result = run_vault_lint(vault_path, rules=["dead_wikilink"], exclude=["orphan_card"])
# result = {run_id, vault_path, total_findings, findings: list[dict], rule_counts: dict}

created = write_lint_to_review(result["findings"])
# created = number of new review items (deduped)
```

### 问题陈述

Obsidian vault 是 signalvault 的核心输出产物。随着使用时间增长，vault 中的质量问题会累积：

| 问题类型 | 例子 | 影响 |
|----------|------|------|
| frontmatter 损坏 | YAML 格式错误、缺少 `---` 闭合 | Obsidian Dataview/插件无法解析 |
| 死 wikilink | `[[不存在的页面]]` | 用户点击后 404 |
| 重复报告 | 同一视频导出了两次 | 污染搜索结果 |
| 孤立卡片 | Topic 卡片创建后无关联报告 | 卡片无实际内容支撑 |
| 命名不一致 | NVIDIA / Nvidia / nvidia | 知识图谱碎片化 |
| 过期内容 | 90 天未更新的 watchlist brief | 误导用户以为是最新的 |

### 实现概要

5 条 lint rule 已在 `workspace/vault_lint.py` 中实现。每条 rule 是一个独立函数，输入 vault_path，返回 `list[dict]`（findings）。Runner `run_vault_lint()` 协调所有规则，支持 `--rules` 和 `--exclude` 过滤。`write_lint_to_review()` 将 findings 批量写入 `review_items` 表，带去重。

---

## 第二部分：P3-C Review Queue（已实现）

### ReviewItem 表 — 12 列

| # | 列名 | 类型 | 说明 |
|---|------|------|------|
| 1 | `id` | INTEGER PK | 自增主键 |
| 2 | `item_type` | VARCHAR(40) NOT NULL | 8 种类型（见下） |
| 3 | `severity` | VARCHAR(10) | error / warning / info |
| 4 | `status` | VARCHAR(20) | open / accepted / skipped / resolved |
| 5 | `title` | VARCHAR(500) NOT NULL | 简短标题 |
| 6 | `description` | TEXT | 详细说明 |
| 7 | `source_ref` | VARCHAR(200) | 来源标识（如 `lint:dead_wikilink`） |
| 8 | `source_path` | VARCHAR(500) | vault 相对路径 |
| 9 | `suggested_action_json` | TEXT | 建议操作（JSON） |
| 10 | `resolution_note` | TEXT | 处理备注 |
| 11 | `created_at` | DATETIME | 创建时间 |
| 12 | `resolved_at` | DATETIME | 解决时间 |

索引：`idx_review_status`, `idx_review_type`, `idx_review_severity`

### Review Item 类型（已实现 8 种）

| item_type | 来源 | 说明 |
|-----------|------|------|
| `lint_frontmatter_invalid` | Vault Lint | YAML 解析失败 |
| `lint_frontmatter_missing` | Vault Lint | 必填字段缺失 |
| `lint_dead_wikilink` | Vault Lint | wikilink 目标不存在 |
| `lint_duplicate_report` | Vault Lint | 重复 report |
| `lint_orphan_card` | Vault Lint | 孤立卡片 |
| `entity_duplicate_candidate` | 手动/未来 | 实体重复候选 |
| `patch_review` | Patch Review（未来） | 预留，现有 Patch Review 不受影响 |
| `manual` | 用户 | 手动创建 |

### 状态机

```
open ──→ accepted ──→ resolved
  │
  ├──→ skipped
  │
  └──→ resolved

允许的转换：
  open → accepted / skipped / resolved
  accepted → resolved
  skipped → (终端)
  resolved → (终端)
```

### 去重规则

同一 `source_path + item_type + status = 'open'` 的组合不重复创建。
再次 lint 同一文件不会产生重复的 review item。

### CLI 使用示例

```bash
# 列出所有 open 的 review items
python -m signalvault review list --status open

# 按类型过滤
python -m signalvault review list --type lint_dead_wikilink

# 查看详情
python -m signalvault review show 1

# 接受 / 跳过 / 解决
python -m signalvault review accept 1 --note "已修复"
python -m signalvault review skip 1 --note "暂不处理"
python -m signalvault review resolve 1 --note "已解决"

# Lint 后自动创建 review items
python -m signalvault vault-lint --vault /path/to/vault --write-review
```

### `--write-review` 行为

1. `vault-lint` 运行所有规则 → 生成 findings 列表
2. 对每条 finding，检查 `review_items` 表中是否已有相同 `(item_type, source_path, open)` 的记录
3. 若无 → 创建新的 review item（status=open）
4. 若有 → 跳过（不重复创建）
5. 返回创建的条数

### 与 Patch Review 的关系

- `patch_review` item_type 已预留
- 现有 Patch Review 系统（`llm_wiki/` 模块、`/patches` 页面、CLI 命令）完全保留
- 未来可通过适配层让 patch 生成时自动写入 review_items
- 当前阶段不做修改

### 十、DB Schema

```sql
CREATE TABLE IF NOT EXISTS review_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    review_type     TEXT NOT NULL,            -- lint_issue / patch_proposal / entity_merge / ...
    status          TEXT NOT NULL DEFAULT 'pending',
        -- pending / in_review / accepted / rejected / deferred

    -- Reference to source
    source_system   TEXT NOT NULL,            -- lint / patch_generator / card_cleanup / ...
    source_id       TEXT,                     -- lint_result.id / patch filename / ...
    source_url      TEXT,                     -- Web 链接或文件路径

    -- Content
    title           TEXT NOT NULL,            -- 简短标题
    description     TEXT,                     -- 详细说明
    suggestion      TEXT,                     -- 建议操作

    -- Priority
    priority        TEXT NOT NULL DEFAULT 'medium',  -- high / medium / low

    -- Resolution
    resolution_note TEXT,                     -- 处理备注
    resolved_by     TEXT,                     -- 处理人
    resolved_at     DATETIME,

    -- Timestamps
    created_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at      DATETIME NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_review_status ON review_items(status);
CREATE INDEX IF NOT EXISTS idx_review_type ON review_items(review_type);
CREATE INDEX IF NOT EXISTS idx_review_priority ON review_items(priority);
```

### 十一、状态机

```
                    ┌─────────┐
                    │ pending  │ ← 系统自动创建
                    └────┬─────┘
                         │ 用户点击"开始处理"
                    ┌────▼─────┐
                    │ in_review│
                    └────┬─────┘
               ┌─────────┼─────────┐
               │         │         │
          ┌────▼──┐ ┌───▼───┐ ┌───▼────┐
          │accepted│ │rejected│ │deferred│
          └────────┘ └───────┘ └────────┘
                          │
                    ┌─────▼─────┐
                    │  pending  │ ← 可选：重新激活
                    └───────────┘
```

### 十二、Web 面板设计

`GET /reviews`

- 顶部：统计栏（pending 数 / in_review 数 / 按 type 分布）
- 过滤器：按 type、priority、status
- 列表：每行显示 type 图标 + title + priority 标签 + created_at
- 点击进入详情

`GET /reviews/{id}`

- 完整描述
- 源文件链接（lint issue → 跳转到文件；patch → 跳转到 patch detail）
- 建议操作
- 操作按钮：开始处理 / 采纳 / 拒绝 / 推迟

### 十三、与现有 Patch Review 的关系

```
Patch Review (现有)           Review Queue (P3-C)
─────────────────────         ─────────────────────
00_Inbox/LLM_Patches/*.md    review_items 表
patch_detail.html             /reviews/{id}
patches_list.html             /reviews（含 type=patch_proposal）
CLI: llm-wiki apply-patch     Web: 一键 accept → 触发 apply

关联方式：
- patch 生成时 → 同时写入 review_items（review_type=patch_proposal）
- patch 被 apply/reject 时 → 更新 review_items.status
- patch detail 页面底部增加 "查看 Review 项" 链接
```

### 十四、CLI 设计

```bash
# 列出 review items
python -m signalvault reviews list --status pending --type lint_issue

# 查看详情
python -m signalvault reviews show 1

# 更新状态
python -m signalvault reviews update 1 --status accepted --note "fixed"

# 自动生成 review items（从 lint 结果）
python -m signalvault reviews generate --from-lint --run-id <uuid>

# 统计
python -m signalvault reviews stats
```

### 十五、测试计划

```
tests/test_review_queue.py:

class TestReviewItemCRUD:
    def test_create_review_item
    def test_update_status
    def test_status_transition_valid
    def test_status_transition_invalid
    def test_list_by_status
    def test_list_by_type
    def test_list_by_priority

class TestReviewFromLint:
    def test_lint_error_creates_review_item
    def test_lint_warning_creates_review_item
    def test_lint_info_creates_review_item
    def test_fixed_lint_updates_review_status

class TestReviewFromPatch:
    def test_patch_generation_creates_review_item
    def test_patch_apply_updates_review_status
    def test_patch_reject_updates_review_status

class TestReviewWeb:
    def test_reviews_page_loads
    def test_reviews_filter_by_type
    def test_review_detail_shows_source_link
```

预计 ≥15 tests。

---

## 第三部分：共享基础设施

### 十六、`lint_results` → `review_items` 流转

```
vault-lint 运行
  → lint_results 表写入
  → review_items 自动创建（type=lint_issue, source_system=lint）
     - severity=error → priority=high
     - severity=warning → priority=medium
     - severity=info → priority=low

用户在 /reviews 处理 lint_issue
  → accepted: lint_results.fixed = true（下次 lint 不再报告）
  → rejected: lint_results 保留，review_items 标记
  → deferred: review_items 保留，等后续
```

### 十七、不做什么（P3-B + P3-C）

- 不修改现有 Patch Review 的核心逻辑（generate/validate/apply/rollback）
- 不修改现有 Claim/Signal CLI
- 不修改 Card Cleanup/Consolidation 逻辑（只在其输出上追加 review_items 写入）
- Lint 不做语义检查（只做结构和格式检查）
- Review 不做自动决策（所有决策由人工确认）
- 不发送通知/邮件
