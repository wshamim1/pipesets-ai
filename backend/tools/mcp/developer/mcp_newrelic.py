"""MCP New Relic — built-in MCP server `mcp_newrelic`: New Relic's managed remote server, reached
over Streamable HTTP. Authentication uses a user API key in the ``api-key`` header (not
``Authorization``); the region dropdown picks the US, EU or JP endpoint. OAuth-only tools such as
``natural_language_to_nrql_query`` are not available with an API key.
"""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._http import remote_server
from tools.mcp._stdio import config_value

NEW_RELIC_URLS = {
    "us": "https://mcp.newrelic.com/mcp/",
    "eu": "https://mcp.eu.newrelic.com/mcp/",
    "jp": "https://mcp.jp.newrelic.com/mcp/",
}
URL = NEW_RELIC_URLS["us"]

TOOL = ToolSpec(
    id="mcp_newrelic",
    name="MCP New Relic",
    type="mcp",
    icon="🟢",
    group="mcp_servers",
    category="DevOps & Observability",
    description="Run NRQL queries and inspect New Relic entities, alerts, logs, traces and dashboards.",
    default_config={
        "transport": "http",
        "url": URL,
        "newrelic_region": "us",
        "newrelic_api_key": "",
        "newrelic_account_id": "",
    },
    required=("newrelic_api_key",),
    selects={"newrelic_region": Select("Region", [(region, region.upper()) for region in NEW_RELIC_URLS])},
    order=40,
    is_new=True,
)

DEFAULT_TOOL = "list_available_new_relic_accounts"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    region = str(config.get("newrelic_region") or "us").lower()
    url = NEW_RELIC_URLS.get(region, URL)
    api_key = config_value(config, "newrelic_api_key")
    headers = {"api-key": api_key}
    query = input_text.strip()
    account_id = config_value(config, "newrelic_account_id")
    tool_name = config.get("tool_name")
    if tool_name:
        call_args = config.get("arguments") or {}
    elif query and account_id:
        tool_name = "execute_nrql_query"
        call_args = {"account_id": account_id, "nrql": query}
    else:
        tool_name = defaults["default_tool"]
        call_args = config.get("arguments") or {}
    return url, headers, tool_name, call_args


run = remote_server("MCP New Relic", DEFAULT_TOOL, prepare, TOOL.required)
