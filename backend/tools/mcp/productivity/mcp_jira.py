"""MCP Jira — built-in MCP server `mcp_jira` (mcp-atlassian; version pinned)."""

import os
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_jira",
    name="MCP Jira",
    type="mcp",
    icon="🎯",
    group="mcp_servers",
    category="Productivity",
    description="Jira issues, sprints, and projects via the Atlassian MCP server.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-atlassian@0.23.1"],
        "env_vars": {"JIRA_URL": "", "JIRA_USERNAME": "", "JIRA_API_TOKEN": ""},
    },
    order=220,
)

COMMAND = "uvx"
ARGS = ["mcp-atlassian@0.23.1"]
DEFAULT_TOOL = "jira_get_issue"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    for k in ("JIRA_URL", "JIRA_USERNAME", "JIRA_API_TOKEN"):
        val = config.get(k.lower()) or config.get(k) or os.environ.get(k, "")
        if val:
            env_vars[k] = val
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"issue_key": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
