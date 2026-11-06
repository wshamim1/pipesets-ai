"""MCP Confluence — built-in MCP server `mcp_confluence` (mcp-atlassian; version pinned)."""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_confluence",
    name="MCP Confluence",
    type="mcp",
    icon="📘",
    group="mcp_servers",
    category="Productivity",
    description="Search, read and (if allowed) edit Confluence pages. Read-only unless you turn it off.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-atlassian@0.23.1"],
        "confluence_url": "",
        "confluence_username": "",
        "confluence_api_token": "",
        "read_only": "true",
    },
    required=("confluence_url", "confluence_api_token"),
    selects={"read_only": Select("Access", [("true", "Read-only"), ("false", "Read and write")])},
    order=320,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["mcp-atlassian@0.23.1"]
DEFAULT_TOOL = "confluence_search"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    for key in ("confluence_url", "confluence_username", "confluence_api_token"):
        value = config_value(config, key)
        if value:
            env_vars[key.upper()] = value
    env_vars["READ_ONLY_MODE"] = "false" if str(config.get("read_only", "true")).lower() == "false" else "true"
    call_args = config.get("arguments") or {"query": input_text.strip()}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
