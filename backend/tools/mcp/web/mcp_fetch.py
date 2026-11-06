"""MCP Fetch — built-in MCP server `mcp_fetch`."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_fetch",
    name="MCP Fetch",
    type="mcp",
    icon="🔗",
    group="mcp_servers",
    category="Web & Browser",
    description="Fetch any URL and return clean readable text or markdown. Great for reading docs and API pages.",
    default_config={"transport": "stdio", "command": "uvx", "args": ["mcp-server-fetch@2026.10.28"]},
    order=120,
)

COMMAND = "uvx"
ARGS = ["mcp-server-fetch@2026.10.28"]
DEFAULT_TOOL = "fetch"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    tool_name = config.get("tool_name") or defaults["default_tool"]
    url = input_text.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    call_args = config.get("arguments") or {"url": url}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
