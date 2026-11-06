"""MCP Google Drive — built-in MCP server `mcp_gdrive`.

The reference server is deprecated upstream and pinned to its last release (no maintained replacement yet)."""

import os
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_gdrive",
    name="MCP Google Drive",
    type="mcp",
    icon="📂",
    group="mcp_servers",
    category="Productivity",
    description="List, read, and search Google Drive files. Requires OAuth credentials JSON.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-gdrive@2025.1.14"],
        "env_vars": {"GDRIVE_CREDENTIALS_FILE": ""},
    },
    order=190,
)

COMMAND = "npx"
ARGS = ["-y", "@modelcontextprotocol/server-gdrive@2025.1.14"]
DEFAULT_TOOL = "search"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    creds_file = (
        config.get("gdrive_credentials_file")
        or config.get("GDRIVE_CREDENTIALS_FILE")
        or os.environ.get("GDRIVE_CREDENTIALS_FILE", "")
    )
    if creds_file:
        env_vars["GDRIVE_CREDENTIALS_FILE"] = creds_file
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"query": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
