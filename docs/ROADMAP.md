# Roadmap

## Current State

SignalVault has moved from a YouTube/podcast transcript research tool to a multi-source investment research assistant.

Current verified collection count:

```bash
python -m pytest --collect-only -q  # 1993 tests collected
```

Backend/CLI capabilities through P7 are implemented. The active product work is now frontend experience alignment:

- Daily change radar
- Multi-source workbench
- Guided import flow
- Unified investment knowledge search

See `docs/FRONTEND_EXPERIENCE_EXECUTION_PLAN.md`.

## Completed

| Phase | Description | Status |
|---|---|---|
| P0-A | CLI local subtitle analysis with mock LLM | ✅ |
| P0-B | YouTube transcript adapter | ✅ |
| P1-A | CLI report library | ✅ |
| P1-B | FastAPI read-only API | ✅ |
| P1-C | Jinja2 Web Console | ✅ |
| P1-D | SQLite FTS5 report search | ✅ |
| P1-E | YouTube channel management | ✅ |
| P1-F | Tech/AI seed channel pack + tags | ✅ |
| P2-A | Prompt v2 + schema enhancement + cross-channel evaluation | ✅ |
| P2-B | Long video Map-Reduce chunking | ✅ |
| P2-C | Obsidian Vault export + channel cards | ✅ |
| P2-D | Topic/Company card ecosystem + taxonomy | ✅ |
| P2-E | LLM-WIKI patch review/apply/rollback | ✅ |
| P2-F | Claim & Signal card system | ✅ |
| P2-H | Workspace management | ✅ |
| P2-K | Watchlist + task queue + failure diagnostics | ✅ |
| P2-L | First-run Vault setup + repair | ✅ |
| P2-M | Channel filters + source pages + visual polish | ✅ |
| P2-N | Research brief quality tuning | ✅ |
| P2-O | Engineering stabilization + UI smoke tests | ✅ |
| P2-S | External sources, deep notes, URL/file import, unified sources dashboard | ✅ |
| P3 | Persistent ingest queue, Vault lint, Review Queue, MCP Server | ✅ |
| P4 | PDF text extraction, PDF analysis, page-level evidence | ✅ |
| P5 | Unified search + lightweight knowledge graph + MCP tools | ✅ |
| P6 | ZSXQ read-only subscription import + topic analysis | ✅ |
| P7 | Error taxonomy, operation logs, diagnostics center, diagnostic bundle, recovery actions, CLI integration | ✅ backend/CLI |

## Active

| Track | Description | Status |
|---|---|---|
| UI-X | SignalVault frontend experience refactor using four prototypes | ✅ Implemented (Phase 8 validated) |

## Implemented Frontend Phases

| Phase | Description | Status |
|---|---|---|
| UI-X-1 | Global shell and SignalVault brand | ✅ |
| UI-X-2 | Dashboard as investment change radar | ✅ |
| UI-X-3 | Source workbench for YouTube/Web/PDF/File/ZSXQ/tracked sources | ✅ |
| UI-X-4 | Guided import entry and preview flow | ✅ |
| UI-X-5 | Unified knowledge search page | ✅ |
| UI-X-6 | Report detail evidence trail UX | ✅ |
| UI-X-7 | Diagnostics and operation log Web pages | ✅ |

## Not Planned

- React / Next.js / Vue frontend frameworks
- Whisper local transcription
- RAG / vector databases / AI Q&A
- PDF/Word export
- Team collaboration / cloud sync
- Login/authentication
- Automated scheduled fetching
- ZSXQ write-capable client
- Writing MCP tools
