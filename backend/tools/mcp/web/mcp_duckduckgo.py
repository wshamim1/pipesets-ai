"""MCP DuckDuckGo — built-in MCP server `mcp_duckduckgo` (duckduckgo-mcp-server; version pinned).

Web search and page reading with no API key. A URL input fetches that page as clean text; anything
else becomes a search. ``safe_search`` and ``region`` go in the server's ``DDG_*`` env vars.
"""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_duckduckgo",
    name="MCP DuckDuckGo",
    type="mcp",
    icon="🦆",
    group="mcp_servers",
    category="Web & Browser",
    description="Search the web with DuckDuckGo and read result pages as clean text. No key needed.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["duckduckgo-mcp-server@0.7.0"],
        "safe_search": "MODERATE",
        "region": "",
    },
    selects={"safe_search": Select("Safe search", (("STRICT", "Strict"), ("MODERATE", "Moderate"), ("OFF", "Off")))},
    order=380,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["duckduckgo-mcp-server@0.7.0"]
DEFAULT_TOOL = "search"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    env_vars["DDG_SAFE_SEARCH"] = (config_value(config, "safe_search") or "MODERATE").upper()
    region = config_value(config, "region")
    if region:
        env_vars["DDG_REGION"] = region
    text = input_text.strip()
    if config.get("tool_name"):
        return args, config["tool_name"], config.get("arguments") or {}
    if text.startswith(("http://", "https://")):
        return args, "fetch_content", {"url": text}
    return args, defaults["default_tool"], {"query": text}


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
