"""Generate patch proposals for Topic/Company cards.

Supports:
- Mock mode: generates placeholder patches for testing
- Real LLM mode: calls OpenAI-compatible API to generate patches

Both modes produce patches with YAML frontmatter and Review Checklist.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from podcast_research.llm_wiki.context_builder import TopicContext, CompanyContext
from podcast_research.llm_wiki.prompts import (
    GENERATE_PATCH_SYSTEM,
    GENERATE_PATCH_USER,
    GENERATE_COMPANY_PATCH_SYSTEM,
    GENERATE_COMPANY_PATCH_USER,
    build_source_reports_context,
)

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1.0"

REVIEW_CHECKLIST = """## Review Checklist

- [ ] 每条关键判断都能追溯到 Source Reports
- [ ] 没有新增 source reports 中不存在的事实
- [ ] 没有输出投资建议
- [ ] 已区分事实、观点、推测和未验证问题
- [ ] Related Companies 合理
- [ ] Related Topics 合理
- [ ] Open Questions 有实际跟踪价值
- [ ] Timeline 没有伪造日期
- [ ] 可以安全应用到目标 Topic Card"""


def _build_frontmatter(
    target_name: str,
    provider: str,
    model: str,
    source_report_filenames: list[str],
    target_card_rel_path: str = "",
    target_type: str = "topic",
) -> str:
    """Build YAML frontmatter for a patch file.

    Args:
        target_name: Topic or company name (e.g. "AI Agents", "NVIDIA")
        provider: Provider name ("mock" or "openai_compatible")
        model: Model name
        source_report_filenames: List of source report filenames (no extension)
        target_card_rel_path: Relative path to target card from vault root
        target_type: "topic" or "company"

    Returns:
        YAML frontmatter string with --- delimiters
    """
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    prefix = "02_Topics" if target_type == "topic" else "03_Companies"
    target_card = target_card_rel_path or f"{prefix}/{target_name}.md"

    source_list = "\n".join(f'  - "{r}"' for r in source_report_filenames) if source_report_filenames else "  []"

    return f"""---
type: llm_wiki_patch
target_type: {target_type}
target: "{target_name}"
target_card: "{target_card}"
provider: {provider}
model: {model}
prompt_version: {PROMPT_VERSION}
generated_at: "{now_utc}"
source_reports:
{source_list}
status: pending_review
auto_apply: false
---"""


def _has_frontmatter(content: str) -> bool:
    """Check if content already starts with YAML frontmatter."""
    return content.strip().startswith("---")


def _strip_existing_frontmatter(content: str) -> str:
    """Remove existing YAML frontmatter if present."""
    stripped = content.strip()
    if not stripped.startswith("---"):
        return content
    # Find closing ---
    end_idx = stripped.find("---", 3)
    if end_idx == -1:
        return content
    return stripped[end_idx + 3:].strip()


def generate_topic_patch(
    topic_context: TopicContext,
    provider: str = "mock",
    api_key: str = "",
    base_url: str = "",
    model: str = "gpt-4o-mini",
) -> str:
    """Generate a patch proposal for a topic.

    Args:
        topic_context: Context built from topic card and source reports
        provider: "mock" or "openai_compatible"
        api_key: API key for real LLM (required if provider != "mock")
        base_url: Base URL for OpenAI-compatible API
        model: Model name for real LLM

    Returns:
        Markdown string of the patch proposal (with frontmatter + checklist)
    """
    source_filenames = [r.filename for r in topic_context.source_reports]

    if provider == "mock":
        display_model = "mock-v1"
        body = _generate_mock_patch_body(topic_context)
    elif provider == "openai_compatible":
        display_model = model
        body = _generate_real_patch_body(
            topic_context, api_key, base_url, model
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")

    # Build frontmatter
    target_card_rel = str(topic_context.topic_card_path).replace("\\", "/")
    # Try to extract relative path from vault
    # Since we don't have vault_path here, use a default
    frontmatter = _build_frontmatter(
        target_name=topic_context.topic_name,
        provider=provider,
        model=display_model,
        source_report_filenames=source_filenames,
        target_card_rel_path=f"02_Topics/{topic_context.topic_name}.md",
        target_type="topic",
    )

    # Strip any existing frontmatter from LLM output
    body = _strip_existing_frontmatter(body)

    # Assemble full patch: frontmatter + body + checklist
    return f"{frontmatter}\n\n{body}\n\n{REVIEW_CHECKLIST}\n"


def _generate_mock_patch_body(topic_context: TopicContext) -> str:
    """Generate a mock patch body (without frontmatter)."""
    topic_name = topic_context.topic_name
    source_reports = topic_context.source_reports

    # Build source reports list
    source_list = "\n".join(
        f"- [[{r.filename}]]" for r in source_reports
    ) or "- No source reports"

    # Build mock key claims
    mock_claims = []
    for r in source_reports[:2]:  # Use first 2 reports
        mock_claims.append(
            f"- Mock claim from [[{r.filename}]] about {topic_name}\n"
            f"  - Source: [[{r.filename}]]\n"
            f"  - Evidence: mock-evidence"
        )
    claims_text = "\n".join(mock_claims) if mock_claims else "- No claims extracted"

    # Build mock related companies (use placeholders for mock mode)
    mock_companies = [
        "NVIDIA",
        "OpenAI",
        "Anthropic",
    ]
    companies_text = "\n".join(f"- [[{c}]]" for c in mock_companies)

    # Build mock related topics
    mock_topics = [
        "AI Models",
        "Enterprise AI",
        "Developer Tools",
    ]
    topics_text = "\n".join(f"- [[{t}]]" for t in mock_topics[:3])

    # Build mock open questions
    mock_questions = [
        f"- What is the long-term impact of {topic_name} on the industry?",
        f"- How does {topic_name} compare to alternative approaches?",
    ]
    questions_text = "\n".join(mock_questions)

    # Build mock timeline
    now = datetime.now().strftime("%Y-%m-%d")
    mock_timeline = f"- {now}: Initial patch generated (mock mode)"

    # Build mock evidence notes
    mock_evidence = []
    for r in source_reports[:1]:
        if r.source_quotes:
            mock_evidence.append(
                f"- Claim: Mock claim about {topic_name}\n"
                f"  - Source: [[{r.filename}]]\n"
                f"  - Quote: {r.source_quotes[:100]}...\n"
                f"  - Timestamp: N/A"
            )
    evidence_text = "\n".join(mock_evidence) if mock_evidence else "- No evidence notes"

    # Build mock understanding
    mock_understanding = (
        f"{topic_name} is an important topic in the AI/Tech investment space. "
        f"This mock patch summarizes key points from {len(source_reports)} source reports. "
        f"In production mode, this section would contain a detailed analysis based on "
        f"the source reports."
    )

    # Assemble patch body (no frontmatter, no checklist — those are added by caller)
    return f"""# Patch Proposal: {topic_name}

## Target Card

[[{topic_name}]]

## Source Reports Used

{source_list}

## Proposed Current Understanding

{mock_understanding}

## Proposed Key Claims

{claims_text}

## Proposed Related Companies

{companies_text}

## Proposed Related Topics

{topics_text}

## Proposed Open Questions

{questions_text}

## Proposed Timeline

{mock_timeline}

## Evidence Notes

{evidence_text}

## Patch Safety

- This is a proposal only.
- No source card has been modified.
- Generated in **mock mode** for testing.
"""


def _generate_real_patch_body(
    topic_context: TopicContext,
    api_key: str,
    base_url: str,
    model: str,
) -> str:
    """Generate a real patch body using OpenAI-compatible API (without frontmatter)."""
    # Import here to avoid circular dependency
    from podcast_research.llm.openai_compatible_provider import OpenAICompatibleProvider

    if not api_key:
        raise ValueError("api_key is required for real LLM mode")
    if not base_url:
        raise ValueError("base_url is required for real LLM mode")

    provider = OpenAICompatibleProvider(
        base_url=base_url,
        api_key=api_key,
        model=model,
        max_retries=2,
        timeout=120.0,
    )

    # Build user prompt
    source_reports_context = build_source_reports_context(topic_context.source_reports)
    user_prompt = GENERATE_PATCH_USER.format(
        topic_name=topic_context.topic_name,
        current_card_content=topic_context.current_card_content,
        source_reports_context=source_reports_context,
    )

    # Call LLM
    logger.info(
        "Generating real patch for topic '%s' with %d source reports",
        topic_context.topic_name,
        len(topic_context.source_reports),
    )
    body = provider._chat(GENERATE_PATCH_SYSTEM, user_prompt)

    return body


def write_patch_file(
    vault_path: Path,
    target_name: str,
    patch_markdown: str,
    output_dir: str = "00_Inbox/LLM_Patches",
    patch_prefix: str = "topic",
) -> Path:
    """Write patch markdown to a file in the inbox.

    Args:
        vault_path: Path to vault root
        target_name: Topic or company name (used in filename)
        patch_markdown: Markdown content of the patch
        output_dir: Relative path to output directory
        patch_prefix: "topic" or "company" for filename prefix

    Returns:
        Path to the written patch file
    """
    # Create output directory if needed
    output_path = vault_path / output_dir
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate filename: {prefix}_{SafeName}_{YYYYMMDD_HHMMSS}.md
    safe_name = target_name.replace(" ", "_").replace("&", "and")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{patch_prefix}_{safe_name}_{timestamp}.md"
    filepath = output_path / filename

    # If file exists, add suffix
    if filepath.exists():
        counter = 1
        while filepath.exists():
            filename = f"topic_{safe_name}_{timestamp}_{counter}.md"
            filepath = output_path / filename
            counter += 1

    # Write file
    filepath.write_text(patch_markdown, encoding="utf-8")
    logger.info("Patch file written to %s", filepath)

    return filepath


def generate_company_patch(
    company_context: CompanyContext,
    provider: str = "mock",
    api_key: str = "",
    base_url: str = "",
    model: str = "gpt-4o-mini",
) -> str:
    """Generate a patch proposal for a company.

    Args:
        company_context: Context built from company card and source reports
        provider: "mock" or "openai_compatible"
        api_key: API key for real LLM (required if provider != "mock")
        base_url: Base URL for OpenAI-compatible API
        model: Model name for real LLM

    Returns:
        Markdown string of the patch proposal (with frontmatter + checklist)
    """
    source_filenames = [r.filename for r in company_context.source_reports]

    if provider == "mock":
        display_model = "mock-v1"
        body = _generate_mock_company_patch_body(company_context)
    elif provider == "openai_compatible":
        display_model = model
        body = _generate_real_company_patch_body(
            company_context, api_key, base_url, model
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")

    frontmatter = _build_frontmatter(
        target_name=company_context.company_name,
        provider=provider,
        model=display_model,
        source_report_filenames=source_filenames,
        target_card_rel_path=f"03_Companies/{company_context.company_name}.md",
        target_type="company",
    )

    body = _strip_existing_frontmatter(body)
    return f"{frontmatter}\n\n{body}\n\n{REVIEW_CHECKLIST}\n"


def _generate_mock_company_patch_body(company_context: CompanyContext) -> str:
    """Generate a mock company patch body (without frontmatter)."""
    company_name = company_context.company_name
    source_reports = company_context.source_reports

    source_list = "\n".join(
        f"- [[{r.filename}]]" for r in source_reports
    ) or "- No source reports"

    mock_claims = []
    for r in source_reports[:2]:
        mock_claims.append(
            f"- Mock claim about {company_name} from [[{r.filename}]]\n"
            f"  - Source: [[{r.filename}]]\n"
            f"  - Evidence: mock-evidence"
        )
    claims_text = "\n".join(mock_claims) if mock_claims else "- No claims extracted"

    companies_text = "\n".join(f"- [[{c}]]" for c in ["NVIDIA", "OpenAI", "TSMC"][:3])

    topics_text = "\n".join(f"- [[{t}]]" for t in ["AI Infrastructure", "Semiconductor", "AI Models"][:3])

    mock_questions = [
        f"- What is {company_name}'s competitive position in the AI value chain?",
        f"- What are the key risks facing {company_name}?",
    ]
    questions_text = "\n".join(mock_questions)

    mock_risks = [
        f"- Competitive pressure in {company_name}'s core markets\n"
        f"  - Source: mock-evidence",
        f"- Regulatory uncertainty\n"
        f"  - Source: mock-evidence",
    ]
    risks_text = "\n".join(mock_risks)

    now = datetime.now().strftime("%Y-%m-%d")
    mock_timeline = f"- {now}: Initial company patch generated (mock mode)"

    mock_evidence = []
    for r in source_reports[:1]:
        if r.source_quotes:
            mock_evidence.append(
                f"- Claim: Mock claim about {company_name}\n"
                f"  - Source: [[{r.filename}]]\n"
                f"  - Quote: {r.source_quotes[:100]}...\n"
                f"  - Timestamp: N/A"
            )
    evidence_text = "\n".join(mock_evidence) if mock_evidence else "- No evidence notes"

    mock_thesis = (
        f"{company_name} is an important company in the AI/Tech investment landscape. "
        f"This mock patch summarizes key points from {len(source_reports)} source reports. "
        f"In production mode, this section would contain a detailed analysis based on "
        f"the source reports."
    )

    return f"""# Patch Proposal: {company_name}

## Target Card

[[{company_name}]]

## Source Reports Used

{source_list}

## Proposed Current Thesis

{mock_thesis}

## Proposed Key Claims

{claims_text}

## Proposed Related Topics

{topics_text}

## Proposed Related Companies

{companies_text}

## Proposed Risks

{risks_text}

## Proposed Open Questions

{questions_text}

## Proposed Timeline

{mock_timeline}

## Evidence Notes

{evidence_text}

## Patch Safety

- This is a proposal only.
- No source card has been modified.
- Generated in **mock mode** for testing.
"""


def _generate_real_company_patch_body(
    company_context: CompanyContext,
    api_key: str,
    base_url: str,
    model: str,
) -> str:
    """Generate a real company patch body using OpenAI-compatible API."""
    from podcast_research.llm.openai_compatible_provider import OpenAICompatibleProvider

    if not api_key:
        raise ValueError("api_key is required for real LLM mode")
    if not base_url:
        raise ValueError("base_url is required for real LLM mode")

    provider = OpenAICompatibleProvider(
        base_url=base_url,
        api_key=api_key,
        model=model,
        max_retries=2,
        timeout=120.0,
    )

    source_reports_context = build_source_reports_context(company_context.source_reports)
    user_prompt = GENERATE_COMPANY_PATCH_USER.format(
        company_name=company_context.company_name,
        current_card_content=company_context.current_card_content,
        source_reports_context=source_reports_context,
    )

    logger.info(
        "Generating real company patch for '%s' with %d source reports",
        company_context.company_name,
        len(company_context.source_reports),
    )
    body = provider._chat(GENERATE_COMPANY_PATCH_SYSTEM, user_prompt)
    return body
