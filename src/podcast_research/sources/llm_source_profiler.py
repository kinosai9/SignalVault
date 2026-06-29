"""P2-S.3.2.1: LLM Source Profiler — optional LLM enhancement for profiling.

This is a stub. The rule-based profiler in source_profiler.py handles all
profiling decisions. When an LLM is connected, it can refine confidence scores
and suggest additional risk warnings, but it MUST NOT:
  - Promote an unsupported source to supported
  - Select an adapter not in TRACKABLE_ADAPTER_ALLOWLIST
  - Override the source_kind assigned by rule-based profiling
  - Write any Report, Deep Notes, or Source Archive
"""

from __future__ import annotations

from podcast_research.sources.models import SourceProfile


class LLMSourceProfiler:
    """Stub LLM profiler — returns base profile unchanged.

    Future implementation should:
      1. Accept the HTML snapshot alongside the rule-based profile
      2. Refine confidence, suggest additional risk_warnings
      3. Validate all outputs against the allowlist before returning
    """

    def profile(
        self, url: str, html: str, base_profile: SourceProfile,
    ) -> SourceProfile:
        """Return the base profile unchanged (stub)."""
        return base_profile


def enhance_source_profile_with_llm(
    profile: SourceProfile,
    html_snapshot: str,
) -> SourceProfile:
    """Stub: returns profile unchanged. No LLM calls in test/production."""
    return profile
