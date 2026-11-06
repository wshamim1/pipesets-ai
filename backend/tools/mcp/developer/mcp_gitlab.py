"""MCP GitLab — built-in MCP server `mcp_gitlab` (@zereight/mcp-gitlab; version pinned)."""

import os
from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_gitlab",
    name="MCP GitLab",
    type="mcp",
    icon="🦊",
    group="mcp_servers",
    category="Developer Tools",
    description="GitLab repos, merge requests, issues, and pipelines (gitlab.com or self-hosted).",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@zereight/mcp-gitlab@2.3.19"],
        "env_vars": {"GITLAB_PERSONAL_ACCESS_TOKEN": "", "GITLAB_API_URL": "https://gitlab.com/api/v4"},
        "read_only": "true",
    },
    selects={"read_only": Select("Access", [("true", "Read-only"), ("false", "Read and write")])},
    order=180,
)

COMMAND = "npx"
ARGS = ["-y", "@zereight/mcp-gitlab@2.3.19"]
DEFAULT_TOOL = "list_projects"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    token = (
        config.get("gitlab_token")
        or config.get("GITLAB_PERSONAL_ACCESS_TOKEN")
        or os.environ.get("GITLAB_PERSONAL_ACCESS_TOKEN", "")
    )
    if token:
        env_vars["GITLAB_PERSONAL_ACCESS_TOKEN"] = token
    api_url = config.get("gitlab_api_url") or os.environ.get("GITLAB_API_URL", "https://gitlab.com/api/v4")
    env_vars["GITLAB_API_URL"] = api_url
    if str(config.get("read_only", "")).lower() == "true":
        env_vars["GITLAB_READ_ONLY_MODE"] = "true"
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"search": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
