"""Claim and Signal Card generation and index writing.

Writes cards to 06_Claims/ and 07_Signals/. Generates indexes and log.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from podcast_research.claim_signal.extractor import (
    ClaimCandidate,
    SignalCandidate,
    extract_claims,
    extract_signals,
)

logger = logging.getLogger(__name__)


@dataclass
class CardResult:
    """Result for a single card generation."""
    card_type: str  # "claim" or "signal"
    slug: str
    statement: str
    source: str
    action: str  # create / skip / overwrite
    reason: str = ""
    path: Path | None = None


@dataclass
class GenerationResult:
    """Overall generation result."""
    claims_created: int = 0
    claims_skipped: int = 0
    claims_overwritten: int = 0
    signals_created: int = 0
    signals_skipped: int = 0
    signals_overwritten: int = 0
    results: list[CardResult] = field(default_factory=list)


def _safe_filename(slug: str) -> str:
    """Make a safe filename from a slug."""
    safe = slug.replace("/", "_").replace("\\", "_").replace(":", "_")
    safe = safe.replace("*", "_").replace("?", "_").replace('"', "_")
    safe = safe.replace("<", "_").replace(">", "_").replace("|", "_")
    # Truncate to reasonable length
    if len(safe) > 120:
        safe = safe[:120]
    return f"{safe}.md"


def generate_claim_card(
    candidate: ClaimCandidate,
    claims_dir: Path,
    overwrite: bool = False,
) -> CardResult:
    """Generate a Claim Card from a candidate.

    Args:
        candidate: ClaimCandidate with extracted data
        claims_dir: Path to 06_Claims/ directory
        overwrite: Whether to overwrite existing cards

    Returns:
        CardResult
    """
    claims_dir.mkdir(parents=True, exist_ok=True)
    filename = _safe_filename(candidate.slug)
    filepath = claims_dir / filename

    result = CardResult(
        card_type="claim",
        slug=candidate.slug,
        statement=candidate.statement[:80],
        source=candidate.source_file,
        action="create",
    )

    if filepath.exists() and not overwrite:
        result.action = "skip"
        result.reason = "exists"
        result.path = filepath
        return result

    result.action = "overwrite" if filepath.exists() else "create"
    result.path = filepath
    result.reason = "new"

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    source_file = candidate.source_file.replace(".md", "")

    card = f"""---
type: claim
status: active
claim: "{candidate.statement[:120]}"
related_topics: []
related_companies: []
source_reports:
  - "{source_file}"
evidence_strength: extracted
created_at: "{now}"
updated_at: "{now}"
---

# Claim: {candidate.statement[:100]}

## Statement

{candidate.statement}

## Evidence

- Source: [[{source_file}]]
"""
    if candidate.evidence_quote:
        card += f"- Quote: {candidate.evidence_quote}\n"
    if candidate.evidence_timestamp:
        card += f"- Timestamp: {candidate.evidence_timestamp}\n"

    card += """
## Related Topics

## Related Companies

## Supporting Sources

## Challenging Sources

## Notes
"""

    filepath.write_text(card, encoding="utf-8")
    logger.info("Claim card written: %s", filename)
    return result


def generate_signal_card(
    candidate: SignalCandidate,
    signals_dir: Path,
    overwrite: bool = False,
) -> CardResult:
    """Generate a Signal Card from a candidate.

    Args:
        candidate: SignalCandidate with extracted data
        signals_dir: Path to 07_Signals/ directory
        overwrite: Whether to overwrite existing cards

    Returns:
        CardResult
    """
    signals_dir.mkdir(parents=True, exist_ok=True)
    filename = _safe_filename(candidate.slug)
    filepath = signals_dir / filename

    result = CardResult(
        card_type="signal",
        slug=candidate.slug,
        statement=candidate.statement[:80],
        source=candidate.source_file,
        action="create",
    )

    if filepath.exists() and not overwrite:
        result.action = "skip"
        result.reason = "exists"
        result.path = filepath
        return result

    result.action = "overwrite" if filepath.exists() else "create"
    result.path = filepath
    result.reason = "new"

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    source_file = candidate.source_file.replace(".md", "")

    topics_yaml = "\n".join(f'  - "{t}"' for t in candidate.related_topics[:5])
    companies_yaml = "\n".join(f'  - "{c}"' for c in candidate.related_companies[:5])

    card = f"""---
type: signal
status: open
signal: "{candidate.statement[:120]}"
related_topics:
{topics_yaml if topics_yaml else '  []'}
related_companies:
{companies_yaml if companies_yaml else '  []'}
source_reports:
  - "{source_file}"
suggested_check_frequency: monthly
created_at: "{now}"
updated_at: "{now}"
---

# Signal: {candidate.statement[:100]}

## What to Watch

{candidate.statement}

## Why It Matters

Extracted from {candidate.source_section} in [[{source_file}]].

## Source

- [[{source_file}]]

## Related Topics

{chr(10).join(f'- [[{t}]]' for t in candidate.related_topics[:5]) if candidate.related_topics else '- (none)'}

## Related Companies

{chr(10).join(f'- [[{c}]]' for c in candidate.related_companies[:5]) if candidate.related_companies else '- (none)'}

## Status

open

## Updates
"""

    filepath.write_text(card, encoding="utf-8")
    logger.info("Signal card written: %s", filename)
    return result


def generate_indexes(
    vault_path: Path,
    results: list[CardResult],
) -> None:
    """Generate Claim Index, Signal Index, and Generation Log.

    Args:
        vault_path: Path to vault root
        results: List of CardResult from generation
    """
    system_dir = vault_path / "99_System"
    system_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    claims = [r for r in results if r.card_type == "claim" and r.action in ("create", "overwrite")]
    signals = [r for r in results if r.card_type == "signal" and r.action in ("create", "overwrite")]

    # Claim Index
    if claims:
        claim_index = "# Claim Index\n\n"
        claim_index += f"Generated: {now}\n\n"
        claim_index += f"Total claims: {len(claims)}\n\n"
        for r in claims:
            claim_index += f"- [[../06_Claims/{_safe_filename(r.slug)}|{r.statement[:60]}]] — {r.source}\n"
        (system_dir / "Claim Index.md").write_text(claim_index, encoding="utf-8")

    # Signal Index
    if signals:
        signal_index = "# Signal Index\n\n"
        signal_index += f"Generated: {now}\n\n"
        signal_index += f"Total signals: {len(signals)}\n\n"
        for r in signals:
            fname = _safe_filename(r.slug)
            signal_index += f"- [[../07_Signals/{fname}|{r.statement[:60]}]] — {r.source}\n"
        (system_dir / "Signal Index.md").write_text(signal_index, encoding="utf-8")

    # Generation Log
    created_count = sum(1 for r in results if r.action == "create")
    overwritten_count = sum(1 for r in results if r.action == "overwrite")
    skipped_count = sum(1 for r in results if r.action == "skip")

    log = f"""# Claim / Signal Generation Log

## {now}

- **Claims created**: {len(claims)}
- **Signals created**: {len(signals)}
- **Total created**: {created_count}
- **Overwritten**: {overwritten_count}
- **Skipped (existing)**: {skipped_count}

### Details

"""
    for r in results:
        log += f"- [{r.action}] [{r.card_type}] {r.statement[:80]} — {r.source} ({r.reason})\n"

    (system_dir / "Claim_Signal_Generation_Log.md").write_text(log, encoding="utf-8")


def generate_all(
    vault_path: Path,
    dry_run: bool = True,
    source: str = "all",
    claims_only: bool = False,
    signals_only: bool = False,
    limit: int = 50,
    overwrite: bool = False,
) -> GenerationResult:
    """Generate Claim and Signal cards from vault sources.

    Args:
        vault_path: Path to vault root
        dry_run: If True, preview only (no files written)
        source: "reports", "patches", or "all"
        claims_only: Only generate claims
        signals_only: Only generate signals
        limit: Max candidates per type
        overwrite: Overwrite existing cards

    Returns:
        GenerationResult
    """
    result = GenerationResult()
    do_claims = not signals_only
    do_signals = not claims_only

    # Extract
    if do_claims:
        claim_candidates = extract_claims(vault_path, source=source, limit=limit)
    else:
        claim_candidates = []

    if do_signals:
        signal_candidates = extract_signals(vault_path, source=source, limit=limit)
    else:
        signal_candidates = []

    # Generate claims
    claims_dir = vault_path / "06_Claims"
    for c in claim_candidates:
        if dry_run:
            card_result = CardResult(
                card_type="claim",
                slug=c.slug,
                statement=c.statement[:80],
                source=c.source_file,
                action="skip" if (claims_dir / _safe_filename(c.slug)).exists() and not overwrite else "create",
                reason="exists" if (claims_dir / _safe_filename(c.slug)).exists() and not overwrite else "new",
            )
        else:
            card_result = generate_claim_card(c, claims_dir, overwrite=overwrite)

        if card_result.action == "create":
            result.claims_created += 1
        elif card_result.action == "overwrite":
            result.claims_overwritten += 1
        else:
            result.claims_skipped += 1
        result.results.append(card_result)

    # Generate signals
    signals_dir = vault_path / "07_Signals"
    for s in signal_candidates:
        if dry_run:
            card_result = CardResult(
                card_type="signal",
                slug=s.slug,
                statement=s.statement[:80],
                source=s.source_file,
                action="skip" if (signals_dir / _safe_filename(s.slug)).exists() and not overwrite else "create",
                reason="exists" if (signals_dir / _safe_filename(s.slug)).exists() and not overwrite else "new",
            )
        else:
            card_result = generate_signal_card(s, signals_dir, overwrite=overwrite)

        if card_result.action == "create":
            result.signals_created += 1
        elif card_result.action == "overwrite":
            result.signals_overwritten += 1
        else:
            result.signals_skipped += 1
        result.results.append(card_result)

    # Generate indexes (only if not dry-run)
    if not dry_run and result.results:
        generate_indexes(vault_path, result.results)

    return result
