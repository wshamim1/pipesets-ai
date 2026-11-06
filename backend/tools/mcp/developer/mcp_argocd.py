"""MCP Argo CD — built-in MCP server `mcp_argocd` (argocd-mcp, by argoproj-labs; version pinned).

Applications, their sync and health status, resource trees, events and workload logs. The base URL
and API token go in ``ARGOCD_BASE_URL`` / ``ARGOCD_API_TOKEN``, never on the command line.
``read_only`` (on by default) sets ``MCP_READ_ONLY``, which removes the create / update / delete /
sync / resource-action tools. The input searches applications by name.
"""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_argocd",
    name="MCP Argo CD",
    type="mcp",
    icon="🐙",
    group="mcp_servers",
    category="DevOps & Observability",
    description="Argo CD applications: sync and health status, resource trees, events and workload logs; syncs when read-only is off.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "argocd-mcp@0.9.0", "stdio"],
        "argocd_base_url": "",
        "argocd_api_token": "",
        "read_only": "on",
    },
    required=("argocd_base_url", "argocd_api_token"),
    selects={"read_only": Select("Read-only", (("on", "On — no sync or changes"), ("off", "Off — allow sync and changes")))},
    order=460,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "argocd-mcp@0.9.0", "stdio"]
DEFAULT_TOOL = "list_applications"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    env_vars["ARGOCD_BASE_URL"] = config_value(config, "argocd_base_url")
    env_vars["ARGOCD_API_TOKEN"] = config_value(config, "argocd_api_token")
    if str(config.get("read_only", "on")).lower() not in ("off", "false", "no", "0"):
        env_vars["MCP_READ_ONLY"] = "true"
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or ({"search": input_text.strip()} if input_text.strip() and tool_name == DEFAULT_TOOL else {})
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
