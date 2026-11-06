"""MCP Hyperbrowser — built-in MCP server `mcp_hyperbrowser` (hyperbrowser-mcp, by Hyperbrowser;
version pinned).

Cloud browser automation: scrape pages, crawl sites, extract structured data and run a browser-use
agent. The API key goes in ``HYPERBROWSER_API_KEY`` (``HB_API_KEY`` is also accepted by the server).
"""

import os
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_hyperbrowser",
    name="MCP Hyperbrowser",
    type="mcp",
    icon="🌐",
    group="mcp_servers",
    category="Web & Browser",
    description="Scrape and crawl pages, extract structured data and run browser agents with Hyperbrowser.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "hyperbrowser-mcp@1.0.25"],
        "hyperbrowser_api_key": "",
    },
    required=("hyperbrowser_api_key",),
    order=360,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "hyperbrowser-mcp@1.0.25"]
DEFAULT_TOOL = "scrape_webpage"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    api_key = (config_value(config, "hyperbrowser_api_key")
               or str(config.get("HB_API_KEY") or os.environ.get("HB_API_KEY") or "").strip())
    env_vars["HYPERBROWSER_API_KEY"] = api_key
    url = input_text.strip()
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or (
        {"url": url, "outputFormat": ["markdown"]} if url else {}
    )
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
