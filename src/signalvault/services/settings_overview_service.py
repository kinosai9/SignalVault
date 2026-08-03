"""C2-C: Settings Overview Service — unified read-only aggregation.

Provides get_settings_overview(), get_system_info(), get_about_info()
for the settings homepage, system page, and about page.

Reuses ai_settings_service, obsidian_settings_service, diagnostics
summary, AppPaths, and DB schema — no duplicated logic.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# Settings Overview (for /settings homepage)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class SettingsOverview:
    """Aggregated view for the settings homepage — no secrets, no file contents."""

    # ── AI card ────────────────────────────────────────────────────────────
    ai_provider: str = "mock"
    ai_model: str = "mock-v1"
    ai_status_label: str = "Mock 模式"
    ai_status_class: str = "status-mock"
    ai_key_source: str = ""
    ai_last_validation_at: str = ""
    ai_overridden_by_env: bool = False
    ai_overridden_fields: list[str] = field(default_factory=list)

    # ── Obsidian card ──────────────────────────────────────────────────────
    obsidian_state: str = "disabled"
    obsidian_state_label: str = "已禁用"
    obsidian_vault_path: str = ""
    obsidian_vault_path_short: str = ""    # ~/Documents/MyVault style
    obsidian_has_metadata: bool = False
    obsidian_enabled: bool = False

    # ── System card ────────────────────────────────────────────────────────
    app_version: str = ""
    db_status: str = "正常"
    db_schema_version: int = 0
    data_dir: str = ""
    platform_info: str = ""
    web_url: str = ""

    # ── Diagnostics card ───────────────────────────────────────────────────
    diag_overall_status: str = "ok"
    diag_attention_count: int = 0
    diag_blocked_count: int = 0
    diag_recent_failures: int = 0
    diag_open_review_count: int = 0


def get_settings_overview() -> SettingsOverview:
    """Build the settings homepage overview from live state."""
    ov = SettingsOverview()

    # ── AI card ────────────────────────────────────────────────────────────
    try:
        from signalvault.services.ai_settings_service import get_ai_settings_view
        ai = get_ai_settings_view()
        ov.ai_provider = ai.provider
        ov.ai_model = ai.model
        ov.ai_status_label = ai.status_label
        ov.ai_status_class = ai.status_class
        ov.ai_key_source = ai.api_key_source
        ov.ai_last_validation_at = ai.last_validation_at
        ov.ai_overridden_by_env = ai.overridden_by_env
        ov.ai_overridden_fields = ai.overridden_by_env_fields
    except Exception:
        pass

    # ── Obsidian card ──────────────────────────────────────────────────────
    try:
        from signalvault.services.obsidian_settings_service import (
            get_obsidian_settings_view,
        )
        obs = get_obsidian_settings_view()
        ov.obsidian_state = obs.state
        ov.obsidian_state_label = obs.state_label
        ov.obsidian_vault_path = obs.vault_path
        ov.obsidian_vault_path_short = _shorten_path(obs.vault_path)
        ov.obsidian_has_metadata = obs.has_obsidian_metadata
        ov.obsidian_enabled = obs.enabled
    except Exception:
        pass

    # ── System card ────────────────────────────────────────────────────────
    ov.app_version = _get_version()
    ov.db_status, ov.db_schema_version = _get_db_status()
    ov.data_dir = _get_data_dir()
    ov.platform_info = _get_platform_info()
    ov.web_url = _get_web_url()

    # ── Diagnostics card ───────────────────────────────────────────────────
    try:
        from signalvault.diagnostics.summary import DiagnosticsCenter
        summary = DiagnosticsCenter.get_summary()
        ov.diag_overall_status = summary.overall_status
        ov.diag_attention_count = summary.attention_count
        ov.diag_blocked_count = summary.blocked_count
        ov.diag_recent_failures = len(summary.recent_failures)
        ov.diag_open_review_count = summary.open_review_count
    except Exception:
        pass

    return ov


# ═══════════════════════════════════════════════════════════════════════════════
# System Info (for /settings/system)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class SystemInfo:
    """Read-only system information for the system status page."""

    # App
    app_version: str = ""
    build_commit: str = ""
    release_channel: str = "RC"
    python_version: str = ""
    os_name: str = ""
    architecture: str = ""

    # Paths
    app_support_dir: str = ""
    config_dir: str = ""
    data_dir: str = ""
    db_path: str = ""
    log_dir: str = ""
    cache_dir: str = ""
    backup_dir: str = ""
    diagnostics_dir: str = ""

    # Path annotations
    path_notes: dict[str, str] = field(default_factory=dict)

    # Database
    db_status: str = ""
    db_schema_version: int = 0
    db_table_count: int = 0
    db_fts_table_count: int = 0
    db_file_size: str = ""
    db_last_updated: str = ""
    db_writable: bool = False

    # Database health (M3-C-0.5)
    db_integrity_status: str = ""
    db_integrity_detail: str = ""
    db_last_backup_at: str = ""
    db_backup_count: int = 0
    db_backup_max: int = 10
    stat_reports: int = 0
    stat_investment_views: int = 0
    stat_tracking_signals: int = 0
    stat_entities: int = 0
    stat_source_documents: int = 0

    # Service
    web_host: str = "127.0.0.1"
    web_port: int = 8000
    web_local_only: bool = True
    web_url: str = ""
    web_reload: bool = False

    # Automation (M3-C-3c)
    auto_analysis_mode: str = "off"
    auto_analysis_label: str = "关闭"


def get_system_info() -> SystemInfo:
    """Build system info from live state.  Read-only — no modification allowed."""
    info = SystemInfo()

    # App
    info.app_version = _get_version()
    info.build_commit = _get_build_commit()
    info.release_channel = "RC"
    info.python_version = sys.version.split()[0]
    info.os_name = platform.system()
    info.architecture = platform.machine()

    # Paths
    try:
        from signalvault.config import get_app_paths
        paths = get_app_paths()
        info.app_support_dir = str(paths.app_support_dir)
        info.config_dir = str(paths.config_dir)
        info.data_dir = str(paths.data_dir)
        info.db_path = str(paths.db_path)
        info.log_dir = str(paths.log_dir)
        info.cache_dir = str(paths.cache_dir)
        info.backup_dir = str(paths.backup_dir)
        info.diagnostics_dir = str(paths.diagnostics_dir)

        info.path_notes = {
            "app_support_dir": "必须备份",
            "config_dir": "必须备份（含密钥和配置）",
            "data_dir": "必须备份（含 SQLite 数据库）",
            "db_path": "必须备份",
            "log_dir": "可清理（系统自动轮转）",
            "cache_dir": "可重建（系统自动创建）",
            "backup_dir": "可备份后清理",
            "diagnostics_dir": "可清理（诊断导出后）",
        }
    except Exception:
        pass

    # Database
    info.db_status, info.db_schema_version = _get_db_status()
    info.db_table_count, info.db_fts_table_count = _count_db_tables()
    info.db_file_size = _get_db_file_size(info.db_path)
    info.db_last_updated = _get_db_last_updated()
    info.db_writable = _check_db_writable()

    # Database health (M3-C-0.5)
    try:
        from signalvault.db.session import MAX_DB_BACKUPS
        info.db_backup_max = MAX_DB_BACKUPS
    except Exception:
        pass
    info.db_integrity_status, info.db_integrity_detail = _get_integrity_status()
    info.db_last_backup_at, info.db_backup_count = _get_backup_info()
    _stats = _get_data_stats()
    info.stat_reports = _stats.get("reports", 0)
    info.stat_investment_views = _stats.get("investment_views", 0)
    info.stat_tracking_signals = _stats.get("tracking_signals", 0)
    info.stat_entities = _stats.get("entities", 0)
    info.stat_source_documents = _stats.get("source_documents", 0)

    # Service
    try:
        from signalvault.settings.service import get_config_service
        svc = get_config_service()
        info.web_host = str(svc.get("web.host"))
        info.web_port = int(svc.get("web.port"))
        info.web_reload = bool(svc.get("web.reload"))
    except Exception:
        pass

    info.web_local_only = info.web_host in ("127.0.0.1", "localhost", "::1")
    info.web_url = f"http://{info.web_host}:{info.web_port}"

    # Automation (M3-C-3c)
    try:
        from signalvault.settings.service import get_config_service
        svc = get_config_service()
        info.auto_analysis_mode = str(svc.get("intake.auto_analysis_mode"))
        mode_labels = {"off": "关闭", "high_value": "高价值来源", "all": "全部来源"}
        info.auto_analysis_label = mode_labels.get(info.auto_analysis_mode, "关闭")
    except Exception:
        pass

    return info


# ═══════════════════════════════════════════════════════════════════════════════
# About Info (for /settings/about)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class AboutInfo:
    """Information for the About page — version, license, system summary."""

    app_version: str = ""
    release_channel: str = "RC"
    build_commit: str = ""

    python_version: str = ""
    os_name: str = ""
    architecture: str = ""

    db_path: str = ""

    ai_provider: str = ""
    ai_status: str = ""
    ai_key_configured: bool = False

    obsidian_state: str = ""
    obsidian_state_label: str = ""

    diagnostics_ok: bool = True


def get_about_info() -> AboutInfo:
    """Build about page info."""
    info = AboutInfo()

    info.app_version = _get_version()
    info.release_channel = "RC"
    info.build_commit = _get_build_commit()
    info.python_version = sys.version.split()[0]
    info.os_name = platform.system()
    info.architecture = platform.machine()

    try:
        from signalvault.config import get_app_paths
        info.db_path = str(get_app_paths().db_path)
    except Exception:
        pass

    # AI status (no secrets)
    try:
        from signalvault.services.ai_settings_service import get_ai_settings_view
        ai = get_ai_settings_view()
        info.ai_provider = ai.provider
        info.ai_status = ai.status_label
        info.ai_key_configured = ai.api_key_configured
    except Exception:
        pass

    # Obsidian status
    try:
        from signalvault.services.obsidian_settings_service import (
            get_obsidian_settings_view,
        )
        obs = get_obsidian_settings_view()
        info.obsidian_state = obs.state
        info.obsidian_state_label = obs.state_label
    except Exception:
        pass

    # Diagnostics
    try:
        from signalvault.diagnostics.summary import DiagnosticsCenter
        summary = DiagnosticsCenter.get_summary()
        info.diagnostics_ok = summary.overall_status == "ok"
    except Exception:
        pass

    return info


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _get_version() -> str:
    """Get app version from package metadata."""
    try:
        from signalvault import __version__
        return __version__
    except (ImportError, AttributeError):
        return "0.1.0"


def _get_build_commit() -> str:
    """Best-effort git commit hash."""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _get_db_status() -> tuple[str, int]:
    """Return (status_label, schema_version).

    M3-C-0: 真实查询 schema_version 表，不再硬编码为 1。
    """
    try:
        from signalvault.db.session import _engine
        if _engine is None:
            return ("未初始化", 0)
        from sqlalchemy import text
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            # M3-C-0: 读取已应用的最高 schema 版本
            try:
                result = conn.execute(
                    text("SELECT MAX(version) FROM schema_version")
                )
                row = result.fetchone()
                version = int(row[0]) if row and row[0] is not None else 0
            except Exception:
                version = 0  # schema_version 表缺失（极旧或异常）→ 0，不阻塞
        return ("正常", version)
    except Exception:
        return ("异常", 0)


def _get_integrity_status() -> tuple[str, str]:
    """Map check_db_integrity() to a Chinese status label + detail (M3-C-0.5)."""
    try:
        from signalvault.db.session import check_db_integrity
        status, detail = check_db_integrity()
        label = {"ok": "正常", "warning": "警告", "error": "异常"}.get(status, "未知")
        return (label, detail)
    except Exception:
        return ("未知", "")


def _get_backup_info() -> tuple[str, int]:
    """Scan backups/ for the latest snapshot timestamp + count (M3-C-0.5)."""
    try:
        from signalvault.db.session import _resolve_backup_dir
        backup_dir = _resolve_backup_dir()
        backups = sorted(
            backup_dir.glob("signalvault-*.db"),
            key=lambda p: p.stat().st_mtime,
        )
        if not backups:
            return ("从未备份", 0)
        latest = backups[-1]
        ts = datetime.fromtimestamp(latest.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        return (ts, len(backups))
    except Exception:
        return ("未知", 0)


def _get_data_stats() -> dict[str, int]:
    """Count rows in core content tables for the data-health view (M3-C-0.5)."""
    try:
        from signalvault.db.session import _engine
        if _engine is None:
            return {}
        from sqlalchemy import text
        tables = [
            "reports",
            "investment_views",
            "tracking_signals",
            "entities",
            "source_documents",
        ]
        stats: dict[str, int] = {}
        with _engine.connect() as conn:
            for table in tables:
                try:
                    row = conn.execute(
                        text(f"SELECT COUNT(*) FROM {table}")
                    ).fetchone()
                    stats[table] = int(row[0]) if row else 0
                except Exception:
                    stats[table] = 0
        return stats
    except Exception:
        return {}


def _count_db_tables() -> tuple[int, int]:
    """Return (orm_table_count, fts_table_count)."""
    try:
        from signalvault.db.session import _engine
        if _engine is None:
            return (0, 0)
        from sqlalchemy import inspect
        inspector = inspect(_engine)
        tables = inspector.get_table_names()
        fts = sum(1 for t in tables if t.endswith("_fts") or t.startswith("fts_"))
        return (len(tables), fts)
    except Exception:
        return (0, 0)


def _get_db_file_size(db_path_str: str) -> str:
    """Human-readable DB file size."""
    if not db_path_str:
        return ""
    p = Path(db_path_str)
    if not p.exists():
        return "文件不存在"
    size = p.stat().st_size
    if size > 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size > 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size} B"


def _get_db_last_updated() -> str:
    """Best-effort last DB modification time."""
    try:
        from signalvault.config import get_app_paths
        p = get_app_paths().db_path
        if p.exists():
            ts = p.stat().st_mtime
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        pass
    return ""


def _check_db_writable() -> bool:
    """Check if DB is writable."""
    try:
        from signalvault.db.session import _engine
        if _engine is None:
            return False
        from sqlalchemy import text
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _get_data_dir() -> str:
    try:
        from signalvault.config import get_app_paths
        return str(get_app_paths().data_dir)
    except Exception:
        return ""


def _get_platform_info() -> str:
    return f"{platform.system()} {platform.release()} ({platform.machine()})"


def _get_web_url() -> str:
    try:
        from signalvault.settings.service import get_config_service
        svc = get_config_service()
        host = str(svc.get("web.host"))
        port = int(svc.get("web.port"))
        return f"http://{host}:{port}"
    except Exception:
        return "http://127.0.0.1:8000"


def _shorten_path(path: str) -> str:
    """Shorten a path for display: ~/Documents/MyVault style."""
    if not path:
        return ""
    home = str(Path.home())
    if path.startswith(home):
        return "~" + path[len(home):]
    # On Windows, also try with forward slashes
    home_fwd = home.replace("\\", "/")
    path_fwd = path.replace("\\", "/")
    if path_fwd.startswith(home_fwd):
        return "~" + path_fwd[len(home_fwd):]
    return path
