"""MCP PDF — built-in MCP server `mcp_pdf`."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_pdf",
    name="MCP PDF",
    type="mcp",
    icon="📄",
    group="mcp_servers",
    category="Web & Browser",
    description="Read and extract text from PDF documents via MCP.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-pdf@2.0.4"],
    },
    order=87,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@modelcontextprotocol/server-pdf@2.0.4"]
DEFAULT_TOOL = "read_pdf"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"path": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
