"""P2-S.3.x: Data models — ActionEnum, ImportPreview, ConflictInfo, SourceProfile."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum


class ActionEnum(str, Enum):
    """Import actions available to the user across all source types."""
    # Deep Notes actions (URL / tracked sources)
    import_as_deep_notes = "import_as_deep_notes"
    import_as_deep_notes_linked = "import_as_deep_notes_linked"
    import_as_deep_notes_derived_only = "import_as_deep_notes_derived_only"
    overwrite_deep_notes = "overwrite_deep_notes"
    # Source Archive actions (URL / tracked sources)
    import_as_source_archive = "import_as_source_archive"
    link_as_derived_source = "link_as_derived_source"
    archive_only = "archive_only"
    # File upload actions
    confirm_archive = "confirm_archive"
    # Universal
    skip = "skip"


# Human-readable descriptions for the UI
ACTION_DESCRIPTIONS: dict[ActionEnum, str] = {
    ActionEnum.import_as_deep_notes: "导入为深度精读笔记（Deep Notes）",
    ActionEnum.import_as_deep_notes_linked: "导入为 Deep Notes 并关联已有投资报告",
    ActionEnum.import_as_deep_notes_derived_only: "导入为独立 Deep Notes（无关联报告）",
    ActionEnum.import_as_source_archive: "保存为来源归档",
    ActionEnum.link_as_derived_source: "关联到已有报告（作为衍生来源）",
    ActionEnum.archive_only: "仅归档（不做关联）",
    ActionEnum.skip: "跳过不导入",
    ActionEnum.overwrite_deep_notes: "覆盖已有 Deep Notes",
    ActionEnum.confirm_archive: "确认归档至 SourceArchive",
}


@dataclass
class ConflictInfo:
    """A detected conflict for a prospective import."""
    conflict_type: str = ""     # "same_url", "same_video_id_report", etc.
    severity: str = "info"      # "info", "warning", "blocker"
    description: str = ""       # human-readable
    existing_path: str = ""     # path to existing file or report


@dataclass
class ImportPreview:
    """Full preview of a web URL import before any writes occur.

    Built by build_import_preview(). Stored in-memory (never written to DB).
    The user reviews this and picks an action before confirm executes writes.
    """
    preview_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    url: str = ""
    adapter_name: str = ""
    provider: str = ""
    source_type: str = ""           # "derived" or "generic_web_page"
    title: str = ""
    canonical_url: str = ""
    detected_youtube_video_id: str = ""
    original_source_url: str = ""
    summary: str = ""
    content_blocks_count: int = 0   # h1-h3 + paragraphs
    parse_quality: str = ""         # "good", "degraded", "minimal"
    source_confidence: str = "secondary"
    content_hash: str = ""
    conflicts: list[ConflictInfo] = field(default_factory=list)
    recommended_action: ActionEnum = ActionEnum.skip
    available_actions: list[ActionEnum] = field(default_factory=list)
    warning_messages: list[str] = field(default_factory=list)

    # Internal: the raw adapter output, stored for confirm execution
    # Not serialized — lives only in _preview_store memory
    _parsed_data: object = field(default=None, repr=False, compare=False)


# ── P2-S.3.2.1: Source Profiling ────────────────────────────────────────────


class SourceKind(str, Enum):
    """Classification of a remote URL's page type."""
    allin_notes_index = "allin_notes_index"
    rss_feed = "rss_feed"
    atom_feed = "atom_feed"
    generic_list_page = "generic_list_page"
    single_article = "single_article"
    single_page_monitor = "single_page_monitor"
    youtube_channel = "youtube_channel"
    unknown = "unknown"


class TrackingEligibility(str, Enum):
    """Whether a source can be persistently tracked."""
    supported = "supported"
    unsupported = "unsupported"
    needs_adapter = "needs_adapter"
    low_confidence = "low_confidence"
    manual_only = "manual_only"


class SuggestedAction(str, Enum):
    """Recommended next step after profiling."""
    create_tracked_source = "create_tracked_source"
    use_single_url_import = "use_single_url_import"
    use_rss_import_future = "use_rss_import_future"
    create_adapter_first = "create_adapter_first"
    unsupported = "unsupported"


@dataclass
class SourceProfile:
    """Result of profiling a URL for tracking eligibility.

    Built by profile_source_url(). Read-only — profiling must not write to
    any Report, Deep Notes, Source Archive, Claim, or Signal store.
    """

    url: str = ""
    normalized_url: str = ""
    provider: str = ""
    domain: str = ""

    source_kind: SourceKind = SourceKind.unknown
    tracking_supported: bool = False
    tracking_eligibility: TrackingEligibility = TrackingEligibility.low_confidence
    confidence: float = 0.0

    recommended_adapter: str | None = None
    discovery_strategy: str | None = None
    identity_strategy: str | None = None
    change_detection_strategy: str | None = None

    detected_title: str | None = None
    detected_description: str | None = None
    detected_feed_url: str | None = None
    detected_youtube_channel_id: str | None = None
    detected_entry_candidates_count: int = 0

    risk_warnings: list[str] = field(default_factory=list)
    unsupported_reason: str | None = None
    suggested_action: SuggestedAction = SuggestedAction.unsupported


# ── P2-S.3.3: File Upload Import ────────────────────────────────────────────


class FileArchiveType(str, Enum):
    """Recommended archive type for an uploaded file."""
    source_archive = "source_archive"
    report_material = "report_material"
    deep_notes_candidate = "deep_notes_candidate"
    skip = "skip"


@dataclass
class UploadedFileProfile:
    """Profile of an uploaded text file after validation and content inspection.

    Built by profile_uploaded_file(). Read-only — no vault writes.
    """
    filename: str = ""
    original_filename: str = ""
    extension: str = ""
    mime_type: str | None = None
    file_size_bytes: int = 0
    supported: bool = False
    unsupported_reason: str | None = None
    detected_encoding: str | None = None
    content_hash: str | None = None
    extracted_text_length: int = 0
    extracted_blocks_count: int = 0
    parse_quality: str = "minimal"  # "good", "degraded", "minimal"
    quality_warnings: list[str] = field(default_factory=list)


@dataclass
class FileImportEligibility:
    """Result of evaluating whether an uploaded file qualifies for archive import."""
    import_eligible: bool = False
    ineligible_reason: str | None = None
    recommended_archive_type: FileArchiveType = FileArchiveType.source_archive
    warning_messages: list[str] = field(default_factory=list)


@dataclass
class FileImportPreview:
    """Full preview of a file upload import before any writes occur.

    Built by build_file_import_preview(). Stored in-memory (never written to DB).
    The user reviews this and picks an action before confirm executes writes.
    """
    preview_id: str = field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    filename: str = ""
    extension: str = ""
    file_size_bytes: int = 0
    content_hash: str = ""
    title: str = ""
    extracted_text_excerpt: str = ""
    extracted_text_length: int = 0
    parse_quality: str = "minimal"
    import_eligible: bool = False
    ineligible_reason: str | None = None
    conflicts: list[ConflictInfo] = field(default_factory=list)
    recommended_action: ActionEnum = ActionEnum.skip
    recommended_path: str = ""
    available_actions: list[ActionEnum] = field(default_factory=list)
    warning_messages: list[str] = field(default_factory=list)

    # Internal: the full extracted text, stored for confirm execution
    # Not serialized — lives only in _file_preview_store memory
    _extracted_text: str = field(default="", repr=False, compare=False)
