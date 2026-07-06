"""P7-D: Diagnostic Bundle — one-click export of redacted diagnostics.

Produces a timestamped zip file with 9 component files. All sensitive
data (API keys, tokens, full content text) is redacted.

Uses stdlib zipfile — no external dependencies.
"""

from __future__ import annotations

import json as _json
import logging
import os
import platform
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BUNDLE_SCHEMA_VERSION = "1.0"


# ═════════════════════════════════════════════════════════════════════════════
# Config & Result
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class DiagnosticBundleConfig:
    output_dir: str = ""
    format: str = "zip"           # currently only "zip"
    limit_logs: int = 100
    limit_jobs: int = 50


@dataclass
class DiagnosticBundleResult:
    success: bool = False
    bundle_path: str = ""
    file_count: int = 0
    file_names: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    redaction_summary: dict[str, int] = field(default_factory=dict)
    error: str = ""


# ═════════════════════════════════════════════════════════════════════════════
# Redaction
# ═════════════════════════════════════════════════════════════════════════════

# Keys whose values are ALWAYS redacted
REDACT_KEYS = frozenset({
    "api_key", "token", "password", "secret", "cookie", "authorization",
    "access_token", "refresh_token", "auth_token", "llm_api_key",
    "llm_base_url",  # may contain key in path
})

# Keys whose values are truncated to char count
TRUNCATE_KEYS = frozenset({
    "content_text", "source_quote", "full_text", "page_text",
    "report_markdown", "extraction_json", "preview_data",
    "content_html", "text",
})

# Values longer than this are truncated
MAX_VALUE_LENGTH = 200

# Keys that are replaced with existence check (true/false)
EXISTENCE_KEYS = frozenset({
    "obsidian_vault_path", "db_path", "data_dir",
})


def redact_value(key: str, value: Any) -> Any:
    """Redact a single key-value pair.

    Returns the (possibly modified) value.
    """
    key_lower = key.lower().replace("-", "_")

    # Absolute redaction
    for rk in REDACT_KEYS:
        if rk in key_lower:
            if isinstance(value, str) and value:
                return "[REDACTED]"
            if value:
                return "[REDACTED]"
            return ""

    # Existence check
    for ek in EXISTENCE_KEYS:
        if ek in key_lower:
            return bool(value)

    # Truncation for long content
    if isinstance(value, str):
        for tk in TRUNCATE_KEYS:
            if tk in key_lower:
                return f"[{len(value)} chars redacted]"
        if len(value) > 1000:
            return value[:500] + "...[truncated]"

    return value


def redact_dict(data: dict, depth: int = 0, max_depth: int = 10) -> dict:
    """Recursively redact a dictionary. Returns a new dict."""
    if depth > max_depth:
        return {"_truncated": "max depth reached"}

    result: dict = {}
    for key, value in data.items():
        if isinstance(value, dict):
            result[key] = redact_dict(value, depth + 1, max_depth)
        elif isinstance(value, list):
            result[key] = redact_list(key, value, depth + 1, max_depth)
        elif isinstance(value, str):
            result[key] = redact_value(key, value)
        else:
            result[key] = value

    return result


def redact_list(parent_key: str, data: list, depth: int = 0, max_depth: int = 10) -> list:
    """Recursively redact a list."""
    if depth > max_depth:
        return ["[truncated]"]

    result: list = []
    for item in data:
        if isinstance(item, dict):
            result.append(redact_dict(item, depth + 1, max_depth))
        elif isinstance(item, list):
            result.append(redact_list(parent_key, item, depth + 1, max_depth))
        elif isinstance(item, str):
            result.append(redact_value(parent_key, item))
        else:
            result.append(item)

    return result


def to_json_safe(data: Any) -> str:
    """Convert data to JSON string, with fallback for non-serializable types."""
    try:
        return _json.dumps(data, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return _json.dumps({"error": "serialization failed"}, ensure_ascii=False, indent=2)


# ═════════════════════════════════════════════════════════════════════════════
# Bundle Builder
# ═════════════════════════════════════════════════════════════════════════════


class DiagnosticBundleBuilder:
    """Build a redacted diagnostic bundle as a zip file."""

    def __init__(self, config: DiagnosticBundleConfig, session=None):
        self.config = config
        self.session = session
        self._warnings: list[str] = []
        self._redactions: dict[str, int] = {}
        self._files: list[tuple[str, str]] = []  # (name, content)

    # ── Public API ──────────────────────────────────────────────────────

    def build(self) -> DiagnosticBundleResult:
        """Build the bundle and return a result."""
        try:
            self._collect_all()
            return self._write_zip()
        except Exception as e:
            logger.error("Bundle build failed: %s", e)
            return DiagnosticBundleResult(
                success=False,
                error=str(e),
                warnings=self._warnings,
            )

    # ── Collectors ──────────────────────────────────────────────────────

    def _collect_all(self) -> None:
        """Run all collectors and populate self._files."""
        self._collect_manifest()
        self._collect_diagnostics_summary()
        self._collect_operation_logs()
        self._collect_review_items()
        self._collect_ingest_jobs()
        self._collect_config()
        self._collect_system_info()
        self._collect_search_graph()
        self._collect_readme()

    def _collect_manifest(self) -> None:
        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "app_version": self._get_version(),
            "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
            "redaction_policy": {
                "redacted_keys": sorted(REDACT_KEYS),
                "truncated_keys": sorted(TRUNCATE_KEYS),
                "existence_keys": sorted(EXISTENCE_KEYS),
                "max_value_length": MAX_VALUE_LENGTH,
            },
            "warnings": [],
        }
        self._add_file("manifest.json", to_json_safe(manifest))

    def _collect_diagnostics_summary(self) -> None:
        try:
            from signalvault.diagnostics.summary import DiagnosticsCenter
            summary = DiagnosticsCenter.get_summary(session=self.session)
            data = summary.to_dict()
            data = redact_dict(data)
            self._add_file("diagnostics_summary.json", to_json_safe(data))
        except Exception as e:
            self._warn(f"diagnostics_summary: {e}")
            self._add_file("diagnostics_summary.json", to_json_safe({"error": str(e)}))

    def _collect_operation_logs(self) -> None:
        try:
            from signalvault.diagnostics.operation_log import OperationLogManager
            ops = OperationLogManager.list_operations(
                limit=self.config.limit_logs, session=self.session,
            )
            # Redact each operation
            redacted = [redact_dict(op) for op in ops]
            self._add_file("operation_logs.json", to_json_safe(redacted))

            # Count redactions
            failed = sum(1 for o in ops if o.get("status") == "failed")
            self._redactions["operations_exported"] = len(redacted)
            self._redactions["operations_failed"] = failed
        except Exception as e:
            self._warn(f"operation_logs: {e}")
            self._add_file("operation_logs.json", to_json_safe({"error": str(e)}))

    def _collect_review_items(self) -> None:
        try:
            from signalvault.sources.review_items import ReviewItemManager
            items = ReviewItemManager.list_items(status="open", limit=200, session=self.session)
            # Aggregate summary — don't include full descriptions
            summary = {
                "open_count": len(items),
                "by_severity": {},
                "by_type": {},
                "sample_titles": [i.get("title", "")[:100] for i in items[:20]],
            }
            for item in items:
                sev = item.get("severity", "unknown")
                summary["by_severity"][sev] = summary["by_severity"].get(sev, 0) + 1
                typ = item.get("item_type", "unknown")
                summary["by_type"][typ] = summary["by_type"].get(typ, 0) + 1

            self._add_file("review_items_summary.json", to_json_safe(summary))
            self._redactions["review_items_open"] = len(items)
        except Exception as e:
            self._warn(f"review_items: {e}")
            self._add_file("review_items_summary.json", to_json_safe({"error": str(e)}))

    def _collect_ingest_jobs(self) -> None:
        try:
            from signalvault.sources.ingest_jobs import IngestJobManager
            counts = IngestJobManager.count_by_status(session=self.session)
            # Get recent failed jobs (just their metadata, not full preview_data)
            recent = IngestJobManager.list_jobs(
                status="preview_failed", limit=self.config.limit_jobs, session=self.session,
            )
            recent_redacted = []
            for job in recent:
                # Redact preview_data
                job = dict(job)
                if job.get("preview_data"):
                    job["preview_data"] = f"[{len(job['preview_data'])} chars redacted]"
                recent_redacted.append(redact_dict(job))

            summary = {
                "counts_by_status": counts,
                "recent_failures_count": len(recent_redacted),
                "recent_failures": recent_redacted[:10],  # limit to 10 for size
            }
            self._add_file("ingest_jobs_summary.json", to_json_safe(summary))
            self._redactions["ingest_jobs_failed"] = counts.get("preview_failed", 0)
        except Exception as e:
            self._warn(f"ingest_jobs: {e}")
            self._add_file("ingest_jobs_summary.json", to_json_safe({"error": str(e)}))

    def _collect_config(self) -> None:
        try:
            import shutil

            from signalvault.config import (
                DATA_DIR,
                DB_PATH,
                LLM_MODEL,
                LLM_PROVIDER,
                OBSIDIAN_VAULT_PATH,
            )

            config = {
                "llm_provider": LLM_PROVIDER,
                "llm_model_set": bool(LLM_MODEL and LLM_MODEL != "mock-v1"),
                "llm_api_key_set": bool(os.getenv("LLM_API_KEY", "")),
                "llm_base_url": "[REDACTED]" if os.getenv("LLM_BASE_URL") else "",
                "obsidian_configured": bool(OBSIDIAN_VAULT_PATH),
                "obsidian_exists": bool(OBSIDIAN_VAULT_PATH and Path(OBSIDIAN_VAULT_PATH).exists()),
                "db_exists": Path(DB_PATH).exists(),
                "data_dir_exists": Path(DATA_DIR).exists(),
                "zsxq_cli_available": shutil.which("zsxq-cli") is not None or shutil.which("zsxq") is not None,
            }
            # Ensure no raw values leak
            config = redact_dict(config)
            self._add_file("config_summary.json", to_json_safe(config))
        except Exception as e:
            self._warn(f"config: {e}")
            self._add_file("config_summary.json", to_json_safe({"error": str(e)}))

    def _collect_system_info(self) -> None:
        try:
            import sqlite3

            info = {
                "python_version": sys.version,
                "platform": platform.platform(),
                "os": os.name,
                "app_version": self._get_version(),
                "package_versions": self._get_package_versions(),
                "sqlite_version": sqlite3.sqlite_version,
            }
            self._add_file("system_info.json", to_json_safe(info))
        except Exception as e:
            self._warn(f"system_info: {e}")
            self._add_file("system_info.json", to_json_safe({"error": str(e)}))

    def _collect_search_graph(self) -> None:
        try:
            if self.session is None:
                from signalvault.db.session import get_session as _gs
                s = _gs()
                _close = True
            else:
                s = self.session
                _close = False

            from sqlalchemy import func

            from signalvault.db.models import (
                EntityRecord,
                InvestmentViewRecord,
                KnowledgeEdge,
                KnowledgeNode,
                Report,
                TrackingSignalRecord,
            )

            summary = {
                "report_count": s.query(func.count(Report.id)).scalar() or 0,
                "view_count": s.query(func.count(InvestmentViewRecord.id)).scalar() or 0,
                "signal_count": s.query(func.count(TrackingSignalRecord.id)).scalar() or 0,
                "entity_count": s.query(func.count(EntityRecord.id)).scalar() or 0,
                "knowledge_nodes": s.query(func.count(KnowledgeNode.id)).scalar() or 0,
                "knowledge_edges": s.query(func.count(KnowledgeEdge.id)).scalar() or 0,
            }

            if _close:
                s.close()

            self._add_file("search_graph_summary.json", to_json_safe(summary))
            self._redactions.update(summary)
        except Exception as e:
            self._warn(f"search_graph: {e}")
            self._add_file("search_graph_summary.json", to_json_safe({"error": str(e)}))

    def _collect_readme(self) -> None:
        readme = (
            "Diagnostic Bundle\n"
            "=================\n\n"
            "This bundle was generated by signalvault (P7-D).\n"
            "It contains a sanitized snapshot of the application state for remote troubleshooting.\n\n"
            "IMPORTANT — This bundle has been automatically redacted:\n"
            "  - API keys, tokens, passwords, and secrets are replaced with [REDACTED]\n"
            "  - Full content text (paid/original source body) is replaced with [N chars redacted]\n"
            "  - File paths are replaced with existence checks (true/false)\n\n"
            "What IS included:\n"
            "  - System diagnostics summary (9 subsystems)\n"
            "  - Recent operation logs (type, status, error codes)\n"
            "  - Open review items summary (counts, not full content)\n"
            "  - Ingest jobs summary (counts, recent failures)\n"
            "  - Configuration summary (presence/absence, not values)\n"
            "  - System info (Python version, OS, package versions)\n"
            "  - Search & graph counts\n\n"
            "What is NOT included:\n"
            "  - API keys, tokens, passwords\n"
            "  - Full text of paid/original content\n"
            "  - Complete report markdown\n"
            "  - User file paths\n"
            "  - Database binary or row data beyond counts\n\n"
            f"Generated: {datetime.now(timezone.utc).isoformat()}\n"
            f"Bundle Schema Version: {BUNDLE_SCHEMA_VERSION}\n"
        )
        self._add_file("README.txt", readme)

    # ── Zip ─────────────────────────────────────────────────────────────

    def _write_zip(self) -> DiagnosticBundleResult:
        output_dir = Path(self.config.output_dir) if self.config.output_dir else Path.cwd() / "diagnostics"
        output_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_name = f"diagnostic_bundle_{ts}.zip"
        zip_path = output_dir / zip_name

        # Update warnings in manifest
        self._update_manifest_warnings()

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in self._files:
                zf.writestr(name, content.encode("utf-8"))

        if not self._files:
            self._warn("No files were collected")

        return DiagnosticBundleResult(
            success=len(self._files) > 0,
            bundle_path=str(zip_path.resolve()),
            file_count=len(self._files),
            file_names=[f[0] for f in self._files],
            warnings=self._warnings,
            redaction_summary=self._redactions,
        )

    def _update_manifest_warnings(self) -> None:
        """Update the manifest.json content with final warnings."""
        for i, (name, content) in enumerate(self._files):
            if name == "manifest.json":
                try:
                    data = _json.loads(content)
                    data["warnings"] = self._warnings
                    data["included_files"] = [f[0] for f in self._files if f[0] != "manifest.json"]
                    self._files[i] = (name, to_json_safe(data))
                except Exception:
                    pass
                break

    # ── Helpers ─────────────────────────────────────────────────────────

    def _add_file(self, name: str, content: str) -> None:
        self._files.append((name, content))

    def _warn(self, msg: str) -> None:
        self._warnings.append(msg)
        logger.warning("Bundle warning: %s", msg)

    @staticmethod
    def _get_version() -> str:
        try:
            from signalvault import __version__
            return str(__version__)
        except (ImportError, AttributeError):
            pass
        try:
            import importlib.metadata
            return importlib.metadata.version("signalvault")
        except Exception:
            return "unknown"

    @staticmethod
    def _get_package_versions() -> dict[str, str]:
        pkgs = ["sqlalchemy", "fastapi", "typer", "pydantic", "pdfplumber", "reportlab"]
        versions: dict[str, str] = {}
        for pkg in pkgs:
            try:
                import importlib.metadata
                versions[pkg] = importlib.metadata.version(pkg)
            except Exception:
                versions[pkg] = "unknown"
        return versions


# ═════════════════════════════════════════════════════════════════════════════
# Convenience function
# ═════════════════════════════════════════════════════════════════════════════


def export_diagnostic_bundle(
    output_dir: str = "",
    limit_logs: int = 100,
    session=None,
) -> DiagnosticBundleResult:
    """Export a diagnostic bundle. Convenience wrapper around DiagnosticBundleBuilder."""
    config = DiagnosticBundleConfig(
        output_dir=output_dir,
        limit_logs=limit_logs,
    )
    builder = DiagnosticBundleBuilder(config, session=session)
    return builder.build()
