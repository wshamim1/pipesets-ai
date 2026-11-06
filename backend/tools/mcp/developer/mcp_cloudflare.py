"""MCP Cloudflare — built-in MCP server `mcp_cloudflare`: Cloudflare's managed remote server,
reached over Streamable HTTP. The server is token-efficient code mode: ``docs`` searches the
Cloudflare documentation, ``search`` searches the OpenAPI spec and ``execute`` runs sandboxed
JavaScript against the Cloudflare API. Authentication uses an API token in the ``Authorization``
header; tokens with Client IP Address Filtering enabled are not supported.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._http import remote_server
from tools.mcp._stdio import config_value

URL = "https://mcp.cloudflare.com/mcp"

TOOL = ToolSpec(
    id="mcp_cloudflare",
    name="MCP Cloudflare",
    type="mcp",
    icon="🧡",
    group="mcp_servers",
    category="Developer Tools",
    description="Search Cloudflare docs and the API spec, and run Cloudflare API calls through Cloudflare's own MCP server.",
    default_config={
        "transport": "http",
        "url": URL,
        "cloudflare_api_token": "",
    },
    required=("cloudflare_api_token",),
    order=330,
    is_new=True,
)

DEFAULT_TOOL = "docs"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    token = config_value(config, "cloudflare_api_token")
    headers = {"Authorization": f"Bearer {token}"}
    query = input_text.strip()
    tool_name = config.get("tool_name") or ("docs" if query else "whoami")
    call_args = config.get("arguments") or ({"query": query} if query else {})
    return URL, headers, tool_name, call_args


run = remote_server("MCP Cloudflare", DEFAULT_TOOL, prepare, TOOL.required)
