"""MCP GitHub — built-in MCP server `mcp_github`: GitHub's own remote server (api.githubcopilot.com/mcp),
reached over Streamable HTTP with a personal access token. Replaces the deprecated
`@modelcontextprotocol/server-github`; the tool names it shared (search_repositories,
get_file_contents, list_issues, …) are the same. Read-only sends ``X-MCP-Readonly``."""

import os
from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._http import remote_server

URL = "https://api.githubcopilot.com/mcp/"

TOOL = ToolSpec(
    id="mcp_github",
    name="MCP GitHub",
    type="mcp",
    icon="🐙",
    group="mcp_servers",
    category="Developer Tools",
    description="Repos, files, issues, pull requests and commits through GitHub's own MCP server.",
    default_config={
        "transport": "http",
        "url": URL,
        "github_token": "",
        "read_only": "true",
    },
    required=("github_token",),
    selects={"read_only": Select("Access", [("true", "Read-only"), ("false", "Read and write")],
                                 "Write access also needs a token that is allowed to write")},
    order=20,
)

DEFAULT_TOOL = "search_repositories"


def prepare(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any]):
    """Node config → (url, headers, tool name, call arguments)."""
    token = (
        config.get("github_token")
        or config.get("GITHUB_PERSONAL_ACCESS_TOKEN")
        or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "")
        or os.environ.get("GITHUB_TOKEN", "")
    )
    headers = {"Authorization": f"Bearer {token}"}
    # Nodes saved before the read-only setting existed keep their write access
    if str(config.get("read_only", "false")).lower() == "true":
        headers["X-MCP-Readonly"] = "true"
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"query": input_text.strip()}
    return URL, headers, tool_name, call_args


run = remote_server("MCP GitHub", DEFAULT_TOOL, prepare, TOOL.required)
