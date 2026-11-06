"""MCP BigQuery — built-in MCP server `mcp_bigquery` (@ergut/mcp-bigquery-server; version pinned).

Authentication uses Google Application Default Credentials, or a service-account key file passed
through ``GOOGLE_APPLICATION_CREDENTIALS`` rather than on the command line.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_bigquery",
    name="MCP BigQuery",
    type="mcp",
    icon="🔷",
    group="mcp_servers",
    category="Databases & Data",
    description="Run read-only SQL against Google BigQuery datasets, with schema and table discovery.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@ergut/mcp-bigquery-server@1.0.4"],
        "bigquery_project_id": "",
        "bigquery_location": "US",
        "bigquery_key_file": "",
    },
    required=("bigquery_project_id",),
    order=390,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@ergut/mcp-bigquery-server@1.0.4"]
DEFAULT_TOOL = "query"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    args = [*args, "--project-id", config_value(config, "bigquery_project_id")]
    location = config_value(config, "bigquery_location", "US")
    if location:
        args = [*args, "--location", location]
    key_file = config_value(config, "bigquery_key_file")
    if key_file:
        env_vars["GOOGLE_APPLICATION_CREDENTIALS"] = key_file
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"sql": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
