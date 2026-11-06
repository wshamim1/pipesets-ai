"""MCP Airtable — built-in MCP server `mcp_airtable` (airtable-mcp-server; version pinned)."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_airtable",
    name="MCP Airtable",
    type="mcp",
    icon="🗂️",
    group="mcp_servers",
    category="Productivity",
    description="Airtable bases, tables and records: list, search, create and update. Uses a personal access token.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "airtable-mcp-server@1.14.0"],
        "airtable_api_key": "",
    },
    required=("airtable_api_key",),
    order=310,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "airtable-mcp-server@1.14.0"]
DEFAULT_TOOL = "list_bases"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["AIRTABLE_API_KEY"] = config_value(config, "airtable_api_key")
    call_args = config.get("arguments") or {}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
