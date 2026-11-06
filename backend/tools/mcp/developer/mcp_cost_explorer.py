"""MCP AWS Cost Explorer — built-in MCP server `mcp_cost_explorer` (awslabs.cost-explorer-mcp-server, by
AWS Labs; version pinned).

Read-only AWS spend: cost and usage by service, account, region or tag, period-over-period
comparisons with the drivers of the change, and forecasts. Credentials and the region come from the
standard AWS environment variables (or a profile on the backend machine); the IAM user needs
``ce:Get*``. Each Cost Explorer API request costs $0.01.

The default call reads this month's cost by service (month to date).
"""

from datetime import date, timedelta
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_cost_explorer",
    name="MCP AWS Cost Explorer",
    type="mcp",
    icon="💰",
    group="mcp_servers",
    category="DevOps & Observability",
    description="AWS spend (read-only): cost and usage by service, account or tag, month-over-month drivers, and forecasts. Each request costs $0.01 on AWS.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["--from", "awslabs.cost-explorer-mcp-server@0.0.21", "awslabs.cost-explorer-mcp-server"],
        "aws_region": "us-east-1",
        "aws_profile": "",
        "aws_access_key_id": "",
        "aws_secret_access_key": "",
        "aws_session_token": "",
    },
    required=("aws_region",),
    order=485,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["--from", "awslabs.cost-explorer-mcp-server@0.0.21", "awslabs.cost-explorer-mcp-server"]
DEFAULT_TOOL = "get_cost_and_usage"


def month_to_date(today: date) -> Dict[str, str]:
    """This month so far; on the 1st, last month (Cost Explorer's end date is exclusive)."""
    start = (today - timedelta(days=1)).replace(day=1)
    return {"start_date": start.isoformat(), "end_date": today.isoformat()}


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    for key in ("aws_region", "aws_profile", "aws_access_key_id", "aws_secret_access_key", "aws_session_token"):
        value = config_value(config, key)
        if value:
            env_vars[key.upper()] = value
    env_vars["FASTMCP_LOG_LEVEL"] = "ERROR"
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or ({"date_range": month_to_date(date.today()), "granularity": "MONTHLY",
                                              "group_by": "SERVICE"} if tool_name == DEFAULT_TOOL else {})
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
