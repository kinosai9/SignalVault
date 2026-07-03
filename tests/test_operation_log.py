"""P7-B: Operation log tests — lifecycle, queries, sanitization, CLI smoke."""

from __future__ import annotations

import json as _json
import time

# ═════════════════════════════════════════════════════════════════════════════
# Operation lifecycle tests
# ═════════════════════════════════════════════════════════════════════════════


class TestOperationLifecycle:
    def test_start_creates_log(self, db_session):
        from podcast_research.diagnostics.operation_log import OperationLogManager

        op = OperationLogManager.start(
            operation_type="graph.rebuild",
            source_type="",
            summary="测试图谱重建",
            session=db_session,
        )
        assert op.operation_id != ""
        assert len(op.operation_id) == 36  # UUID4
        assert op.status == "started"
        assert op.operation_type == "graph.rebuild"
        assert op.started_at != ""

        # Verify persisted
        stored = OperationLogManager.get(op.operation_id, session=db_session)
        assert stored is not None
        assert stored["operation_id"] == op.operation_id
        assert stored["status"] == "started"

    def test_start_then_succeed(self, db_session):
        from podcast_research.diagnostics.operation_log import OperationLogManager

        op = OperationLogManager.start(
            operation_type="pdf.preview",
            source_type="pdf_upload",
            target_ref="file:test.pdf",
            summary="预览 PDF",
            session=db_session,
        )
        time.sleep(0.01)  # ensure measurable duration

        op = OperationLogManager.succeed(
            op,
            summary="预览完成: test.pdf, 5 pages",
            metadata={"pages": 5, "quality": "good"},
            session=db_session,
        )

        assert op.status == "succeeded"
        assert op.finished_at != ""
        assert op.duration_ms > 0

        # Verify persisted
        stored = OperationLogManager.get(op.operation_id, session=db_session)
        assert stored["status"] == "succeeded"
        assert stored["duration_ms"] > 0
        assert "5 pages" in stored["summary"]

    def test_start_then_fail(self, db_session):
        from podcast_research.diagnostics.operation_log import OperationLogManager

        op = OperationLogManager.start(
            operation_type="zsxq.topic.analyze",
            source_type="zsxq_topic",
            target_ref="group:G001/topic:T001",
            session=db_session,
        )

        op = OperationLogManager.fail(
            op,
            error_code="AUTH_ZSXQ_001",
            error_detail="zsxq-cli returned 'not logged in'",
            summary="分析失败: 未登录",
            session=db_session,
        )

        assert op.status == "failed"
        assert op.error_code == "AUTH_ZSXQ_001"
        assert op.duration_ms > 0

        stored = OperationLogManager.get(op.operation_id, session=db_session)
        assert stored["status"] == "failed"
        assert stored["error_code"] == "AUTH_ZSXQ_001"

    def test_unknown_operation_type_logged(self, db_session):
        from podcast_research.diagnostics.operation_log import OperationLogManager

        op = OperationLogManager.start(
            operation_type="custom.action",  # not in VALID_OPERATION_TYPES
            session=db_session,
        )
        assert op.operation_id != ""
        # Should still work — unknown types get a debug log but no error


# ═════════════════════════════════════════════════════════════════════════════
# Query tests
# ═════════════════════════════════════════════════════════════════════════════


class TestOperationQueries:
    def test_list_operations(self, db_session):
        from podcast_research.diagnostics.operation_log import OperationLogManager

        OperationLogManager.start(
            operation_type="pdf.preview", session=db_session,
        )
        OperationLogManager.start(
            operation_type="graph.rebuild", session=db_session,
        )

        ops = OperationLogManager.list_operations(session=db_session)
        assert len(ops) >= 2

    def test_list_filter_by_type(self, db_session):
        from podcast_research.diagnostics.operation_log import OperationLogManager

        OperationLogManager.start(
            operation_type="pdf.preview", session=db_session,
        )
        OperationLogManager.start(
            operation_type="graph.rebuild", session=db_session,
        )

        pdf_ops = OperationLogManager.list_operations(
            operation_type="pdf.preview", session=db_session,
        )
        assert all(o["operation_type"] == "pdf.preview" for o in pdf_ops)

    def test_list_filter_by_status(self, db_session):
        from podcast_research.diagnostics.operation_log import OperationLogManager

        op1 = OperationLogManager.start(
            operation_type="graph.rebuild", session=db_session,
        )
        OperationLogManager.succeed(op1, session=db_session)

        op2 = OperationLogManager.start(
            operation_type="pdf.analyze", session=db_session,
        )
        OperationLogManager.fail(op2, error_code="TEST_ERR", session=db_session)

        succeeded = OperationLogManager.list_operations(
            status="succeeded", session=db_session,
        )
        failed = OperationLogManager.list_operations(
            status="failed", session=db_session,
        )
        assert all(o["status"] == "succeeded" for o in succeeded)
        assert all(o["status"] == "failed" for o in failed)

    def test_count_by_status(self, db_session):
        from podcast_research.diagnostics.operation_log import OperationLogManager

        op = OperationLogManager.start(
            operation_type="graph.rebuild", session=db_session,
        )
        OperationLogManager.succeed(op, session=db_session)

        counts = OperationLogManager.count_by_status(session=db_session)
        assert "succeeded" in counts
        assert counts["succeeded"] >= 1

    def test_recent_failures(self, db_session):
        from podcast_research.diagnostics.operation_log import OperationLogManager

        op = OperationLogManager.start(
            operation_type="pdf.analyze", session=db_session,
        )
        OperationLogManager.fail(
            op,
            error_code="EXTRACT_PDF_001",
            error_detail="PDF corrupted",
            session=db_session,
        )

        failures = OperationLogManager.recent_failures(session=db_session)
        assert len(failures) >= 1
        assert failures[0]["status"] == "failed"

    def test_get_nonexistent(self, db_session):
        from podcast_research.diagnostics.operation_log import OperationLogManager

        result = OperationLogManager.get("nonexistent-id", session=db_session)
        assert result is None


# ═════════════════════════════════════════════════════════════════════════════
# Sanitization tests
# ═════════════════════════════════════════════════════════════════════════════


class TestSanitization:
    def test_api_key_redacted(self, db_session):
        from podcast_research.diagnostics.operation_log import OperationLogManager

        op = OperationLogManager.start(
            operation_type="graph.rebuild",
            metadata={"llm_api_key": "sk-secret-12345", "user": "test"},
            session=db_session,
        )

        stored = OperationLogManager.get(op.operation_id, session=db_session)
        meta = _json.loads(stored["metadata_json"])
        assert meta["llm_api_key"] == "[REDACTED]"
        assert meta["user"] == "test"

    def test_token_password_secret_redacted(self, db_session):
        from podcast_research.diagnostics.operation_log import OperationLogManager

        op = OperationLogManager.start(
            operation_type="zsxq.doctor",
            metadata={
                "access_token": "tok123",
                "password": "pwd456",
                "refresh_token": "ref789",
                "group_name": "投资研究",
            },
            session=db_session,
        )

        stored = OperationLogManager.get(op.operation_id, session=db_session)
        meta = _json.loads(stored["metadata_json"])
        assert meta["access_token"] == "[REDACTED]"
        assert meta["password"] == "[REDACTED]"
        assert meta["refresh_token"] == "[REDACTED]"
        assert meta["group_name"] == "投资研究"

    def test_long_content_truncated(self, db_session):
        from podcast_research.diagnostics.operation_log import OperationLogManager

        long_text = "A" * 1000
        op = OperationLogManager.start(
            operation_type="pdf.preview",
            metadata={"notes": long_text},
            session=db_session,
        )

        stored = OperationLogManager.get(op.operation_id, session=db_session)
        meta = _json.loads(stored["metadata_json"])
        assert len(meta["notes"]) <= 505  # 500 + "..." max

    def test_full_text_content_redacted(self, db_session):
        from podcast_research.diagnostics.operation_log import OperationLogManager

        op = OperationLogManager.start(
            operation_type="zsxq.topic.analyze",
            metadata={
                "content_text": "完整的付费原文" * 100,
                "source_quote": "引用原文" * 50,
                "title": "正常标题",
            },
            session=db_session,
        )

        stored = OperationLogManager.get(op.operation_id, session=db_session)
        meta = _json.loads(stored["metadata_json"])
        assert "redacted" in meta.get("content_text", "")
        assert "redacted" in meta.get("source_quote", "")
        assert meta["title"] == "正常标题"


# ═════════════════════════════════════════════════════════════════════════════
# CLI smoke tests
# ═════════════════════════════════════════════════════════════════════════════


class TestLogsCLI:
    def _reload_cli(self):
        import importlib

        import podcast_research.cli as cli_mod
        importlib.reload(cli_mod)
        return cli_mod

    def test_logs_list_help(self):
        cli_mod = self._reload_cli()
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["logs", "list", "--help"])
        assert result.exit_code == 0
        assert "--status" in result.stdout
        assert "--type" in result.stdout
        assert "--limit" in result.stdout
        assert "--json" in result.stdout

    def test_logs_show_help(self):
        cli_mod = self._reload_cli()
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["logs", "show", "--help"])
        assert result.exit_code == 0

    def test_logs_list_empty_does_not_crash(self, db_session):
        cli_mod = self._reload_cli()
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["logs", "list"])
        assert result.exit_code == 0

    def test_logs_list_json_output(self, db_session):
        """Verify --json flag produces valid JSON."""
        from podcast_research.diagnostics.operation_log import OperationLogManager
        OperationLogManager.start(
            operation_type="graph.rebuild",
            summary="test",
            session=db_session,
        )

        cli_mod = self._reload_cli()
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["logs", "list", "--json"])
        assert result.exit_code == 0
        data = _json.loads(result.stdout)
        assert isinstance(data, list)


# ═════════════════════════════════════════════════════════════════════════════
# Integration: operation log + error record
# ═════════════════════════════════════════════════════════════════════════════


class TestOperationWithError:
    def test_fail_with_error_record(self, db_session):
        from podcast_research.diagnostics.errors import create_error_record
        from podcast_research.diagnostics.operation_log import OperationLogManager

        error = create_error_record("EXTRACT_PDF_001", entity_ref="test.pdf")
        assert error is not None

        op = OperationLogManager.start(
            operation_type="pdf.analyze",
            source_type="pdf_upload",
            target_ref="file:test.pdf",
            session=db_session,
        )
        OperationLogManager.fail(
            op,
            error_code=error.error_code,
            error_detail=error.user_message,
            summary="PDF分析失败",
            session=db_session,
        )

        stored = OperationLogManager.get(op.operation_id, session=db_session)
        assert stored["error_code"] == "EXTRACT_PDF_001"
        assert "PDF" in stored["error_detail"]

    def test_db_migration_creates_table(self, db_session):
        """Verify operation_logs table exists after migration."""
        from sqlalchemy import inspect
        insp = inspect(db_session.bind)
        tables = insp.get_table_names()
        assert "operation_logs" in tables, f"operation_logs not in: {tables}"
