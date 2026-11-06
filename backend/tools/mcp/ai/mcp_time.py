"""MCP Time — built-in MCP server `mcp_time` (mcp-server-time, MCP reference server; version pinned)."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_time",
    name="MCP Time",
    type="mcp",
    icon="🕒",
    group="mcp_servers",
    category="AI & Memory",
    description="Current time in any IANA timezone, and conversion between timezones. No key needed.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-time@2026.10.28"],
        "local_timezone": "",
    },
    order=310,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["mcp-server-time@2026.10.28"]
DEFAULT_TOOL = "get_current_time"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    local = config_value(config, "local_timezone")
    if local:
        args = [*args, "--local-timezone", local]
    call_args = config.get("arguments") or {"timezone": input_text.strip() or local or "UTC"}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
