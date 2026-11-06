"""MCP Apify — built-in MCP server `mcp_apify` (@apify/actors-mcp-server, by Apify; version pinned).

Searches Apify Store and runs Actors for web scraping, data extraction and browser automation.
The API token goes in ``APIFY_TOKEN`` rather than on the command line.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_apify",
    name="MCP Apify",
    type="mcp",
    icon="🕷️",
    group="mcp_servers",
    category="Web & Browser",
    description="Search Apify Store and run Actors for web scraping, crawling and browser automation.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@apify/actors-mcp-server@0.20.0"],
        "apify_token": "",
    },
    required=("apify_token",),
    order=340,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@apify/actors-mcp-server@0.20.0"]
DEFAULT_TOOL = "search-actors"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    env_vars["APIFY_TOKEN"] = config_value(config, "apify_token")
    keywords = input_text.strip()
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or ({"keywords": keywords} if keywords else {})
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
