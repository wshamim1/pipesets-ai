"""MCP Kubernetes — built-in MCP server `mcp_kubernetes` (mcp-server-kubernetes).

Pods, deployments, services, namespaces and events through kubectl-style calls via the
mcp-server-kubernetes server. Launched over stdio with npx; an explicit kubeconfig (or context)
can be passed — without one it uses the user's default cluster access.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_kubernetes",
    name="MCP Kubernetes",
    type="mcp",
    icon="☸️",
    group="mcp_servers",
    category="Developer Tools",
    description=("Kubernetes via the mcp-server-kubernetes server — list / describe / create and "
                 "patch namespaces, pods, deployments and services; read events and pod logs."),
    default_config={"transport": "stdio", "command": "npx", "args": ["-y", "mcp-server-kubernetes@4.2.1"],
                    "kubeconfig": ""},
    order=280,
)

COMMAND = "npx"
ARGS = ["-y", "mcp-server-kubernetes@4.2.1"]
DEFAULT_TOOL = "list_namespaces"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    kubeconfig = (config.get("kubeconfig") or "").strip()
    if kubeconfig:
        env_vars["KUBECONFIG"] = kubeconfig
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
