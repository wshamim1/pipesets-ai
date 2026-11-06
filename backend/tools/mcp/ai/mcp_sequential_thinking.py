"""MCP Sequential Thinking — built-in MCP server `mcp_sequential_thinking`."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_sequential_thinking",
    name="MCP Sequential Thinking",
    type="mcp",
    icon="🧠",
    group="mcp_servers",
    category="AI & Memory",
    description="Structured multi-step reasoning — breaks complex problems into tracked thought chains for deeper analysis.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sequential-thinking@2.0.0"],
    },
    order=130,
)

COMMAND = "npx"
ARGS = ["-y", "@modelcontextprotocol/server-sequential-thinking@2.0.0"]
DEFAULT_TOOL = "sequentialthinking"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"thought": input_text.strip(), "nextThoughtNeeded": True, "thoughtNumber": 1, "totalThoughts": 5}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
