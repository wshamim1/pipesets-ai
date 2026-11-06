"""MCP Elasticsearch — built-in MCP server `mcp_elasticsearch` (@elastic/mcp-server-elasticsearch,
by Elastic; version pinned). With an index configured the default tool searches it; otherwise it
lists indices.

Hidden since 2026-11-04: Elastic deprecated the npm package (and the server: security fixes only) in
favour of the Agent Builder MCP endpoint in Kibana 9.2+ — see `mcp_elastic_agent_builder`. Pipelines
that use it keep running; it's no longer offered.
"""

import json
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_elasticsearch",
    name="MCP Elasticsearch",
    type="mcp",
    icon="🔎",
    group="mcp_servers",
    category="Databases & Data",
    description="Search Elasticsearch indices with query DSL, list indices and inspect field mappings.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@elastic/mcp-server-elasticsearch@0.3.1"],
        "elasticsearch_url": "",
        "elasticsearch_api_key": "",
        "elasticsearch_username": "",
        "elasticsearch_password": "",
        "index": "",
    },
    required=("elasticsearch_url",),
    hidden=True,
    order=400,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@elastic/mcp-server-elasticsearch@0.3.1"]
DEFAULT_TOOL = "list_indices"


def _query_body(text: str) -> Dict[str, Any]:
    """The input as Elasticsearch query DSL; plain text becomes a query_string search."""
    text = text.strip()
    if not text:
        return {"query": {"match_all": {}}}
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return {"query": {"query_string": {"query": text}}}
    return value if isinstance(value, dict) else {"query": {"query_string": {"query": text}}}


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["ES_URL"] = config_value(config, "elasticsearch_url")
    api_key = config_value(config, "elasticsearch_api_key")
    if api_key:
        env_vars["ES_API_KEY"] = api_key
    username = config_value(config, "elasticsearch_username")
    if username:
        env_vars["ES_USERNAME"] = username
        env_vars["ES_PASSWORD"] = config_value(config, "elasticsearch_password")

    index = config_value(config, "index")
    tool_name = config.get("tool_name") or ("search" if index else defaults["default_tool"])
    call_args = config.get("arguments")
    if call_args is None:
        call_args = {"index": index, "queryBody": _query_body(input_text)} if index else {}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
