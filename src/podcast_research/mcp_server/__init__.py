"""MCP Server for podcast_research — read-only knowledge base access.

Provides 8 read-only tools for querying reports, entities, investment views,
tracking signals, channels, and review items from the SQLite knowledge base.

Usage (CLI):
    python -m podcast_research mcp-serve [--db-path path/to/db]

Usage (Claude Desktop config):
    {
        "mcpServers": {
            "podcast-research": {
                "command": "python",
                "args": ["-m", "podcast_research", "mcp-serve"],
                "env": {
                    "DB_PATH": "/path/to/data/podcast_analyst.db"
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

from podcast_research.mcp_server.server import create_mcp_server, run_mcp_server
from podcast_research.mcp_server.tools import TOOLS, handle_call_tool

__all__ = [
    "create_mcp_server",
    "run_mcp_server",
    "TOOLS",
    "handle_call_tool",
]
