"""MCP E2B — built-in MCP server `mcp_e2b` (@e2b/mcp-server, by E2B; version pinned).

Runs Python code in an E2B secure sandbox using Jupyter Notebook syntax. The only tool is
``run_code``; the API key goes in ``E2B_API_KEY``.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_e2b",
    name="MCP E2B",
    type="mcp",
    icon="🧪",
    group="mcp_servers",
    category="AI & Memory",
    description="Run Python code in an E2B secure sandbox with Jupyter Notebook syntax.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@e2b/mcp-server@0.2.3"],
        "e2b_api_key": "",
    },
    required=("e2b_api_key",),
    order=330,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@e2b/mcp-server@0.2.3"]
DEFAULT_TOOL = "run_code"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    env_vars["E2B_API_KEY"] = config_value(config, "e2b_api_key")
    tool_name = config.get("tool_name") or defaults["default_tool"]
    code = input_text.strip()
    call_args = config.get("arguments") or ({"code": code} if code else {})
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
