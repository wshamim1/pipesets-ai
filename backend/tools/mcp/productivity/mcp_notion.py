"""MCP Notion — built-in MCP server `mcp_notion`."""

import os
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_notion",
    name="MCP Notion",
    type="mcp",
    icon="📓",
    group="mcp_servers",
    category="Productivity",
    description="Read and write Notion pages, databases, and blocks via the Notion API.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@notionhq/notion-mcp-server@2.6.1"],
        "env_vars": {"OPENAPI_MCP_HEADERS": ""},
    },
    order=200,
)

COMMAND = "npx"
ARGS = ["-y", "@notionhq/notion-mcp-server@2.6.1"]
DEFAULT_TOOL = "API-post-search"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    token = (
        config.get("notion_token")
        or config.get("NOTION_TOKEN")
        or os.environ.get("NOTION_TOKEN", "")
    )
    if token:
        env_vars["OPENAPI_MCP_HEADERS"] = f'{{"Authorization": "Bearer {token}", "Notion-Version": "2022-06-28"}}'
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"query": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
