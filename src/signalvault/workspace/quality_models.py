"""P2-N.3: Quality audit data models for knowledge graph health checks."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReportQualityFinding:
    report_id: int
    video_id: str
    title: str
    channel_name: str
    issue: str
    severity: str  # "blocking" | "warning" | "info"
    category: str  # "duplicate" | "density" | "metadata" | "sync" | "archived"


@dataclass
class DuplicateFinding:
    entity_type: str  # "report" | "claim" | "signal" | "company" | "topic" | "source_report"
    entity_a: str
    entity_b: str
    normalized_a: str
    normalized_b: str
    match_type: str  # "exact" | "normalized" | "suffix" | "alias"
    action: str  # "merge" | "archive" | "manual_review"


@dataclass
class EntityConfusionFinding:
    name: str
    current_type: str  # "company" | "topic"
    suggested_type: str
    reason: str  # "company_whitelist" | "topic_pattern" | "generic_name"
    severity: str
    status: str = "active"  # "active" | "archived" | "resolved" | "new"
    source_layer: str = ""  # "vault_file" | "db_entity" | "card_frontmatter"
    source_file: str = ""  # path to the file or report reference
    archived: bool = False
    should_count: bool = True  # only active + new should count
    suggested_action: str = ""


@dataclass
class ClaimSignalQuality:
    entity_type: str  # "claim" | "signal"
    slug: str
    text: str
    issue: str
    severity: str
    evidence_count: int
    related_company_count: int
    related_topic_count: int


@dataclass
class ObsidianGraphFinding:
    card_type: str  # "report" | "topic" | "company" | "claim" | "signal"
    card_path: str
    issue: str
    severity: str  # "blocking" | "warning" | "info"


@dataclass
class ExtractionDensity:
    report_id: int
    video_id: str
    title: str
    views_count: int
    claims_count: int
    signals_count: int
    entities_count: int
    topic_tags_count: int
    source_quotes_count: int
    high_relevance_views: int
    related_companies: int
    related_topics: int
    is_low_density: bool
    low_density_reason: str


@dataclass
class QualityAuditResult:
    """Complete audit output."""
    # Summary
    total_reports: int = 0
    current_reports: int = 0
    archived_reports: int = 0
    total_companies: int = 0
    total_topics: int = 0
    total_claims: int = 0
    total_signals: int = 0

    # Findings
    report_findings: list[ReportQualityFinding] = field(default_factory=list)
    duplicate_findings: list[DuplicateFinding] = field(default_factory=list)
    entity_confusions: list[EntityConfusionFinding] = field(default_factory=list)
    claim_signal_issues: list[ClaimSignalQuality] = field(default_factory=list)
    obsidian_findings: list[ObsidianGraphFinding] = field(default_factory=list)
    extraction_density: list[ExtractionDensity] = field(default_factory=list)

    # Computed
    blocking_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    low_density_reports: list[int] = field(default_factory=list)
    duplicate_report_ids: list[list[int]] = field(default_factory=list)
    orphan_claims: list[str] = field(default_factory=list)
    orphan_signals: list[str] = field(default_factory=list)
    topic_company_confusions: list[str] = field(default_factory=list)
    # P2-N.3.2: Breakdown counts
    entity_confusions_raw: int = 0
    entity_confusions_active: int = 0
    entity_confusions_archived: int = 0
    entity_confusions_resolved: int = 0
    entity_confusions_new: int = 0

    # Root cause counts
    root_causes: dict[str, int] = field(default_factory=lambda: {
        "prompt": 0, "taxonomy": 0, "normalization": 0,
        "sync": 0, "scanner": 0, "rerun_archive": 0,
        "dashboard_brief": 0,
    })

    # Recommended actions
    no_rerun_fixes: list[str] = field(default_factory=list)
    rebuild_artifacts: list[str] = field(default_factory=list)
    targeted_rerun_candidates: list[int] = field(default_factory=list)
    prompt_changes: list[str] = field(default_factory=list)
