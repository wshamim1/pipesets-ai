"""MCP Grafana — built-in MCP server `mcp_grafana` (mcp-grafana, by Grafana Labs; version pinned).

The PyPI wheel bundles Grafana's official Go binary. Credentials go in the environment, and
``--disable-write`` keeps the server read-only by default.
"""

import os
from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_grafana",
    name="MCP Grafana",
    type="mcp",
    icon="📈",
    group="mcp_servers",
    category="DevOps & Observability",
    description="Search Grafana dashboards, run Prometheus/Loki queries and inspect datasources. Read-only by default.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-grafana@2.2.0"],
        "grafana_url": "http://localhost:3000",
        "grafana_token": "",
        "read_only": "true",
    },
    required=("grafana_token",),
    selects={"read_only": Select("Access", [("true", "Read-only"), ("false", "Read and write")])},
    order=10,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["mcp-grafana@2.2.0"]
DEFAULT_TOOL = "search_dashboards"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["GRAFANA_URL"] = config_value(config, "grafana_url", "http://localhost:3000")
    token = (
        config.get("grafana_token")
        or config.get("GRAFANA_SERVICE_ACCOUNT_TOKEN")
        or config.get("GRAFANA_API_KEY")
        or os.environ.get("GRAFANA_SERVICE_ACCOUNT_TOKEN", "")
        or os.environ.get("GRAFANA_API_KEY", "")
    )
    if token:
        env_vars["GRAFANA_SERVICE_ACCOUNT_TOKEN"] = token
    if str(config.get("read_only", "true")).lower() != "false":
        args = [*args, "--disable-write"]
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"query": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
