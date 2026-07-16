"""C1-B: Runtime configuration schema.

Defines every configuration item that the application actually reads at runtime.
Excluded: CI settings, Ruff version, Python version, deprecated/duplicate items.

Each item carries metadata (type, default, category, …) but NOT the value itself.
Values are resolved by ConfigService at access time.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class ConfigCategory(Enum):
    LLM = "llm"
    OBSIDIAN = "obsidian"
    WEB = "web"
    LOGGING = "logging"
    ANALYSIS = "analysis"
    INTEGRATIONS = "integrations"
    META = "meta"


@dataclass(frozen=True)
class ConfigItem:
    """Metadata for a single configuration item.  Does NOT hold the value."""

    key: str
    type: type = str
    default: Any = ""
    category: ConfigCategory = ConfigCategory.META
    description: str = ""
    env_var: str | None = None       # legacy .env / os.environ name
    sensitive: bool = False           # must go through SecretStore
    web_editable: bool = False        # show in future config centre
    restart_required: bool = False    # needs process restart to take effect
    validator: Callable[[Any], bool] | None = None


# ═══════════════════════════════════════════════════════════════════════════
# Runtime schema — only items the application actually reads
# ═══════════════════════════════════════════════════════════════════════════

RUNTIME_SCHEMA: dict[str, ConfigItem] = {
    # ── LLM ──────────────────────────────────────────────────────────────
    "llm.provider": ConfigItem(
        key="llm.provider",
        type=str, default="mock",
        category=ConfigCategory.LLM,
        description="LLM provider: 'mock' or 'openai-compatible'",
        env_var="LLM_PROVIDER",
        web_editable=True, restart_required=True,
        validator=lambda v: v in ("mock", "openai-compatible"),
    ),
    "llm.model": ConfigItem(
        key="llm.model",
        type=str, default="mock-v1",
        category=ConfigCategory.LLM,
        description="LLM model name",
        env_var="LLM_MODEL",
        web_editable=True, restart_required=True,
    ),
    "llm.base_url": ConfigItem(
        key="llm.base_url",
        type=str, default="",
        category=ConfigCategory.LLM,
        description="OpenAI-compatible API base URL",
        env_var="LLM_BASE_URL",
        web_editable=True, restart_required=True,
    ),
    "llm.timeout": ConfigItem(
        key="llm.timeout",
        type=float, default=120.0,
        category=ConfigCategory.LLM,
        description="LLM API request timeout in seconds",
        web_editable=False, restart_required=True,
    ),
    "llm.max_retries": ConfigItem(
        key="llm.max_retries",
        type=int, default=2,
        category=ConfigCategory.LLM,
        description="Max retries for failed LLM API calls",
        web_editable=False, restart_required=True,
    ),
    "llm.temperature": ConfigItem(
        key="llm.temperature",
        type=float, default=0.1,
        category=ConfigCategory.LLM,
        description="LLM sampling temperature",
        web_editable=False, restart_required=True,
    ),
    # ── Obsidian ─────────────────────────────────────────────────────────
    "llm.api_key": ConfigItem(
        key="llm.api_key",
        type=str, default="",
        category=ConfigCategory.LLM,
        description="LLM API key (stored in SecretStore, never in config.toml)",
        env_var="LLM_API_KEY",
        sensitive=True,
        web_editable=True, restart_required=True,
    ),
    # ── Obsidian ─────────────────────────────────────────────────────────
    "obsidian.vault_path": ConfigItem(
        key="obsidian.vault_path",
        type=str, default="",
        category=ConfigCategory.OBSIDIAN,
        description="Path to Obsidian vault directory",
        env_var="OBSIDIAN_VAULT_PATH",
        web_editable=True, restart_required=False,
    ),
    "obsidian.export_enabled": ConfigItem(
        key="obsidian.export_enabled",
        type=bool, default=False,
        category=ConfigCategory.OBSIDIAN,
        description="Auto-export reports to Obsidian vault",
        env_var="OBSIDIAN_EXPORT_ENABLED",
        web_editable=True, restart_required=False,
    ),
    # ── Web server ───────────────────────────────────────────────────────
    "web.host": ConfigItem(
        key="web.host",
        type=str, default="127.0.0.1",
        category=ConfigCategory.WEB,
        description="Web server bind address",
        web_editable=False, restart_required=True,
    ),
    "web.port": ConfigItem(
        key="web.port",
        type=int, default=8000,
        category=ConfigCategory.WEB,
        description="Web server listen port",
        web_editable=False, restart_required=True,
    ),
    "web.reload": ConfigItem(
        key="web.reload",
        type=bool, default=False,
        category=ConfigCategory.WEB,
        description="Enable auto-reload (dev mode)",
        web_editable=False, restart_required=True,
    ),
    # ── Logging ──────────────────────────────────────────────────────────
    "logging.level": ConfigItem(
        key="logging.level",
        type=str, default="INFO",
        category=ConfigCategory.LOGGING,
        description="Log level (DEBUG, INFO, WARNING, ERROR)",
        env_var="LOG_LEVEL",
        web_editable=False, restart_required=True,
    ),
    "logging.max_bytes": ConfigItem(
        key="logging.max_bytes",
        type=int, default=5_000_000,
        category=ConfigCategory.LOGGING,
        description="Max size per log file before rotation",
        web_editable=False, restart_required=True,
    ),
    "logging.backup_count": ConfigItem(
        key="logging.backup_count",
        type=int, default=3,
        category=ConfigCategory.LOGGING,
        description="Number of rotated log files to keep",
        web_editable=False, restart_required=True,
    ),
    # ── Analysis defaults ────────────────────────────────────────────────
    "analysis.depth": ConfigItem(
        key="analysis.depth",
        type=str, default="standard",
        category=ConfigCategory.ANALYSIS,
        description="Default analysis depth: 'standard' or 'deep'",
        web_editable=False, restart_required=False,
    ),
    "analysis.focus": ConfigItem(
        key="analysis.focus",
        type=str, default="",
        category=ConfigCategory.ANALYSIS,
        description="Default focus areas (comma-separated)",
        web_editable=False, restart_required=False,
    ),
    "analysis.chunk_size": ConfigItem(
        key="analysis.chunk_size",
        type=int, default=30000,
        category=ConfigCategory.ANALYSIS,
        description="Characters per chunk for long transcripts",
        web_editable=False, restart_required=False,
    ),
    "analysis.chunk_overlap": ConfigItem(
        key="analysis.chunk_overlap",
        type=int, default=2000,
        category=ConfigCategory.ANALYSIS,
        description="Overlap characters between chunks",
        web_editable=False, restart_required=False,
    ),
    "analysis.youtube_lang": ConfigItem(
        key="analysis.youtube_lang",
        type=str, default="",
        category=ConfigCategory.ANALYSIS,
        description="Default YouTube subtitle language priority",
        web_editable=False, restart_required=False,
    ),
    # ── Integrations ─────────────────────────────────────────────────────
    "integrations.zsxq_cli_path": ConfigItem(
        key="integrations.zsxq_cli_path",
        type=str, default="",
        category=ConfigCategory.INTEGRATIONS,
        description="Custom path to zsxq-cli executable",
        env_var="ZSXQ_CLI_PATH",
        web_editable=False, restart_required=False,
    ),
    # ── Meta ─────────────────────────────────────────────────────────────
    "meta.config_version": ConfigItem(
        key="meta.config_version",
        type=int, default=1,
        category=ConfigCategory.META,
        description="Internal config format version",
        web_editable=False, restart_required=False,
    ),
    "meta.migration_version": ConfigItem(
        key="meta.migration_version",
        type=int, default=0,
        category=ConfigCategory.META,
        description="Last completed migration step",
        web_editable=False, restart_required=False,
    ),
    "_internal.llm_validation": ConfigItem(
        key="_internal.llm_validation",
        type=str, default="",
        category=ConfigCategory.META,
        description="Persisted LLM validation state (JSON, non-sensitive)",
        web_editable=False, restart_required=False,
    ),
    "_internal.llm_secret_revision": ConfigItem(
        key="_internal.llm_secret_revision",
        type=int, default=0,
        category=ConfigCategory.META,
        description="Monotonic counter incremented on every API key set/delete; used to invalidate cached validation",
        web_editable=False, restart_required=False,
    ),
}


# ── Convenience ─────────────────────────────────────────────────────────────

def get_schema_keys() -> list[str]:
    """All registered config keys in sorted order."""
    return sorted(RUNTIME_SCHEMA.keys())


def get_sensitive_keys() -> list[str]:
    """Keys that must be stored in SecretStore, never in config.toml."""
    return [k for k, v in RUNTIME_SCHEMA.items() if v.sensitive]


def get_defaults() -> dict[str, Any]:
    """Schema default values (for first-launch and fallback)."""
    return {k: v.default for k, v in RUNTIME_SCHEMA.items()}
