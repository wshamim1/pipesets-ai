"""MCP Firecrawl — built-in MCP server `mcp_firecrawl`."""

import os
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_firecrawl",
    name="MCP Firecrawl",
    type="mcp",
    icon="🔥",
    group="mcp_servers",
    category="Web & Browser",
    description="Full JS-rendered web crawl and structured extraction. Handles SPAs and dynamic pages.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "firecrawl-mcp@3.36.0"],
        "env_vars": {"FIRECRAWL_API_KEY": ""},
    },
    order=140,
)

COMMAND = "npx"
ARGS = ["-y", "firecrawl-mcp@3.36.0"]
DEFAULT_TOOL = "firecrawl_scrape"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    api_key = (
        config.get("firecrawl_api_key")
        or config.get("FIRECRAWL_API_KEY")
        or os.environ.get("FIRECRAWL_API_KEY", "")
    )
    if api_key:
        env_vars["FIRECRAWL_API_KEY"] = api_key
    tool_name = config.get("tool_name") or defaults["default_tool"]
    url = input_text.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    call_args = config.get("arguments") or {"url": url}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
