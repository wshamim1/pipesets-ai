"""MCP Netlify — built-in MCP server `mcp_netlify` (@netlify/mcp, by Netlify; version pinned).

Netlify's server groups its read and write operations behind one tool per domain. The default
tool is the project reader, which lists the user's sites (optionally filtered by name). The
personal access token goes in ``NETLIFY_PERSONAL_ACCESS_TOKEN`` rather than on the command line.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_netlify",
    name="MCP Netlify",
    type="mcp",
    icon="🌐",
    group="mcp_servers",
    category="Developer Tools",
    description="List Netlify projects and deploys, manage environment variables and extensions, and deploy sites.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@netlify/mcp@1.21.0"],
        "netlify_personal_access_token": "",
    },
    required=("netlify_personal_access_token",),
    order=310,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@netlify/mcp@1.21.0"]
DEFAULT_TOOL = "netlify-project-services-reader"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    env_vars["NETLIFY_PERSONAL_ACCESS_TOKEN"] = config_value(config, "netlify_personal_access_token")
    search = input_text.strip()
    tool_name = config.get("tool_name") or defaults["default_tool"]
    selector: Dict[str, Any] = {"operation": "get-projects"}
    if search:
        selector["params"] = {"projectNameSearchValue": search}
    call_args = config.get("arguments") or {"selectSchema": selector}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
