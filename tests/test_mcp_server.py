"""P3-D: MCP Server tests — core query functions + tool handler + server smoke.

Covers:
  - All 8 tool query functions with seeded_db
  - Empty DB / no-results stable structure
  - Tool handler dispatch
  - Server creation + tool registration
  - Read-only verification (no write tools exposed)
"""

from __future__ import annotations

import asyncio
import json

import pytest

from signalvault.mcp_server.server import create_mcp_server

# ── Core query function imports (sync, testable without MCP dependency) ─────
from signalvault.mcp_server.tools import (
    _query_get_entity_profile,
    _query_get_report,
    _query_list_channels,
    _query_list_investment_views,
    _query_list_review_items,
    _query_list_tracking_signals,
    _query_search_entities,
    _query_search_reports,
    handle_call_tool,
)

# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def _init_engine_for_seeded(seeded_db):
    """seeded_db already initializes the global engine via conftest's db_session."""
    yield


# ═════════════════════════════════════════════════════════════════════════════
# Smoke: Server + tool registration
# ═════════════════════════════════════════════════════════════════════════════


class TestMCPServerSmoke:
    """Server creation and tool registration — no stdio transport."""

    def test_server_creates_without_error(self, seeded_db):
        """Server can be created with a seeded DB."""
        server = create_mcp_server()
        assert server is not None
        # The server should have the signalvault name
        assert server.name == "signalvault"

    def test_all_tools_registered(self, seeded_db):
        """9 tools are registered on the server (8 original + unified_search)."""
        from signalvault.mcp_server import TOOLS
        assert len(TOOLS) == 12
        tool_names = {t.name for t in TOOLS}
        expected = {
            "search_reports",
            "get_report",
            "list_channels",
            "search_entities",
            "get_entity_profile",
            "list_investment_views",
            "list_tracking_signals",
            "list_review_items",
            "unified_search",
            "get_entity_neighborhood",
            "list_graph_edges",
            "get_evidence_trail",
        }
        assert tool_names == expected

    def test_no_write_tools_exposed(self, seeded_db):
        """Verify no tool names contain write/accept/skip/resolve/retry/run/modify."""
        from signalvault.mcp_server import TOOLS
        write_keywords = [
            "accept", "skip", "resolve", "retry", "run", "modify",
            "create", "delete", "update", "write", "insert", "drop",
            "ingest", "export", "generate", "apply", "rollback",
        ]
        for tool in TOOLS:
            name_lower = tool.name.lower()
            for kw in write_keywords:
                assert kw not in name_lower, (
                    f"Tool '{tool.name}' contains write keyword '{kw}'"
                )

    def test_tool_descriptions_are_non_empty(self, seeded_db):
        """All tools have meaningful descriptions."""
        from signalvault.mcp_server import TOOLS
        for tool in TOOLS:
            assert tool.description, f"Tool '{tool.name}' has empty description"
            assert len(tool.description) > 10, (
                f"Tool '{tool.name}' description too short"
            )


# ═════════════════════════════════════════════════════════════════════════════
# search_reports
# ═════════════════════════════════════════════════════════════════════════════


class TestSearchReports:
    def test_search_by_keyword(self, seeded_db):
        results = _query_search_reports("NVIDIA")
        assert isinstance(results, list)
        assert len(results) > 0
        for r in results:
            assert "id" in r
            assert "title" in r
            assert "source_type" in r

    def test_search_no_match(self, seeded_db):
        results = _query_search_reports("xyz_nonexistent_keyword_12345")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_search_limit(self, seeded_db):
        results = _query_search_reports("投资", limit=1)
        assert len(results) <= 1

    def test_search_default_limit(self, seeded_db):
        results = _query_search_reports("AI")
        assert len(results) <= 10  # default limit

    def test_search_result_structure(self, seeded_db):
        """Each result has expected fields."""
        results = _query_search_reports("AI")
        for r in results:
            rid = r.get("id") or r.get("report_id")
            assert rid is not None
            assert isinstance(rid, int)
            assert isinstance(r["title"], str)
            assert isinstance(r["source_type"], str)
            assert r["source_type"] in ("youtube", "local", "")
            assert "match_excerpt" in r
            assert "created_at" in r


# ═════════════════════════════════════════════════════════════════════════════
# get_report
# ═════════════════════════════════════════════════════════════════════════════


class TestGetReport:
    def test_get_existing_report(self, seeded_db):
        # Report 1: 宁德时代 (seeded by conftest)
        report = _query_get_report(1)
        assert report is not None
        assert report["id"] == 1
        assert "title" in report
        assert "source_type" in report
        assert "report_markdown" in report
        assert "views" in report
        assert isinstance(report["views"], list)
        assert "signals" in report
        assert isinstance(report["signals"], list)

    def test_get_report_has_views(self, seeded_db):
        report = _query_get_report(1)
        assert len(report["views"]) > 0
        view = report["views"][0]
        assert "target_name" in view
        assert "view_direction" in view
        assert "source_quote" in view

    def test_get_report_has_signals(self, seeded_db):
        report = _query_get_report(1)
        assert len(report["signals"]) > 0
        signal = report["signals"][0]
        assert "target_name" in signal
        assert "signal" in signal

    def test_get_nonexistent_report(self, seeded_db):
        report = _query_get_report(99999)
        assert report is None

    def test_get_report_structure_serializable(self, seeded_db):
        report = _query_get_report(1)
        # Verify it can be JSON serialized
        encoded = json.dumps(report, ensure_ascii=False, default=str)
        decoded = json.loads(encoded)
        assert decoded["id"] == 1


# ═════════════════════════════════════════════════════════════════════════════
# list_channels
# ═════════════════════════════════════════════════════════════════════════════


class TestListChannels:
    def test_list_channels_returns_list(self, seeded_db):
        results = _query_list_channels()
        assert isinstance(results, list)

    def test_list_channels_structure(self, seeded_db):
        results = _query_list_channels()
        for ch in results:
            assert "id" in ch
            assert "name" in ch
            assert "youtube_channel_id" in ch
            assert "is_active" in ch
            assert "total_videos" in ch

    def test_list_channels_active_only(self, seeded_db):
        results = _query_list_channels(active_only=True)
        for ch in results:
            assert ch["is_active"] is True

    def test_list_channels_empty_db(self, db_session):
        """Empty DB returns empty list, not error."""
        results = _query_list_channels()
        assert results == []


# ═════════════════════════════════════════════════════════════════════════════
# search_entities
# ═════════════════════════════════════════════════════════════════════════════


class TestSearchEntities:
    def test_search_entities_returns_list(self, seeded_db):
        results = _query_search_entities()
        assert isinstance(results, list)
        # Seeded DB has 3 entities
        assert len(results) >= 3

    def test_search_entities_structure(self, seeded_db):
        results = _query_search_entities()
        for e in results:
            assert "name" in e
            assert "entity_type" in e
            assert "normalized_name" in e
            assert "aliases" in e

    def test_search_entities_filter_by_type(self, seeded_db):
        results = _query_search_entities(entity_type="stock")
        for e in results:
            assert e["entity_type"] == "stock"

    def test_search_entities_filter_by_name(self, seeded_db):
        results = _query_search_entities(name_filter="宁德")
        assert len(results) > 0
        names = [e["name"] for e in results]
        assert any("宁德" in n for n in names)

    def test_search_entities_no_match(self, seeded_db):
        results = _query_search_entities(name_filter="xyznonexistent123")
        assert results == []

    def test_search_entities_limit(self, seeded_db):
        results = _query_search_entities(limit=2)
        assert len(results) <= 2

    def test_search_entities_empty_db(self, db_session):
        results = _query_search_entities()
        assert results == []


# ═════════════════════════════════════════════════════════════════════════════
# get_entity_profile
# ═════════════════════════════════════════════════════════════════════════════


class TestGetEntityProfile:
    def test_get_entity_profile_found(self, seeded_db):
        profile = _query_get_entity_profile("宁德时代")
        assert profile is not None
        assert profile["name"] == "宁德时代"
        assert "entity_type" in profile
        assert "report_count" in profile
        assert "view_count" in profile
        assert "last_seen" in profile
        assert "recent_views" in profile
        assert isinstance(profile["recent_views"], list)

    def test_get_entity_profile_has_views(self, seeded_db):
        profile = _query_get_entity_profile("宁德时代")
        assert profile["view_count"] >= 1
        assert len(profile["recent_views"]) >= 1
        v = profile["recent_views"][0]
        assert "report_id" in v
        assert "view_direction" in v

    def test_get_entity_profile_not_found(self, seeded_db):
        profile = _query_get_entity_profile("不存在的实体")
        assert profile is None

    def test_get_entity_profile_serializable(self, seeded_db):
        profile = _query_get_entity_profile("宁德时代")
        encoded = json.dumps(profile, ensure_ascii=False, default=str)
        decoded = json.loads(encoded)
        assert decoded["name"] == "宁德时代"


# ═════════════════════════════════════════════════════════════════════════════
# list_investment_views
# ═════════════════════════════════════════════════════════════════════════════


class TestListInvestmentViews:
    def test_list_views_returns_list(self, seeded_db):
        results = _query_list_investment_views()
        assert isinstance(results, list)
        # Seeded DB has 3 views (1 per report)
        assert len(results) >= 3

    def test_list_views_structure(self, seeded_db):
        results = _query_list_investment_views()
        for v in results:
            assert "target_name" in v
            assert "view_direction" in v
            assert "report_id" in v
            assert v["view_direction"] in ("bullish", "bearish", "neutral", "")

    def test_list_views_filter_by_target(self, seeded_db):
        results = _query_list_investment_views(target_name="NVIDIA")
        assert len(results) >= 1
        assert all("nvidia" in r["target_name"].lower() for r in results)

    def test_list_views_filter_by_direction(self, seeded_db):
        results = _query_list_investment_views(view_direction="bullish")
        assert len(results) >= 1
        for v in results:
            assert v["view_direction"] == "bullish"

    def test_list_views_limit(self, seeded_db):
        results = _query_list_investment_views(limit=2)
        assert len(results) <= 2

    def test_list_views_empty_db(self, db_session):
        results = _query_list_investment_views()
        assert results == []


# ═════════════════════════════════════════════════════════════════════════════
# list_tracking_signals
# ═════════════════════════════════════════════════════════════════════════════


class TestListTrackingSignals:
    def test_list_signals_returns_list(self, seeded_db):
        results = _query_list_tracking_signals()
        assert isinstance(results, list)
        # Seeded DB has 3 signals (1 per report), all with status="open"
        assert len(results) >= 3

    def test_list_signals_structure(self, seeded_db):
        results = _query_list_tracking_signals()
        for s in results:
            assert "target_name" in s
            assert "signal" in s
            assert "status" in s
            assert "report_id" in s

    def test_list_signals_filter_by_target(self, seeded_db):
        results = _query_list_tracking_signals(target_name="NVIDIA")
        assert len(results) >= 1
        assert all("nvidia" in r["target_name"].lower() for r in results)

    def test_list_signals_filter_by_status(self, seeded_db):
        results = _query_list_tracking_signals(status="open")
        for s in results:
            assert s["status"] == "open"

    def test_list_signals_all_status(self, seeded_db):
        results = _query_list_tracking_signals(status="all")
        assert isinstance(results, list)

    def test_list_signals_limit(self, seeded_db):
        results = _query_list_tracking_signals(limit=2)
        assert len(results) <= 2

    def test_list_signals_empty_db(self, db_session):
        results = _query_list_tracking_signals()
        assert results == []


# ═════════════════════════════════════════════════════════════════════════════
# list_review_items
# ═════════════════════════════════════════════════════════════════════════════


class TestListReviewItems:
    def test_list_review_items_returns_list(self, seeded_db):
        results = _query_list_review_items()
        assert isinstance(results, list)

    def test_list_review_items_empty_when_no_data(self, seeded_db):
        """Empty list when no review items exist, not error."""
        results = _query_list_review_items()
        assert results == []

    def test_list_review_items_structure(self, seeded_db):
        """Verify structure even if empty."""
        results = _query_list_review_items()
        assert isinstance(results, list)

    def test_list_review_items_limit(self, seeded_db):
        results = _query_list_review_items(limit=10)
        assert len(results) <= 10

    def test_list_review_items_empty_db(self, db_session):
        results = _query_list_review_items()
        assert results == []


# ═════════════════════════════════════════════════════════════════════════════
# Empty DB stability
# ═════════════════════════════════════════════════════════════════════════════


class TestEmptyDB:
    """All query functions return stable structures on empty DB."""

    def test_search_reports_empty(self, db_session):
        result = _query_search_reports("anything")
        assert result == []

    def test_get_report_empty(self, db_session):
        result = _query_get_report(1)
        assert result is None

    def test_list_channels_empty(self, db_session):
        result = _query_list_channels()
        assert result == []

    def test_search_entities_empty(self, db_session):
        result = _query_search_entities()
        assert result == []

    def test_get_entity_profile_empty(self, db_session):
        result = _query_get_entity_profile("anything")
        assert result is None

    def test_list_views_empty(self, db_session):
        result = _query_list_investment_views()
        assert result == []

    def test_list_signals_empty(self, db_session):
        result = _query_list_tracking_signals()
        assert result == []

    def test_list_review_items_empty(self, db_session):
        result = _query_list_review_items()
        assert result == []


# ═════════════════════════════════════════════════════════════════════════════
# Tool handler dispatch (async smoke tests)
# ═════════════════════════════════════════════════════════════════════════════


class TestToolHandler:
    """Test handle_call_tool dispatching via asyncio.run()."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_search_reports_handler(self, seeded_db):
        from mcp.types import TextContent
        result = self._run(handle_call_tool("search_reports", {"query": "AI"}))
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        data = json.loads(result[0].text)
        assert isinstance(data, list)

    def test_get_report_found_handler(self, seeded_db):
        result = self._run(handle_call_tool("get_report", {"report_id": 1}))
        data = json.loads(result[0].text)
        assert data["id"] == 1
        assert "views" in data

    def test_get_report_not_found_handler(self, seeded_db):
        result = self._run(handle_call_tool("get_report", {"report_id": 99999}))
        data = json.loads(result[0].text)
        assert "error" in data

    def test_get_report_invalid_id_handler(self, seeded_db):
        result = self._run(handle_call_tool("get_report", {"report_id": 0}))
        data = json.loads(result[0].text)
        assert "error" in data

    def test_list_channels_handler(self, seeded_db):
        result = self._run(handle_call_tool("list_channels", {}))
        data = json.loads(result[0].text)
        assert isinstance(data, list)

    def test_search_entities_handler(self, seeded_db):
        result = self._run(handle_call_tool("search_entities", {}))
        data = json.loads(result[0].text)
        assert isinstance(data, list)

    def test_get_entity_profile_found_handler(self, seeded_db):
        result = self._run(handle_call_tool("get_entity_profile", {"entity_name": "宁德时代"}))
        data = json.loads(result[0].text)
        assert data["name"] == "宁德时代"

    def test_get_entity_profile_not_found_handler(self, seeded_db):
        result = self._run(handle_call_tool("get_entity_profile", {"entity_name": "不存在"}))
        data = json.loads(result[0].text)
        assert "error" in data

    def test_list_investment_views_handler(self, seeded_db):
        result = self._run(handle_call_tool("list_investment_views", {}))
        data = json.loads(result[0].text)
        assert isinstance(data, list)

    def test_list_tracking_signals_handler(self, seeded_db):
        result = self._run(handle_call_tool("list_tracking_signals", {}))
        data = json.loads(result[0].text)
        assert isinstance(data, list)

    def test_list_review_items_handler(self, seeded_db):
        result = self._run(handle_call_tool("list_review_items", {}))
        data = json.loads(result[0].text)
        assert isinstance(data, list)

    def test_unknown_tool_handler(self, seeded_db):
        result = self._run(handle_call_tool("nonexistent_tool", {}))
        data = json.loads(result[0].text)
        assert "error" in data
        assert "Unknown tool" in data["error"]

    def test_all_handler_results_are_json(self, seeded_db):
        """Every tool handler returns valid JSON."""
        calls = [
            ("search_reports", {"query": "test"}),
            ("get_report", {"report_id": 1}),
            ("list_channels", {}),
            ("search_entities", {}),
            ("get_entity_profile", {"entity_name": "宁德时代"}),
            ("list_investment_views", {}),
            ("list_tracking_signals", {}),
            ("list_review_items", {}),
        ]
        for name, args in calls:
            result = self._run(handle_call_tool(name, args))
            assert len(result) == 1
            # Must be parseable JSON
            data = json.loads(result[0].text)
            assert isinstance(data, (dict, list)), f"{name} returned non-dict/list"


# ═════════════════════════════════════════════════════════════════════════════
# Read-only verification
# ═════════════════════════════════════════════════════════════════════════════


class TestMCPReadOnly:
    """Verify the MCP server exposes no write operations."""

    def test_tools_dont_modify_db(self, seeded_db):
        """Running queries doesn't change report counts."""
        from signalvault.db.models import Report
        session = seeded_db
        count_before = session.query(Report).count()

        # Run all query functions
        _query_search_reports("AI")
        _query_get_report(1)
        _query_list_channels()
        _query_search_entities()
        _query_get_entity_profile("宁德时代")
        _query_list_investment_views()
        _query_list_tracking_signals()
        _query_list_review_items()

        count_after = session.query(Report).count()
        assert count_before == count_after

    def test_tool_names_are_read_only(self, seeded_db):
        """Tool names imply read-only operations."""
        from signalvault.mcp_server import TOOLS
        read_prefixes = ["search_", "get_", "list_", "unified_"]
        for tool in TOOLS:
            assert any(
                tool.name.startswith(p) for p in read_prefixes
            ), f"Tool '{tool.name}' does not start with read prefix"

    def test_handle_call_tool_returns_text_content_only(self, seeded_db):
        """All responses are TextContent (no file modifications)."""
        import asyncio
        result = asyncio.run(handle_call_tool("list_channels", {}))
        assert len(result) == 1
        from mcp.types import TextContent
        assert isinstance(result[0], TextContent)
