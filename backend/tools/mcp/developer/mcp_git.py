"""MCP Git — built-in MCP server `mcp_git`."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_git",
    name="MCP Git",
    type="mcp",
    icon="🌿",
    group="mcp_servers",
    category="Developer Tools",
    description="Local Git repo operations — commits, diffs, branches, blame, log. No GitHub account needed.",
    default_config={"transport": "stdio", "command": "uvx", "args": ["mcp-server-git@2026.10.28", "--repository", "."]},
    order=110,
)

COMMAND = "uvx"
ARGS = ["mcp-server-git@2026.10.28", "--repository", "."]
DEFAULT_TOOL = "git_log"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    repo = (config.get("repo_path") or config.get("repository") or ".").strip()
    # replace the placeholder "." arg with the configured repo path
    args = [a if a != "." else repo for a in args]
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"repo_path": repo, "query": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
