"""MCP Microsoft Learn — built-in MCP server `mcp_microsoft_learn`: Microsoft's hosted Learn Docs server
(learn.microsoft.com/api/mcp), reached over Streamable HTTP with no key. It searches and reads the
official docs for Azure, .NET, Microsoft 365 and the rest of Learn. A learn.microsoft.com URL input
reads that page; anything else becomes a docs search.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._http import remote_server

URL = "https://learn.microsoft.com/api/mcp"

TOOL = ToolSpec(
    id="mcp_microsoft_learn",
    name="MCP Microsoft Learn",
    type="mcp",
    icon="📘",
    group="mcp_servers",
    category="Developer Tools",
    description="Search and read official Microsoft docs (Azure, .NET, Microsoft 365) and code samples. No key needed.",
    default_config={
        "transport": "http",
        "url": URL,
    },
    order=350,
    is_new=True,
)

DEFAULT_TOOL = "microsoft_docs_search"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    text = input_text.strip()
    if config.get("tool_name"):
        tool_name = config["tool_name"]
        call_args = config.get("arguments") or {}
    elif text.startswith(("http://", "https://")):
        tool_name = "microsoft_docs_fetch"
        call_args = {"url": text}
    else:
        tool_name = defaults["default_tool"]
        call_args = {"query": text} if text else {}
    return URL, {}, tool_name, call_args


run = remote_server("MCP Microsoft Learn", DEFAULT_TOOL, prepare)
