"""MCP Docker — built-in MCP server `mcp_docker` (mcp-server-docker; version pinned).

Replaces the npm `docker-mcp`, a little-used package from an individual publisher. MCP Podman
(mcp_podman.py) runs the same server against the Podman socket."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_docker",
    name="MCP Docker",
    type="mcp",
    icon="🐳",
    group="mcp_servers",
    category="Developer Tools",
    description="List, create, run, stop and inspect containers, images, networks and volumes through Docker.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-docker@0.3.0"],
        "docker_host": "",
    },
    order=230,
)

COMMAND = "uvx"
ARGS = ["mcp-server-docker@0.3.0"]
DEFAULT_TOOL = "list_containers"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    host = config_value(config, "docker_host")
    if host:
        env_vars["DOCKER_HOST"] = host
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
