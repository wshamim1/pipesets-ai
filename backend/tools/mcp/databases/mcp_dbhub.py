"""MCP DBHub — built-in MCP server `mcp_dbhub` (@bytebase/dbhub, by Bytebase; version pinned).

A token-efficient database server for PostgreSQL, MySQL, MariaDB, SQL Server, Oracle and SQLite.
The connection string goes in ``DSN`` (never on the command line). Read-only access is configured
in a ``dbhub.toml`` file, because the old ``--readonly`` flag has been removed. Requires Node.js
22.5 or newer.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_dbhub",
    name="MCP DBHub",
    type="mcp",
    icon="🗄️",
    group="mcp_servers",
    category="Databases & Data",
    description="Query PostgreSQL, MySQL, MariaDB, SQL Server, Oracle or SQLite through one DSN-based server.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@bytebase/dbhub@1.5.0", "--transport", "stdio"],
        "dsn": "",
    },
    required=("dsn",),
    order=440,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@bytebase/dbhub@1.5.0", "--transport", "stdio"]
DEFAULT_TOOL = "execute_sql"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    env_vars["DSN"] = config_value(config, "dsn")
    tool_name = config.get("tool_name") or defaults["default_tool"]
    sql = input_text.strip()
    call_args = config.get("arguments") or ({"sql": sql} if sql else {})
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
