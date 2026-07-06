"""P6-A1: ZSXQ import tests — models, registry, profile, ingest_jobs, review, CLI.

All tests use mock JSON — no real zsxq-cli, no real accounts, no network.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from signalvault.sources.zsxq_models import (
    ZsxqGroup,
    ZsxqSourceProfile,
    ZsxqTopic,
    compute_content_hash,
)

# ═════════════════════════════════════════════════════════════════════════════
# Data model tests
# ═════════════════════════════════════════════════════════════════════════════


class TestZsxqModels:
    def test_group_defaults(self):
        g = ZsxqGroup()
        assert g.access_status == "active"

    def test_topic_defaults(self):
        t = ZsxqTopic()
        assert t.parse_quality == "good"

    def test_source_profile_defaults(self):
        p = ZsxqSourceProfile()
        assert p.source_type == "zsxq_topic"
        assert p.group_access_status == "active"

    def test_content_hash_stable(self):
        h1 = compute_content_hash("Hello World")
        h2 = compute_content_hash("Hello World")
        assert h1 == h2
        assert len(h1) == 16

    def test_content_hash_different(self):
        h1 = compute_content_hash("Hello")
        h2 = compute_content_hash("World")
        assert h1 != h2


# ═════════════════════════════════════════════════════════════════════════════
# Group Registry tests
# ═════════════════════════════════════════════════════════════════════════════


class TestGroupRegistry:
    def test_list_empty_registry(self):
        from signalvault.sources.zsxq_registry import list_registry
        groups = list_registry()
        assert isinstance(groups, list)

    @pytest.fixture(autouse=True)
    def _isolate_registry(self, tmp_path, monkeypatch):
        """Isolate registry file to temp dir."""
        from signalvault.sources import zsxq_registry
        tmp_file = tmp_path / "zsxq_groups.json"
        monkeypatch.setattr(zsxq_registry, "REGISTRY_FILE", tmp_file)

    def test_refresh_adds_new_groups(self):
        from signalvault.sources.zsxq_registry import (
            list_registry,
            refresh_registry,
        )

        cli_groups = [
            {"group_id": "111", "name": "投资研究", "topic_count": 100},
            {"group_id": "222", "name": "AI观察", "topic_count": 50},
        ]
        changes = refresh_registry(cli_groups)
        assert changes["added"] == 2
        assert changes["unchanged"] == 0

        groups = list_registry()
        assert len(groups) == 2
        assert all(g.access_status == "active" for g in groups)

    def test_refresh_unchanged(self):
        from signalvault.sources.zsxq_registry import refresh_registry
        cli_groups = [{"group_id": "111", "name": "投资研究", "topic_count": 100}]
        refresh_registry(cli_groups)
        changes = refresh_registry(cli_groups)
        assert changes["unchanged"] == 1
        assert changes["added"] == 0

    def test_refresh_deactivated(self):
        from signalvault.sources.zsxq_registry import (
            list_registry,
            refresh_registry,
        )
        # Add group
        refresh_registry([{"group_id": "111", "name": "投资研究", "topic_count": 100}])
        # Refresh with empty list → deactivate
        changes = refresh_registry([])
        assert changes["deactivated"] == 1
        groups = list_registry()
        assert groups[0].access_status == "inaccessible"

    def test_refresh_reactivated(self):
        from signalvault.sources.zsxq_registry import (
            list_registry,
            refresh_registry,
        )
        refresh_registry([{"group_id": "111", "name": "投资研究", "topic_count": 100}])
        refresh_registry([])  # deactivate
        changes = refresh_registry([{"group_id": "111", "name": "投资研究", "topic_count": 200}])
        assert changes["reactivated"] == 1
        groups = list_registry()
        assert groups[0].access_status == "active"
        assert groups[0].topic_count == 200  # updated

    def test_historical_data_preserved(self):
        from signalvault.sources.zsxq_registry import (
            list_registry,
            refresh_registry,
        )
        refresh_registry([{"group_id": "111", "name": "投资研究", "topic_count": 100}])
        refresh_registry([])  # deactivate
        groups = list_registry()
        assert len(groups) == 1  # not deleted
        assert groups[0].group_id == "111"


# ═════════════════════════════════════════════════════════════════════════════
# Source Profile tests
# ═════════════════════════════════════════════════════════════════════════════


class TestSourceProfile:
    def test_build_profile_eligible(self):
        from signalvault.sources.zsxq_import import build_zsxq_source_profile
        topic = ZsxqTopic(
            group_id="111", group_name="Test", topic_id="t1",
            topic_title="Hello World" * 20,  # 220 chars
            content_text="A" * 300,
            content_hash="abc123", parse_quality="good",
        )
        profile = build_zsxq_source_profile(topic)
        assert profile.import_eligible is True
        assert profile.source_type == "zsxq_topic"

    def test_build_profile_ineligible_short(self):
        from signalvault.sources.zsxq_import import build_zsxq_source_profile
        topic = ZsxqTopic(
            group_id="111", topic_id="t1",
            content_text="Hi", content_hash="abc", parse_quality="good",
        )
        profile = build_zsxq_source_profile(topic)
        assert profile.import_eligible is False

    def test_build_profile_ineligible_minimal_quality(self):
        from signalvault.sources.zsxq_import import build_zsxq_source_profile
        topic = ZsxqTopic(
            group_id="111", topic_id="t1",
            content_text="A" * 300, content_hash="abc",
            parse_quality="minimal",
        )
        profile = build_zsxq_source_profile(topic)
        assert profile.import_eligible is False


# ═════════════════════════════════════════════════════════════════════════════
# Ingest Jobs integration
# ═════════════════════════════════════════════════════════════════════════════


MOCK_TOPIC_JSON = json.dumps({
    "group_name": "投资研究",
    "title": "2025 AI 芯片需求分析",
    "type": "talk",
    "author": "tech_analyst",
    "create_time": "2025-12-01T10:00:00",
    "content": "<p>全球 AI 芯片需求持续增长。NVIDIA 在数据中心 GPU 市场保持 82% 份额。</p><p>TSMC 3nm 产能扩张预计带动 25% 营收增长。</p>",
    "tags": ["AI", "芯片", "投资"],
    "url": "https://zsxq.com/t/123",
})


class TestIngestJobs:
    def test_zsxq_topic_job_key(self):
        from signalvault.sources.ingest_jobs import _make_job_key
        key = _make_job_key("zsxq_topic", source_hash="abc123")
        assert key.startswith("zsxq_topic:")

    @patch("signalvault.sources.zsxq_import.fetch_topic")
    def test_import_topic_creates_job(self, mock_fetch, db_session):
        from signalvault.sources.zsxq_models import compute_content_hash

        text = "全球 AI 芯片需求持续增长。NVIDIA 数据中心 GPU 市场份额 82%。"
        mock_fetch.return_value = ZsxqTopic(
            group_id="111", group_name="投资研究", topic_id="t1",
            topic_title="AI 芯片分析", topic_type="talk",
            author_name="analyst", content_text=text,
            content_hash=compute_content_hash(text),
            char_count=len(text), parse_quality="good",
            create_time="2025-12-01T10:00:00",
            tags=["AI", "芯片"],
        )

        from signalvault.sources.zsxq_import import import_topic_to_ingest
        result = import_topic_to_ingest("111", "t1", session=db_session)
        assert result["success"] is True
        assert result["profile"] is not None
        assert result["job"] is not None
        assert result["job"]["source_type"] == "zsxq_topic"

    @patch("signalvault.sources.zsxq_import.fetch_topic")
    def test_duplicate_topic_no_duplicate_job(self, mock_fetch, db_session):
        from signalvault.sources.zsxq_models import compute_content_hash

        text = "Test content for dedup check. " * 10
        mock_fetch.return_value = ZsxqTopic(
            group_id="111", group_name="Test", topic_id="t1",
            topic_title="Test", content_text=text,
            content_hash=compute_content_hash(text),
            char_count=len(text), parse_quality="good",
        )

        from signalvault.sources.zsxq_import import import_topic_to_ingest
        r1 = import_topic_to_ingest("111", "t1", session=db_session)
        assert r1["success"] is True

        r2 = import_topic_to_ingest("111", "t1", session=db_session)
        assert r2["success"] is False
        assert "duplicate" in r2.get("error_type", "")


# ═════════════════════════════════════════════════════════════════════════════
# Error handling tests
# ═════════════════════════════════════════════════════════════════════════════


class TestErrorHandling:
    @patch("signalvault.sources.zsxq_import.fetch_topic")
    def test_cli_missing_error(self, mock_fetch, db_session):
        from signalvault.sources.zsxq_cli import ZsxqCliMissingError
        mock_fetch.side_effect = ZsxqCliMissingError("zsxq-cli not found")

        from signalvault.sources.zsxq_import import import_topic_to_ingest
        result = import_topic_to_ingest("111", "t1", session=db_session)
        assert result["success"] is False
        assert result["error_type"] == "zsxq_cli_missing"
        assert len(result["review_findings"]) > 0

    @patch("signalvault.sources.zsxq_import.fetch_topic")
    def test_auth_required_error(self, mock_fetch, db_session):
        from signalvault.sources.zsxq_cli import ZsxqAuthRequiredError
        mock_fetch.side_effect = ZsxqAuthRequiredError("Not logged in")

        from signalvault.sources.zsxq_import import import_topic_to_ingest
        result = import_topic_to_ingest("111", "t1", session=db_session)
        assert result["error_type"] == "zsxq_auth_required"

    @patch("signalvault.sources.zsxq_import.fetch_topic")
    def test_permission_denied_error(self, mock_fetch, db_session):
        from signalvault.sources.zsxq_cli import ZsxqPermissionDeniedError
        mock_fetch.side_effect = ZsxqPermissionDeniedError("Access denied")

        from signalvault.sources.zsxq_import import import_topic_to_ingest
        result = import_topic_to_ingest("111", "t1", session=db_session)
        assert result["error_type"] == "zsxq_permission_denied"

    @patch("signalvault.sources.zsxq_import.fetch_topic")
    def test_parse_error(self, mock_fetch, db_session):
        from signalvault.sources.zsxq_cli import ZsxqParseError
        mock_fetch.side_effect = ZsxqParseError("Invalid JSON")

        from signalvault.sources.zsxq_import import import_topic_to_ingest
        result = import_topic_to_ingest("111", "t1", session=db_session)
        assert result["error_type"] == "zsxq_parse_failed"


# ═════════════════════════════════════════════════════════════════════════════
# Review items
# ═════════════════════════════════════════════════════════════════════════════


class TestReviewItems:
    def test_zsxq_item_types_in_valid(self):
        from signalvault.sources.review_items import VALID_ITEM_TYPES
        assert "zsxq_cli_missing" in VALID_ITEM_TYPES
        assert "zsxq_auth_required" in VALID_ITEM_TYPES
        assert "zsxq_permission_denied" in VALID_ITEM_TYPES
        assert "zsxq_parse_failed" in VALID_ITEM_TYPES
        assert "zsxq_attachment_unsupported" in VALID_ITEM_TYPES

    @patch("signalvault.sources.zsxq_import.fetch_topic")
    def test_error_writes_review(self, mock_fetch, db_session):
        from signalvault.sources.zsxq_cli import ZsxqCliMissingError
        mock_fetch.side_effect = ZsxqCliMissingError("not found")

        from signalvault.sources.review_items import ReviewItemManager
        from signalvault.sources.zsxq_import import import_topic_to_ingest

        result = import_topic_to_ingest("111", "t1", session=db_session)
        findings = result["review_findings"]
        assert len(findings) > 0

        created = ReviewItemManager.create_from_lint_findings(findings, session=db_session)
        assert created > 0


# ═════════════════════════════════════════════════════════════════════════════
# CLI check (without subprocess)
# ═════════════════════════════════════════════════════════════════════════════


class TestCliCheck:
    def test_check_cli_returns_structure(self):
        from signalvault.sources.zsxq_cli import check_cli
        result = check_cli()
        assert "available" in result
        assert "version" in result
        assert "logged_in" in result
        assert "error" in result

    @patch("shutil.which", return_value=None)
    def test_check_cli_not_found(self, mock_which):
        from signalvault.sources.zsxq_cli import check_cli
        result = check_cli()
        assert result["available"] is False
        assert "not found" in result.get("error", "").lower()


# ═════════════════════════════════════════════════════════════════════════════
# CLI smoke tests
# ═════════════════════════════════════════════════════════════════════════════


class TestCliZsxq:
    def _reload_cli(self):
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        return cli_mod

    def test_zsxq_doctor_help(self):
        cli_mod = self._reload_cli()
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["zsxq", "doctor"])
        assert result.exit_code == 0

    def test_zsxq_groups_help(self):
        cli_mod = self._reload_cli()
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["zsxq", "groups", "--help"])
        assert result.exit_code == 0
        assert "refresh" in result.stdout

    def test_zsxq_import_topic_help(self):
        cli_mod = self._reload_cli()
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["zsxq", "import-topic", "--help"])
        assert result.exit_code == 0

    def test_zsxq_sync_help(self):
        cli_mod = self._reload_cli()
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["zsxq", "sync", "--help"])
        assert result.exit_code == 0
