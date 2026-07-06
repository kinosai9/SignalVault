# UI Prototypes

## Purpose

This directory contains standalone front-end prototypes for discussion only.
They are not wired to FastAPI routes, Jinja templates, SQLite, Obsidian, or any
production data contract.

## Prototype Brand

Current prototype naming:

- Product name: `SignalVault`
- Chinese subtitle: `多源投资研究助手`

## Scope Rules

- Prototype files live only under `docs/ui_prototypes/`.
- Do not import code from `src/podcast_research/web/templates/`.
- Do not edit production templates or `src/podcast_research/web/static/style.css`
  while iterating on these prototypes.
- Use static mock data that reflects the investment research workflow.
- Keep the desktop web console as the primary target. Mobile polish is not a
  design goal for this round.
- Each prototype should make the intended user action obvious without relying
  on explanatory copy inside the interface.

## Files

| File | Role |
|------|------|
| `prototype.css` | Shared prototype-only styles |
| `investment_radar.html` | Dashboard prototype for investment change monitoring |
| `knowledge_search.html` | Unified knowledge search prototype |
| `source_workbench.html` | Unified source ingestion workbench prototype |
| `guided_import.html` | Guided import and recovery flow prototype |

## Adoption Path

After design alignment, selected patterns can be ported into the existing
Jinja templates with the backend data contract unchanged.
