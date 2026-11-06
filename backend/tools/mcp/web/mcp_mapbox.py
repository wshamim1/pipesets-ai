"""MCP Mapbox — built-in MCP server `mcp_mapbox` (@mapbox/mcp-server, by Mapbox; version pinned).

Geocoding, place and category search, directions, travel-time matrices and isochrones, static maps,
plus offline geometry (distance, area, buffers). The access token goes in ``MAPBOX_ACCESS_TOKEN``.
The input becomes a place / address search.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_mapbox",
    name="MCP Mapbox",
    type="mcp",
    icon="🗺️",
    group="mcp_servers",
    category="Web & Browser",
    description="Geocode places and addresses, get directions, travel times and isochrones, and render static maps with Mapbox.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@mapbox/mcp-server@0.16.0"],
        "mapbox_access_token": "",
    },
    required=("mapbox_access_token",),
    order=370,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@mapbox/mcp-server@0.16.0"]
DEFAULT_TOOL = "search_and_geocode_tool"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    env_vars["MAPBOX_ACCESS_TOKEN"] = config_value(config, "mapbox_access_token")
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"q": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
