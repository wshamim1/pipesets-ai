"""MCP Honeycomb — built-in MCP server `mcp_honeycomb`: Honeycomb's managed remote server,
reached over Streamable HTTP. Queries, traces, SLOs, boards and semantic conventions are exposed
as tools. Authentication uses a management API key in ``Bearer <KEY_ID>:<SECRET_KEY>`` form; the
region dropdown picks the US or EU endpoint.
"""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._http import remote_server
from tools.mcp._stdio import config_value

HONEYCOMB_URLS = {
    "us": "https://mcp.honeycomb.io/mcp",
    "eu": "https://mcp.eu1.honeycomb.io/mcp",
}
URL = HONEYCOMB_URLS["us"]

TOOL = ToolSpec(
    id="mcp_honeycomb",
    name="MCP Honeycomb",
    type="mcp",
    icon="🍯",
    group="mcp_servers",
    category="DevOps & Observability",
    description="Query Honeycomb telemetry, traces and SLOs, and inspect boards and semantic conventions.",
    default_config={
        "transport": "http",
        "url": URL,
        "honeycomb_region": "us",
        "honeycomb_api_key": "",
    },
    required=("honeycomb_api_key",),
    selects={"honeycomb_region": Select("Region", [(region, region.upper()) for region in HONEYCOMB_URLS])},
    order=50,
    is_new=True,
)

DEFAULT_TOOL = "get_workspace_context"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    region = str(config.get("honeycomb_region") or "us").lower()
    url = HONEYCOMB_URLS.get(region, URL)
    api_key = config_value(config, "honeycomb_api_key")
    headers = {"Authorization": f"Bearer {api_key}"}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {}
    return url, headers, tool_name, call_args


run = remote_server("MCP Honeycomb", DEFAULT_TOOL, prepare, TOOL.required)
