"""MCP Neon — built-in MCP server `mcp_neon`: Neon's managed remote server, reached over
Streamable HTTP. Authentication uses a Neon API key in the ``Authorization`` header, so the
local npm package (whose launcher takes the key on the command line) isn't needed.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._http import remote_server
from tools.mcp._stdio import config_value

URL = "https://mcp.neon.tech/mcp"

TOOL = ToolSpec(
    id="mcp_neon",
    name="MCP Neon",
    type="mcp",
    icon="🐘",
    group="mcp_servers",
    category="Databases & Data",
    description="Manage Neon Postgres projects and branches and run SQL through Neon's own MCP server.",
    default_config={
        "transport": "http",
        "url": URL,
        "neon_api_key": "",
    },
    required=("neon_api_key",),
    order=405,
    is_new=True,
)

DEFAULT_TOOL = "list_projects"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    token = config_value(config, "neon_api_key")
    headers = {"Authorization": f"Bearer {token}"}
    search = input_text.strip()
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or ({"search": search} if search else {})
    return URL, headers, tool_name, call_args


run = remote_server("MCP Neon", DEFAULT_TOOL, prepare, TOOL.required)
