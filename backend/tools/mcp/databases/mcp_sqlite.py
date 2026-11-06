"""MCP SQLite — built-in MCP server `mcp_sqlite`."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_sqlite",
    name="MCP SQLite",
    type="mcp",
    icon="🗂️",
    group="mcp_servers",
    category="Databases & Data",
    description="Read/write a local SQLite database — query tables, insert rows, inspect schema.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-sqlite@2025.4.25", "--db-path", "./data.db"],
    },
    order=150,
)

COMMAND = "uvx"
ARGS = ["mcp-server-sqlite@2025.4.25"]
DEFAULT_TOOL = "list-tables"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    db_path = (config.get("db_path") or "./data.db").strip()
    args = [a if a != "./data.db" else db_path for a in args]
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"query": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
