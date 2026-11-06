"""MCP Render — built-in MCP server `mcp_render`: Render's managed remote server, reached over
Streamable HTTP. It lists workspaces, services, deploys, logs, metrics and Postgres databases,
and can create and redeploy services. Authentication uses a Render API key in the
``Authorization`` header for non-interactive clients.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._http import remote_server
from tools.mcp._stdio import config_value

URL = "https://mcp.render.com/mcp"

TOOL = ToolSpec(
    id="mcp_render",
    name="MCP Render",
    type="mcp",
    icon="▲",
    group="mcp_servers",
    category="Developer Tools",
    description="List Render services and deploys, read logs and metrics, and manage Postgres databases.",
    default_config={
        "transport": "http",
        "url": URL,
        "render_api_key": "",
    },
    required=("render_api_key",),
    order=340,
    is_new=True,
)

DEFAULT_TOOL = "list_services"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    token = config_value(config, "render_api_key")
    headers = {"Authorization": f"Bearer {token}"}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {}
    return URL, headers, tool_name, call_args


run = remote_server("MCP Render", DEFAULT_TOOL, prepare, TOOL.required)
