"""MCP Postman — built-in MCP server `mcp_postman`: Postman's managed remote server, reached over
Streamable HTTP. The minimal endpoint covers collections, workspaces, environments, specs and
mocks; the API key goes in the ``Authorization`` header. The EU region is API-key only.
"""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._http import remote_server
from tools.mcp._stdio import config_value

POSTMAN_URLS = {
    "us": "https://mcp.postman.com/minimal",
    "eu": "https://mcp.eu.postman.com/minimal",
}
URL = POSTMAN_URLS["us"]

TOOL = ToolSpec(
    id="mcp_postman",
    name="MCP Postman",
    type="mcp",
    icon="📮",
    group="mcp_servers",
    category="Developer Tools",
    description="Search and manage Postman collections, workspaces, environments, specs and mocks.",
    default_config={
        "transport": "http",
        "url": URL,
        "postman_region": "us",
        "postman_api_key": "",
    },
    required=("postman_api_key",),
    selects={"postman_region": Select("Region", [(region, region.upper()) for region in POSTMAN_URLS])},
    order=320,
    is_new=True,
)

DEFAULT_TOOL = "searchPostmanElements"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    region = str(config.get("postman_region") or "us").lower()
    url = POSTMAN_URLS.get(region, URL)
    token = config_value(config, "postman_api_key")
    headers = {"Authorization": f"Bearer {token}"}
    query = input_text.strip()
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or ({"q": query} if query else {})
    return url, headers, tool_name, call_args


run = remote_server("MCP Postman", DEFAULT_TOOL, prepare, TOOL.required)
