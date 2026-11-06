"""MCP Shopify Dev — built-in MCP server `mcp_shopify_dev` (@shopify/dev-mcp, by Shopify; version pinned).

Searches shopify.dev documentation and validates GraphQL, Liquid theme and UI extension code against
Shopify's schemas. It reads public docs only, so no store or key is needed. The input becomes a docs
search.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_shopify_dev",
    name="MCP Shopify Dev",
    type="mcp",
    icon="🛍️",
    group="mcp_servers",
    category="Developer Tools",
    description="Search shopify.dev docs and validate Admin GraphQL, Liquid themes and extension code. No key needed.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@shopify/dev-mcp@1.18.0"],
    },
    order=370,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@shopify/dev-mcp@1.18.0"]
DEFAULT_TOOL = "search_docs_chunks"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → the MCP tool to call with its arguments."""
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"prompt": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
