# Developer Guide

## Setup

```bash
pip install -e ".[dev]"
cp .env.example .env   # edit if using real LLM
```

## Run Tests

```bash
python -m pytest tests/ -v              # full suite (mock, no API calls)
python -m pytest --collect-only -q      # currently collects 1908 tests
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
python -m podcast_research --youtube-url "VIDEO_URL" --focus "AI投资,美股" --no-mock
```

- Costs API fees. Check `logs/` on failure.
- Never print API keys to terminal or logs.
- Long videos auto-chunk (N chunks = N API calls).

## Run the App

```bash
python -m podcast_research serve          # API + Web Console at 127.0.0.1:8000
python -m podcast_research serve --reload # dev mode with auto-reload
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
python -m podcast_research --subtitle-file file.srt
python -m podcast_research --youtube-url "URL" --mock

# Reports
python -m podcast_research reports list|show|search|targets|sources
python -m podcast_research reports rebuild-index

# Channels
python -m podcast_research channels add|list|refresh|videos|tag|seed-tech-ai|analyze-video

# Evaluation
python -m podcast_research eval reports|export|summary

# Obsidian
python -m podcast_research obsidian export|cleanup-unknown|sync-channel-cards|generate-cards|cleanup-cards|consolidate-topics|generate-claims-signals
python -m podcast_research obsidian workspace refresh|backfill-relations|refresh-curation-status|polish-report-metadata|cleanup-long-tail-topics|watchlist-brief

# Claims & Signals
python -m podcast_research claims list|show|update-status|update-meta|find-similar|backlog
python -m podcast_research signals list|show|update-status|update-meta|find-similar|backlog|update-tracking|add-update|tracking-backlog

# LLM-WIKI
python -m podcast_research llm-wiki generate-patches|validate-patches|apply-patch|list-applied-patches|rollback-patch|reject-patch

# Ingest / Review / Diagnostics
python -m podcast_research ingest list|show|retry|resume
python -m podcast_research review list|show|accept|skip|resolve
python -m podcast_research doctor
python -m podcast_research diagnostics summary|bundle
python -m podcast_research logs list|show

# Search / Graph
python -m podcast_research search "NVIDIA" --type investment_view --source-type pdf_upload
python -m podcast_research graph rebuild|neighborhood|evidence-trail|export

# PDF
python -m podcast_research pdf preview|extract|analyze

# ZSXQ read-only import
python -m podcast_research zsxq doctor|groups|import-topic|sync|analyze

# MCP
python -m podcast_research mcp-serve
```
