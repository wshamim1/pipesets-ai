"""MCP Tavily — built-in MCP server `mcp_tavily` (tavily-mcp, by Tavily; version pinned)."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_tavily",
    name="MCP Tavily",
    type="mcp",
    icon="🔎",
    group="mcp_servers",
    category="Web & Browser",
    description="Web search, page extraction, site crawl and site map through Tavily.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "tavily-mcp@0.2.22"],
        "tavily_api_key": "",
    },
    required=("tavily_api_key",),
    order=300,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "tavily-mcp@0.2.22"]
DEFAULT_TOOL = "tavily_search"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["TAVILY_API_KEY"] = config_value(config, "tavily_api_key")
    call_args = config.get("arguments") or {"query": input_text.strip()}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
