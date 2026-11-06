"""MCP Brave Search — built-in MCP server `mcp_brave_search` (@brave/brave-search-mcp-server, by Brave; version pinned)."""

import os
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_brave_search",
    name="MCP Brave Search",
    type="mcp",
    icon="🦁",
    group="mcp_servers",
    category="Web & Browser",
    description="Web, local, news, image and video search through the Brave Search API.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@brave/brave-search-mcp-server@2.1.4"],
        "env_vars": {"BRAVE_API_KEY": ""},
    },
    order=50,
)

COMMAND = "npx"
ARGS = ["-y", "@brave/brave-search-mcp-server@2.1.4"]
DEFAULT_TOOL = "brave_web_search"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    api_key = (
        config.get("brave_api_key")
        or config.get("BRAVE_API_KEY")
        or os.environ.get("BRAVE_API_KEY", "")
    )
    if api_key:
        env_vars["BRAVE_API_KEY"] = api_key
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"query": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
