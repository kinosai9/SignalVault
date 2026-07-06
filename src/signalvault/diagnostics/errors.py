"""P7-A: Error Taxonomy — unified structured error records.

ErrorSeverity → ErrorCategory → ErrorRecord → ErrorCodeRegistry.
All user_messages are in Chinese, oriented toward non-IT users.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

# ── Enums ────────────────────────────────────────────────────────────────────


class ErrorSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKER = "blocker"


class ErrorCategory(str, Enum):
    SOURCE = "source_error"
    AUTH = "auth_error"
    PERMISSION = "permission_error"
    EXTRACTION = "extraction_error"
    ANALYSIS = "analysis_error"
    LLM = "llm_error"
    DATABASE = "database_error"
    VAULT = "vault_error"
    SEARCH_GRAPH = "search_graph_error"
    MCP = "mcp_error"
    CONFIG = "config_error"


# ── ErrorRecord ──────────────────────────────────────────────────────────────


@dataclass
class ErrorRecord:
    """Unified error record — CLI / API / Web common."""

    # Identity
    error_code: str = ""       # "SOURCE_FETCH_001", "AUTH_ZSXQ_001", etc.
    category: str = ""         # ErrorCategory value

    # Severity
    severity: str = "warning"  # ErrorSeverity value

    # User-facing (Chinese, ≤200 chars)
    user_message: str = ""
    user_message_detail: str = ""

    # Technical
    technical_detail: str = ""
    exception_type: str = ""
    trace_id: str = ""          # operation_id / job_id

    # Recovery
    suggested_actions: list[str] = field(default_factory=list)

    # Routing
    related_command: str = ""
    source_type: str = ""
    entity_ref: str = ""

    # Review queue
    create_review_item: bool = False
    review_item_type: str = ""

    # Metadata
    created_at: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "error_code": self.error_code,
            "category": self.category,
            "severity": self.severity,
            "user_message": self.user_message,
            "user_message_detail": self.user_message_detail,
            "technical_detail": self.technical_detail,
            "exception_type": self.exception_type,
            "trace_id": self.trace_id,
            "suggested_actions": self.suggested_actions,
            "related_command": self.related_command,
            "source_type": self.source_type,
            "entity_ref": self.entity_ref,
            "create_review_item": self.create_review_item,
            "review_item_type": self.review_item_type,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


# ── ErrorCodeRegistry ────────────────────────────────────────────────────────


class ErrorCodeRegistry:
    """Central registry of all known error codes.

    Register built-in codes at module load. Get by code or filter by
    category / severity / source_type.
    """

    _codes: dict[str, ErrorRecord] = {}

    @classmethod
    def register(cls, record: ErrorRecord) -> None:
        if record.error_code in cls._codes:
            raise ValueError(f"Duplicate error_code: {record.error_code}")
        cls._codes[record.error_code] = record

    @classmethod
    def get(cls, error_code: str) -> ErrorRecord | None:
        return cls._codes.get(error_code)

    @classmethod
    def list_all(cls) -> list[ErrorRecord]:
        return list(cls._codes.values())

    @classmethod
    def list_by_category(cls, category: str) -> list[ErrorRecord]:
        return [r for r in cls._codes.values() if r.category == category]

    @classmethod
    def list_by_severity(cls, severity: str) -> list[ErrorRecord]:
        return [r for r in cls._codes.values() if r.severity == severity]

    @classmethod
    def list_by_source_type(cls, source_type: str) -> list[ErrorRecord]:
        return [r for r in cls._codes.values() if r.source_type == source_type]

    @classmethod
    def count(cls) -> int:
        return len(cls._codes)


# ── Factory helpers ──────────────────────────────────────────────────────────


def create_error_record(
    error_code: str,
    *,
    trace_id: str = "",
    source_type: str = "",
    entity_ref: str = "",
    technical_detail: str = "",
    exception_type: str = "",
    metadata: dict | None = None,
    suggested_actions: list[str] | None = None,
) -> ErrorRecord | None:
    """Create a runtime ErrorRecord from a registered error_code.

    Returns None if error_code is not in the registry.
    """
    template = ErrorCodeRegistry.get(error_code)
    if template is None:
        return None

    return ErrorRecord(
        error_code=template.error_code,
        category=template.category,
        severity=template.severity,
        user_message=template.user_message,
        user_message_detail=template.user_message_detail,
        technical_detail=technical_detail or template.technical_detail,
        exception_type=exception_type,
        trace_id=trace_id,
        suggested_actions=suggested_actions or list(template.suggested_actions),
        related_command=template.related_command,
        source_type=source_type or template.source_type,
        entity_ref=entity_ref,
        create_review_item=template.create_review_item,
        review_item_type=template.review_item_type,
        created_at=datetime.now(timezone.utc).isoformat(),
        metadata=metadata or {},
    )


def map_exception_to_error(exc: Exception) -> ErrorRecord | None:
    """Map a Python exception to an ErrorRecord based on exception type.

    Covers the 4 ZSXQ exceptions and common built-in exceptions.
    """
    from signalvault.sources.zsxq_cli import (
        ZsxqAuthRequiredError,
        ZsxqCliMissingError,
        ZsxqParseError,
        ZsxqPermissionDeniedError,
    )

    exc_name = type(exc).__name__

    if isinstance(exc, ZsxqCliMissingError):
        return create_error_record("CONFIG_DEP_001",
                                   exception_type=exc_name,
                                   technical_detail=str(exc))
    if isinstance(exc, ZsxqAuthRequiredError):
        return create_error_record("AUTH_ZSXQ_001",
                                   exception_type=exc_name,
                                   technical_detail=str(exc))
    if isinstance(exc, ZsxqPermissionDeniedError):
        return create_error_record("PERM_ZSXQ_001",
                                   exception_type=exc_name,
                                   technical_detail=str(exc))
    if isinstance(exc, ZsxqParseError):
        return create_error_record("SOURCE_PARSE_001",
                                   exception_type=exc_name,
                                   technical_detail=str(exc))
    if isinstance(exc, ValueError):
        return create_error_record("CONFIG_INVALID_001",
                                   exception_type=exc_name,
                                   technical_detail=str(exc))
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return create_error_record("SOURCE_FETCH_001",
                                   exception_type=exc_name,
                                   technical_detail=str(exc))
    return create_error_record("ANALYSIS_PIPELINE_001",
                               exception_type=exc_name,
                               technical_detail=str(exc))


def review_item_to_error_record(item: dict) -> ErrorRecord | None:
    """Map a review_item dict to an ErrorRecord.

    Uses the review item_type to find the matching error_code.
    """
    # Mapping from review item_type → error_code
    _MAPPING = {
        "pdf_needs_ocr": "EXTRACT_PDF_003",
        "pdf_quality_issue": "EXTRACT_PDF_002",
        "pdf_extraction_failed": "EXTRACT_PDF_001",
        "pdf_analysis_skipped": "ANALYSIS_ELIGIBILITY_001",
        "pdf_evidence_missing": "ANALYSIS_ELIGIBILITY_001",
        "zsxq_cli_missing": "CONFIG_DEP_001",
        "zsxq_auth_required": "AUTH_ZSXQ_001",
        "zsxq_permission_denied": "PERM_ZSXQ_001",
        "zsxq_parse_failed": "SOURCE_PARSE_001",
        "zsxq_attachment_unsupported": "EXTRACT_ZSXQ_001",
        "zsxq_analysis_skipped": "ANALYSIS_ELIGIBILITY_001",
        "zsxq_content_too_short": "EXTRACT_ZSXQ_002",
        "zsxq_evidence_missing": "EXTRACT_ZSXQ_001",
    }

    item_type = item.get("item_type", "")
    error_code = _MAPPING.get(item_type)
    if error_code is None:
        return None

    return create_error_record(
        error_code,
        entity_ref=item.get("source_path", ""),
        technical_detail=item.get("description", ""),
        source_type="",
    )


# ═════════════════════════════════════════════════════════════════════════════
# Built-in Error Codes (registered at module load)
# ═════════════════════════════════════════════════════════════════════════════


def _register_builtin_codes() -> None:
    """Register all built-in error codes. Called at module import."""

    # ── SOURCE ───────────────────────────────────────────────────────────
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="SOURCE_FETCH_001", category=ErrorCategory.SOURCE, severity=ErrorSeverity.ERROR,
        user_message="无法获取信息源内容。请检查网络连接后重试。",
        suggested_actions=["检查网络连接", "确认信息源链接是否有效", "稍后重试"],
        related_command="",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="SOURCE_FETCH_002", category=ErrorCategory.SOURCE, severity=ErrorSeverity.WARNING,
        user_message="信息源返回内容为空，可能已被删除或链接失效。",
        suggested_actions=["检查链接是否仍然有效", "确认信息源是否已被删除"],
        related_command="",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="SOURCE_PARSE_001", category=ErrorCategory.SOURCE, severity=ErrorSeverity.ERROR,
        user_message="内容格式解析失败。信息源格式可能已变更。",
        suggested_actions=["确认信息源格式是否已变更", "检查 CLI 版本是否需要更新"],
        related_command="signalvault doctor",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="SOURCE_UNSUPPORTED_001", category=ErrorCategory.SOURCE, severity=ErrorSeverity.WARNING,
        user_message="当前版本不支持该信息源类型。",
        suggested_actions=["确认信息源类型是否在支持列表中", "查看 README 获取支持的信息源列表"],
        related_command="",
    ))

    # ── AUTH ─────────────────────────────────────────────────────────────
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="AUTH_ZSXQ_001", category=ErrorCategory.AUTH, severity=ErrorSeverity.ERROR,
        user_message="知识星球未登录。请在终端运行 `zsxq-cli auth login` 后重试。",
        suggested_actions=["运行 zsxq-cli auth login", "运行 signalvault zsxq doctor 检查状态"],
        related_command="signalvault zsxq doctor",
        create_review_item=True, review_item_type="zsxq_auth_required",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="AUTH_LLM_001", category=ErrorCategory.AUTH, severity=ErrorSeverity.BLOCKER,
        user_message="未配置 AI 模型密钥。请在 .env 文件中设置 LLM_API_KEY。",
        suggested_actions=["编辑 .env 文件，添加 LLM_API_KEY=您的密钥",
                           "或使用 --mock 标志以测试模式运行"],
        related_command="",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="AUTH_LLM_002", category=ErrorCategory.AUTH, severity=ErrorSeverity.ERROR,
        user_message="AI 模型密钥验证失败。请检查 .env 中的 LLM_API_KEY 是否正确。",
        suggested_actions=["检查 LLM_API_KEY 是否正确", "检查 LLM_BASE_URL 是否可访问",
                           "确认 API 账户余额是否充足"],
        related_command="",
    ))

    # ── PERMISSION ───────────────────────────────────────────────────────
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="PERM_ZSXQ_001", category=ErrorCategory.PERMISSION, severity=ErrorSeverity.WARNING,
        user_message="无权访问该知识星球。请确认已在知识星球 App 中订阅该星球。",
        suggested_actions=["在知识星球 App 中确认订阅状态",
                           "运行 signalvault zsxq groups --refresh 刷新授权"],
        related_command="signalvault zsxq groups --refresh",
        create_review_item=True, review_item_type="zsxq_permission_denied",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="PERM_VAULT_001", category=ErrorCategory.PERMISSION, severity=ErrorSeverity.ERROR,
        user_message="Obsidian 知识库目录无写入权限。请检查目录权限设置。",
        suggested_actions=["检查 Obsidian Vault 目录的读写权限",
                           "确认 OBSIDIAN_VAULT_PATH 配置正确"],
        related_command="",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="PERM_DB_001", category=ErrorCategory.PERMISSION, severity=ErrorSeverity.BLOCKER,
        user_message="数据库文件无法访问。请检查 data/ 目录权限。",
        suggested_actions=["检查 data/ 目录是否存在且可读写", "检查磁盘空间是否充足"],
        related_command="signalvault doctor",
    ))

    # ── EXTRACTION ───────────────────────────────────────────────────────
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="EXTRACT_PDF_001", category=ErrorCategory.EXTRACTION, severity=ErrorSeverity.ERROR,
        user_message="PDF 文本提取失败。文件可能已损坏或为扫描版。",
        suggested_actions=["确认 PDF 文件是否完整（未损坏）",
                           "扫描版 PDF 建议先用 OCR 工具预处理"],
        related_command="signalvault pdf preview <file>",
        create_review_item=True, review_item_type="pdf_extraction_failed",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="EXTRACT_PDF_002", category=ErrorCategory.EXTRACTION, severity=ErrorSeverity.WARNING,
        user_message="PDF 提取的文本质量较低（大部分页面为空或乱码）。",
        suggested_actions=["查看 PDF 是否为扫描版（需要 OCR）",
                           "如果内容很少，分析结果可能不完整"],
        related_command="signalvault pdf preview <file>",
        create_review_item=True, review_item_type="pdf_quality_issue",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="EXTRACT_PDF_003", category=ErrorCategory.EXTRACTION, severity=ErrorSeverity.WARNING,
        user_message="该 PDF 为扫描版，需要 OCR 处理。当前暂不支持自动 OCR。",
        suggested_actions=["手动使用 OCR 工具（如 Tesseract）预处理 PDF",
                           "或直接使用文字版 PDF"],
        related_command="",
        create_review_item=True, review_item_type="pdf_needs_ocr",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="EXTRACT_YT_001", category=ErrorCategory.EXTRACTION, severity=ErrorSeverity.WARNING,
        user_message="该视频无可用字幕（可能未生成或已禁用）。",
        suggested_actions=["确认视频是否有字幕", "尝试其他语言的视频"],
        related_command="",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="EXTRACT_ZSXQ_001", category=ErrorCategory.EXTRACTION, severity=ErrorSeverity.WARNING,
        user_message="该知识星球主题正文为空，无法提取有效内容。",
        suggested_actions=["确认主题是否包含文字内容", "附件内容暂不支持自动提取"],
        related_command="",
        create_review_item=True, review_item_type="zsxq_evidence_missing",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="EXTRACT_ZSXQ_002", category=ErrorCategory.EXTRACTION, severity=ErrorSeverity.WARNING,
        user_message="该主题正文字数不足，不适合进行分析。",
        suggested_actions=["选择内容更丰富的主题进行分析", "短内容可手动阅读"],
        related_command="",
        create_review_item=True, review_item_type="zsxq_content_too_short",
    ))

    # ── ANALYSIS ─────────────────────────────────────────────────────────
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="ANALYSIS_PIPELINE_001", category=ErrorCategory.ANALYSIS, severity=ErrorSeverity.ERROR,
        user_message="分析过程出现异常。系统已记录错误详情，可重试。",
        suggested_actions=["稍后重试分析", "如果持续失败，运行 signalvault doctor 检查系统状态",
                           "缩短分析内容或更换信息源"],
        related_command="signalvault doctor",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="ANALYSIS_ELIGIBILITY_001", category=ErrorCategory.ANALYSIS, severity=ErrorSeverity.INFO,
        user_message="该内容不满足分析条件（过短、质量过低或来源状态异常）。",
        suggested_actions=["确认信息源是否可正常访问", "选择内容更丰富的信息源"],
        related_command="",
    ))

    # ── LLM ──────────────────────────────────────────────────────────────
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="LLM_CALL_001", category=ErrorCategory.LLM, severity=ErrorSeverity.ERROR,
        user_message="AI 模型调用失败。请检查网络连接和 API 配置。",
        suggested_actions=["检查网络连接", "确认 LLM_API_KEY 和 LLM_BASE_URL 配置正确",
                           "确认 API 服务是否正常运行"],
        related_command="signalvault doctor",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="LLM_CALL_002", category=ErrorCategory.LLM, severity=ErrorSeverity.ERROR,
        user_message="AI 模型返回了无法解析的内容。系统将使用降级策略。",
        suggested_actions=["稍后重试", "尝试更换 LLM 模型", "如果持续出现，可能是 prompt 兼容性问题"],
        related_command="",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="LLM_CALL_003", category=ErrorCategory.LLM, severity=ErrorSeverity.WARNING,
        user_message="内容超出 AI 模型处理上限。系统已自动分段处理，不影响最终结果。",
        suggested_actions=["无需操作（系统已自动处理）"],
        related_command="",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="LLM_CALL_004", category=ErrorCategory.LLM, severity=ErrorSeverity.ERROR,
        user_message="AI 模型响应超时。可尝试缩短内容或更换模型。",
        suggested_actions=["缩短分析内容", "检查网络连接速度", "更换 LLM 模型或 API 端点"],
        related_command="",
    ))

    # ── DATABASE ─────────────────────────────────────────────────────────
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="DB_CONNECT_001", category=ErrorCategory.DATABASE, severity=ErrorSeverity.BLOCKER,
        user_message="无法连接到数据库。请检查 data/ 目录是否存在且可访问。",
        suggested_actions=["确认 data/ 目录存在", "检查磁盘空间", "如果数据库损坏，可删除 data/signalvault.db 重新初始化"],
        related_command="signalvault doctor",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="DB_WRITE_001", category=ErrorCategory.DATABASE, severity=ErrorSeverity.ERROR,
        user_message="数据保存失败。可能是磁盘空间不足。",
        suggested_actions=["检查磁盘空间", "确认 data/ 目录有写入权限"],
        related_command="",
    ))

    # ── VAULT ────────────────────────────────────────────────────────────
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="VAULT_NOT_FOUND_001", category=ErrorCategory.VAULT, severity=ErrorSeverity.WARNING,
        user_message="Obsidian 知识库路径未配置或不存在。报告不会自动导出到 Obsidian。",
        suggested_actions=["在 .env 中设置 OBSIDIAN_VAULT_PATH",
                           "或使用 vault-lint 检查现有 Vault 健康"],
        related_command="signalvault vault-lint --vault <path>",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="VAULT_LINT_001", category=ErrorCategory.VAULT, severity=ErrorSeverity.WARNING,
        user_message="Obsidian 知识库存在格式问题。",
        suggested_actions=["运行 vault-lint 查看详情", "根据 lint 建议修复问题"],
        related_command="signalvault vault-lint --vault <path>",
    ))

    # ── SEARCH / GRAPH ───────────────────────────────────────────────────
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="SEARCH_FTS_001", category=ErrorCategory.SEARCH_GRAPH, severity=ErrorSeverity.INFO,
        user_message="全文搜索功能受限（使用基础搜索模式）。搜索功能仍可用。",
        suggested_actions=["无需操作（系统已自动降级）"],
        related_command="",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="GRAPH_BUILD_001", category=ErrorCategory.SEARCH_GRAPH, severity=ErrorSeverity.WARNING,
        user_message="知识图谱重建时部分节点未成功创建。可尝试重新 rebuild。",
        suggested_actions=["运行 signalvault graph rebuild 重新构建"],
        related_command="signalvault graph rebuild",
    ))

    # ── MCP ──────────────────────────────────────────────────────────────
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="MCP_START_001", category=ErrorCategory.MCP, severity=ErrorSeverity.ERROR,
        user_message="MCP Server 启动失败。请检查端口是否被占用。",
        suggested_actions=["检查端口是否被占用", "确认数据库可正常访问"],
        related_command="signalvault doctor",
    ))

    # ── CONFIG ───────────────────────────────────────────────────────────
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="CONFIG_MISSING_001", category=ErrorCategory.CONFIG, severity=ErrorSeverity.WARNING,
        user_message="未配置 AI 模型。系统当前使用 Mock 模式运行（仅用于测试，不产生真实分析结果）。",
        suggested_actions=["在 .env 中设置 LLM_PROVIDER 和 LLM_API_KEY",
                           "Mock 模式可继续使用，但结果不代表真实分析"],
        related_command="signalvault doctor",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="CONFIG_INVALID_001", category=ErrorCategory.CONFIG, severity=ErrorSeverity.ERROR,
        user_message="配置文件格式有误。请检查 .env 文件。",
        suggested_actions=["检查 .env 文件格式", "参考 .env.example 确认配置项"],
        related_command="",
    ))
    ErrorCodeRegistry.register(ErrorRecord(
        error_code="CONFIG_DEP_001", category=ErrorCategory.CONFIG, severity=ErrorSeverity.ERROR,
        user_message="缺少必要的外部工具。",
        suggested_actions=["安装缺失的工具", "运行 signalvault doctor 检查依赖"],
        related_command="signalvault doctor",
        create_review_item=True, review_item_type="zsxq_cli_missing",
    ))


# Register on import
_register_builtin_codes()
