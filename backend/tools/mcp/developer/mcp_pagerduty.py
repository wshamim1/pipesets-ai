"""MCP PagerDuty — built-in MCP server `mcp_pagerduty` (pagerduty-mcp, by PagerDuty; version pinned).

Incidents, alerts, on-call schedules, services, escalation policies, teams and change events. The
user API key goes in ``PAGERDUTY_USER_API_KEY``; ``api_host`` is for EU accounts
(https://api.eu.pagerduty.com). Read-only unless ``write_tools`` is on, which passes
``--enable-write-tools`` (acknowledge, resolve, create incidents and more). The default tool lists
open incidents. The package needs Python 3.12, which ``uvx --python 3.12`` provides (installing it if needed).
"""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_pagerduty",
    name="MCP PagerDuty",
    type="mcp",
    icon="📟",
    group="mcp_servers",
    category="DevOps & Observability",
    description="PagerDuty incidents, alerts, on-call schedules, services and escalation policies; read-only unless write tools are on.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["--from", "pagerduty-mcp@1.1.0", "--python", "3.12", "pagerduty-mcp"],
        "pagerduty_user_api_key": "",
        "api_host": "",
        "write_tools": "off",
    },
    required=("pagerduty_user_api_key",),
    selects={"write_tools": Select("Write tools", (("off", "Off — read-only"), ("on", "On — acknowledge, resolve, create")))},
    order=470,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["--from", "pagerduty-mcp@1.1.0", "--python", "3.12", "pagerduty-mcp"]
DEFAULT_TOOL = "list_incidents"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars and flags, and the MCP tool to call with its arguments."""
    env_vars["PAGERDUTY_USER_API_KEY"] = config_value(config, "pagerduty_user_api_key")
    host = config_value(config, "api_host")
    if host:
        env_vars["PAGERDUTY_API_HOST"] = host
    if str(config.get("write_tools", "off")).lower() in ("on", "true", "yes", "1"):
        args = [*args, "--enable-write-tools"]
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or (
        {"request_scope": "all", "statuses": ["triggered", "acknowledged"]} if tool_name == DEFAULT_TOOL else {})
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
