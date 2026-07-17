# SignalVault Frontend Experience Execution Plan

> Status: Phase 0 complete preparation  
> Scope: Web Console information architecture and UX implementation plan  
> Rule: keep backend data contracts unchanged; do not refactor core analysis/source/db services

## 1. Goal

SignalVault is now a multi-source investment research assistant, not only a YouTube subtitle analysis tool. The frontend should guide non-technical users through the daily research workflow:

1. See what changed today.
2. Import or fix information sources.
3. Read report details when needed.
4. Search the investment knowledge base by topic, company, signal, evidence, and relevance.
5. Understand failures and recovery actions without reading CLI docs.

The immediate priority is to make everyday entry points smooth before adding specialist pages.

## 2. Current Capability Scan

### 2.1 Existing Web Pages

| Area | Current route | Current user value | Gap |
|---|---|---|---|
| First entry | `/dashboard` | Shows research brief, watchlist, recommendations, recent reports | Needs to become a change-oriented daily radar |
| Reports | `/reports`, `/reports/{id}` | Lists reports and shows views/signals/markdown | Evidence trail and source-type differences are not prominent enough |
| Search | `/search` | Searches reports | Does not yet expose P5 unified search result types and graph context |
| YouTube source | `/sources/channels`, `/sources/channels/{id}/videos` | Channel and video candidate management | Good functional coverage, needs integration into source workbench |
| Web URL import | `/sources/import` | URL preview and confirm import | Flow is technical and separate from other import types |
| File upload | `/sources/files/import` | Text file preview and archive | Copy is outdated for current PDF capability; PDF has no Web flow |
| Tracked sources | `/sources/tracked` | Fixed web source profile, refresh, entries, import | Should be surfaced as one source lane in the workbench |
| Tasks | `/tasks`, `/tasks/{id}`, `/tasks/{id}/logs` | Background task status and logs | Failure guidance can reuse P7 recovery actions |
| Watchlist | `/watchlist`, `/watchlist/settings` | User focus areas | Should feed the daily radar and search filters |
| LLM-WIKI patches | `/patches`, `/patches/{id}` | Patch review lifecycle | Should remain specialist, surfaced via review queue |
| Setup | `/setup/obsidian` | First-run Vault initialization | C3 wizard step 3 |

### 2.2 Implemented Backend/CLI Capabilities Not Fully Reflected in Web

| Capability | Implemented surface | Frontend status | UX implication |
|---|---|---|---|
| Persistent ingest queue | `ingest list/show/retry/resume`, `IngestJobManager` | Partially used by imports, no unified queue page | Source workbench should show pending, failed, expired, retryable items |
| Review Queue | `review list/show/accept/skip/resolve`, `ReviewItemManager` | No dedicated Web queue | Users need one place for PDF OCR, Vault lint, ZSXQ, patch/entity issues |
| PDF preview/extract/analyze | `pdf preview/extract/analyze`, `sources/pdf_*` | No Web page | Add source lane and guided import flow; preserve CLI-only advanced actions if needed |
| ZSXQ read-only import/analyze | `zsxq doctor/groups/import-topic/sync/analyze` | No Web page | Add source lane, status, login guidance, topic import/analyze entry |
| Unified search | `search` CLI, `db.unified_search.unified_search()` | `/search` still report-centric | Replace or extend with report/view/signal/entity result cards |
| Knowledge graph | `graph rebuild/neighborhood/evidence-trail/export` | No Web page | Search and report detail should show neighborhood/evidence trail links |
| Diagnostics summary | `doctor`, `diagnostics summary`, `DiagnosticsCenter` | No Web page/API route | Add diagnostics center and dashboard health cards |
| Diagnostic bundle | `diagnostics bundle`, `export_diagnostic_bundle()` | No Web action | Add export entry for support/debug flow |
| Operation logs | `logs list/show`, `OperationLogManager` | No Web page | Add operation timeline and connect failed actions to recovery suggestions |
| Error taxonomy/recovery actions | `diagnostics.summary` recovery registry | CLI only | Render user-facing failure banners and action buttons |

## 3. Contract Freeze

This frontend effort must not destabilize the recently completed backend work.

### 3.1 Allowed Changes

- Jinja templates under `src/signalvault/web/templates/`
- Web CSS under `src/signalvault/web/static/style.css`
- Web route glue in `src/signalvault/web/routes.py` when it only calls existing managers/services
- API route additions for already implemented read-only data, if required by Web rendering
- Tests for changed DOM, route behavior, and UI smoke
- Documentation updates under `docs/`

### 3.2 Avoided Changes

- No changes to `analysis/pipeline.py`
- No changes to LLM prompts or provider contracts
- No database schema changes unless a backend bug is discovered and explicitly approved
- No React/Vue/Next.js introduction
- No source ingestion behavior rewrite
- No automatic external upload for OCR or ZSXQ auth
- No investment advice wording
- No changes that remove existing routes or CLI commands

### 3.3 Data Contract Rule

Frontend pages should consume existing structures:

- `ReportDetail`, report views/signals, and markdown
- `IngestJobManager` dict outputs
- `ReviewItemManager` dict outputs
- `DiagnosticsSummary.to_dict()`
- `OperationLogManager` dict outputs
- `UnifiedSearchResult`
- Knowledge graph query dicts

If a page needs a different presentation shape, adapt it in Web route context builders, not in core services.

## 4. Target Information Architecture

### 4.1 Primary Navigation

| New nav label | Current route candidate | Purpose |
|---|---|---|
| 变化雷达 | `/dashboard` | Daily entry: what changed, what needs attention |
| 信息源 | `/sources` | Source health, import, queue, recovery |
| 知识库搜索 | `/search` | Unified search across reports/views/signals/entities/evidence |
| 报告库 | `/reports` | Durable report archive |
| 任务与诊断 | `/tasks`, new `/diagnostics` | Running work, failures, system health |

Specialist pages remain accessible from these hubs:

- Watchlist settings
- Patch review
- Channel management
- Tracked source detail
- Review Queue
- Operation logs

### 4.2 Four Prototype Templates To Adopt

| Prototype | Production target | Adoption role |
|---|---|---|
| `investment_radar.html` | `/dashboard` | Daily change radar layout |
| `source_workbench.html` | `/sources` | Multi-source health and queue workbench |
| `guided_import.html` | new/import entry plus existing import pages | Guided source selection and precheck pattern |
| `knowledge_search.html` | `/search` | Unified search result layout and graph context |

## 5. Phase Plan

### Phase 1: Global Shell and Brand

Objective: make SignalVault identity and daily workflow visible everywhere.

Tasks:

- Replace product name in Web shell with `SignalVault`
- Add subtitle `多源投资研究助手`
- Adopt prototype icon asset or equivalent local static asset
- Adjust primary nav to workflow labels
- Move inline source sub-nav styles into CSS classes

Validation:

- `/dashboard`, `/sources`, `/search`, `/reports` screenshots
- `tests/test_web_pages.py`
- `tests/test_ui_smoke.py`

### Phase 2: Dashboard As Change Radar

Objective: turn the first screen into a decision-oriented daily radar.

Tasks:

- Add first-screen summary cards: new signals, reinforced views, divergence/risk, pending review
- Keep research brief and watchlist, but reorder by user action priority
- Add source/diagnostics side panels using existing data
- Show recovery-oriented notices instead of raw technical errors

Data sources:

- `_build_dashboard_context()`
- `DiagnosticsCenter.get_summary()`
- `IngestJobManager`
- `ReviewItemManager`

Validation:

- Screenshot: normal dashboard
- Screenshot: dashboard with open review/pending ingest
- Screenshot: no Vault / setup redirect behavior

### Phase 3: Source Workbench

Objective: make all source types understandable from one page.

Tasks:

- Redesign `/sources` around source lanes: YouTube, Web, PDF/File, ZSXQ, Tracked Source
- Add unified pending queue from ingest jobs, tracked entries, review items
- Add right-side "needs your action" diagnostics
- Link existing source pages without changing their contracts
- Update outdated file upload copy that says PDF is unsupported

Data sources:

- Existing channel/tracked source queries
- `IngestJobManager.count_by_status()` and recent jobs
- `ReviewItemManager.list_items()`
- `DiagnosticsCenter` ZSXQ/PDF/Vault summaries

Validation:

- Screenshot: source workbench with empty/normal state
- Screenshot: source workbench with pending/failed/review items
- Existing source page tests must still pass

### Phase 4: Guided Import Entry

Objective: unify import decision-making without rewriting existing import handlers.

Tasks:

- Add a guided import hub route, for example `/sources/import/new`
- Offer source choices: YouTube, Web URL, PDF/File, ZSXQ Topic, Tracked Source, Queue
- Route users into existing pages/actions where available
- For not-yet-Web-native flows such as ZSXQ/PDF analysis, first expose safe precheck/status and CLI guidance or thin Web wrappers around existing services
- Standardize preview pages around: source identity, quality, conflicts, recommendation, confirm action

Validation:

- Screenshot: source type chooser
- Screenshot: preview with recommendation
- Screenshot: low-quality/blocked state

### Phase 5: Unified Knowledge Search

Objective: upgrade `/search` from report search to knowledge search.

Tasks:

- Use `unified_search()` for result generation
- Add result type tabs: all, reports, views, signals, entities
- Add source/type/direction/status filters
- Render page/timestamp/source_quote in result cards
- Add links to report detail and evidence trail
- Add entity neighborhood summary when the query matches an entity

Validation:

- Screenshot: mixed result types
- Screenshot: PDF page evidence
- Screenshot: entity result with neighborhood
- Existing `/api/search` tests remain stable unless intentionally extended

### Phase 6: Report Detail Evidence UX

Objective: make report detail useful for investment research review.

Tasks:

- Make report title/source/focus first-class instead of `报告 #id`
- Highlight views/signals with evidence, timestamp/page, source quote
- Add source-type-specific evidence labels: YouTube timestamp, PDF page, ZSXQ topic
- Add "view evidence trail" links when graph data exists

Validation:

- Screenshot: YouTube report detail
- Screenshot: PDF report detail
- Screenshot: search highlight entry

### Phase 7: Diagnostics and Operations

Objective: expose P7 reliability work to non-technical users.

Tasks:

- Add `/diagnostics` summary page
- Add `/operations` recent operation timeline
- Render subsystem cards, recent failures, recovery actions, diagnostic bundle export
- Reuse recovery action titles/descriptions from `diagnostics.summary`
- Keep commands visible as fallback, but make the first action understandable in plain Chinese

Validation:

- Screenshot: all ok
- Screenshot: attention/blocker
- Screenshot: operation failure detail

## 6. Testing and Screenshot Checklist

Every production template/CSS change should run:

```bash
python -m pytest tests/test_web_pages.py -v
python -m pytest tests/test_ui_smoke.py -v
```

For route additions or cross-page refactors:

```bash
python -m pytest tests/ -q
```

Screenshot targets:

- `/dashboard`
- `/sources`
- `/sources/import`
- `/sources/files/import`
- `/search`
- `/reports/1`
- `/tasks`
- `/diagnostics` after added

Suggested screenshot directory:

```text
docs/ui_prototypes/screenshots/implementation/
```

## 7. Phase 0 Findings

1. The backend has moved faster than the Web UI. PDF, ZSXQ, unified search, graph, diagnostics, and operation logs are implemented but not yet fully visible to users.
2. Existing Web routes should be preserved. They already cover many operational details and tests rely on them.
3. The first frontend pass should not chase complete feature parity page by page. It should create coherent hubs that route users to existing capabilities.
4. The most important user-facing gap is not aesthetics; it is action clarity: users need to know what changed, what is waiting, what failed, and what to do next.
5. Documentation has drift: older Source Ingestion docs still describe pre-PDF scope. Frontend implementation should follow latest README, acceptance reports, and actual code.

## 8. Recommended First Implementation Batch

1. Global brand/navigation shell.
2. Dashboard change radar.
3. Source workbench.
4. Unified search.

This batch touches the pages users visit every day and avoids destabilizing specialist backend flows.
