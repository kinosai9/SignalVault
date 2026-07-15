# Developer Guide

## Setup

```bash
pip install -e ".[dev]"
cp .env.example .env   # edit if using real LLM
```

## Run Tests

```bash
python -m pytest tests/ -v              # full suite (mock, no API calls)
python -m pytest --collect-only -q      # currently collects 2013 tests
python -m pytest tests/ -x              # stop on first failure
python -m pytest tests/test_cli.py -v   # specific file
```

## Mock Provider

- Default for all tests. Rule engine based on Chinese keyword matching.
- English videos → 0 views is expected behavior in mock mode.
- Never expand English keyword rules just to boost mock output.
- Real LLM tests are manual-only, not in default test suite.

## Real LLM (Manual Verification)

```bash
# Requires .env: LLM_PROVIDER, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
python -m signalvault --youtube-url "VIDEO_URL" --focus "AI投资,美股" --no-mock
```

- Costs API fees. Check `logs/` on failure.
- Never print API keys to terminal or logs.
- Long videos auto-chunk (N chunks = N API calls).

## Run the App

```bash
python -m signalvault serve          # API + Web Console at 127.0.0.1:8000
python -m signalvault serve --reload # dev mode with auto-reload
```

## Conventions

### Naming
- Code, commands, variable names: English
- Comments, docs, commit messages: Chinese for context, English for technical

### Testing
- Every new core feature must add tests.
- Tests use `db_session` / `seeded_db` fixtures for DB isolation.
- Tests use `tmp_path` for file output, never write to real `data/`.
- YouTube adapter tests must mock `YouTubeTranscriptApi`.
- Obsidian tests use `tmp_path` vault, never real vault.

### Commit Messages
- English, concise, describe change intent.
- End with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

### Git
- Push only for cross-device sync, not automatically.
- GitHub repos use SSH protocol.

## Key Commands Reference

```bash
# Analysis
python -m signalvault --subtitle-file file.srt
python -m signalvault --youtube-url "URL" --mock

# Reports
python -m signalvault reports list|show|search|targets|sources
python -m signalvault reports rebuild-index

# Channels
python -m signalvault channels add|list|refresh|videos|tag|seed-tech-ai|analyze-video

# Evaluation
python -m signalvault eval reports|export|summary

# Obsidian
python -m signalvault obsidian export|cleanup-unknown|sync-channel-cards|generate-cards|cleanup-cards|consolidate-topics|generate-claims-signals
python -m signalvault obsidian workspace refresh|backfill-relations|refresh-curation-status|polish-report-metadata|cleanup-long-tail-topics|watchlist-brief

# Claims & Signals
python -m signalvault claims list|show|update-status|update-meta|find-similar|backlog
python -m signalvault signals list|show|update-status|update-meta|find-similar|backlog|update-tracking|add-update|tracking-backlog

# LLM-WIKI
python -m signalvault llm-wiki generate-patches|validate-patches|apply-patch|list-applied-patches|rollback-patch|reject-patch

# Ingest / Review / Diagnostics
python -m signalvault ingest list|show|retry|resume
python -m signalvault review list|show|accept|skip|resolve
python -m signalvault doctor
python -m signalvault diagnostics summary|bundle
python -m signalvault logs list|show

# Search / Graph
python -m signalvault search "NVIDIA" --type investment_view --source-type pdf_upload
python -m signalvault graph rebuild|neighborhood|evidence-trail|export

# PDF
python -m signalvault pdf preview|extract|analyze

# ZSXQ read-only import
python -m signalvault zsxq doctor|groups|import-topic|sync|analyze

# MCP
python -m signalvault mcp-serve
```
