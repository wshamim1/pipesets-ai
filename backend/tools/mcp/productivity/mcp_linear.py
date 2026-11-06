"""MCP Linear — built-in MCP server `mcp_linear`: Linear's own remote server (mcp.linear.app), reached over
Streamable HTTP with a Linear API key in the Authorization header (Linear supports that instead of
the interactive OAuth flow). Replaces the npm `linear-mcp`, an individual's package last updated
in 2025. Read-only uses Linear's ``/mcp/readonly`` endpoint."""

import os
from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._http import remote_server

URL = "https://mcp.linear.app/mcp"

TOOL = ToolSpec(
    id="mcp_linear",
    name="MCP Linear",
    type="mcp",
    icon="📐",
    group="mcp_servers",
    category="Productivity",
    description="Linear issues, projects, cycles and comments through Linear's own MCP server.",
    default_config={
        "transport": "http",
        "url": URL,
        "linear_api_key": "",
        "read_only": "true",
    },
    required=("linear_api_key",),
    selects={"read_only": Select("Access", [("true", "Read-only"), ("false", "Read and write")])},
    order=210,
)

DEFAULT_TOOL = "list_issues"   # from Linear's tool list; pick another with the tool picker


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    token = (
        config.get("linear_api_key")
        or config.get("LINEAR_API_KEY")
        or os.environ.get("LINEAR_API_KEY", "")
    )
    # Nodes saved before the read-only setting existed keep their write access
    url = f"{URL}/readonly" if str(config.get("read_only", "false")).lower() == "true" else URL
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or ({"query": input_text.strip()} if input_text.strip() else {})
    return url, {"Authorization": f"Bearer {token}"}, tool_name, call_args


run = remote_server("MCP Linear", DEFAULT_TOOL, prepare, TOOL.required)
