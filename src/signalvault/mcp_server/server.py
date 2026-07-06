"""MCP server setup and stdio runner for signalvault.

Provides create_mcp_server() and run_mcp_server() — the latter is the
entry point for `python -m signalvault mcp-serve`.
"""

from __future__ import annotations

import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server

from signalvault.mcp_server.tools import TOOLS, handle_call_tool

logger = logging.getLogger(__name__)


def create_mcp_server(
    db_path: str | None = None,
) -> Server:
    """Build an MCP Server instance with all read-only tools registered.

    The server uses the @list_tools / @call_tool decorator pattern to
    register the tool list and a single dispatching handler.

    Args:
        db_path: Optional path to SQLite database. If None, uses config default.
    """
    # Initialize DB engine once (idempotent — init_db checks _engine)
    from signalvault.db.session import init_db
    init_db(db_path)

    server = Server(
        "signalvault",
        version="0.1.0",
    )

    @server.list_tools()
    async def list_tools() -> list:
        return list(TOOLS)

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        return await handle_call_tool(name, arguments)

    return server


async def run_mcp_server(
    db_path: str | None = None,
) -> None:
    """Run the MCP server over stdio transport (blocking until stdin closes).

    This is the async entry point called by the CLI.
    """
    server = create_mcp_server(db_path=db_path)
    async with stdio_server() as (read_stream, write_stream):
        logger.info("MCP server started (stdio transport, read-only)")
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
