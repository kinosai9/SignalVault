"""P2-F: Claim / Signal Card Generation v1.

Deterministic extraction of claims and signals from reports and applied patches.
No LLM calls. No investment advice. Safe write-only to 06_Claims/ and 07_Signals/.
"""

from podcast_research.claim_signal.extractor import (
    ClaimCandidate,
    SignalCandidate,
    extract_claims,
    extract_signals,
)
from podcast_research.claim_signal.generator import (
    GenerationResult,
    generate_all,
    generate_claim_card,
    generate_indexes,
    generate_signal_card,
)

__all__ = [
    "extract_claims",
    "extract_signals",
    "ClaimCandidate",
    "SignalCandidate",
    "generate_claim_card",
    "generate_signal_card",
    "generate_indexes",
    "generate_all",
    "GenerationResult",
]
