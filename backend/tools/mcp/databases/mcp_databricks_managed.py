"""MCP Databricks Managed — built-in MCP server `mcp_databricks_managed`: the managed MCP servers a
Databricks workspace hosts itself, reached over Streamable HTTP at ``<host>/api/2.0/mcp/...``.
Authentication is a personal access token (or service principal token) as a bearer token.

The server dropdown picks which one: Databricks SQL, a Genie space, the Unity Catalog functions in
a schema, or the Vector Search indexes in a schema. Their tool names come from the workspace (a
function's name, a Genie space ID…), so there is no fixed default tool — list the server's tools
and pick one.
"""

from typing import Any, Dict
from urllib.parse import quote

from tools.base import Select, ToolSpec
from tools.mcp._http import remote_server
from tools.mcp._stdio import config_value, missing_key

LABEL = "MCP Databricks Managed"
SERVERS = {"sql": "Databricks SQL", "genie": "Genie space", "functions": "Unity Catalog functions",
           "vector-search": "Vector Search"}

TOOL = ToolSpec(
    id="mcp_databricks_managed",
    name=LABEL,
    type="mcp",
    icon="🧱",
    group="mcp_servers",
    category="Databases & Data",
    description="Databricks' own managed MCP servers: Databricks SQL, Genie spaces, Unity Catalog functions and Vector Search.",
    default_config={
        "transport": "http",
        "databricks_host": "",
        "databricks_token": "",
        "server": "sql",
        "catalog": "",
        "schema": "",
        "genie_space_id": "",
    },
    required=("databricks_host", "databricks_token"),
    selects={"server": Select("Server", list(SERVERS.items()))},
    order=426,
    is_new=True,
)


def server_url(config: Dict[str, Any]) -> str:
    """The managed server's endpoint, or "" when a value its path needs is missing."""
    host = config_value(config, "databricks_host").rstrip("/")
    if host and not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    server = str(config.get("server") or "sql").lower()
    if server == "genie":
        space = str(config.get("genie_space_id") or "").strip()
        return f"{host}/api/2.0/mcp/genie/{quote(space, safe='')}" if space else ""
    if server in ("functions", "vector-search"):
        catalog, schema = (str(config.get(k) or "").strip() for k in ("catalog", "schema"))
        return f"{host}/api/2.0/mcp/{server}/{quote(catalog, safe='')}/{quote(schema, safe='')}" \
            if catalog and schema else ""
    return f"{host}/api/2.0/mcp/sql"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    headers = {"Authorization": f"Bearer {config_value(config, 'databricks_token')}"}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    query = input_text.strip()
    call_args = config.get("arguments") or ({"query": query} if query else {})
    return server_url(config), headers, tool_name, call_args


_remote = remote_server(LABEL, "", prepare, TOOL.required)


def _needs(config: Dict[str, Any]) -> str:
    server = str(config.get("server") or "sql").lower()
    if server == "genie":
        return "genie_space_id"
    return "catalog and schema" if server in ("functions", "vector-search") else ""


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> str:
    missing = missing_key(cfg, TOOL.required)
    if missing:
        return f"[{LABEL}] Set {missing} in the node's Parameters & Auth first."
    if not server_url(cfg) and _needs(cfg):
        return f"[{LABEL}] Set {_needs(cfg)} for the {cfg.get('server')} server first."
    if not cfg.get("tool_name"):
        return f"[{LABEL}] Pick a tool first — list this server's tools to see what the workspace exposes."
    return await _remote(inp, cfg, tool_type)


async def discover(cfg: Dict[str, Any], tool_type: str = ""):
    if not server_url(cfg) and _needs(cfg):
        raise RuntimeError(f"[{LABEL}] Set {_needs(cfg)} to list this server's tools.")
    return await _remote.discover(cfg, tool_type)


run.discover = discover
