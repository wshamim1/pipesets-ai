"""MCP Slack — built-in MCP server `mcp_slack`.

The reference server is deprecated upstream and pinned to its last release (Slack's own MCP server is remote and needs a Slack app with OAuth)."""

import os
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_slack",
    name="MCP Slack",
    type="mcp",
    icon="🔔",
    group="mcp_servers",
    category="Productivity",
    description="Send messages, read channels, and manage Slack workspaces via MCP.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-slack@2025.4.25"],
        "env_vars": {"SLACK_BOT_TOKEN": "", "SLACK_TEAM_ID": ""},
    },
    order=70,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@modelcontextprotocol/server-slack@2025.4.25"]
DEFAULT_TOOL = "slack_list_channels"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    for key in ("SLACK_BOT_TOKEN", "SLACK_TEAM_ID", "SLACK_CHANNEL_IDS"):
        val = config.get(key.lower()) or config.get(key) or os.environ.get(key, "")
        if val:
            env_vars[key] = val
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"limit": 25}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
