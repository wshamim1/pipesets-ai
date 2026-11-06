"""MCP Filesystem — built-in MCP server `mcp_filesystem`."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_filesystem",
    name="MCP Filesystem",
    type="mcp",
    icon="📁",
    group="mcp_servers",
    category="Developer Tools",
    description="Read/write local project files and directories via MCP stdio.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem@2.1.0", "/Users/workspace"],
    },
    order=10,
)

COMMAND = "npx"
ARGS = ["-y", "@modelcontextprotocol/server-filesystem@2.1.0"]
DEFAULT_TOOL = "read_file"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    allowed_path = (config.get("allowed_path") or "").strip()
    if allowed_path:
        args.append(allowed_path)
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"path": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
