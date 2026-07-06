"""P7-C: Diagnostics Center — system health snapshot aggregation.

Queries all subsystems (ingest, review, operation_log, zsxq, pdf, vault,
search, graph, mcp/config) and produces a unified DiagnosticsSummary.
All statuses are in Chinese, oriented toward non-IT users.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

# ── Status constants ─────────────────────────────────────────────────────────

STATUS_OK = "ok"               # healthy
STATUS_ATTENTION = "attention"  # needs attention but not blocking
STATUS_BLOCKED = "blocked"      # core function unavailable
STATUS_UNKNOWN = "unknown"      # cannot determine (e.g. missing dependency)


# ═════════════════════════════════════════════════════════════════════════════
# SubsystemStatus
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class SubsystemStatus:
    name: str = ""
    label: str = ""            # Chinese label
    status: str = STATUS_OK    # ok / attention / blocked / unknown
    summary: str = ""          # one-line human-readable summary
    counts: dict[str, int] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "status": self.status,
            "summary": self.summary,
            "counts": self.counts,
            "issues": self.issues,
            "suggested_actions": self.suggested_actions,
            "metadata": self.metadata,
        }


# ═════════════════════════════════════════════════════════════════════════════
# DiagnosticsSummary
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class DiagnosticsSummary:
    overall_status: str = STATUS_OK  # ok / attention / blocked
    generated_at: str = ""
    subsystems: list[SubsystemStatus] = field(default_factory=list)
    recent_failures: list[dict] = field(default_factory=list)
    open_review_count: int = 0
    blocked_count: int = 0
    attention_count: int = 0
    suggested_actions: list[dict] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "overall_status": self.overall_status,
            "generated_at": self.generated_at,
            "subsystems": [s.to_dict() for s in self.subsystems],
            "recent_failures": self.recent_failures,
            "open_review_count": self.open_review_count,
            "blocked_count": self.blocked_count,
            "attention_count": self.attention_count,
            "suggested_actions": self.suggested_actions,
            "metadata": self.metadata,
        }


# ═════════════════════════════════════════════════════════════════════════════
# RecoveryAction
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class RecoveryAction:
    action_id: str = ""
    title: str = ""            # Chinese
    description: str = ""      # Chinese
    command: str = ""          # CLI command or action instruction
    severity: str = "warning"  # info / warning / error
    category: str = ""         # subsystem name
    user_message: str = ""     # short user-facing tip for CLI/error display

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "title": self.title,
            "description": self.description,
            "command": self.command,
            "severity": self.severity,
            "category": self.category,
            "user_message": self.user_message or self.description,
        }


# ── Error code → recovery action mapping ──────────────────────────────────

# Maps error_code prefixes/patterns to recovery action_ids
_ERROR_TO_ACTION: dict[str, list[str]] = {
    # ZSXQ errors
    "AUTH_ZSXQ_001": ["login_zsxq"],
    "AUTH_ZSXQ_002": ["login_zsxq"],
    "PERM_ZSXQ_001": ["refresh_zsxq_groups"],
    "PERM_ZSXQ_002": ["refresh_zsxq_groups"],
    "CONFIG_DEP_001": ["install_zsxq_cli"],
    "SOURCE_PARSE_001": ["install_zsxq_cli"],
    # PDF errors
    "EXTRACT_PDF_001": ["handle_pdf_ocr"],
    "EXTRACT_PDF_002": ["handle_pdf_ocr"],
    "EXTRACT_PDF_003": ["handle_pdf_ocr"],
    # Analysis errors
    "ANALYSIS_PIPELINE_001": ["retry_ingest_job", "export_diagnostic_bundle"],
    "ANALYSIS_ELIGIBILITY_001": ["review_open_items"],
    # LLM errors
    "AUTH_LLM_001": ["configure_llm"],
    "AUTH_LLM_002": ["configure_llm"],
    "LLM_CALL_001": ["configure_llm"],
    # Vault
    "VAULT_NOT_FOUND_001": ["run_vault_lint"],
    "VAULT_LINT_001": ["run_vault_lint"],
    # Graph
    "GRAPH_BUILD_001": ["rebuild_graph"],
    # DB
    "DB_CONNECT_001": ["export_diagnostic_bundle"],
    "DB_WRITE_001": ["export_diagnostic_bundle"],
    # General
    "SOURCE_FETCH_001": ["retry_ingest_job"],
}

# Subsystem → default recovery actions
_SUBSYSTEM_ACTIONS: dict[str, list[str]] = {
    "ingest": ["retry_ingest_job"],
    "review": ["review_open_items"],
    "zsxq": ["install_zsxq_cli", "login_zsxq", "refresh_zsxq_groups"],
    "pdf": ["handle_pdf_ocr"],
    "vault": ["run_vault_lint"],
    "search": [],
    "graph": ["rebuild_graph"],
    "operations": [],
    "config": ["configure_llm", "export_diagnostic_bundle"],
}


class RecoveryActionRegistry:
    """Central lookup for recovery actions by various keys."""

    @staticmethod
    def get(action_id: str) -> RecoveryAction | None:
        for a in RECOVERY_ACTIONS:
            if a.action_id == action_id:
                return a
        return None

    @staticmethod
    def list_all() -> list[RecoveryAction]:
        return list(RECOVERY_ACTIONS)

    @staticmethod
    def list_by_category(category: str) -> list[RecoveryAction]:
        return [a for a in RECOVERY_ACTIONS if a.category == category]

    @staticmethod
    def for_error_code(error_code: str) -> list[RecoveryAction]:
        """Get recovery actions relevant to a specific error_code."""
        action_ids = _ERROR_TO_ACTION.get(error_code, [])
        if not action_ids:
            # Try prefix match (e.g. "AUTH_ZSXQ_" for any ZSXQ auth error)
            for prefix, ids in _ERROR_TO_ACTION.items():
                if error_code.startswith(prefix.rstrip("0123456789_")) or error_code.startswith(prefix[:8]):
                    action_ids = ids
                    break
        result = []
        for aid in action_ids:
            a = RecoveryActionRegistry.get(aid)
            if a:
                result.append(a)
        return result

    @staticmethod
    def for_subsystem(subsystem: str) -> list[RecoveryAction]:
        """Get default recovery actions for a subsystem."""
        action_ids = _SUBSYSTEM_ACTIONS.get(subsystem, [])
        result = []
        for aid in action_ids:
            a = RecoveryActionRegistry.get(aid)
            if a:
                result.append(a)
        return result

    @staticmethod
    def for_error_or_subsystem(error_code: str, subsystem: str = "") -> list[RecoveryAction]:
        """Get actions: prefer error_code-specific, fall back to subsystem defaults."""
        actions = RecoveryActionRegistry.for_error_code(error_code)
        if actions:
            return actions
        if subsystem:
            return RecoveryActionRegistry.for_subsystem(subsystem)
        # Fall back to generic diagnostic bundle export
        a = RecoveryActionRegistry.get("export_diagnostic_bundle")
        return [a] if a else []


# Registered recovery actions
RECOVERY_ACTIONS: list[RecoveryAction] = [
    RecoveryAction(
        action_id="install_zsxq_cli",
        title="安装 zsxq-cli",
        description="知识星球命令行工具未安装。安装后可导入已订阅的星球内容。",
        command="pip install zsxq-cli",
        severity="error",
        category="zsxq",
    ),
    RecoveryAction(
        action_id="login_zsxq",
        title="登录知识星球",
        description="知识星球未登录，无法获取已订阅内容。",
        command="zsxq-cli auth login",
        severity="warning",
        category="zsxq",
    ),
    RecoveryAction(
        action_id="refresh_zsxq_groups",
        title="刷新授权星球列表",
        description="运行后同步最新星球授权状态。",
        command="signalvault zsxq groups --refresh",
        severity="info",
        category="zsxq",
    ),
    RecoveryAction(
        action_id="retry_ingest_job",
        title="重试失败摄入任务",
        description="有摄入任务失败。重试可能恢复。",
        command="signalvault ingest retry <job_id>",
        severity="warning",
        category="ingest",
    ),
    RecoveryAction(
        action_id="review_open_items",
        title="处理待审核事项",
        description="审核队列中有待处理的问题，建议逐个审核。",
        command="signalvault review list",
        severity="warning",
        category="review",
    ),
    RecoveryAction(
        action_id="run_vault_lint",
        title="检查知识库健康",
        description="运行 Vault 健康检查以发现格式问题。",
        command="signalvault vault-lint --vault <path>",
        severity="info",
        category="vault",
    ),
    RecoveryAction(
        action_id="rebuild_graph",
        title="重建知识图谱",
        description="知识图谱数据不足或重建失败时，可重新构建。",
        command="signalvault graph rebuild",
        severity="warning",
        category="graph",
    ),
    RecoveryAction(
        action_id="configure_llm",
        title="配置 AI 模型",
        description="在 .env 中配置 LLM_API_KEY 以使用真实 AI 分析（当前为 Mock 模式）。",
        command="编辑 .env 文件，添加 LLM_PROVIDER 和 LLM_API_KEY",
        severity="info",
        category="config",
    ),
    RecoveryAction(
        action_id="handle_pdf_ocr",
        title="处理需 OCR 的 PDF",
        description="有 PDF 文件需要 OCR 处理。当前暂不支持自动 OCR。",
        command="使用外部 OCR 工具预处理扫描版 PDF",
        severity="info",
        category="pdf",
        user_message="PDF 可能是扫描件，当前已加入待处理列表。",
    ),
    RecoveryAction(
        action_id="export_diagnostic_bundle",
        title="导出诊断包",
        description="导出系统诊断信息（已自动脱敏），发送给技术支持进行远程排查。",
        command="signalvault diagnostics bundle --output ./diagnostics",
        severity="info",
        category="config",
        user_message="如需远程协助，请导出诊断包（已自动脱敏，不包含密钥和原文）。",
    ),
]


@lru_cache(maxsize=1)
def get_recovery_action(action_id: str) -> RecoveryAction | None:
    return RecoveryActionRegistry.get(action_id)


def list_recovery_actions(category: str | None = None) -> list[dict]:
    if category:
        return [a.to_dict() for a in RecoveryActionRegistry.list_by_category(category)]
    return [a.to_dict() for a in RecoveryActionRegistry.list_all()]


def actions_for_error_code(error_code: str) -> list[dict]:
    """Get recovery actions for a given error_code (JSON-safe)."""
    return [a.to_dict() for a in RecoveryActionRegistry.for_error_code(error_code)]


def actions_for_subsystem(subsystem: str) -> list[dict]:
    """Get recovery actions for a subsystem (JSON-safe)."""
    return [a.to_dict() for a in RecoveryActionRegistry.for_subsystem(subsystem)]


# ═════════════════════════════════════════════════════════════════════════════
# DiagnosticsCenter
# ═════════════════════════════════════════════════════════════════════════════


class DiagnosticsCenter:
    """Aggregate system health across all subsystems."""

    @staticmethod
    def get_summary(
        session=None,
        *,
        check_zsxq: bool = False,
        vault_path: str = "",
    ) -> DiagnosticsSummary:
        """Build a full DiagnosticsSummary.

        Args:
            session: Optional DB session for testability.
            check_zsxq: If True, try to check zsxq-cli (requires real CLI).
                        Default False — in tests/mock mode, uses local registry only.
            vault_path: Optional Obsidian vault path for lint check.
        """
        summary = DiagnosticsSummary(
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

        # Collect all subsystem statuses
        subsystems: list[SubsystemStatus] = []

        subsystems.append(DiagnosticsCenter._check_ingest(session))
        subsystems.append(DiagnosticsCenter._check_review(session))
        subsystems.append(DiagnosticsCenter._check_operations(session))
        subsystems.append(DiagnosticsCenter._check_zsxq(session, check_zsxq=check_zsxq))
        subsystems.append(DiagnosticsCenter._check_pdf(session))
        subsystems.append(DiagnosticsCenter._check_vault(session, vault_path=vault_path))
        subsystems.append(DiagnosticsCenter._check_search(session))
        subsystems.append(DiagnosticsCenter._check_graph(session))
        subsystems.append(DiagnosticsCenter._check_config())

        summary.subsystems = subsystems

        # Collect recent failures from operation logs
        summary.recent_failures = DiagnosticsCenter._get_recent_failures(session)

        # Aggregate counts
        summary.open_review_count = sum(
            s.counts.get("open_items", 0) for s in subsystems if s.name == "review"
        )
        summary.blocked_count = sum(1 for s in subsystems if s.status == STATUS_BLOCKED)
        summary.attention_count = sum(1 for s in subsystems if s.status == STATUS_ATTENTION)

        # Compute overall status
        summary.overall_status = DiagnosticsCenter._compute_overall(summary)

        # Collect suggested actions from subsystems
        actions: list[dict] = []
        seen: set[str] = set()
        for s in summary.subsystems:
            for action_id in s.suggested_actions:
                if action_id not in seen:
                    seen.add(action_id)
                    ra = get_recovery_action(action_id)
                    if ra:
                        actions.append(ra.to_dict())
        summary.suggested_actions = actions

        # Always add diagnostic bundle export as a fallback action
        bundle_action = get_recovery_action("export_diagnostic_bundle")
        if bundle_action and summary.overall_status in (STATUS_ATTENTION, STATUS_BLOCKED):
            bid = bundle_action.action_id
            if bid not in seen:
                summary.suggested_actions.append(bundle_action.to_dict())

        summary.metadata = {
            "subsystem_count": len(summary.subsystems),
            "total_issues": sum(len(s.issues) for s in summary.subsystems),
            "user_guidance": _overall_guidance(summary.overall_status),
        }

        return summary

    # ── Overall status computation ──────────────────────────────────────

    @staticmethod
    def _compute_overall(summary: DiagnosticsSummary) -> str:
        if summary.blocked_count > 0:
            return STATUS_BLOCKED
        if summary.attention_count > 0 or summary.open_review_count > 0:
            return STATUS_ATTENTION
        return STATUS_OK

    # ── Ingest subsystem ────────────────────────────────────────────────

    @staticmethod
    def _check_ingest(session=None) -> SubsystemStatus:
        try:
            from signalvault.sources.ingest_jobs import IngestJobManager
            counts = IngestJobManager.count_by_status(session=session)
        except Exception as e:
            return SubsystemStatus(
                name="ingest", label="摄入队列",
                status=STATUS_UNKNOWN,
                summary=f"无法查询摄入状态: {e}",
            )

        pending = counts.get("pending_preview", 0)
        failed = counts.get("preview_failed", 0)
        expired = counts.get("expired", 0)

        status = STATUS_OK
        issues: list[str] = []
        actions: list[str] = []

        if failed > 0:
            status = STATUS_ATTENTION
            issues.append(f"{failed} 个摄入任务失败")
            actions.append("retry_ingest_job")
        if pending > 10:
            status = STATUS_ATTENTION
            issues.append(f"待处理摄入任务较多 ({pending} 个)")
        if expired > 5:
            status = STATUS_ATTENTION
            issues.append(f"{expired} 个摄入任务已过期")

        return SubsystemStatus(
            name="ingest", label="摄入队列",
            status=status,
            summary=f"待处理 {pending}，失败 {failed}，过期 {expired}",
            counts={"pending": pending, "failed": failed, "expired": expired},
            issues=issues,
            suggested_actions=actions,
        )

    # ── Review subsystem ────────────────────────────────────────────────

    @staticmethod
    def _check_review(session=None) -> SubsystemStatus:
        try:
            from signalvault.sources.review_items import ReviewItemManager
            items = ReviewItemManager.list_items(status="open", limit=200, session=session)
        except Exception as e:
            return SubsystemStatus(
                name="review", label="审核队列",
                status=STATUS_UNKNOWN,
                summary=f"无法查询审核队列: {e}",
            )

        open_count = len(items)
        error_count = sum(1 for i in items if i.get("severity") == "error")
        warning_count = sum(1 for i in items if i.get("severity") == "warning")

        status = STATUS_OK
        issues: list[str] = []
        actions: list[str] = []

        if error_count > 0:
            status = STATUS_ATTENTION
            issues.append(f"{error_count} 个严重审核项待处理")
            actions.append("review_open_items")
        elif warning_count > 5:
            status = STATUS_ATTENTION
            issues.append(f"{warning_count} 个警告审核项待处理")
            actions.append("review_open_items")

        # Collect type distribution (top 5)
        type_counts: dict[str, int] = {}
        for i in items:
            t = i.get("item_type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
        top_types = sorted(type_counts.items(), key=lambda x: -x[1])[:5]

        return SubsystemStatus(
            name="review", label="审核队列",
            status=status,
            summary=f"待审核 {open_count} 项（严重 {error_count}，警告 {warning_count}）",
            counts={"open_items": open_count, "error": error_count, "warning": warning_count},
            issues=issues,
            suggested_actions=actions,
            metadata={"top_types": dict(top_types)},
        )

    # ── Operations subsystem ────────────────────────────────────────────

    @staticmethod
    def _check_operations(session=None) -> SubsystemStatus:
        try:
            from signalvault.diagnostics.operation_log import OperationLogManager
            failures = OperationLogManager.recent_failures(limit=10, session=session)
            counts = OperationLogManager.count_by_status(session=session)
        except Exception as e:
            return SubsystemStatus(
                name="operations", label="操作日志",
                status=STATUS_UNKNOWN,
                summary=f"无法查询操作日志: {e}",
            )

        failed_count = counts.get("failed", 0)
        total = sum(counts.values())

        status = STATUS_OK
        issues: list[str] = []
        actions: list[str] = []

        if failed_count >= 3:
            status = STATUS_ATTENTION
            issues.append(f"最近 {failed_count} 个操作失败")
            # Extract error codes from recent failures
            error_codes = {f.get("error_code", "") for f in failures if f.get("error_code")}
            if error_codes:
                issues.append(f"错误类型: {', '.join(sorted(error_codes)[:3])}")

        return SubsystemStatus(
            name="operations", label="操作日志",
            status=status,
            summary=f"共 {total} 条操作记录，失败 {failed_count}",
            counts={"total": total, "failed": failed_count,
                     "succeeded": counts.get("succeeded", 0)},
            issues=issues,
            suggested_actions=actions,
            metadata={"recent_error_codes": [f.get("error_code") for f in failures[:5]
                                               if f.get("error_code")]},
        )

    # ── ZSXQ subsystem ──────────────────────────────────────────────────

    @staticmethod
    def _check_zsxq(session=None, *, check_zsxq: bool = False) -> SubsystemStatus:
        """Check ZSXQ status. In mock/test mode, only checks registry."""

        from signalvault.config import DATA_DIR

        registry_file = DATA_DIR / "zsxq_groups.json"

        # Check registry
        groups: list[dict] = []
        if registry_file.exists():
            import json
            try:
                data = json.loads(registry_file.read_text(encoding="utf-8"))
                groups = data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError):
                pass

        active = sum(1 for g in groups if g.get("access_status") == "active")
        inaccessible = sum(1 for g in groups if g.get("access_status") == "inaccessible")
        total = len(groups)

        actions: list[str] = []

        # Try zsxq-cli check (only if explicitly requested — may not exist)
        cli_available = False
        logged_in = False
        cli_error = ""

        if check_zsxq:
            try:
                from signalvault.sources.zsxq_cli import check_cli
                cli_result = check_cli()
                cli_available = cli_result.get("available", False)
                logged_in = cli_result.get("logged_in", False)
                if cli_result.get("error"):
                    cli_error = cli_result["error"]
            except Exception as e:
                cli_error = str(e)
        else:
            # Lightweight: just check if binary exists
            import shutil
            cli_available = shutil.which("zsxq-cli") is not None or shutil.which("zsxq") is not None

        status = STATUS_OK
        issues: list[str] = []

        if not cli_available:
            status = STATUS_ATTENTION
            issues.append("zsxq-cli 未安装")
            actions.append("install_zsxq_cli")
        elif check_zsxq and not logged_in:
            status = STATUS_ATTENTION
            issues.append("知识星球未登录")
            actions.append("login_zsxq")

        if inaccessible > 0:
            issues.append(f"{inaccessible} 个星球授权已失效")

        summary_parts = []
        if cli_available:
            summary_parts.append("CLI 可用" if not check_zsxq or logged_in else "CLI 可用（未登录）")
        else:
            summary_parts.append("CLI 不可用")
        summary_parts.append(f"{total} 个星球（{active} 活跃）")
        summary = "，".join(summary_parts)

        return SubsystemStatus(
            name="zsxq", label="知识星球",
            status=status,
            summary=summary,
            counts={"groups_total": total, "groups_active": active,
                     "groups_inaccessible": inaccessible},
            issues=issues,
            suggested_actions=actions,
            metadata={"cli_available": cli_available, "logged_in": logged_in,
                       "cli_error": cli_error},
        )

    # ── PDF subsystem ───────────────────────────────────────────────────

    @staticmethod
    def _check_pdf(session=None) -> SubsystemStatus:
        try:
            from signalvault.sources.review_items import ReviewItemManager
            items = ReviewItemManager.list_items(status="open", limit=200, session=session)
        except Exception:
            items = []

        pdf_types = {"pdf_needs_ocr", "pdf_quality_issue", "pdf_extraction_failed"}
        pdf_items = [i for i in items if i.get("item_type") in pdf_types]

        needs_ocr = sum(1 for i in pdf_items if i["item_type"] == "pdf_needs_ocr")
        quality_issue = sum(1 for i in pdf_items if i["item_type"] == "pdf_quality_issue")
        extraction_failed = sum(1 for i in pdf_items if i["item_type"] == "pdf_extraction_failed")

        status = STATUS_OK
        issues: list[str] = []
        actions: list[str] = []

        if extraction_failed > 0:
            status = STATUS_ATTENTION
            issues.append(f"{extraction_failed} 个 PDF 提取失败")
        if needs_ocr > 0:
            issues.append(f"{needs_ocr} 个 PDF 需要 OCR")
            actions.append("handle_pdf_ocr")
        if quality_issue > 0:
            issues.append(f"{quality_issue} 个 PDF 质量偏低")

        return SubsystemStatus(
            name="pdf", label="PDF 处理",
            status=status,
            summary=f"需 OCR: {needs_ocr}，质量问题: {quality_issue}，提取失败: {extraction_failed}",
            counts={"needs_ocr": needs_ocr, "quality_issue": quality_issue,
                     "extraction_failed": extraction_failed},
            issues=issues,
            suggested_actions=actions,
        )

    # ── Vault subsystem ─────────────────────────────────────────────────

    @staticmethod
    def _check_vault(session=None, *, vault_path: str = "") -> SubsystemStatus:
        from signalvault.config import OBSIDIAN_VAULT_PATH

        path = vault_path or OBSIDIAN_VAULT_PATH
        vault_configured = bool(path)
        vault_exists = False

        if vault_configured:
            from pathlib import Path
            vault_exists = Path(path).exists()

        # Check vault lint review items
        lint_types = {"lint_frontmatter_invalid", "lint_frontmatter_missing",
                       "lint_dead_wikilink", "lint_duplicate_report", "lint_orphan_card"}
        lint_count = 0
        try:
            from signalvault.sources.review_items import ReviewItemManager
            items = ReviewItemManager.list_items(status="open", limit=200, session=session)
            lint_count = sum(1 for i in items if i.get("item_type") in lint_types)
        except Exception:
            pass

        status = STATUS_OK
        issues: list[str] = []
        actions: list[str] = []

        if not vault_configured:
            status = STATUS_ATTENTION
            issues.append("Obsidian Vault 未配置")
        elif not vault_exists:
            status = STATUS_ATTENTION
            issues.append(f"Vault 目录不存在: {path}")

        if lint_count > 0:
            status = STATUS_ATTENTION
            issues.append(f"{lint_count} 个 Vault 格式问题")
            actions.append("run_vault_lint")

        summary = "已配置" if vault_configured and vault_exists else "未配置或路径不存在"

        return SubsystemStatus(
            name="vault", label="Obsidian 知识库",
            status=status,
            summary=summary,
            counts={"lint_issues": lint_count},
            issues=issues,
            suggested_actions=actions,
            metadata={"configured": vault_configured, "exists": vault_exists},
        )

    # ── Search subsystem ────────────────────────────────────────────────

    @staticmethod
    def _check_search(session=None) -> SubsystemStatus:
        # Lightweight check: can we perform a basic query?
        search_ok = False
        try:
            from signalvault.db.unified_search import unified_search
            results = unified_search(session or __import__("signalvault.db.session", fromlist=["get_session"]).get_session(),
                                     keyword="测试", limit=1)
            search_ok = isinstance(results, list)
        except Exception:
            search_ok = False

        status = STATUS_OK if search_ok else STATUS_ATTENTION

        return SubsystemStatus(
            name="search", label="统一搜索",
            status=status,
            summary="搜索功能正常" if search_ok else "搜索功能异常",
            counts={},
            issues=[] if search_ok else ["搜索功能可能不可用"],
            suggested_actions=[],
            metadata={"available": search_ok},
        )

    # ── Graph subsystem ─────────────────────────────────────────────────

    @staticmethod
    def _check_graph(session=None) -> SubsystemStatus:
        try:
            from sqlalchemy import func
            if session is None:
                from signalvault.db.session import get_session
                s = get_session()
                _close = True
            else:
                s = session
                _close = False

            from signalvault.db.models import KnowledgeEdge, KnowledgeNode
            node_count = s.query(func.count(KnowledgeNode.id)).scalar() or 0
            edge_count = s.query(func.count(KnowledgeEdge.id)).scalar() or 0

            if _close:
                s.close()
        except Exception:
            node_count = 0
            edge_count = 0

        # Check if graph rebuild recently failed
        rebuild_failed = False
        try:
            from signalvault.diagnostics.operation_log import OperationLogManager
            failures = OperationLogManager.list_operations(
                operation_type="graph.rebuild", status="failed", limit=5, session=session,
            )
            rebuild_failed = len(failures) > 0
        except Exception:
            pass

        status = STATUS_OK
        issues: list[str] = []
        actions: list[str] = []

        if node_count == 0 and edge_count == 0:
            # New/empty DB — not necessarily a problem
            status = STATUS_OK
        elif rebuild_failed:
            status = STATUS_ATTENTION
            issues.append("最近图谱重建失败")
            actions.append("rebuild_graph")

        return SubsystemStatus(
            name="graph", label="知识图谱",
            status=status,
            summary=f"{node_count} 节点，{edge_count} 边" + ("（重建失败）" if rebuild_failed else ""),
            counts={"nodes": node_count, "edges": edge_count},
            issues=issues,
            suggested_actions=actions,
            metadata={"rebuild_failed": rebuild_failed},
        )

    # ── Config subsystem ────────────────────────────────────────────────

    @staticmethod
    def _check_config() -> SubsystemStatus:
        from pathlib import Path

        from signalvault.config import (
            DATA_DIR,
            DB_PATH,
            LLM_API_KEY,
            LLM_MODEL,
            LLM_PROVIDER,
            OBSIDIAN_VAULT_PATH,
        )

        issues: list[str] = []
        actions: list[str] = []

        # Check LLM config (without revealing keys)
        llm_configured = bool(LLM_API_KEY and LLM_API_KEY.strip())
        llm_model_set = bool(LLM_MODEL and LLM_MODEL != "mock-v1")
        is_mock = LLM_PROVIDER == "mock"

        if is_mock or not llm_configured:
            issues.append("当前使用 Mock 模式（不产生真实 AI 分析）")
            if not llm_configured:
                actions.append("configure_llm")

        # Check DB
        db_exists = Path(DB_PATH).exists()

        # Check data dir
        data_exists = Path(DATA_DIR).exists()

        # Check Obsidian
        obsidian_configured = bool(OBSIDIAN_VAULT_PATH)
        obsidian_exists = Path(OBSIDIAN_VAULT_PATH).exists() if obsidian_configured else False

        # Check zsxq-cli
        import shutil
        zsxq_cli = shutil.which("zsxq-cli") is not None or shutil.which("zsxq") is not None

        missing: list[str] = []
        if not llm_configured:
            missing.append("LLM_API_KEY")
        if not obsidian_configured:
            missing.append("OBSIDIAN_VAULT_PATH")
        if not zsxq_cli:
            missing.append("zsxq-cli")

        status = STATUS_OK
        if not db_exists:
            status = STATUS_BLOCKED
            issues.append("数据库文件不存在")
        elif missing:
            status = STATUS_ATTENTION

        summary = f"LLM: {'Mock' if is_mock else LLM_PROVIDER}"
        if missing:
            summary += f"，缺失: {', '.join(missing[:3])}"

        return SubsystemStatus(
            name="config", label="系统配置",
            status=status,
            summary=summary,
            counts={},
            issues=issues,
            suggested_actions=actions,
            metadata={
                "llm_provider": LLM_PROVIDER,
                "llm_model_set": llm_model_set,
                "llm_key_set": llm_configured,
                "db_exists": db_exists,
                "data_dir_exists": data_exists,
                "obsidian_configured": obsidian_configured,
                "obsidian_exists": obsidian_exists,
                "zsxq_cli_on_path": zsxq_cli,
                "missing_items": missing,
            },
        )

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _get_recent_failures(session=None) -> list[dict]:
        try:
            from signalvault.diagnostics.operation_log import OperationLogManager
            failures = OperationLogManager.recent_failures(limit=5, session=session)
            return [
                {
                    "operation_type": f.get("operation_type", ""),
                    "error_code": f.get("error_code", ""),
                    "summary": f.get("summary", ""),
                    "occurred_at": f.get("started_at", ""),
                    "operation_id": f.get("operation_id", ""),
                }
                for f in failures
            ]
        except Exception:
            return []

def _overall_guidance(status: str) -> str:
    """Return a user-facing guidance message for each overall status."""
    if status == STATUS_BLOCKED:
        return "系统存在阻断性问题，部分功能不可用。请按上方建议操作，或导出诊断包发送给技术支持。"
    elif status == STATUS_ATTENTION:
        return "系统基本正常，但有一些需要关注的事项。请查看上方建议，逐步处理。"
    else:
        return "系统运行正常，所有检查项均通过。"


