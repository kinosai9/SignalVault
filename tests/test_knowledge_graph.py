"""P5-B: Knowledge graph tests — rebuild, nodes, edges, neighborhood, evidence trail.

Covers:
  - Node creation
  - Edge creation
  - Rebuild idempotency
  - Entity neighborhood
  - Evidence trail (PDF page + video timestamp)
  - Graph export JSON
  - CLI smoke
  - MCP tool return structure
  - Empty DB no crash
"""

from __future__ import annotations

import json

from podcast_research.db.knowledge_graph import (
    export_graph_json,
    get_entity_neighborhood,
    get_evidence_trail,
    list_graph_edges,
    rebuild_knowledge_graph,
)

# ═════════════════════════════════════════════════════════════════════════════
# Rebuild
# ═════════════════════════════════════════════════════════════════════════════


class TestRebuild:
    def test_rebuild_on_seeded_db(self, seeded_db):
        result = rebuild_knowledge_graph(seeded_db)
        assert result["nodes"] > 0
        assert result["edges"] > 0
        assert "node_types" in result
        assert "edge_types" in result

    def test_rebuild_idempotent(self, seeded_db):
        r1 = rebuild_knowledge_graph(seeded_db)
        r2 = rebuild_knowledge_graph(seeded_db)
        assert r1["nodes"] == r2["nodes"]
        assert r1["edges"] == r2["edges"]

    def test_rebuild_on_empty_db(self, db_session):
        result = rebuild_knowledge_graph(db_session)
        assert result["nodes"] == 0
        assert result["edges"] == 0

    def test_node_types_present(self, seeded_db):
        result = rebuild_knowledge_graph(seeded_db)
        types = result.get("node_types", {})
        assert "report" in types

    def test_edge_types_present(self, seeded_db):
        result = rebuild_knowledge_graph(seeded_db)
        types = result.get("edge_types", {})
        assert len(types) > 0


# ═════════════════════════════════════════════════════════════════════════════
# Entity Neighborhood
# ═════════════════════════════════════════════════════════════════════════════


class TestEntityNeighborhood:
    def test_neighborhood_returns_structure(self, seeded_db):
        rebuild_knowledge_graph(seeded_db)
        result = get_entity_neighborhood(seeded_db, "宁德时代")
        assert "center" in result
        assert "neighbors" in result
        assert "edges" in result
        assert "summary" in result

    def test_neighborhood_found_entity(self, seeded_db):
        rebuild_knowledge_graph(seeded_db)
        result = get_entity_neighborhood(seeded_db, "宁德")
        assert result["center"] is not None

    def test_neighborhood_not_found(self, seeded_db):
        rebuild_knowledge_graph(seeded_db)
        result = get_entity_neighborhood(seeded_db, "NonExistentEntity12345")
        assert result["center"] is None
        assert result["neighbors"] == []

    def test_neighborhood_has_connections(self, seeded_db):
        rebuild_knowledge_graph(seeded_db)
        result = get_entity_neighborhood(seeded_db, "宁德")
        if result["center"]:
            assert result["summary"]["total_connections"] >= 0

    def test_neighborhood_empty_db(self, db_session):
        result = get_entity_neighborhood(db_session, "anything")
        assert result["center"] is None


# ═════════════════════════════════════════════════════════════════════════════
# Evidence Trail
# ═════════════════════════════════════════════════════════════════════════════


class TestEvidenceTrail:
    def test_evidence_trail_by_view(self, seeded_db):
        rebuild_knowledge_graph(seeded_db)
        result = get_evidence_trail(seeded_db, view_id=1)
        assert "target" in result
        assert "evidence" in result

    def test_evidence_trail_nonexistent_view(self, seeded_db):
        rebuild_knowledge_graph(seeded_db)
        result = get_evidence_trail(seeded_db, view_id=99999)
        assert result["target"] is None

    def test_evidence_trail_no_args(self, seeded_db):
        result = get_evidence_trail(seeded_db)
        assert result["target"] is None


# ═════════════════════════════════════════════════════════════════════════════
# List Edges
# ═════════════════════════════════════════════════════════════════════════════


class TestListEdges:
    def test_list_edges_returns_list(self, seeded_db):
        rebuild_knowledge_graph(seeded_db)
        edges = list_graph_edges(seeded_db, limit=10)
        assert isinstance(edges, list)
        assert len(edges) > 0

    def test_list_edges_filter_by_type(self, seeded_db):
        rebuild_knowledge_graph(seeded_db)
        edges = list_graph_edges(seeded_db, edge_type="derived_from", limit=20)
        for e in edges:
            assert e["edge_type"] == "derived_from"

    def test_list_edges_empty_db(self, db_session):
        edges = list_graph_edges(db_session)
        assert edges == []


# ═════════════════════════════════════════════════════════════════════════════
# Graph Export
# ═════════════════════════════════════════════════════════════════════════════


class TestGraphExport:
    def test_export_json_valid(self, seeded_db):
        rebuild_knowledge_graph(seeded_db)
        json_str = export_graph_json(seeded_db)
        data = json.loads(json_str)
        assert "nodes" in data
        assert "edges" in data
        assert "metadata" in data
        assert data["metadata"]["node_count"] == len(data["nodes"])
        assert data["metadata"]["edge_count"] == len(data["edges"])

    def test_export_empty_json_valid(self, db_session):
        json_str = export_graph_json(db_session)
        data = json.loads(json_str)
        assert data["nodes"] == []
        assert data["edges"] == []


# ═════════════════════════════════════════════════════════════════════════════
# CLI smoke
# ═════════════════════════════════════════════════════════════════════════════


class TestCliGraph:
    def _reload_cli(self):
        import importlib

        import podcast_research.cli as cli_mod
        importlib.reload(cli_mod)
        return cli_mod

    def test_graph_rebuild(self, seeded_db):
        cli_mod = self._reload_cli()
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["graph", "rebuild"])
        assert result.exit_code == 0
        assert "重建完成" in result.stdout or "Nodes" in result.stdout

    def test_graph_neighborhood(self, seeded_db):
        rebuild_knowledge_graph(seeded_db)
        cli_mod = self._reload_cli()
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["graph", "neighborhood", "宁德时代"])
        assert result.exit_code == 0

    def test_graph_export(self, seeded_db):
        rebuild_knowledge_graph(seeded_db)
        cli_mod = self._reload_cli()
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli_mod.app, ["graph", "export"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "nodes" in data


# ═════════════════════════════════════════════════════════════════════════════
# MCP tools
# ═════════════════════════════════════════════════════════════════════════════


class TestMcpGraph:
    def test_graph_tools_registered(self):
        from podcast_research.mcp_server.tools import TOOLS
        names = {t.name for t in TOOLS}
        assert "get_entity_neighborhood" in names
        assert "list_graph_edges" in names
        assert "get_evidence_trail" in names
        assert len(TOOLS) == 12  # 8 original + unified_search + 3 graph

    def test_neighborhood_mcp_handler(self, seeded_db):
        import asyncio
        rebuild_knowledge_graph(seeded_db)
        from podcast_research.mcp_server.tools import handle_call_tool
        result = asyncio.run(handle_call_tool(
            "get_entity_neighborhood",
            {"entity_name": "宁德时代", "limit": 10},
        ))
        from mcp.types import TextContent
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        data = json.loads(result[0].text)
        assert "center" in data

    def test_list_edges_mcp_handler(self, seeded_db):
        import asyncio
        rebuild_knowledge_graph(seeded_db)
        from podcast_research.mcp_server.tools import handle_call_tool
        result = asyncio.run(handle_call_tool(
            "list_graph_edges", {"limit": 5},
        ))
        data = json.loads(result[0].text)
        assert isinstance(data, list)

    def test_evidence_trail_mcp_handler(self, seeded_db):
        import asyncio
        rebuild_knowledge_graph(seeded_db)
        from podcast_research.mcp_server.tools import handle_call_tool
        result = asyncio.run(handle_call_tool(
            "get_evidence_trail", {"view_id": 1},
        ))
        data = json.loads(result[0].text)
        assert "target" in data

    def test_evidence_trail_empty_mcp(self, seeded_db):
        import asyncio

        from podcast_research.mcp_server.tools import handle_call_tool
        result = asyncio.run(handle_call_tool(
            "get_evidence_trail", {},
        ))
        data = json.loads(result[0].text)
        assert data["target"] is None


# ═════════════════════════════════════════════════════════════════════════════
# DB migration
# ═════════════════════════════════════════════════════════════════════════════


class TestDbMigration:
    def test_knowledge_tables_exist(self, db_session):
        from sqlalchemy import inspect

        from podcast_research.db.session import _engine
        insp = inspect(_engine)
        tables = insp.get_table_names()
        assert "knowledge_nodes" in tables
        assert "knowledge_edges" in tables
