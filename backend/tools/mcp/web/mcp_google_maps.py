"""MCP Google Maps — built-in MCP server `mcp_google_maps`.

The reference server is deprecated upstream and pinned to its last release (no maintained replacement yet)."""

import os
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_google_maps",
    name="MCP Google Maps",
    type="mcp",
    icon="🗺️",
    group="mcp_servers",
    category="Web & Browser",
    description="Geocoding, directions, and place search via the Google Maps MCP server.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-google-maps@0.6.2"],
        "env_vars": {"GOOGLE_MAPS_API_KEY": ""},
    },
    order=80,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@modelcontextprotocol/server-google-maps@0.6.2"]
DEFAULT_TOOL = "maps_search_places"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    api_key = (
        config.get("google_maps_api_key")
        or config.get("GOOGLE_MAPS_API_KEY")
        or os.environ.get("GOOGLE_MAPS_API_KEY", "")
    )
    if api_key:
        env_vars["GOOGLE_MAPS_API_KEY"] = api_key
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"query": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
