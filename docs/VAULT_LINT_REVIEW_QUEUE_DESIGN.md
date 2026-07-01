# P3-B + P3-C: Vault Lint & Review Queue 设计

> 状态：Design | P3 | 2026-07-01

## 第一部分：P3-B Vault Lint

### 一、问题陈述

Obsidian vault 是 podcast_research 的核心输出产物。随着使用时间增长，vault 中的质量问题会累积：

| 问题类型 | 例子 | 影响 |
|----------|------|------|
| frontmatter 损坏 | YAML 格式错误、缺少 `---` 闭合 | Obsidian Dataview/插件无法解析 |
| 死 wikilink | `[[不存在的页面]]` | 用户点击后 404 |
| 重复报告 | 同一视频导出了两次 | 污染搜索结果 |
| 孤立卡片 | Topic 卡片创建后无关联报告 | 卡片无实际内容支撑 |
| 命名不一致 | NVIDIA / Nvidia / nvidia | 知识图谱碎片化 |
| 过期内容 | 90 天未更新的 watchlist brief | 误导用户以为是最新的 |

### 二、Lint Rules 详细设计

#### Rule 1: frontmatter_format

```
检测：YAML frontmatter 是否能被 yaml.safe_load() 正确解析
严重度：error
扫描范围：vault 下所有 *.md
auto-fix：否（需要人工判断原意）
```

实现：
```python
def lint_frontmatter(filepath: Path) -> list[LintFinding]:
    text = filepath.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return []  # 无 frontmatter，不报错
    # 查找第二个 ---
    end = text.find("---", 3)
    if end == -1:
        return [LintFinding(
            rule="frontmatter_format",
            severity="error",
            message="frontmatter 未闭合，缺少第二个 ---",
            file=str(filepath),
        )]
    yaml_str = text[3:end]
    try:
        yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        return [LintFinding(
            rule="frontmatter_format",
            severity="error",
            message=f"frontmatter YAML 解析失败: {e}",
            file=str(filepath),
        )]
    return []
```

#### Rule 2: required_fields

```
检测：特定类型文件缺少必填 frontmatter 字段
严重度：warning
扫描范围：01_Reports/*.md, 02_Topics/*.md, 03_Companies/*.md, 06_Claims/*.md, 07_Signals/*.md
auto-fix：补默认值（--apply）
```

必填字段表：

| 文件目录 | type 值 | 必填字段 |
|----------|---------|----------|
| 01_Reports/ | report | type, source_type, channel, video_id, analyzed_at |
| 02_Topics/ | topic | type, status |
| 03_Companies/ | company | type, status |
| 06_Claims/ | claim | type, claim_id, status |
| 07_Signals/ | signal | type, signal_id, status |

#### Rule 3: dead_wikilink

```
检测：正文中的 [[wikilink]] 目标文件不存在
严重度：warning
扫描范围：vault 下所有 *.md
auto-fix：删除链接文本（保留链接文字）--apply
```

```python
def lint_dead_wikilinks(filepath: Path, all_files: set[str]) -> list[LintFinding]:
    text = filepath.read_text(encoding="utf-8")
    wikilinks = re.findall(r'\[\[([^\]|#]+)(?:[|#][^\]]+)?\]\]', text)
    findings = []
    for link in wikilinks:
        target = f"{link}.md"
        if target not in all_files:
            findings.append(LintFinding(
                rule="dead_wikilink",
                severity="warning",
                message=f"[[{link}]] 指向不存在的文件",
                file=str(filepath),
                detail=link,
            ))
    return findings
```

#### Rule 4: duplicate_report

```
检测：01_Reports/ 中 content_hash 相同或 title 相同的文件
严重度：warning
扫描范围：01_Reports/*.md
auto-fix：标记较旧的文件 frontmatter 中 duplicate_of: <新文件路径>
```

#### Rule 5: orphan_card

```
检测：Topic/Company/Claim/Signal 卡片没有关联任何 report
严重度：info
扫描范围：02_Topics/*.md, 03_Companies/*.md, 06_Claims/*.md, 07_Signals/*.md
auto-fix：标记 frontmatter 中 orphan: true
```

#### Rule 6: naming_inconsistency

```
检测：同一实体的名称在不同文件中写法不一致
严重度：info
扫描范围：vault 下所有 frontmatter 中的 target_name, company, topic 字段
auto-fix：否（需要人工判断）
```

使用 `TOPIC_CANONICAL_MAP`（现有）和 entity 名称对比：

```python
def lint_naming_inconsistency(vault_path: Path) -> list[LintFinding]:
    # 收集所有 entity 引用
    entity_refs: dict[str, set[str]] = {}
    for md in vault_path.rglob("*.md"):
        fm = parse_frontmatter(md)
        for key in ("company", "topic", "target_name"):
            if key in fm:
                entity_refs.setdefault(fm[key].lower(), set()).add(fm[key])

    # 同一 entity 有多个写法
    findings = []
    for lower, variants in entity_refs.items():
        if len(variants) > 1:
            findings.append(LintFinding(
                rule="naming_inconsistency",
                severity="info",
                message=f"命名不一致: {', '.join(sorted(variants))}",
                detail=sorted(variants),
            ))
    return findings
```

#### Rule 7: stale_content

```
检测：frontmatter 中 updated_at / analyzed_at 超过 90 天
严重度：info
扫描范围：01_Reports/*.md, 02_Topics/*.md, 03_Companies/*.md, 99_System/*Brief*.md
auto-fix：标记 frontmatter 中 stale: true
```

### 三、CLI 设计

```bash
# 运行全部 lint
python -m podcast_research vault-lint --vault /path/to/vault

# 仅运行特定 rules
python -m podcast_research vault-lint --vault /path/to/vault --rules frontmatter,dead_wikilink

# 排除特定 rules
python -m podcast_research vault-lint --vault /path/to/vault --exclude naming_inconsistency

# Auto-fix（慎用）
python -m podcast_research vault-lint --vault /path/to/vault --apply --rules dead_wikilink

# 输出格式
python -m podcast_research vault-lint --vault /path/to/vault --format json
python -m podcast_research vault-lint --vault /path/to/vault --format table  # 默认

# Dry-run（默认，与 --apply 互斥）
python -m podcast_research vault-lint --vault /path/to/vault --dry-run
```

### 四、Web 集成

`GET /lint` → 显示 lint 结果面板，按 rule 分组，按 severity 着色。

在 `/sources` Dashboard 的 pending 区域中新增 lint 计数卡片。

### 五、DB Schema

```sql
CREATE TABLE IF NOT EXISTS lint_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,            -- 每次 lint 运行的 UUID
    rule        TEXT NOT NULL,            -- rule 名称
    severity    TEXT NOT NULL,            -- error / warning / info
    file_path   TEXT NOT NULL,            -- vault 相对路径
    line        INTEGER,                  -- 行号（可选）
    message     TEXT NOT NULL,
    detail      TEXT,                     -- 额外信息（JSON）
    fixed       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  DATETIME NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_lint_run ON lint_results(run_id);
CREATE INDEX IF NOT EXISTS idx_lint_rule ON lint_results(rule);
CREATE INDEX IF NOT EXISTS idx_lint_severity ON lint_results(severity);
```

### 六、测试计划

```
tests/test_vault_lint.py:

class TestFrontmatterLint:
    def test_valid_frontmatter_no_error
    def test_missing_closing_delimiter
    def test_yaml_parse_error
    def test_no_frontmatter_no_error

class TestRequiredFields:
    def test_report_missing_type
    def test_topic_missing_status
    def test_claim_missing_claim_id

class TestDeadWikilink:
    def test_valid_wikilink_no_error
    def test_dead_wikilink_detected
    def test_wikilink_with_alias
    def test_wikilink_with_section

class TestDuplicateReport:
    def test_same_content_hash
    def test_same_title_different_content

class TestOrphanCard:
    def test_topic_with_report_not_orphan
    def test_topic_without_report_is_orphan

class TestNamingInconsistency:
    def test_multiple_variants_detected
    def test_single_variant_no_error

class TestStaleContent:
    def test_fresh_content_not_stale
    def test_90_day_old_is_stale

class TestCLI:
    def test_lint_all_rules
    def test_lint_specific_rules
    def test_lint_json_output
    def test_lint_apply_flag
```

预计 ≥15 tests。

---

## 第二部分：P3-C Review Queue

### 七、问题陈述

当前有多种"待处理"事项分散在不同系统中：

| 事项 | 当前系统 | 入口 |
|------|----------|------|
| Patch 审阅 | Patch Review（llm_wiki/） | `/patches` |
| Claim backlog | Claim CLI | `claims backlog` |
| Signal backlog | Signal CLI | `signals backlog` |
| Card 清理建议 | Card Cleanup | `obsidian cleanup-cards` |
| Topic 合并 | Topic Consolidation | `obsidian consolidate-topics` |
| Lint issues | ✗（不存在） | ✗ |

用户需要去 5+ 个不同地方查看待处理事项，没有统一优先级排序，没有"全部处理完"的全局视图。

### 八、目标

- 统一的 `review_items` 表承载所有需要人工审核的事项
- 统一的 Web 面板（`/reviews`）替代多个分散页面
- 统一状态机：pending → in_review → accepted / rejected / deferred
- 各来源系统（Lint、Patch、Card Cleanup）自动写入 review_items
- 不破坏现有子系统（Patch Review、Claim/Signal CLI 继续独立运行）

### 九、Review Item 类型

| Type | 来源系统 | 自动生成 | 优先级默认值 |
|------|----------|----------|-------------|
| `lint_issue` | Vault Lint (P3-B) | ✓（lint 运行后） | 按 severity: error→high, warning→medium, info→low |
| `patch_proposal` | Patch Generator | ✓（patch 生成后） | medium |
| `entity_merge` | Card Cleanup | ✓（cleanup --dry-run 后） | low |
| `duplicate_report` | Vault Lint / Conflict Detector | ✓ | medium |
| `missing_card` | Workspace Scanner | ✓（workspace refresh 后） | low |
| `stale_content` | Vault Lint | ✓ | low |
| `manual` | 用户 | — | medium |

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
python -m podcast_research reviews list --status pending --type lint_issue

# 查看详情
python -m podcast_research reviews show 1

# 更新状态
python -m podcast_research reviews update 1 --status accepted --note "fixed"

# 自动生成 review items（从 lint 结果）
python -m podcast_research reviews generate --from-lint --run-id <uuid>

# 统计
python -m podcast_research reviews stats
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
