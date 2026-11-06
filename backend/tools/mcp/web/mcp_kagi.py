"""MCP Kagi — built-in MCP server `mcp_kagi` (kagimcp, by Kagi; version pinned).

Ad-free web, news, video and podcast search with optional page extraction, from Kagi's Search API.
The API key goes in ``KAGI_API_KEY``. A URL input extracts that page; anything else is searched.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_kagi",
    name="MCP Kagi Search",
    type="mcp",
    icon="🔍",
    group="mcp_servers",
    category="Web & Browser",
    description="Ad-free web, news and video search through Kagi, and extract a page's content. Needs a Kagi API key.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["kagimcp@1.1.0"],
        "kagi_api_key": "",
    },
    required=("kagi_api_key",),
    order=400,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["kagimcp@1.1.0"]
DEFAULT_TOOL = "kagi_search_fetch"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    env_vars["KAGI_API_KEY"] = config_value(config, "kagi_api_key")
    if config.get("tool_name"):
        return args, config["tool_name"], config.get("arguments") or {}
    text = input_text.strip()
    if text.startswith(("http://", "https://")):
        return args, "kagi_extract", {"url": text}
    return args, defaults["default_tool"], {"query": text}


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
