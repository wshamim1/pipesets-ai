"""MCP Elastic Agent Builder — built-in MCP server `mcp_elastic_agent_builder`: the MCP endpoint built
into Kibana (Elastic 9.2+ and Elasticsearch Serverless), reached over HTTP at
``<kibana_url>[/s/<space>]/api/agent_builder/mcp``. It replaces Elastic's deprecated stand-alone
Elasticsearch MCP server.

It serves Agent Builder's tools — ``platform.core.*`` (list indices, index mappings, search, ES|QL),
plus the observability and security tools the deployment enables — so run "Discover tools" on the node
to see them. Auth is an Elasticsearch API key sent as ``Authorization: ApiKey <key>``; the key needs the
Agent Builder read privilege for the space and decides which indices the tools can read. The default
tool lists indices.
"""

import os
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._http import remote_server

TOOL = ToolSpec(
    id="mcp_elastic_agent_builder",
    name="MCP Elastic Agent Builder",
    type="mcp",
    icon="🔎",
    group="mcp_servers",
    category="Databases & Data",
    description="Elastic's own MCP endpoint in Kibana (9.2+ / Serverless): index search, mappings and ES|QL, plus Elastic observability and security tools.",
    default_config={
        "transport": "http",
        "kibana_url": "",
        "space": "",
        "elastic_api_key": "",
    },
    required=("kibana_url", "elastic_api_key"),
    order=465,
    is_new=True,
)

DEFAULT_TOOL = "platform.core.list_indices"


def endpoint(config: Dict[str, Any]) -> str:
    base = str(config.get("kibana_url") or os.environ.get("KIBANA_URL", "")).strip().rstrip("/")
    space = str(config.get("space") or "").strip().strip("/")
    return f"{base}/s/{space}/api/agent_builder/mcp" if space and space != "default" else f"{base}/api/agent_builder/mcp"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    key = str(config.get("elastic_api_key") or os.environ.get("ELASTIC_API_KEY", "")).strip()
    headers = {"Authorization": f"ApiKey {key}"}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {}
    return endpoint(config), headers, tool_name, call_args


run = remote_server("MCP Elastic Agent Builder", DEFAULT_TOOL, prepare, TOOL.required)
