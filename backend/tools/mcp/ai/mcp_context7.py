"""MCP Context7 — built-in MCP server `mcp_context7` (@upstash/context7-mcp, by Upstash; version pinned)."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_context7",
    name="MCP Context7",
    type="mcp",
    icon="📚",
    group="mcp_servers",
    category="AI & Memory",
    description="Up-to-date library and framework documentation for coding agents. The API key is optional (higher rate limits).",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@upstash/context7-mcp@4.4.4"],
        "context7_api_key": "",
    },
    order=300,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@upstash/context7-mcp@4.4.4"]
DEFAULT_TOOL = "resolve-library-id"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    key = config_value(config, "context7_api_key")
    if key:
        env_vars["CONTEXT7_API_KEY"] = key
    text = input_text.strip()
    call_args = config.get("arguments") or {"libraryName": text, "query": text}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
