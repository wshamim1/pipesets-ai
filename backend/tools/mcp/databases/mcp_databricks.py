"""MCP Databricks — built-in MCP server `mcp_databricks` (databricks-mcp-server; version pinned).

The workspace host and token go in the package's ``DATABRICKS_*`` environment variables, never on
the command line. It exposes ~40 tools across clusters, jobs, notebooks, DBFS, repos, libraries,
SQL and Unity Catalog. With input and no tool chosen, the input runs as SQL (``execute_sql``);
without input it lists clusters.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_databricks",
    name="MCP Databricks",
    type="mcp",
    icon="🧱",
    group="mcp_servers",
    category="Databases & Data",
    description="Manage Databricks clusters, jobs, notebooks, DBFS, repos and Unity Catalog, and run SQL on a warehouse.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["--from", "databricks-mcp-server@0.4.4", "databricks-mcp-server"],
        "databricks_host": "",
        "databricks_token": "",
        "databricks_warehouse_id": "",
    },
    required=("databricks_host", "databricks_token"),
    order=425,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["--from", "databricks-mcp-server@0.4.4", "databricks-mcp-server"]
DEFAULT_TOOL = "list_clusters"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    host = config_value(config, "databricks_host").rstrip("/")
    if host and not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    if host:
        env_vars["DATABRICKS_HOST"] = host
    for key in ("databricks_token", "databricks_warehouse_id"):
        value = config_value(config, key)
        if value:
            env_vars[key.upper()] = value
    statement = input_text.strip()
    tool_name = config.get("tool_name") or ("execute_sql" if statement else defaults["default_tool"])
    call_args = config.get("arguments") or ({"statement": statement} if tool_name == "execute_sql" else {})
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
