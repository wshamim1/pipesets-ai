"""MCP monday.com — built-in MCP server `mcp_monday`: monday.com's hosted Platform MCP server,
reached over Streamable HTTP. Authentication uses a personal API token in the ``Authorization``
header; OAuth is also supported but not required for non-interactive clients. The input becomes a
board search, or the user context is returned when there is no input.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._http import remote_server
from tools.mcp._stdio import config_value

URL = "https://mcp.monday.com/mcp"

TOOL = ToolSpec(
    id="mcp_monday",
    name="MCP monday.com",
    type="mcp",
    icon="🟣",
    group="mcp_servers",
    category="Productivity",
    description="Search monday.com boards, docs and folders, and read or update items, groups and columns.",
    default_config={
        "transport": "http",
        "url": URL,
        "monday_api_token": "",
    },
    required=("monday_api_token",),
    order=450,
    is_new=True,
)

DEFAULT_TOOL = "search"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    token = config_value(config, "monday_api_token")
    headers = {"Authorization": f"Bearer {token}"}
    search = input_text.strip()
    tool_name = config.get("tool_name") or ("search" if search else "get_user_context")
    call_args = config.get("arguments") or (
        {"searchType": "BOARD", "searchTerm": search} if search else {}
    )
    return URL, headers, tool_name, call_args


run = remote_server("MCP monday.com", DEFAULT_TOOL, prepare, TOOL.required)
