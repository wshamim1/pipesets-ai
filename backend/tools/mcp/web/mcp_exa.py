"""MCP Exa — built-in MCP server `mcp_exa` (exa-mcp-server, by Exa; version pinned)."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_exa",
    name="MCP Exa",
    type="mcp",
    icon="🧭",
    group="mcp_servers",
    category="Web & Browser",
    description="Neural web search and page fetch through Exa.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "exa-mcp-server@3.4.3"],
        "exa_api_key": "",
    },
    required=("exa_api_key",),
    order=310,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "exa-mcp-server@3.4.3"]
DEFAULT_TOOL = "web_search_exa"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["EXA_API_KEY"] = config_value(config, "exa_api_key")
    call_args = config.get("arguments") or {"query": input_text.strip()}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
