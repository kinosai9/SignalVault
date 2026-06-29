# Changelog

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
