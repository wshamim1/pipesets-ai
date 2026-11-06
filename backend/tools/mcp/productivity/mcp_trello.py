"""MCP Trello — built-in MCP server `mcp_trello` (@delorenj/mcp-server-trello; version pinned)."""

import os
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_trello",
    name="MCP Trello",
    type="mcp",
    icon="📋",
    group="mcp_servers",
    category="Productivity",
    description="Boards, lists, cards, checklists, and labels in Trello.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@delorenj/mcp-server-trello@1.8.1"],
        "env_vars": {"TRELLO_API_KEY": "", "TRELLO_TOKEN": ""},
    },
    order=240,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@delorenj/mcp-server-trello@1.8.1"]
DEFAULT_TOOL = "list_boards"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    for key in ("TRELLO_API_KEY", "TRELLO_TOKEN"):
        val = config.get(key.lower()) or config.get(key) or os.environ.get(key, "")
        if val:
            env_vars[key] = val
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
