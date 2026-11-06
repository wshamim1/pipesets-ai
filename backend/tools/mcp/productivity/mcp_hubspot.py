"""MCP HubSpot — built-in MCP server `mcp_hubspot` (@hubspot/mcp-server, by HubSpot; version pinned)."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_hubspot",
    name="MCP HubSpot",
    type="mcp",
    icon="🧡",
    group="mcp_servers",
    category="Productivity",
    description="HubSpot CRM: search, read and update contacts, companies, deals, tickets and engagements. Uses a private app access token.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@hubspot/mcp-server@0.4.0"],
        "hubspot_access_token": "",
    },
    required=("hubspot_access_token",),
    order=300,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@hubspot/mcp-server@0.4.0"]
DEFAULT_TOOL = "hubspot-get-user-details"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["PRIVATE_APP_ACCESS_TOKEN"] = config_value(config, "hubspot_access_token")
    call_args = config.get("arguments") or {}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
