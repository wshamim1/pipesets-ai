"""MCP Asana — built-in MCP server `mcp_asana`."""

import os
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_asana",
    name="MCP Asana",
    type="mcp",
    icon="✅",
    group="mcp_servers",
    category="Productivity",
    description="Tasks, projects, sections, and comments in Asana.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "asana-mcp@1.0.1"],
        "env_vars": {
            "ASANA_ACCESS_TOKEN": "",
            "ASANA_MCP_DEFAULT_WORKSPACE": "",
            "ASANA_MCP_WRITE_MODE": "read_only",
        },
    },
    order=245,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "asana-mcp@1.0.1"]
DEFAULT_TOOL = "asana_list_tasks"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    for key in ("ASANA_ACCESS_TOKEN", "ASANA_MCP_DEFAULT_WORKSPACE", "ASANA_MCP_WRITE_MODE"):
        val = config.get(key.lower()) or config.get(key) or os.environ.get(key, "")
        if val:
            env_vars[key] = val
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
