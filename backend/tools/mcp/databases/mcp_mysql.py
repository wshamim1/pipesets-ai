"""MCP MySQL — built-in MCP server `mcp_mysql` (@benborla29/mcp-server-mysql; version pinned).

The package disables writes by default; turning read-only off enables INSERT, UPDATE, DELETE and DDL.
"""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_mysql",
    name="MCP MySQL",
    type="mcp",
    icon="🐬",
    group="mcp_servers",
    category="Databases & Data",
    description="Run SQL against MySQL or MariaDB, with table and schema resources. Read-only by default.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@benborla29/mcp-server-mysql@2.0.9"],
        "mysql_host": "localhost",
        "mysql_port": "3306",
        "mysql_user": "root",
        "mysql_pass": "",
        "mysql_db": "",
        "read_only": "true",
    },
    selects={"read_only": Select("Access", [("true", "Read-only"), ("false", "Read and write")])},
    order=370,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@benborla29/mcp-server-mysql@2.0.9"]
DEFAULT_TOOL = "mysql_query"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["MYSQL_HOST"] = config_value(config, "mysql_host", "localhost")
    env_vars["MYSQL_PORT"] = config_value(config, "mysql_port", "3306")
    env_vars["MYSQL_USER"] = config_value(config, "mysql_user", "root")
    env_vars["MYSQL_PASS"] = config_value(config, "mysql_pass")
    database = config_value(config, "mysql_db")
    if database:
        env_vars["MYSQL_DB"] = database
    if str(config.get("read_only", "true")).lower() == "false":
        for key in ("ALLOW_INSERT_OPERATION", "ALLOW_UPDATE_OPERATION", "ALLOW_DELETE_OPERATION",
                    "ALLOW_DDL_OPERATION"):
            env_vars[key] = "true"
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"sql": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
