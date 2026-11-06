"""MCP Snowflake Managed — built-in MCP server `mcp_snowflake_managed`: a Snowflake-managed MCP server
(a ``CREATE MCP SERVER`` object in the account), reached over Streamable HTTP at
``<account URL>/api/v2/databases/<db>/schemas/<schema>/mcp-servers/<name>``. Authentication is a
programmatic access token (or OAuth token) as a bearer token.

The server's tools are whatever its specification lists (Cortex Search, Cortex Analyst, SQL, custom
tools), so there is no fixed default tool — list the server's tools and pick one.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.data._snowflake import account_url, name_parts, url_part
from tools.mcp._http import remote_server
from tools.mcp._stdio import config_value, missing_key

LABEL = "MCP Snowflake Managed"

TOOL = ToolSpec(
    id="mcp_snowflake_managed",
    name=LABEL,
    type="mcp",
    icon="❄️",
    group="mcp_servers",
    category="Databases & Data",
    description="A Snowflake-managed MCP server in your account, exposing its Cortex Search, Cortex Analyst and SQL tools.",
    default_config={
        "transport": "http",
        "snowflake_account": "",
        "snowflake_token": "",
        "mcp_server": "",
    },
    required=("snowflake_account", "snowflake_token", "mcp_server"),
    order=386,
    is_new=True,
)


def server_url(config: Dict[str, Any]) -> str:
    """The server's endpoint, or "" when ``mcp_server`` isn't db.schema.name."""
    parts = name_parts(str(config.get("mcp_server") or ""), 3)
    base = account_url({"account": config_value(config, "snowflake_account")})
    if not parts or not base:
        return ""
    db, schema, name = (url_part(p) for p in parts)
    return f"{base}/api/v2/databases/{db}/schemas/{schema}/mcp-servers/{name}"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    headers = {"Authorization": f"Bearer {config_value(config, 'snowflake_token')}"}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    query = input_text.strip()
    call_args = config.get("arguments") or ({"query": query} if query else {})
    return server_url(config), headers, tool_name, call_args


_remote = remote_server(LABEL, "", prepare, TOOL.required)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> str:
    missing = missing_key(cfg, TOOL.required)
    if missing:
        return f"[{LABEL}] Set {missing} in the node's Parameters & Auth first."
    if not server_url(cfg):
        return f"[{LABEL}] mcp_server must be db.schema.server_name."
    if not cfg.get("tool_name"):
        return f"[{LABEL}] Pick a tool first — list this server's tools to see what it exposes."
    return await _remote(inp, cfg, tool_type)


async def discover(cfg: Dict[str, Any], tool_type: str = ""):
    if not server_url(cfg) and not missing_key(cfg, TOOL.required):
        raise RuntimeError(f"[{LABEL}] mcp_server must be db.schema.server_name to list its tools.")
    return await _remote.discover(cfg, tool_type)


run.discover = discover
