"""P2-S.3.x: Sources package — web URL import preview, execution, tracked sources, profiling, file upload."""

from signalvault.sources.conflict_detector import ConflictDetector
from signalvault.sources.file_content_extractor import (
    ExtractedFileContent,
    extract_text_from_uploaded_file,
)
from signalvault.sources.file_import_preview import (
    build_file_import_preview,
    confirm_file_import,
    evaluate_file_import_eligibility,
)
from signalvault.sources.file_profile import (
    ALLOWED_TEXT_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    profile_uploaded_file,
)
from signalvault.sources.import_preview import (
    build_import_preview,
    execute_import_action,
    select_adapter_for_url,
)
from signalvault.sources.llm_source_profiler import (
    LLMSourceProfiler,
    enhance_source_profile_with_llm,
)
from signalvault.sources.models import (
    ACTION_DESCRIPTIONS,
    ActionEnum,
    ConflictInfo,
    FileArchiveType,
    FileImportEligibility,
    FileImportPreview,
    ImportPreview,
    SourceKind,
    SourceProfile,
    SuggestedAction,
    TrackingEligibility,
    UploadedFileProfile,
)
from signalvault.sources.source_profiler import (
    TRACKABLE_ADAPTER_ALLOWLIST,
    profile_source_url,
)
from signalvault.sources.tracked_source_service import (
    import_tracked_source_entries,
    refresh_tracked_source,
    validate_url_for_tracking,
)

__all__ = [
    "ActionEnum",
    "ACTION_DESCRIPTIONS",
    "ALLOWED_TEXT_EXTENSIONS",
    "ConflictDetector",
    "ConflictInfo",
    "ExtractedFileContent",
    "FileArchiveType",
    "FileImportEligibility",
    "FileImportPreview",
    "ImportPreview",
    "LLMSourceProfiler",
    "MAX_UPLOAD_BYTES",
    "SourceKind",
    "SourceProfile",
    "SuggestedAction",
    "TRACKABLE_ADAPTER_ALLOWLIST",
    "TrackingEligibility",
    "UploadedFileProfile",
    "build_file_import_preview",
    "build_import_preview",
    "confirm_file_import",
    "enhance_source_profile_with_llm",
    "evaluate_file_import_eligibility",
    "execute_import_action",
    "extract_text_from_uploaded_file",
    "import_tracked_source_entries",
    "profile_source_url",
    "profile_uploaded_file",
    "refresh_tracked_source",
    "select_adapter_for_url",
    "validate_url_for_tracking",
]
