"""MCP Contentful — built-in MCP server `mcp_contentful` (@contentful/mcp-server, by Contentful;
version pinned).

Entries, assets, content types, locales, tags, releases, taxonomy and AI actions in a Contentful
space: search and read, and create, update, publish and delete (the server has no read-only mode).
The management token goes in ``CONTENTFUL_MANAGEMENT_ACCESS_TOKEN`` with ``SPACE_ID`` /
``ENVIRONMENT_ID`` / ``CONTENTFUL_HOST``, never on the command line.

The input searches entries by full text; no input lists the content types.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_contentful",
    name="MCP Contentful",
    type="mcp",
    icon="🧩",
    group="mcp_servers",
    category="Productivity",
    description="Contentful CMS: search and read entries, assets and content types, and create, update or publish content (no read-only mode).",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@contentful/mcp-server@1.24.4"],
        "contentful_management_access_token": "",
        "space_id": "",
        "environment_id": "master",
        "contentful_host": "api.contentful.com",
    },
    required=("contentful_management_access_token", "space_id"),
    order=465,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@contentful/mcp-server@1.24.4"]
DEFAULT_TOOL = "list_content_types"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    space = config_value(config, "space_id")
    environment = config_value(config, "environment_id", "master") or "master"
    env_vars["CONTENTFUL_MANAGEMENT_ACCESS_TOKEN"] = config_value(config, "contentful_management_access_token")
    env_vars["SPACE_ID"] = space
    env_vars["ENVIRONMENT_ID"] = environment
    env_vars["CONTENTFUL_HOST"] = config_value(config, "contentful_host", "api.contentful.com") or "api.contentful.com"
    if config.get("tool_name"):
        return args, config["tool_name"], config.get("arguments") or {}
    where = {"spaceId": space, "environmentId": environment}
    if input_text.strip():
        return args, "search_entries", {**where, "query": {"query": input_text.strip(), "limit": 10}}
    return args, defaults["default_tool"], where


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
