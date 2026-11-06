"""MCP Discord — built-in MCP server `mcp_discord` (discord-mcp; version pinned)."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_discord",
    name="MCP Discord",
    type="mcp",
    icon="💬",
    group="mcp_servers",
    category="Productivity",
    description="Read Discord channels, messages and members, and send messages as a bot.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "discord-mcp@2.4.0"],
        "discord_bot_token": "",
        "discord_channel_id": "",
    },
    required=("discord_bot_token",),
    order=430,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "discord-mcp@2.4.0"]
DEFAULT_TOOL = "discord_get_channel"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["DISCORD_BOT_TOKEN"] = config_value(config, "discord_bot_token")
    channel_id = input_text.strip() or config_value(config, "discord_channel_id")
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or ({"channelId": channel_id} if channel_id else {})
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
