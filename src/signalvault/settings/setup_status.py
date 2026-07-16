"""C1-C: SetupStatus — composite system health model.

No linear enum — each subsystem reports its own flags independently.
Derived states (core_ready, llm_ready, …) are computed from current facts.
Obsidian is optional — its absence does not block core_ready.

C2-A: llm_ready semantics fixed — mock is always ready;
      real provider requires configuration AND recent successful validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SetupStatus:
    """Composite status of the SignalVault installation.

    All fields are independently settable — no ordered stages.
    Use ``evaluate()`` to compute from live state.
    """

    # ── Core system ──────────────────────────────────────────────────────
    system_initialized: bool = False
    database_ready: bool = False
    wizard_completed: bool = False

    # ── LLM ──────────────────────────────────────────────────────────────
    llm_configured: bool = False     # provider + model + base_url set
    llm_validated: bool = False      # last connectivity test passed
    llm_last_checked_at: str = ""    # ISO 8601 UTC
    llm_provider: str = "mock"       # canonical provider name
    llm_overridden_by_env: bool = False  # env var is shadowing user config

    # ── Obsidian (optional integration) ──────────────────────────────────
    obsidian_enabled: bool = False           # vault path is configured
    obsidian_path_configured: bool = False   # path is set and non-empty
    obsidian_initialized: bool = False       # manifest exists in vault
    obsidian_valid: bool = False             # vault passes validation

    # ── Derived states ───────────────────────────────────────────────────

    @property
    def core_ready(self) -> bool:
        """Core system is operational (DB accessible, dirs created)."""
        return self.system_initialized and self.database_ready

    @property
    def llm_ready(self) -> bool:
        """LLM is usable for analysis.

        - Mock provider: always ready (no API key needed).
        - Real provider: must be configured AND recently validated.
        """
        if self.llm_provider == "mock":
            return True
        # Real provider — needs configuration and successful validation
        return self.llm_configured and self.llm_validated

    @property
    def obsidian_ready(self) -> bool:
        """Vault integration is healthy OR not enabled (optional)."""
        if not self.obsidian_enabled:
            return True  # optional — no vault is fine
        return (
            self.obsidian_path_configured
            and self.obsidian_initialized
            and self.obsidian_valid
        )

    @property
    def needs_onboarding(self) -> bool:
        """User should see first-run wizard."""
        return not self.wizard_completed

    # ── Factory ──────────────────────────────────────────────────────────

    @staticmethod
    def evaluate(
        *,
        vault_path: str = "",
        manifest_path: str = "",
    ) -> "SetupStatus":
        """Compute status from observable facts.

        No ConfigService dependency — callers pass pre-resolved values.
        This keeps the model testable without mocking the full config stack.
        """
        status = SetupStatus()

        # System
        status.system_initialized = True  # process is running = initialized

        # Database
        status.database_ready = _check_db_ready()

        # LLM — caller should set llm_provider, llm_configured,
        # llm_validated explicitly; evaluate() provides defaults only
        status.llm_configured = True  # defaults always provide a provider

        # Obsidian
        if vault_path:
            status.obsidian_enabled = True
            status.obsidian_path_configured = True
            vault = Path(vault_path)
            if vault.exists() and vault.is_dir():
                manifest = manifest_path or str(vault / "99_System" / "signalvault_manifest.json")
                status.obsidian_initialized = Path(manifest).is_file()
                status.obsidian_valid = _check_vault_usable(vault)

        return status


# ── Internal helpers ─────────────────────────────────────────────────────────


def _check_db_ready() -> bool:
    """Check if the SQLite database is accessible."""
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


def _check_vault_usable(vault_path: Path) -> bool:
    """Quick usability check — existence + writability."""
    try:
        if not vault_path.is_dir():
            return False
        # Test write
        test_file = vault_path / ".signalvault_test_write"
        test_file.write_text("", encoding="utf-8")
        test_file.unlink()
        return True
    except (OSError, PermissionError):
        return False
