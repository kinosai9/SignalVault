"""MCP Server for signalvault — read-only knowledge base access.

Provides 8 read-only tools for querying reports, entities, investment views,
tracking signals, channels, and review items from the SQLite knowledge base.

Usage (CLI):
    python -m signalvault mcp-serve [--db-path path/to/db]

Usage (Claude Desktop config):
    {
        "mcpServers": {
            "signalvault": {
                "command": "python",
                "args": ["-m", "signalvault", "mcp-serve"],
                "env": {
                    "DB_PATH": "/path/to/data/signalvault.db"
                }
            }
        }
    }

Exports:
    create_mcp_server() — build a Server instance (for custom transport use)
    run_mcp_server()    — stdio runner (for CLI use)
    TOOLS               — list of Tool definitions
    handle_call_tool()  — tool dispatcher (for testing)
"""

from signalvault.mcp_server.server import create_mcp_server, run_mcp_server
from signalvault.mcp_server.tools import TOOLS, handle_call_tool

__all__ = [
    "create_mcp_server",
    "run_mcp_server",
    "TOOLS",
    "handle_call_tool",
]
