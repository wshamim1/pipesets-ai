"""MCP Sentry — built-in MCP server `mcp_sentry`."""

import os
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_sentry",
    name="MCP Sentry",
    type="mcp",
    icon="🚨",
    group="mcp_servers",
    category="Developer Tools",
    description="Query Sentry for errors, issues, and stack traces by project or organisation.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-sentry@2025.1.14"],
        "env_vars": {"SENTRY_AUTH_TOKEN": ""},
    },
    order=170,
)

COMMAND = "uvx"
ARGS = ["mcp-server-sentry@2025.1.14"]
DEFAULT_TOOL = "get_sentry_issue"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    token = (
        config.get("sentry_auth_token")
        or config.get("SENTRY_AUTH_TOKEN")
        or os.environ.get("SENTRY_AUTH_TOKEN", "")
    )
    if token:
        env_vars["SENTRY_AUTH_TOKEN"] = token
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"issue_id_or_url": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
