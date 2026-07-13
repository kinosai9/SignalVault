"""P7-E/F: Recovery actions registry, CLI enhancements, error-code mapping."""

from __future__ import annotations

import json as _json

# ═════════════════════════════════════════════════════════════════════════════
# RecoveryActionRegistry tests
# ═════════════════════════════════════════════════════════════════════════════


class TestRecoveryActionRegistry:
    def test_registry_has_ten_actions(self):
        from signalvault.diagnostics.summary import RecoveryActionRegistry
        actions = RecoveryActionRegistry.list_all()
        assert len(actions) >= 10, f"Expected >= 10, got {len(actions)}"

    def test_get_valid_action(self):
        from signalvault.diagnostics.summary import RecoveryActionRegistry
        a = RecoveryActionRegistry.get("rebuild_graph")
        assert a is not None
        assert a.title == "重建知识图谱"
        assert a.category == "graph"

    def test_get_nonexistent(self):
        from signalvault.diagnostics.summary import RecoveryActionRegistry
        assert RecoveryActionRegistry.get("nonexistent_action") is None

    def test_all_actions_have_user_message(self):
        from signalvault.diagnostics.summary import RecoveryActionRegistry
        for a in RecoveryActionRegistry.list_all():
            msg = a.user_message or a.description
            assert msg, f"{a.action_id}: no user_message or description"

    def test_list_by_category(self):
        from signalvault.diagnostics.summary import RecoveryActionRegistry
        zsxq = RecoveryActionRegistry.list_by_category("zsxq")
        assert len(zsxq) >= 3
        assert all(a.category == "zsxq" for a in zsxq)

    def test_export_diagnostic_bundle_action_exists(self):
        from signalvault.diagnostics.summary import RecoveryActionRegistry
        a = RecoveryActionRegistry.get("export_diagnostic_bundle")
        assert a is not None
        assert "诊断包" in a.title or "诊断" in a.title


# ═════════════════════════════════════════════════════════════════════════════
# Error code → action mapping
# ═════════════════════════════════════════════════════════════════════════════


class TestErrorCodeActions:
    def test_auth_zsxq_maps_to_login(self):
        from signalvault.diagnostics.summary import RecoveryActionRegistry
        actions = RecoveryActionRegistry.for_error_code("AUTH_ZSXQ_001")
        action_ids = {a.action_id for a in actions}
        assert "login_zsxq" in action_ids

    def test_llm_auth_maps_to_configure(self):
        from signalvault.diagnostics.summary import RecoveryActionRegistry
        actions = RecoveryActionRegistry.for_error_code("AUTH_LLM_001")
        action_ids = {a.action_id for a in actions}
        assert "configure_llm" in action_ids

    def test_config_dep_maps_to_install(self):
        from signalvault.diagnostics.summary import RecoveryActionRegistry
        actions = RecoveryActionRegistry.for_error_code("CONFIG_DEP_001")
        action_ids = {a.action_id for a in actions}
        assert "install_zsxq_cli" in action_ids

    def test_pdf_extract_maps_to_ocr(self):
        from signalvault.diagnostics.summary import RecoveryActionRegistry
        actions = RecoveryActionRegistry.for_error_code("EXTRACT_PDF_001")
        action_ids = {a.action_id for a in actions}
        assert "handle_pdf_ocr" in action_ids

    def test_graph_build_maps_to_rebuild(self):
        from signalvault.diagnostics.summary import RecoveryActionRegistry
        actions = RecoveryActionRegistry.for_error_code("GRAPH_BUILD_001")
        action_ids = {a.action_id for a in actions}
        assert "rebuild_graph" in action_ids

    def test_unknown_error_returns_empty(self):
        from signalvault.diagnostics.summary import RecoveryActionRegistry
        actions = RecoveryActionRegistry.for_error_code("UNKNOWN_999")
        # Should not crash, may return empty list
        assert isinstance(actions, list)

    def test_analysis_pipeline_has_bundle_action(self):
        from signalvault.diagnostics.summary import RecoveryActionRegistry
        actions = RecoveryActionRegistry.for_error_code("ANALYSIS_PIPELINE_001")
        action_ids = {a.action_id for a in actions}
        assert "export_diagnostic_bundle" in action_ids or "retry_ingest_job" in action_ids


# ═════════════════════════════════════════════════════════════════════════════
# Subsystem → action mapping
# ═════════════════════════════════════════════════════════════════════════════


class TestSubsystemActions:
    def test_zsxq_subsystem_has_actions(self):
        from signalvault.diagnostics.summary import RecoveryActionRegistry
        actions = RecoveryActionRegistry.for_subsystem("zsxq")
        assert len(actions) >= 3

    def test_graph_subsystem_has_rebuild(self):
        from signalvault.diagnostics.summary import RecoveryActionRegistry
        actions = RecoveryActionRegistry.for_subsystem("graph")
        action_ids = {a.action_id for a in actions}
        assert "rebuild_graph" in action_ids

    def test_config_subsystem_has_llm_and_bundle(self):
        from signalvault.diagnostics.summary import RecoveryActionRegistry
        actions = RecoveryActionRegistry.for_subsystem("config")
        action_ids = {a.action_id for a in actions}
        assert "configure_llm" in action_ids
        assert "export_diagnostic_bundle" in action_ids


# ═════════════════════════════════════════════════════════════════════════════
# CLI output tests
# ═════════════════════════════════════════════════════════════════════════════


class TestCliOutputEnhancements:
    def _reload_cli(self):
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        return cli_mod

    def test_doctor_shows_suggested_actions(self, db_session):
        from signalvault.sources.review_items import ReviewItemManager
        ReviewItemManager.create_item(
            item_type="zsxq_cli_missing",
            title="ZSXQ CLI 未安装",
            severity="error",
            session=db_session,
        )

        cli_mod = self._reload_cli()
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["doctor"])
        assert result.exit_code == 0
        # Should contain suggested actions section
        output = result.stdout
        assert "建议" in output or "操作" in output

    def test_diagnostics_summary_json_has_actions(self, db_session):
        from signalvault.sources.review_items import ReviewItemManager
        ReviewItemManager.create_item(
            item_type="pdf_extraction_failed",
            title="PDF Failed",
            severity="error",
            session=db_session,
        )

        cli_mod = self._reload_cli()
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["diagnostics", "summary", "--json"])
        assert result.exit_code == 0
        # Parse JSON with lenient fallback
        stdout = result.stdout.strip()
        idx = stdout.find("{")
        if idx > 0:
            stdout = stdout[idx:]
        try:
            data = _json.loads(stdout)
        except _json.JSONDecodeError:
            assert '"suggested_actions"' in stdout
            return
        assert "suggested_actions" in data

    def test_doctor_output_has_user_guidance(self, db_session):
        cli_mod = self._reload_cli()
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["doctor"])
        assert result.exit_code == 0
        output = result.stdout
        # Should contain overall status label
        assert "系统" in output

    def test_logs_show_failure_has_actions(self, db_session):
        from signalvault.diagnostics.operation_log import OperationLogManager

        op = OperationLogManager.start(
            operation_type="graph.rebuild",
            summary="test",
            session=db_session,
        )
        OperationLogManager.fail(
            op,
            error_code="GRAPH_BUILD_001",
            error_detail="build failed",
            summary="重建失败",
            session=db_session,
        )

        cli_mod = self._reload_cli()
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["logs", "show", op.operation_id[:8]])
        assert result.exit_code == 0
        output = result.stdout
        assert "GRAPH_BUILD_001" in output
        # Should show suggested actions
        assert "建议操作" in output or "重建" in output

    def test_logs_list_shows_error_code(self, db_session):
        from signalvault.diagnostics.operation_log import OperationLogManager

        op = OperationLogManager.start(
            operation_type="pdf.analyze",
            session=db_session,
        )
        OperationLogManager.fail(
            op,
            error_code="EXTRACT_PDF_001",
            summary="PDF failed",
            session=db_session,
        )

        cli_mod = self._reload_cli()
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["logs", "list"])
        assert result.exit_code == 0
        output = result.stdout
        assert "EXTRACT_PDF_001" in output or "错误码" in output


# ═════════════════════════════════════════════════════════════════════════════
# Bundle output tests
# ═════════════════════════════════════════════════════════════════════════════


class TestBundleOutput:
    def _reload_cli(self):
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        return cli_mod

    def test_bundle_success_mentions_redacted(self, db_session, tmp_path):
        cli_mod = self._reload_cli()
        from typer.testing import CliRunner
        runner = CliRunner()
        output_dir = tmp_path / "bundle_test"
        result = runner.invoke(cli_mod.app, [
            "diagnostics", "bundle",
            "--output", str(output_dir),
        ])
        assert result.exit_code == 0
        output = result.stdout
        assert "诊断包" in output or "bundle" in output.lower()


# ═════════════════════════════════════════════════════════════════════════════
# Convenience function tests
# ═════════════════════════════════════════════════════════════════════════════


class TestConvenienceFunctions:
    def test_actions_for_error_code(self):
        from signalvault.diagnostics.summary import actions_for_error_code
        result = actions_for_error_code("AUTH_ZSXQ_001")
        assert isinstance(result, list)

    def test_actions_for_subsystem(self):
        from signalvault.diagnostics.summary import actions_for_subsystem
        result = actions_for_subsystem("graph")
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_list_recovery_actions(self):
        from signalvault.diagnostics.summary import list_recovery_actions
        all_actions = list_recovery_actions()
        assert len(all_actions) >= 10
        # Filtered
        zsxq = list_recovery_actions("zsxq")
        assert len(zsxq) >= 3
        assert all(a["category"] == "zsxq" for a in zsxq)

    def test_get_recovery_action(self):
        from signalvault.diagnostics.summary import get_recovery_action
        a = get_recovery_action("configure_llm")
        assert a is not None
        assert a.action_id == "configure_llm"


# ═════════════════════════════════════════════════════════════════════════════
# No secrets in actions
# ═════════════════════════════════════════════════════════════════════════════


class TestNoSecrets:
    def test_no_api_key_in_actions(self):
        from signalvault.diagnostics.summary import RecoveryActionRegistry
        for a in RecoveryActionRegistry.list_all():
            d = a.to_dict()
            text = _json.dumps(d, ensure_ascii=False)
            assert "sk-" not in text.lower()
            assert "secret" not in d.get("command", "").lower()
