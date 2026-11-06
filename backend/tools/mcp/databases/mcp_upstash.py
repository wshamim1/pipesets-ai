"""MCP Upstash — built-in MCP server `mcp_upstash` (@upstash/mcp-server, by Upstash; version pinned).

Manage Upstash Redis databases (create, inspect, back up, run Redis commands) and QStash messages,
schedules and logs through the Upstash Developer API. The account email and management API key go
in ``UPSTASH_EMAIL`` / ``UPSTASH_API_KEY``, never on the command line. The default tool lists the
account's Redis databases.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_upstash",
    name="MCP Upstash",
    type="mcp",
    icon="🟩",
    group="mcp_servers",
    category="Databases & Data",
    description="Manage Upstash Redis databases, run Redis commands, and inspect QStash messages and schedules.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@upstash/mcp-server@0.4.0"],
        "upstash_email": "",
        "upstash_api_key": "",
    },
    required=("upstash_email", "upstash_api_key"),
    order=450,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@upstash/mcp-server@0.4.0"]
DEFAULT_TOOL = "redis_database_list_databases"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    env_vars["UPSTASH_EMAIL"] = config_value(config, "upstash_email")
    env_vars["UPSTASH_API_KEY"] = config_value(config, "upstash_api_key")
    args = [*args, "--disable-telemetry"]
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
