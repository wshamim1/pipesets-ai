"""MCP Snowflake — built-in MCP server `mcp_snowflake` (mcp-server-snowflake; version pinned).

Credentials go in the package's environment variables, never on the command line. Writes stay
disabled unless read-only is turned off, which adds ``--allow_write``.
"""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_snowflake",
    name="MCP Snowflake",
    type="mcp",
    icon="❄️",
    group="mcp_servers",
    category="Databases & Data",
    description="Query Snowflake warehouses, list tables and describe schemas. Read-only by default.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["--from", "mcp-server-snowflake@0.3.8", "mcp_server_snowflake"],
        "snowflake_account": "",
        "snowflake_user": "",
        "snowflake_password": "",
        "snowflake_database": "",
        "snowflake_schema": "PUBLIC",
        "snowflake_warehouse": "",
        "snowflake_role": "",
        "read_only": "true",
    },
    required=("snowflake_account", "snowflake_user", "snowflake_password", "snowflake_database"),
    selects={"read_only": Select("Access", [("true", "Read-only"), ("false", "Read and write")])},
    order=380,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["--from", "mcp-server-snowflake@0.3.8", "mcp_server_snowflake"]
DEFAULT_TOOL = "read_query"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    for key, default in (("snowflake_account", ""), ("snowflake_user", ""), ("snowflake_password", ""),
                         ("snowflake_database", ""), ("snowflake_schema", "PUBLIC"),
                         ("snowflake_warehouse", ""), ("snowflake_role", "")):
        value = config_value(config, key, default)
        if value:
            env_vars[key.upper()] = value
    if str(config.get("read_only", "true")).lower() == "false":
        args = [*args, "--allow_write"]
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"query": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
