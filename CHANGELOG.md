# Changelog

## P3-A — Persistent Ingest Job Queue (2026-07-01)

P3 定位：把 podcast_research 从"可运行的数据处理流水线"升级为"可恢复、可审计、可被 Agent 查询的投资知识库后端"。

### P3-A Done
- **IngestJob model**: 22-column SQLAlchemy model (`db/models.py`) — identity, status, preview JSON, action, result, references, timestamps
- **Migration**: `_migrate_ingest_jobs_table` with partial UNIQUE index on `(job_key, status) WHERE pending_preview` for dedup
- **IngestJobManager**: 14 methods in `sources/ingest_jobs.py` — create, find, list, confirm, mark_failed, retry, resume, expire, count
- **Dual-write (Phase 1)**: All four ingest entry points write to both memory stores and `ingest_jobs`:
  - URL import preview/confirm
  - File upload preview/confirm  
  - Tracked source profile/create
  - Tracked source entry refresh/import
- **Dashboard**: falls back to `ingest_jobs` counts when memory stores are empty (restart recovery)
- **CLI**: `ingest list/show/retry/resume` commands
- **Tests**: 54 new tests in `tests/test_ingest_jobs.py` — CRUD, dedup, status transitions, retry, expiry, restart recovery, dual-write, CLI smoke
- **Result**: 1439 tests (1438 passed, 1 pre-existing flaky), ruff clean

## P3-B/C — Vault Lint + Review Queue (2026-07-01)

### P3-B Vault Lint Done
- **5 lint rules** in `workspace/vault_lint.py`: frontmatter_invalid, frontmatter_missing, dead_wikilink, duplicate_report, orphan_card
- **CLI**: `vault-lint --vault <path>` with `--rules`, `--exclude`, `--json`, `--write-review` flags
- **Runner**: `run_vault_lint()` returns structured findings dict; `write_lint_to_review()` batch-creates review items
- **Integration**: `--write-review` auto-creates review_items with dedup (same source_path + item_type + open)

### P3-C Review Queue Done
- **ReviewItem model**: 12-column SQLAlchemy model (`db/models.py`) — item_type, severity, status, title, description, source_ref, source_path, suggested_action_json, resolution_note, timestamps
- **Migration**: `_migrate_review_items_table` with indexes on status, item_type, severity
- **ReviewItemManager** (`sources/review_items.py`): create_item, create_from_lint_findings, list_items, get_item, count_by_status, accept/skip/resolve
- **Status machine**: `open → accepted | skipped | resolved`; `accepted → resolved`
- **8 item_types**: lint_frontmatter_invalid, lint_frontmatter_missing, lint_dead_wikilink, lint_duplicate_report, lint_orphan_card, entity_duplicate_candidate, patch_review, manual
- **Dedup**: Same source_path + item_type + open → skip creation on re-lint
- **CLI**: `review list/show/accept/skip/resolve`
- **Patch Review compat**: `patch_review` item_type reserved; existing Patch Review system untouched

### Test Results
- **53 new tests** in `tests/test_vault_lint_review.py`
- All existing tests pass; ruff clean

### Planned
- **P3-D**: MCP Server — 9 read-only tools via Python `mcp` package
- Design docs: `docs/P3_PLAN.md`, `docs/INGEST_QUEUE_DESIGN.md`, `docs/VAULT_LINT_REVIEW_QUEUE_DESIGN.md`, `docs/MCP_SERVER_DESIGN.md`
- Project rules: `docs/PROJECT_RULES.md`

## P2-S.3.5 — Source Ingestion Consistency & Release Hardening (2026-07-01)

### Status & Action Label Unification
- Added `SOURCE_STATUS_LABELS`, `ACTION_LABELS`, `SUGGESTED_ACTION_LABELS`, `TRACKING_ELIGIBILITY_LABELS` to `sources/models.py`
- Unified 12 status labels: `preview_ready`→"待确认", `imported`→"已入库", `existing`→"已发现", `failed`→"失败", `degraded`→"解析退化"
- Unified 11 action labels for buttons: `confirm_archive`→"确认归档", `batch_import`→"导入选中项", etc.
- `ACTION_DESCRIPTIONS` keys changed from `ActionEnum` to `str` for simpler template usage
- Updated 5 templates to use template variables instead of hardcoded text

### Dashboard Statistics Consistency
- Verified YouTube channel count ↔ active channels, tracked source count ↔ enabled sources, pending entries, URL/file previews, SourceArchive count all consistent with sub-pages

### Skipped Test Recovery
- `test_full_flow_preview_then_confirm` unskipped — root cause was Windows MAX_PATH (pytest temp dir + archive subdirs > 260 chars)
- Fixed by using `tempfile.mkdtemp(prefix="v_")` for short vault path instead of `tmp_path / "v"`

### Documentation
- New `docs/SOURCE_INGESTION.md` — four entry points, unified processing pipeline, status/action labels, boundaries & limitations
- Updated CLAUDE.md, ROADMAP.md, README.md, CHANGELOG.md, TODO.md, ARCHITECTURE.md, DEV_GUIDE.md

### Naming & Boundary Audit
- Confirmed `confirm_archive` only used for SourceArchive, `existing` only for tracked source entries
- Verified Report not misused by web/file import, Deep Notes boundaries correct, LLM profiler stub safe
- Unsupported tracked URLs correctly redirect to single URL import

### Result
- 1385 tests, ruff clean, 80 Python modules, 1 skipped test recovered

## P2-S.3.3 + P2-S.3.4 — File Upload & Unified Sources Dashboard (2026-06-30)

### P2-S.3.3: User Text File Upload Preview & Archive
- New modules: `sources/file_profile.py`, `sources/file_content_extractor.py`, `sources/file_import_preview.py`
- Supports `.md` / `.txt` / `.html` / `.htm` upload with encoding detection (UTF-8 / UTF-8-SIG / GB18030)
- `UploadedFileProfile` → `ExtractedFileContent` → `FileImportPreview` pipeline
- Content extraction: Markdown H1 as title, HTML script/style/nav stripping via BeautifulSoup
- Import eligibility gate: text ≥ 200 chars, parse_quality ≠ minimal, content_hash required
- Conflict detection: same_content_hash (blocker), same_filename (warning), same_title (info)
- Scan dirs: SourceArchive, ReportMaterial, DeepNotes
- Web routes: GET `/sources/files/import`, POST `/sources/files/preview`, POST `/sources/files/confirm`
- File size limit: 5MB. Temp file cleanup on confirm. Filename sanitization.
- 46 tests (45 passed, 1 skipped due to config_store fixture interaction)

### P2-S.3.4: Source Ingestion Dashboard & Unified Navigation
- New `/sources` dashboard page with four entry cards + stats bar + pending summary + quick-add
- `_build_sources_dashboard_context()` gathers counts from DB, vault, and in-memory preview stores
- Navigation: main nav → `/sources`, sub-nav adds "📋 总览", dashboard button updated
- 19 tests

### Code Consolidation (P2-S.3.x refactor)
- **ActionEnum unified**: added `confirm_archive`, `FileImportPreview` now uses `ActionEnum` instead of bare `str`
- **ConflictDetector unified**: added `detect_for_file()`, removed standalone `detect_file_conflicts()` from `file_import_preview.py`
- **Performance fix**: `generate_watchlist_brief` — pre-compute canonical views outside per-item loop (7.3s → 0.69s, dashboard 10.4s → 2.8s)
- 1384 tests, ruff clean

## P2-S — External Sources & Deep Notes Export (2026-06-26)
- **P2-S.1**: External Derived Source Adapter (`external_html_notes`, `allin_zh_notes`) with retry engine
- **P2-S.2**: Deep Notes markdown export, health check, report linking, episode linking
- **P2-S.2.2**: External fetch reliability — retry with backoff (0.5/1.5/3.0s), error classification
- **P2-S.3.1**: Generic Web URL Import Preview — `GenericWebPageAdapter`, `ImportPreview`, `ConflictDetector`
- Web routes: GET `/sources/import`, POST preview/confirm; Source archive output
- 1261 tests, ruff clean

## P2-O — Engineering Stabilization (2026-06-05)
- GitHub Actions CI (push/PR auto pytest + ruff)
- ruff lint config (76 per-file-ignores)
- CSS cache busting (content hash)
- 7 Playwright UI smoke tests
- docs/ARCHITECTURE.md, docs/RELEASE_CHECKLIST.md
- Runtime observability & task failure UX (P2-O.2/O.2.1)
- 930 tests

## P2-N — Research Brief Quality Tuning (2026-06-05)
- Dashboard markdown artifact cleanup
- Entity/topic classification noise fix
- Research Brief: statistical → explanatory style
- Watchlist Brief: four-section evidence categorization
- 904 tests

## P2-M — Channel Filters & Source Pages (2026-06-05)
- 8 pill-button channel filters (watchlist-matched, by status, by tag)
- Source pages: card-based DOM restructure + CSS hard-fix
- 904 tests

## P2-L — First-run Vault Setup (2026-06-01)
- `/setup/vault` initialization wizard
- Dashboard Vault health detection + one-click repair
- Non-empty directory safety (no overwrite)

## P2-K — Watchlist + Task Queue (2026-06-01)
- Watchlist matching engine + brief generation
- Background task queue (analyze/sync jobs)
- Task failure diagnostics (5-level classification)
- Rerun with archive workflow

## P2-H — Obsidian Workspace Hardening (2026-05-31)
- Home Dashboard + Knowledge Map + Review Queue
- Curation status: raw/indexed/reviewed/enhanced/archived
- Relation backfill (related_topics/related_companies)
- Long-tail topic normalization
- 664 tests

## P2-F — Claim & Signal System (2026-05-30)
- Deterministic extraction from reports and patches
- Card generation with frontmatter + source reports
- Status management, similarity detection, tracking updates
- CLI: claims list/show/update-status/update-meta/find-similar/backlog
- CLI: signals list/show/update-status/update-meta/find-similar/backlog/update-tracking/add-update/tracking-backlog

## P2-E — LLM-WIKI Dynamic Maintenance (2026-05-30)
- Patch Review lifecycle: generate → validate → apply → rollback → reject
- LLM generates patch proposals from source reports
- YAML frontmatter + 9-item Review Checklist per patch
- LLM-WIKI:BEGIN/END markers for safe apply
- Topic + Company card patch generation
- Validation gate: frontmatter, target card, source reports, sections

## P2-D — Topic/Company Card Ecosystem (2026-05-30)
- Deterministic card generation from reports
- Card cleanup: company→topic migration, alias merge
- Topic taxonomy: 25 core topics, 50+ alias map
- Status: core/emerging/long_tail/manual_review
- Generic topic guard + canonical casing

## P2-C — Obsidian Vault Export (2026-05-30)
- Export YouTube reports to Obsidian Vault
- YAML frontmatter + structured Markdown
- Channel cards + system index + export log
- UnknownChannel cleanup with DB backfill
- Channel card reconciliation

## P2-B — Long Video Chunking (2026-05-30)
- Map-Reduce: segment-boundary split → per-chunk extraction → dedup + compaction → single report
- Auto-detect (>50K chars or >1000 segments)
- Manual: --chunked / --no-chunking / --chunk-size / --chunk-overlap

## P2-A — Prompt v2 + Cross-Channel Eval (2026-05-29)
- Tech/AI Investing Prompt v2: 10 evidence types, AI value chain, entity normalization
- target_name blacklist, investment_relevance strict grading
- Cross-channel eval: reports/export/summary, 10 generic target detection

## P1-F — Channel Tags (2026-05-28)
- channels: tags/priority/default_focus/notes fields
- seed-tech-ai: 5 core channels, idempotent + self-healing
- CLI: channels tag --add/--remove/--set, list --tag/--priority

## P1-E — YouTube Channel Management (2026-05-28)
- Channel subscription + yt-dlp video list fetch
- Video dedup (channel_id + video_id), status tracking
- CLI: channels add/list/refresh/videos/analyze-video

## P1-D — FTS5 Search (2026-05-28)
- SQLite FTS5 virtual table, CJK whitespace tokenization
- Search: FTS5 first → LIKE fallback

## P1-C — HTML Web Console (2026-05-27)
- Jinja2 templates, minimal CSS, no frontend framework
- Routes: /reports, /reports/{id}, /search

## P1-B — FastAPI API (2026-05-27)
- Read-only JSON API, 9 endpoints
- create_app() factory, serve command

## P1-A — CLI Report Library (2026-05-27)
- reports list/show/search/targets/sources subcommands
- Rich table output, LIKE search

## P0-B — YouTube Adapter (2026-05-27)
- youtube-transcript-api integration
- Transcript cache, language fallback
- YouTube URL validation

## P0-A — Local Subtitle Analysis (2026-05-27)
- SRT/VTT/TXT parsing + cleaning
- Mock LLM pipeline (keyword rule engine)
- Markdown report + SQLite storage
- CLI: --subtitle-file, --focus, --depth
