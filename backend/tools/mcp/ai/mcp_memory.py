"""MCP Memory — built-in MCP server `mcp_memory`."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_memory",
    name="MCP Memory",
    type="mcp",
    icon="💾",
    group="mcp_servers",
    category="AI & Memory",
    description="Persistent key-value knowledge graph — agents store and recall facts across sessions.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory@2.0.1"],
    },
    order=160,
)

COMMAND = "npx"
ARGS = ["-y", "@modelcontextprotocol/server-memory@2.0.1"]
DEFAULT_TOOL = "create_entities"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"entities": [{"name": input_text.strip(), "entityType": "fact", "observations": [input_text.strip()]}]}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
