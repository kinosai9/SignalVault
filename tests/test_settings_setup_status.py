"""C1-C tests: SetupStatus composite state model."""

from __future__ import annotations

from signalvault.settings.setup_status import SetupStatus


class TestSetupStatusDefaults:
    def test_all_false_by_default(self):
        s = SetupStatus()
        assert s.system_initialized is False
        assert s.database_ready is False
        assert s.wizard_completed is False

    def test_core_not_ready_by_default(self):
        s = SetupStatus()
        assert s.core_ready is False

    def test_core_ready_when_initialized_and_db_ready(self):
        s = SetupStatus(system_initialized=True, database_ready=True)
        assert s.core_ready is True

    def test_core_not_ready_without_db(self):
        s = SetupStatus(system_initialized=True, database_ready=False)
        assert s.core_ready is False


class TestLLMReady:
    def test_mock_always_ready(self):
        """Mock provider is always ready — no API key or validation needed."""
        s = SetupStatus(llm_provider="mock", llm_configured=False, llm_validated=False)
        assert s.llm_ready is True

    def test_real_provider_ready_only_when_configured_and_validated(self):
        s = SetupStatus(
            llm_provider="openai-compatible",
            llm_configured=True,
            llm_validated=True,
        )
        assert s.llm_ready is True

    def test_real_provider_not_ready_when_not_configured(self):
        s = SetupStatus(
            llm_provider="openai-compatible",
            llm_configured=False,
            llm_validated=True,  # validated but not configured → not ready
        )
        assert s.llm_ready is False

    def test_real_provider_not_ready_when_not_validated(self):
        """Configured but not validated → not ready for real providers."""
        s = SetupStatus(
            llm_provider="openai-compatible",
            llm_configured=True,
            llm_validated=False,
        )
        assert s.llm_ready is False

    def test_mock_ready_even_when_not_configured(self):
        """Mock doesn't need any configuration."""
        s = SetupStatus(llm_provider="mock", llm_configured=False)
        assert s.llm_ready is True


class TestObsidianReady:
    def test_obsidian_ready_when_disabled(self):
        """Obsidian is optional — disabled means ready (no blocker)."""
        s = SetupStatus(obsidian_enabled=False)
        assert s.obsidian_ready is True

    def test_obsidian_not_ready_when_path_not_configured(self):
        s = SetupStatus(
            obsidian_enabled=True,
            obsidian_path_configured=False,
        )
        assert s.obsidian_ready is False

    def test_obsidian_ready_when_all_green(self):
        s = SetupStatus(
            obsidian_enabled=True,
            obsidian_path_configured=True,
            obsidian_initialized=True,
            obsidian_valid=True,
        )
        assert s.obsidian_ready is True

    def test_obsidian_not_ready_when_vault_invalid(self):
        s = SetupStatus(
            obsidian_enabled=True,
            obsidian_path_configured=True,
            obsidian_initialized=True,
            obsidian_valid=False,
        )
        assert s.obsidian_ready is False

    def test_obsidian_not_ready_when_not_initialized(self):
        s = SetupStatus(
            obsidian_enabled=True,
            obsidian_path_configured=True,
            obsidian_initialized=False,
            obsidian_valid=True,
        )
        assert s.obsidian_ready is False


class TestNeedsOnboarding:
    def test_needs_onboarding_by_default(self):
        s = SetupStatus()
        assert s.needs_onboarding is True

    def test_no_onboarding_when_wizard_done(self):
        s = SetupStatus(wizard_completed=True)
        assert s.needs_onboarding is False

    def test_wizard_completed_does_not_equal_all_healthy(self):
        """wizard_completed does not mean every integration is healthy."""
        s = SetupStatus(
            wizard_completed=True,
            system_initialized=False,
        )
        assert s.needs_onboarding is False
        assert s.core_ready is False  # wizard done but system broken


class TestEvaluate:
    def test_evaluate_returns_setup_status(self):
        s = SetupStatus.evaluate()
        assert isinstance(s, SetupStatus)

    def test_evaluate_system_initialized(self):
        s = SetupStatus.evaluate()
        assert s.system_initialized is True  # process running = initialized

    def test_evaluate_without_vault(self):
        s = SetupStatus.evaluate(vault_path="")
        assert s.obsidian_enabled is False
        assert s.obsidian_ready is True  # optional

    def test_evaluate_with_nonexistent_vault(self, tmp_path):
        nonexistent = str(tmp_path / "nonexistent_vault")
        s = SetupStatus.evaluate(vault_path=nonexistent)
        assert s.obsidian_enabled is True
        assert s.obsidian_path_configured is True
        assert s.obsidian_initialized is False
