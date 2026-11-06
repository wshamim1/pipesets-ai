"""MCP CloudWatch — built-in MCP server `mcp_cloudwatch` (awslabs.cloudwatch-mcp-server, by AWS Labs;
version pinned).

Read-only CloudWatch: active alarms and alarm history, log groups and Logs Insights queries, metric
data and analysis, PromQL queries. Credentials and the region come from the standard AWS environment
variables (or a profile on the backend machine). The default tool lists the active alarms.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_cloudwatch",
    name="MCP CloudWatch",
    type="mcp",
    icon="☁️",
    group="mcp_servers",
    category="DevOps & Observability",
    description="AWS CloudWatch (read-only): active alarms and history, Logs Insights queries, metric data and analysis.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["--from", "awslabs.cloudwatch-mcp-server@0.3.1", "awslabs.cloudwatch-mcp-server"],
        "aws_region": "",
        "aws_profile": "",
        "aws_access_key_id": "",
        "aws_secret_access_key": "",
        "aws_session_token": "",
    },
    required=("aws_region",),
    order=480,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["--from", "awslabs.cloudwatch-mcp-server@0.3.1", "awslabs.cloudwatch-mcp-server"]
DEFAULT_TOOL = "get_active_alarms"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    for key in ("aws_region", "aws_profile", "aws_access_key_id", "aws_secret_access_key", "aws_session_token"):
        value = config_value(config, key)
        if value:
            env_vars[key.upper()] = value
    env_vars["FASTMCP_LOG_LEVEL"] = "ERROR"
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
