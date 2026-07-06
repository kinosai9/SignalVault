"""P2-N.4.4: Claim/Signal canonicalization — text normalization, fingerprinting,
duplicate grouping, and canonical selection.

Shared by Home, Dashboard, Review Queue, Research Brief, Watchlist Brief.
All surfaces use the same canonical representation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from signalvault.workspace.scanner import ClaimInfo, SignalInfo


# ── Text normalization ──────────────────────────────────────────────

def normalize_text(text: str) -> str:
    """Normalize claim/signal text for comparison purposes.

    Strips markdown, hashtags, wiki links, punctuation variance.
    Produces a canonical lowercase ASCII+CJK string.
    """
    if not text:
        return ""

    # Strip markdown bold/italic
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(?!\*)([^*\n]+?)\*(?!\*)', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)

    # Remove wiki link syntax [[target|alias]] → alias, [[target]] → target
    text = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', r'\2', text)
    text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)

    # Remove hashtags and trailing tag fragments
    text = re.sub(r'#[\w一-鿿㐀-䶿-]*', '', text)

    # Remove trailing backtick fragments
    text = re.sub(r'`[^`]*$', '', text)

    # Normalize CJK punctuation to ASCII equivalents where possible
    text = text.replace('、', ', ')   # 、→,
    text = text.replace('，', ', ')   # ，→,
    text = text.replace('。', '.')    # 。→.
    text = text.replace('；', ';')    # ；→;
    text = text.replace('：', ':')    # ：→:

    # Remove boilerplate prefixes
    for prefix in ('Trigger:', 'Target:', '关注:', '需要观察:', 'Signal:',
                   'Claim:', '**', '__'):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()

    # Lowercase ASCII, collapse whitespace
    text = re.sub(r'\s+', ' ', text)
    text = text.strip().lower()

    return text


def normalize_claim_text(text: str) -> str:
    """Normalize claim text specifically."""
    return normalize_text(text)


def normalize_signal_text(text: str) -> str:
    """Normalize signal text specifically."""
    return normalize_text(text)


# ── Fingerprinting ──────────────────────────────────────────────────

FINGERPRINT_LENGTH = 120


def claim_fingerprint(text: str) -> str:
    """Stable fingerprint for claim dedup. First N chars of normalized text."""
    return normalize_claim_text(text)[:FINGERPRINT_LENGTH]


def signal_fingerprint(text: str) -> str:
    """Stable fingerprint for signal dedup. First N chars of normalized text."""
    return normalize_signal_text(text)[:FINGERPRINT_LENGTH]


# ── Token overlap (for near-duplicate detection) ────────────────────

def _token_overlap(text1: str, text2: str) -> float:
    """Jaccard-like token overlap between two normalized texts."""
    t1 = set(normalize_text(text1).split())
    t2 = set(normalize_text(text2).split())
    if not t1 or not t2:
        return 0.0
    intersection = t1 & t2
    union = t1 | t2
    return len(intersection) / len(union)


def _shared_entities(c1: "ClaimInfo | SignalInfo",
                     c2: "ClaimInfo | SignalInfo") -> bool:
    """Check if two claim/signal items share any related entity."""
    t1 = set(getattr(c1, 'related_topics', []) or [])
    t2 = set(getattr(c2, 'related_topics', []) or [])
    c1_set = set(getattr(c1, 'related_companies', []) or [])
    c2_set = set(getattr(c2, 'related_companies', []) or [])
    return bool((t1 & t2) or (c1_set & c2_set))


# ── Duplicate grouping ──────────────────────────────────────────────

@dataclass
class DuplicateGroup:
    """A group of duplicate claims or signals sharing the same fingerprint."""
    fingerprint: str
    canonical: "ClaimInfo | SignalInfo"
    duplicates: list  # list[ClaimInfo | SignalInfo]
    group_size: int = 0

    def __post_init__(self):
        self.group_size = 1 + len(self.duplicates)

    @property
    def all_items(self) -> list:
        return [self.canonical] + self.duplicates

    @property
    def duplicate_ids(self) -> list[str]:
        return [
            getattr(d, 'card_id', '') or getattr(d, 'name', '')
            for d in self.duplicates
        ]


def group_duplicate_claims(claims: list) -> list[DuplicateGroup]:
    """Group claims by fingerprint, then merge near-duplicates by token overlap.

    Returns list of DuplicateGroup, each containing a canonical claim and
    its duplicates. Unmatched claims become singleton groups.
    """
    return _group_duplicates(claims, claim_fingerprint, select_canonical_claim)


def group_duplicate_signals(signals: list) -> list[DuplicateGroup]:
    """Group signals by fingerprint, then merge near-duplicates by token overlap."""
    return _group_duplicates(signals, signal_fingerprint, select_canonical_signal)


def _group_duplicates(
    items: list,
    fingerprint_fn,
    select_canonical_fn,
) -> list[DuplicateGroup]:
    """Generic duplicate grouping with fingerprint + near-duplicate merging."""
    if not items:
        return []

    # Phase 1: fingerprint-based grouping
    fp_map: dict[str, list] = {}
    for item in items:
        text = getattr(item, 'claim', '') or getattr(item, 'signal', '') or ''
        fp = fingerprint_fn(text)
        if fp not in fp_map:
            fp_map[fp] = []
        fp_map[fp].append(item)

    # Phase 2: merge near-duplicate groups (same fingerprint OR high token overlap + shared entities)
    groups: list[list] = list(fp_map.values())
    merged: list[list] = []
    used: set[int] = set()

    for i, group_i in enumerate(groups):
        if i in used:
            continue
        current = list(group_i)
        used.add(i)
        # Try to merge with other groups
        for j, group_j in enumerate(groups):
            if j in used:
                continue
            # Check if any item in current is near-duplicate of any item in group_j
            if _groups_are_near_duplicates(current, group_j):
                current.extend(group_j)
                used.add(j)
        merged.append(current)

    # Phase 3: select canonical for each merged group
    result = []
    for group in merged:
        canonical = select_canonical_fn(group)
        duplicates = [item for item in group if item is not canonical]
        text = getattr(canonical, 'claim', '') or getattr(canonical, 'signal', '') or ''
        fp = fingerprint_fn(text)
        result.append(DuplicateGroup(
            fingerprint=fp,
            canonical=canonical,
            duplicates=duplicates,
        ))

    return result


def _groups_are_near_duplicates(group_a: list, group_b: list) -> bool:
    """Check if two groups should be merged (near-duplicate detection)."""
    for a in group_a:
        for b in group_b:
            a_text = getattr(a, 'claim', '') or getattr(a, 'signal', '') or ''
            b_text = getattr(b, 'claim', '') or getattr(b, 'signal', '') or ''
            # High token overlap + shared entities
            if _token_overlap(a_text, b_text) > 0.50 and _shared_entities(a, b):
                return True
    return False


# ── Canonical selection ─────────────────────────────────────────────

def select_canonical_claim(claims: list) -> "ClaimInfo":
    """Select the best claim as canonical from a duplicate group."""
    return _select_canonical(claims)


def select_canonical_signal(signals: list) -> "SignalInfo":
    """Select the best signal as canonical from a duplicate group."""
    return _select_canonical(signals)


def _select_canonical(items: list):
    """Select canonical item by priority rules."""
    if len(items) == 1:
        return items[0]

    def _score(item) -> int:
        score = 0
        # More source reports
        sr = getattr(item, 'source_reports', []) or []
        score += len(sr) * 10
        # Higher quality
        quality = getattr(item, 'quality', '') or ''
        if quality == 'high':
            score += 20
        elif quality == 'medium':
            score += 10
        # Has related entities
        rt = getattr(item, 'related_topics', []) or []
        rc = getattr(item, 'related_companies', []) or []
        if rt or rc:
            score += 5
        # Not marked as duplicate
        granularity = getattr(item, 'granularity', '') or ''
        if granularity != 'duplicate':
            score += 5
        # Prefer non-markdown text (cleaner)
        text = getattr(item, 'claim', '') or getattr(item, 'signal', '') or ''
        if not text.startswith('**'):
            score += 3
        return score

    scored = sorted(items, key=_score, reverse=True)
    return scored[0]


# ── Convenience: filter to canonical only ───────────────────────────

def canonical_claims(claims: list) -> list:
    """Return only canonical claims, excluding duplicates."""
    groups = group_duplicate_claims(claims)
    return [g.canonical for g in groups]


def canonical_signals(signals: list) -> list:
    """Return only canonical signals, excluding duplicates."""
    groups = group_duplicate_signals(signals)
    return [g.canonical for g in groups]


def is_duplicate(item, groups: list[DuplicateGroup]) -> bool:
    """Check if an item is a duplicate (not canonical) in any group."""
    return any(item in g.duplicates for g in groups)


def find_group_for(item, groups: list[DuplicateGroup]) -> DuplicateGroup | None:
    """Find the duplicate group containing this item."""
    for g in groups:
        if item is g.canonical or item in g.duplicates:
            return g
    return None
