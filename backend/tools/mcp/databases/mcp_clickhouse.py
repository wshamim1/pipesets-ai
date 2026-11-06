"""MCP ClickHouse — built-in MCP server `mcp_clickhouse` (mcp-clickhouse, by ClickHouse; version pinned)."""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_clickhouse",
    name="MCP ClickHouse",
    type="mcp",
    icon="🧱",
    group="mcp_servers",
    category="Databases & Data",
    description="Query ClickHouse over its HTTP interface, with database and table discovery. Read-only by default.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-clickhouse@0.7.0"],
        "clickhouse_host": "localhost",
        "clickhouse_port": "8123",
        "clickhouse_user": "default",
        "clickhouse_password": "",
        "clickhouse_database": "",
        "clickhouse_secure": "false",
        "read_only": "true",
    },
    selects={
        "clickhouse_secure": Select("Connection", [("false", "HTTP"), ("true", "HTTPS")]),
        "read_only": Select("Access", [("true", "Read-only"), ("false", "Read and write")]),
    },
    order=360,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["mcp-clickhouse@0.7.0"]
DEFAULT_TOOL = "run_query"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["CLICKHOUSE_HOST"] = config_value(config, "clickhouse_host", "localhost")
    secure = str(config.get("clickhouse_secure", "false")).lower() == "true"
    port = config_value(config, "clickhouse_port", "8443" if secure else "8123")
    # The package's own default follows the scheme; our catalog default is the HTTP port
    if secure and port == "8123":
        port = "8443"
    elif not secure and port == "8443":
        port = "8123"
    env_vars["CLICKHOUSE_PORT"] = port
    env_vars["CLICKHOUSE_USER"] = config_value(config, "clickhouse_user", "default")
    # Always present: the server only checks that the variable exists
    env_vars["CLICKHOUSE_PASSWORD"] = config_value(config, "clickhouse_password")
    database = config_value(config, "clickhouse_database")
    if database:
        env_vars["CLICKHOUSE_DATABASE"] = database
    env_vars["CLICKHOUSE_SECURE"] = "true" if secure else "false"
    env_vars["CLICKHOUSE_VERIFY"] = "true" if secure else "false"
    read_only = str(config.get("read_only", "true")).lower() != "false"
    env_vars["CLICKHOUSE_ALLOW_WRITE_ACCESS"] = "false" if read_only else "true"
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"query": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
