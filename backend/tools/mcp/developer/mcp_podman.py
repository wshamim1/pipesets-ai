"""MCP Podman — built-in MCP server `mcp_podman` (mcp-server-docker on the Podman socket; version pinned)."""

import os
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_podman",
    name="MCP Podman",
    type="mcp",
    icon="🦭",
    group="mcp_servers",
    category="Developer Tools",
    description="List, run, stop and inspect containers and images through Podman (the Docker server pointed at the Podman socket).",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-docker@0.3.0"],
        "podman_socket": "",
    },
    order=240,
)

COMMAND = "uvx"
ARGS = ["mcp-server-docker@0.3.0"]
DEFAULT_TOOL = "list_containers"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    # mcp-server-docker works with Podman via DOCKER_HOST pointing at the Podman socket.
    # Resolve socket: explicit config > env > well-known macOS Podman Desktop path.
    import pathlib as _pathlib
    _default_sock = str(
        _pathlib.Path.home() / ".local/share/containers/podman/machine/podman.sock"
    )
    socket_path = (
        config.get("podman_socket")
        or config.get("DOCKER_HOST")
        or os.environ.get("DOCKER_HOST", "")
        or (_default_sock if _pathlib.Path(_default_sock).exists() else "")
    ).strip()
    if socket_path:
        if not socket_path.startswith("unix://"):
            socket_path = f"unix://{socket_path}"
        env_vars["DOCKER_HOST"] = socket_path
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
