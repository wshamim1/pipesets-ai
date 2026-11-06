"""MCP Todoist — built-in MCP server `mcp_todoist` (@doist/todoist-mcp, by Doist; version pinned).

Tasks, projects, sections, labels and comments. The API key goes in ``TODOIST_API_KEY`` rather
than on the command line. The default tool searches tasks by text.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_todoist",
    name="MCP Todoist",
    type="mcp",
    icon="✅",
    group="mcp_servers",
    category="Productivity",
    description="Find, add, update and complete Todoist tasks, and manage projects, sections and labels.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@doist/todoist-mcp@13.8.4"],
        "todoist_api_key": "",
    },
    required=("todoist_api_key",),
    order=440,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@doist/todoist-mcp@13.8.4"]
DEFAULT_TOOL = "find-tasks"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    env_vars["TODOIST_API_KEY"] = config_value(config, "todoist_api_key")
    search = input_text.strip()
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or ({"searchText": search} if search else {})
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
