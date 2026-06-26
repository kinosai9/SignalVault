"""P2-S.3.1: Import data models — ActionEnum, ImportPreview, ConflictInfo."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum


class ActionEnum(str, Enum):
    """Import actions available to the user."""
    import_as_deep_notes = "import_as_deep_notes"
    import_as_deep_notes_linked = "import_as_deep_notes_linked"
    import_as_deep_notes_derived_only = "import_as_deep_notes_derived_only"
    import_as_source_archive = "import_as_source_archive"
    link_as_derived_source = "link_as_derived_source"
    archive_only = "archive_only"
    skip = "skip"
    overwrite_deep_notes = "overwrite_deep_notes"


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
