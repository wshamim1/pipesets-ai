"""MCP Everything (Test) — built-in MCP server `mcp_everything`."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_everything",
    name="MCP Everything (Test)",
    type="mcp",
    icon="🧪",
    group="mcp_servers",
    category="AI & Memory",
    description="Reference MCP server exposing all protocol features for testing.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-everything@2.1.0"],
    },
    order=100,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@modelcontextprotocol/server-everything@2.1.0"]
DEFAULT_TOOL = "echo"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"text": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
