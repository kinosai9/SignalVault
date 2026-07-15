# P7 Acceptance Report — User-facing Reliability & Diagnostics

## 1. P7 Goal

Make SignalVault's reliability visible and actionable for non-technical users. When something fails, users should understand what happened, know what to do next, and be able to export diagnostic information for remote troubleshooting.

## 2. Sub-phase Delivery

### P7-A: Error Taxonomy ✅

**File:** `diagnostics/errors.py`

- `ErrorSeverity` enum: info / warning / error / blocker
- `ErrorCategory` enum: 11 categories (source / auth / permission / extraction / analysis / llm / database / vault / search_graph / mcp / config)
- `ErrorRecord` dataclass: 18 fields with `suggested_actions` in Chinese
- `ErrorCodeRegistry`: register, get, list_all, list_by_category, list_by_severity
- 30 built-in error codes covering P3-P6 scenarios
- `create_error_record()` factory + `map_exception_to_error()` (7 Python types)
- `review_item_to_error_record()` (13 review item_types → error codes)

**Tests:** 28 in `tests/test_diagnostics_errors.py`

### P7-B: Operation Log ✅

**File:** `diagnostics/operation_log.py` + `db/models.py` (OperationLog ORM)

- `OperationLog` ORM: 16 columns + 4 indexes, auto-created on `init_db()`
- `OperationLogManager`: start, succeed, fail, get, list_operations, count_by_status, recent_failures
- 24 VALID_OPERATION_TYPES (zsxq/pdf/ingest/vault/review/search/graph/mcp/system)
- `_sanitize_metadata()` redacts api_key/token/password/secret
- CLI: `logs list` / `logs show`

**Tests:** 20 in `tests/test_operation_log.py`

### P7-C: Diagnostics Center ✅

**File:** `diagnostics/summary.py`

- `DiagnosticsCenter.get_summary()` aggregating 9 subsystems
- `SubsystemStatus` dataclass: name, label, status (ok/attention/blocked/unknown), summary, counts, issues, suggested_actions
- `DiagnosticsSummary` dataclass: overall_status, 9 subsystems, recent_failures
- `RecoveryAction` dataclass + 9 registered actions
- CLI: `diagnostics summary` / `doctor`

**Tests:** 28 in `tests/test_diagnostics_summary.py`

### P7-D: Diagnostic Bundle Export ✅

**File:** `diagnostics/bundle.py`

- `DiagnosticBundleBuilder` producing timestamped zip with 9 files
- 3-tier redaction: REDACT_KEYS (12), TRUNCATE_KEYS (8), EXISTENCE_KEYS (3)
- CLI: `diagnostics bundle --output <path>`
- Web: `GET /tasks/diagnostics/export` (added in Phase 2 optimization)

**Tests:** 34 in `tests/test_diagnostic_bundle.py`

### P7-E: Recovery Actions ✅

- 9 standard recovery actions registered in `DiagnosticsCenter`
- Action titles and descriptions in Chinese
- Rendered in Web diagnostics page (`/tasks`)

**Tests:** 27 in `tests/test_recovery_actions.py`

### P7-F: CLI + Web/API hookup ✅

- CLI: Full diagnostics CLI (`diagnostics summary`, `diagnostics bundle`, `doctor`, `logs list/show`)
- Web: Diagnostics center at `/tasks` with subsystem cards, suggested actions, operation log timeline
- Web: Diagnostic bundle export button at `/tasks`
- Operation log wiring: `graph rebuild`, `zsxq doctor`, `zsxq analyze`

### P7-S: Closeout ✅

- This acceptance report
- Documentation alignment: README, CHANGELOG, ROADMAP updated

## 3. Test Results

| Module | Tests |
|--------|-------|
| test_diagnostics_errors.py | 28 |
| test_operation_log.py | 20 |
| test_diagnostics_summary.py | 28 |
| test_diagnostic_bundle.py | 34 |
| test_recovery_actions.py | 27 |
| **P7 total** | **137** |

Current repository collection baseline (2026-07-15): 2013 tests. P7 module counts above remain the phase acceptance snapshot.

## 4. Explicitly NOT Done

- Automatic remediation (only suggests actions, does not execute them)
- Remote telemetry / error reporting
- Real-time monitoring / alerting
- Performance profiling
- Structured logging framework migration
- Standalone `/diagnostics` page (merged into `/tasks` per Phase 8 validation decision)

## 5. Acceptance Conclusion

P7-A through P7-F all delivered. P7-S complete. Diagnostics system provides non-technical users with understandable failure messages, actionable recovery suggestions, and exportable diagnostic bundles for remote troubleshooting.
