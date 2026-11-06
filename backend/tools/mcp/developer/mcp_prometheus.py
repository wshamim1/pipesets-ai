"""MCP Prometheus — built-in MCP server `mcp_prometheus` (prometheus-mcp-server; version pinned)."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_prometheus",
    name="MCP Prometheus",
    type="mcp",
    icon="🔥",
    group="mcp_servers",
    category="DevOps & Observability",
    description="Run PromQL instant and range queries against Prometheus, and discover metrics and labels.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["prometheus-mcp-server@1.6.2"],
        "prometheus_url": "",
        "prometheus_username": "",
        "prometheus_password": "",
        "prometheus_token": "",
    },
    required=("prometheus_url",),
    order=20,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["prometheus-mcp-server@1.6.2"]
DEFAULT_TOOL = "execute_query"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["PROMETHEUS_URL"] = config_value(config, "prometheus_url")
    for key in ("prometheus_username", "prometheus_password", "prometheus_token"):
        value = config_value(config, key)
        if value:
            env_vars[key.upper()] = value
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"query": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
