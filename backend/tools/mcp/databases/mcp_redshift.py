"""MCP Redshift — built-in MCP server `mcp_redshift` (awslabs.redshift-mcp-server, by AWS Labs;
version pinned).

Discovers Redshift clusters and serverless workgroups, lists databases, schemas, tables and
columns, executes SQL and runs a diagnostic cluster review. Credentials and the region come from
the standard AWS environment variables. Read-only unless the access mode is switched.
"""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_redshift",
    name="MCP Redshift",
    type="mcp",
    icon="🔴",
    group="mcp_servers",
    category="Databases & Data",
    description="Explore Redshift clusters and serverless workgroups, run SQL and review cluster health.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["--from", "awslabs.redshift-mcp-server@0.1.2", "awslabs.redshift-mcp-server"],
        "aws_region": "",
        "aws_profile": "",
        "aws_access_key_id": "",
        "aws_secret_access_key": "",
        "aws_session_token": "",
        "access_mode": "read-only",
    },
    required=("aws_region",),
    selects={"access_mode": Select("Access", [("read-only", "Read-only"), ("read-write", "Read and write")])},
    order=430,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["--from", "awslabs.redshift-mcp-server@0.1.2", "awslabs.redshift-mcp-server"]
DEFAULT_TOOL = "list_clusters"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    for key in ("aws_region", "aws_profile", "aws_access_key_id", "aws_secret_access_key", "aws_session_token"):
        value = config_value(config, key)
        if value:
            env_vars[key.upper()] = value
    env_vars["ACCESS_MODE"] = config_value(config, "access_mode", "read-only")
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
