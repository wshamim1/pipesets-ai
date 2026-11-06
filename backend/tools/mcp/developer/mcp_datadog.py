"""MCP Datadog — built-in MCP server `mcp_datadog`: Datadog's managed remote server, reached over
Streamable HTTP. Authentication uses an API key plus an application key in the ``DD-API-KEY`` and
``DD-APPLICATION-KEY`` headers. The site dropdown picks the matching regional endpoint.
"""

import os
from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._http import remote_server

DATADOG_SITES = {
    "us1": "https://mcp.datadoghq.com/v1/mcp",
    "us3": "https://mcp.us3.datadoghq.com/v1/mcp",
    "us5": "https://mcp.us5.datadoghq.com/v1/mcp",
    "eu1": "https://mcp.datadoghq.eu/v1/mcp",
    "ap1": "https://mcp.ap1.datadoghq.com/v1/mcp",
    "ap2": "https://mcp.ap2.datadoghq.com/v1/mcp",
    "uk1": "https://mcp.uk1.datadoghq.com/v1/mcp",
}
URL = DATADOG_SITES["us1"]

TOOL = ToolSpec(
    id="mcp_datadog",
    name="MCP Datadog",
    type="mcp",
    icon="🐶",
    group="mcp_servers",
    category="DevOps & Observability",
    description="Search Datadog logs, metrics, traces, monitors and incidents through Datadog's own MCP server.",
    default_config={
        "transport": "http",
        "url": URL,
        "datadog_site": "us1",
        "dd_api_key": "",
        "dd_application_key": "",
    },
    required=("dd_api_key", "dd_application_key"),
    selects={"datadog_site": Select("Site", [(site, site.upper()) for site in DATADOG_SITES])},
    order=30,
    is_new=True,
)

DEFAULT_TOOL = "search_datadog_logs"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    site = str(config.get("datadog_site") or "us1").lower()
    url = DATADOG_SITES.get(site, URL)
    api_key = (
        config.get("dd_api_key")
        or config.get("DD_API_KEY")
        or os.environ.get("DD_API_KEY", "")
    )
    application_key = (
        config.get("dd_application_key")
        or config.get("DD_APPLICATION_KEY")
        or os.environ.get("DD_APPLICATION_KEY", "")
    )
    headers = {"DD-API-KEY": api_key, "DD-APPLICATION-KEY": application_key}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"query": input_text.strip() or "*"}
    return url, headers, tool_name, call_args


run = remote_server("MCP Datadog", DEFAULT_TOOL, prepare, TOOL.required)
