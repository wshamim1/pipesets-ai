"""MCP PostHog — built-in MCP server `mcp_posthog`: PostHog's managed remote server, reached over
Streamable HTTP. Authentication uses a personal API key in the ``Authorization`` header.

PostHog's server defaults to a single ``exec`` tool. The URL pins ``mode=tools`` so each PostHog
tool is exposed separately, and ``features`` keeps the default roster to analytics, SQL,
dashboards, flags and error tracking.
"""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._http import remote_server
from tools.mcp._stdio import config_value

FEATURES = "sql,dashboards,insights,flags,error_tracking"
POSTHOG_URLS = {
    "us": f"https://mcp.posthog.com/mcp?mode=tools&features={FEATURES}",
    "eu": f"https://mcp-eu.posthog.com/mcp?mode=tools&features={FEATURES}",
}
URL = POSTHOG_URLS["us"]

TOOL = ToolSpec(
    id="mcp_posthog",
    name="MCP PostHog",
    type="mcp",
    icon="🦔",
    group="mcp_servers",
    category="DevOps & Observability",
    description="Query PostHog analytics with SQL, and inspect dashboards, insights, feature flags and errors.",
    default_config={
        "transport": "http",
        "url": URL,
        "posthog_region": "us",
        "posthog_api_key": "",
    },
    required=("posthog_api_key",),
    selects={"posthog_region": Select("Region", [(region, region.upper()) for region in POSTHOG_URLS])},
    order=40,
    is_new=True,
)

DEFAULT_TOOL = "execute-sql"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    region = str(config.get("posthog_region") or "us").lower()
    url = POSTHOG_URLS.get(region, URL)
    token = config_value(config, "posthog_api_key")
    headers = {"Authorization": f"Bearer {token}"}
    query = input_text.strip()
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or ({"query": query} if query else {})
    return url, headers, tool_name, call_args


run = remote_server("MCP PostHog", DEFAULT_TOOL, prepare, TOOL.required)
