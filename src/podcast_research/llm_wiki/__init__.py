"""P2-E: LLM-WIKI Dynamic Maintenance with Patch Review.

This module generates patch proposals for Topic/Company cards based on
source reports. Patches are written to 00_Inbox/LLM_Patches/ for human review
before applying.

Safety: Never modifies 02_Topics/ or 03_Companies/ directly.
"""

from podcast_research.llm_wiki.context_builder import (
    find_core_topics,
    build_topic_context,
    TopicContext,
    find_companies,
    build_company_context,
    CompanyContext,
    HIGH_VALUE_COMPANIES,
)
from podcast_research.llm_wiki.patch_generator import (
    generate_topic_patch,
    generate_company_patch,
    write_patch_file,
    PROMPT_VERSION,
)
from podcast_research.llm_wiki.applier import (
    apply_patch,
    ApplyResult,
)
from podcast_research.llm_wiki.rollback import (
    list_applied_patches,
    rollback_patch,
    reject_patch,
    AppliedPatch,
    RollbackResult,
    RejectResult,
)
from podcast_research.llm_wiki.taxonomy import (
    SECTION_ORDER,
    normalize_topic_name,
    classify_entity,
)
from podcast_research.llm_wiki.validator import (
    validate_patches,
    validate_patch_file,
    PatchValidationResult,
)

__all__ = [
    "find_core_topics",
    "build_topic_context",
    "TopicContext",
    "find_companies",
    "build_company_context",
    "CompanyContext",
    "HIGH_VALUE_COMPANIES",
    "generate_topic_patch",
    "generate_company_patch",
    "write_patch_file",
    "PROMPT_VERSION",
    "validate_patches",
    "validate_patch_file",
    "PatchValidationResult",
    "apply_patch",
    "ApplyResult",
    "SECTION_ORDER",
    "normalize_topic_name",
    "classify_entity",
    "list_applied_patches",
    "rollback_patch",
    "reject_patch",
    "AppliedPatch",
    "RollbackResult",
    "RejectResult",
]
