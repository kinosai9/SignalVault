"""P2-E: LLM-WIKI Dynamic Maintenance with Patch Review.

This module generates patch proposals for Topic/Company cards based on
source reports. Patches are written to 00_Inbox/LLM_Patches/ for human review
before applying.

Safety: Never modifies 02_Topics/ or 03_Companies/ directly.
"""

from podcast_research.llm_wiki.applier import (
    ApplyResult,
    apply_patch,
)
from podcast_research.llm_wiki.context_builder import (
    HIGH_VALUE_COMPANIES,
    CompanyContext,
    TopicContext,
    build_company_context,
    build_topic_context,
    find_companies,
    find_core_topics,
)
from podcast_research.llm_wiki.patch_generator import (
    PROMPT_VERSION,
    generate_company_patch,
    generate_topic_patch,
    write_patch_file,
)
from podcast_research.llm_wiki.rollback import (
    AppliedPatch,
    RejectResult,
    RollbackResult,
    list_applied_patches,
    reject_patch,
    rollback_patch,
)
from podcast_research.llm_wiki.taxonomy import (
    SECTION_ORDER,
    classify_entity,
    normalize_topic_name,
)
from podcast_research.llm_wiki.validator import (
    PatchValidationResult,
    validate_patch_file,
    validate_patches,
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
