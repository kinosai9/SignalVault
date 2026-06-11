# Architecture

## Project Positioning

Local investment media research tool. Input: YouTube/podcast subtitles and local subtitle files. Output: structured investment views, targets, risk alerts, tracking signals, source quotes → Markdown reports, SQLite DB, Obsidian Vault.

**This is not an investment advice tool.**

## Tech Stack

Python 3.12+, Typer, FastAPI, uvicorn, Pydantic v2, SQLAlchemy 2.x, SQLite, Jinja2, httpx, python-dotenv, youtube-transcript-api, yt-dlp, pytest, rich, logging.

## Layer Architecture

```
CLI (cli.py)  ←→  Web Console (web/)  ←→  API (api/)
        │               │                    │
        └───────────────┼────────────────────┘
                        │
              services/ (analyze, job, sync, watchlist)
                        │
        ┌───────────────┼───────────────┐
        │               │               │
   adapters/        analysis/        llm/
   (data input)    (pipeline)     (LLM providers)
        │               │               │
        └───────────────┼───────────────┘
                        │
                   db/ (SQLAlchemy + SQLite)
                        │
        ┌───────────────┼───────────────┐
        │               │               │
  exporters/      llm_wiki/      claim_signal/
  (Obsidian)    (patch review)   (card system)
                        │
                  workspace/
            (vault management)
```

## Module Boundaries

### adapters/ — Data Source Adapters

Convert subtitles/text from different sources into unified `TranscriptSegment` format. Does NOT touch LLM logic.

| Adapter | Source | Status |
|---------|--------|--------|
| LocalSubtitleAdapter | .srt/.vtt/.txt files | ✅ (via subtitles/parser) |
| YouTubeTranscriptAdapter | youtube-transcript-api | ✅ |
| ChannelVideoAdapter | yt-dlp metadata | ✅ |
| YtDlpAdapter | yt-dlp subtitle fallback | Not implemented |
| XyzDlAdapter | xyz-dl (xiaoyuzhou) | Not implemented |

### llm/ — LLM Provider Adapters

Model provider abstraction only. Does NOT handle data source logic.

| Provider | Description | Status |
|----------|-------------|--------|
| MockLLMProvider | Rule engine (keyword match), default | ✅ |
| OpenAICompatibleProvider | httpx + OpenAI-compatible API | ✅ |

**Rule: adapters adapt data, llm adapts models. Don't move LLM providers into adapters/.**

### analysis/ — Pipeline

- `pipeline.py` — main analysis pipeline. `analyze()` and `analyze_from_transcript()` share `_run_pipeline()`.
- `chunking.py` — Map-Reduce chunking for long transcripts (>50K chars or >1000 segments).
- `models.py` — Pydantic v2 data models (ExtractionResult, InvestmentView, etc.).

### db/ — Data Layer

6 core tables: reports, investment_views, entities, tracking_signals, channels, channel_videos.

- `repository.py` — read/write queries
- `channel_repository.py` — channel/video queries + metadata lookup
- `fts.py` — FTS5 full-text search (CJK whitespace tokenization)
- `session.py` — SQLite session management

### api/ — REST API (FastAPI)

Read-only JSON API. `create_app()` factory pattern. Routes: health, reports, search.

### web/ — Web Console (Jinja2)

HTML pages served by the same FastAPI app. `web/` and `api/` are separated: api returns JSON, web returns HTML. 20 templates, no frontend framework, minimal CSS.

### services/ — Business Logic

- `analyze_service.py` — video analysis orchestration
- `job_service.py` — background job queue management
- `sync_service.py` — knowledge sync (report → Obsidian)
- `watchlist_matcher.py` — watchlist-based video matching

### exporters/ — Output

- `obsidian.py` — export reports to Obsidian Vault (YAML frontmatter + Markdown)
- `markdown_utils.py` — shared Markdown utilities

### llm_wiki/ — LLM-WIKI Dynamic Maintenance

Patch Review lifecycle: LLM generates patch proposals → human reviews → safe apply with markers → rollback support.

### claim_signal/ — Claim & Signal System

Deterministic extraction of claims and signals from reports and patches. Card generation, status management, similarity detection, tracking updates.

### workspace/ — Vault Workspace Management

Vault scanning, dashboard generation, curation status, relation backfill, long-tail cleanup, brief generation.

## Pipeline Rules

1. Don't rewrite the pipeline. `analyze()` and `analyze_from_transcript()` share `_run_pipeline()`.
2. Changes to pipeline must not break local subtitle path.
3. YouTube mode enters through `analyze_from_transcript()`. Don't modify `analyze()` signature.

## LLM Two-Phase Extraction

1. Fact extraction → JSON (InvestmentView, TechIndustryInsight, etc.)
2. Report Markdown generation

Core view fields must include: target_name, target_type, view_direction, logic_chain, evidence_type, evidence_strength, risk_warning, speaker_label, speaker_confidence, source_quote, timestamp, uncertainty.

No source_quote + timestamp → not allowed in core view matrix.
