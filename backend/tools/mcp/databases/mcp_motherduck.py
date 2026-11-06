"""MCP MotherDuck — built-in MCP server `mcp_motherduck` (mcp-server-motherduck; version pinned).

Queries MotherDuck cloud databases and local DuckDB files. The token goes in
``MOTHERDUCK_TOKEN`` rather than on the command line. Read-only unless you turn it off.
"""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_motherduck",
    name="MCP MotherDuck",
    type="mcp",
    icon="🦆",
    group="mcp_servers",
    category="Databases & Data",
    description="Query MotherDuck and DuckDB: run SQL, list databases, tables and columns. Read-only by default.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["--from", "mcp-server-motherduck@1.1.0", "mcp-server-motherduck"],
        "motherduck_db_path": "md:",
        "motherduck_token": "",
        "read_only": "true",
    },
    required=("motherduck_token",),
    selects={"read_only": Select("Access", [("true", "Read-only"), ("false", "Read and write")])},
    order=410,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["--from", "mcp-server-motherduck@1.1.0", "mcp-server-motherduck"]
DEFAULT_TOOL = "execute_query"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["MOTHERDUCK_TOKEN"] = config_value(config, "motherduck_token")
    db_path = config_value(config, "motherduck_db_path", "md:")
    if db_path:
        args = [*args, "--db-path", db_path]
    if str(config.get("read_only", "true")).lower() == "false":
        args = [*args, "--read-write"]
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"sql": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
