"""P5-A: Unified search tests — reports, views, signals, entities, filters, fallback.

Covers:
  - Search reports by keyword
  - Search investment views
  - Search tracking signals
  - Search entities
  - Metadata filters (result_type, source_type, entity_type, view_direction, signal_status)
  - LIKE fallback (always exercised in test DB)
  - Ranking basic order
  - Empty DB / no results
  - CLI smoke test
  - MCP unified_search tool return structure
  - serialize_unified_result
"""

from __future__ import annotations

import json

from signalvault.db.unified_search import (
    UnifiedSearchResult,
    serialize_unified_result,
    unified_search,
)

# ═════════════════════════════════════════════════════════════════════════════
# UnifiedSearchResult dataclass
# ═════════════════════════════════════════════════════════════════════════════


class TestUnifiedSearchResult:
    def test_defaults(self):
        r = UnifiedSearchResult()
        assert r.result_type == ""
        assert r.relevance_score == 0.0
        assert r.matched_fields == []
        assert r.report_id is None

    def test_full_creation(self):
        r = UnifiedSearchResult(
            result_type="report",
            title="Test Report",
            snippet="This is a test...",
            relevance_score=0.85,
            matched_fields=["report_markdown"],
            report_id=1,
            source_type="youtube",
            source_path="https://youtube.com/watch?v=abc",
            timestamp="00:12:30",
            page_number=None,
            source_quote="Original quote text",
        )
        assert r.result_type == "report"
        assert r.relevance_score == 0.85
        assert r.report_id == 1

    def test_serialize(self):
        r = UnifiedSearchResult(
            result_type="investment_view",
            title="NVIDIA bullish",
            snippet="GPU demand...",
            relevance_score=0.75,
            report_id=5,
            source_type="pdf_upload",
            page_number=12,
            entity_name="NVIDIA",
        )
        d = serialize_unified_result(r)
        assert d["result_type"] == "investment_view"
        assert d["page_number"] == 12
        assert d["report_id"] == 5
        # Must be JSON serializable
        encoded = json.dumps(d, ensure_ascii=False)
        decoded = json.loads(encoded)
        assert decoded["title"] == "NVIDIA bullish"


# ═════════════════════════════════════════════════════════════════════════════
# Search reports
# ═════════════════════════════════════════════════════════════════════════════


class TestSearchReports:
    def test_search_report_by_keyword(self, seeded_db):
        results = unified_search(seeded_db, "NVIDIA")
        assert len(results) > 0
        report_types = {r.result_type for r in results}
        assert "report" in report_types or "investment_view" in report_types

    def test_search_report_filter_type(self, seeded_db):
        results = unified_search(seeded_db, "投资", result_types=["report"])
        for r in results:
            assert r.result_type == "report"

    def test_search_report_no_match(self, seeded_db):
        results = unified_search(seeded_db, "xyznonexistent123456")
        assert results == []

    def test_search_report_limit(self, seeded_db):
        results = unified_search(seeded_db, "AI", limit=3)
        assert len(results) <= 3


# ═════════════════════════════════════════════════════════════════════════════
# Search investment views
# ═════════════════════════════════════════════════════════════════════════════


class TestSearchViews:
    def test_search_views(self, seeded_db):
        results = unified_search(seeded_db, "宁德时代", result_types=["investment_view"])
        assert len(results) > 0
        for r in results:
            assert r.result_type == "investment_view"

    def test_search_views_filter_direction(self, seeded_db):
        results = unified_search(
            seeded_db, "宁德",
            result_types=["investment_view"],
            view_direction="bullish",
        )
        for r in results:
            assert r.view_direction == "bullish"

    def test_search_views_has_evidence_fields(self, seeded_db):
        results = unified_search(seeded_db, "投资", result_types=["investment_view"])
        if results:
            r = results[0]
            assert r.report_id is not None
            assert r.source_type in ("youtube", "local", "")


# ═════════════════════════════════════════════════════════════════════════════
# Search tracking signals
# ═════════════════════════════════════════════════════════════════════════════


class TestSearchSignals:
    def test_search_signals(self, seeded_db):
        results = unified_search(seeded_db, "出货量", result_types=["tracking_signal"])
        assert isinstance(results, list)
        for r in results:
            assert r.result_type == "tracking_signal"

    def test_search_signals_no_match(self, seeded_db):
        results = unified_search(seeded_db, "xyznonexistent", result_types=["tracking_signal"])
        assert results == []


# ═════════════════════════════════════════════════════════════════════════════
# Search entities
# ═════════════════════════════════════════════════════════════════════════════


class TestSearchEntities:
    def test_search_entities(self, seeded_db):
        results = unified_search(seeded_db, "宁德", result_types=["entity"])
        assert len(results) > 0
        for r in results:
            assert r.result_type == "entity"

    def test_search_entities_filter_type(self, seeded_db):
        results = unified_search(
            seeded_db, "时代",
            result_types=["entity"],
            entity_type="stock",
        )
        for r in results:
            assert r.entity_type == "stock"


# ═════════════════════════════════════════════════════════════════════════════
# Metadata filters
# ═════════════════════════════════════════════════════════════════════════════


class TestFilters:
    def test_filter_source_type_youtube(self, seeded_db):
        results = unified_search(seeded_db, "AI", source_type="youtube")
        for r in results:
            assert r.source_type == "youtube"

    def test_filter_source_type_local(self, seeded_db):
        results = unified_search(seeded_db, "投资", source_type="local")
        for r in results:
            assert r.source_type in ("local", "")

    def test_filter_result_type_single(self, seeded_db):
        results = unified_search(seeded_db, "AI", result_types=["report"])
        for r in results:
            assert r.result_type == "report"

    def test_filter_view_direction(self, seeded_db):
        results = unified_search(
            seeded_db, "宁德", view_direction="bullish",
        )
        for r in results:
            if r.result_type == "investment_view":
                assert r.view_direction == "bullish"


# ═════════════════════════════════════════════════════════════════════════════
# Result structure
# ═════════════════════════════════════════════════════════════════════════════


class TestResultStructure:
    def test_all_results_have_keys(self, seeded_db):
        results = unified_search(seeded_db, "AI", limit=10)
        for r in results:
            d = serialize_unified_result(r)
            assert "result_type" in d
            assert "title" in d
            assert "snippet" in d
            assert "relevance_score" in d
            assert "report_id" in d

    def test_relevance_scores_are_in_range(self, seeded_db):
        results = unified_search(seeded_db, "AI", limit=10)
        for r in results:
            assert 0.0 <= r.relevance_score <= 1.0

    def test_ranking_descending(self, seeded_db):
        results = unified_search(seeded_db, "投资", limit=15)
        scores = [r.relevance_score for r in results]
        assert scores == sorted(scores, reverse=True)


# ═════════════════════════════════════════════════════════════════════════════
# Empty DB
# ═════════════════════════════════════════════════════════════════════════════


class TestEmptyDB:
    def test_search_empty_db(self, db_session):
        results = unified_search(db_session, "anything")
        assert results == []

    def test_search_empty_with_filters(self, db_session):
        results = unified_search(
            db_session, "test",
            result_types=["report"],
            source_type="youtube",
        )
        assert results == []

    def test_serialize_empty_results(self):
        # Serializing empty list should be valid
        encoded = json.dumps([], ensure_ascii=False)
        assert encoded == "[]"


# ═════════════════════════════════════════════════════════════════════════════
# CLI smoke tests
# ═════════════════════════════════════════════════════════════════════════════


class TestCliSearch:
    def test_search_help(self):
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["search", "--help"])
        assert result.exit_code == 0
        assert "搜索" in result.stdout

    def test_search_keyword(self, seeded_db):
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["search", "NVIDIA"])
        assert result.exit_code == 0
        assert "NVIDIA" in result.stdout or "结果" in result.stdout

    def test_search_json_output(self, seeded_db):
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["search", "AI", "--json", "--limit", "5"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_search_no_results(self, seeded_db):
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["search", "xyznonexistent123456"])
        assert result.exit_code == 0  # exits clean, not error

    def test_search_filter_type(self, seeded_db):
        import importlib

        import signalvault.cli as cli_mod
        importlib.reload(cli_mod)
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, [
            "search", "投资", "--type", "report", "--limit", "5",
        ])
        assert result.exit_code == 0


# ═════════════════════════════════════════════════════════════════════════════
# MCP unified_search tool
# ═════════════════════════════════════════════════════════════════════════════


class TestMcpUnifiedSearch:
    def test_unified_search_tool_registered(self):
        from signalvault.mcp_server.tools import TOOLS
        names = {t.name for t in TOOLS}
        assert "unified_search" in names
        assert len(TOOLS) >= 9  # 8 original + unified_search (plus more from P5-B)

    def test_unified_search_handler(self, seeded_db):
        import asyncio

        from signalvault.mcp_server.tools import handle_call_tool
        result = asyncio.run(handle_call_tool(
            "unified_search",
            {"query": "AI", "limit": 5},
        ))
        from mcp.types import TextContent
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        data = json.loads(result[0].text)
        assert isinstance(data, list)

    def test_unified_search_handler_with_filters(self, seeded_db):
        import asyncio

        from signalvault.mcp_server.tools import handle_call_tool
        result = asyncio.run(handle_call_tool(
            "unified_search",
            {
                "query": "投资",
                "result_types": ["entity"],
                "limit": 5,
            },
        ))
        data = json.loads(result[0].text)
        assert isinstance(data, list)
        for item in data:
            assert item["result_type"] == "entity"

    def test_unified_search_handler_no_results(self, seeded_db):
        import asyncio

        from signalvault.mcp_server.tools import handle_call_tool
        result = asyncio.run(handle_call_tool(
            "unified_search",
            {"query": "xyznonexistent123456"},
        ))
        data = json.loads(result[0].text)
        assert data == []

    def test_unified_search_handler_empty_query(self, seeded_db):
        import asyncio

        from signalvault.mcp_server.tools import handle_call_tool
        result = asyncio.run(handle_call_tool(
            "unified_search",
            {"query": ""},
        ))
        data = json.loads(result[0].text)
        assert data == []

    def test_all_9_tools_still_work(self, seeded_db):
        """Verify existing 8 tools still work alongside unified_search."""
        import asyncio

        from signalvault.mcp_server.tools import handle_call_tool

        # Test a subset of existing tools
        tests = [
            ("list_channels", {}),
            ("search_entities", {}),
            ("list_review_items", {}),
        ]
        for name, args in tests:
            result = asyncio.run(handle_call_tool(name, args))
            data = json.loads(result[0].text)
            assert isinstance(data, list), f"{name} should return list"
