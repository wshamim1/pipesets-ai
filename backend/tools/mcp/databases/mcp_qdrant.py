"""MCP Qdrant — built-in MCP server `mcp_qdrant` (mcp-server-qdrant, by Qdrant; version pinned)."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_qdrant",
    name="MCP Qdrant",
    type="mcp",
    icon="🟥",
    group="mcp_servers",
    category="Databases & Data",
    description="Store and semantically search memories in a Qdrant collection.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-qdrant@0.8.1"],
        "qdrant_url": "http://localhost:6333",
        "collection_name": "",
        "qdrant_api_key": "",
    },
    required=("qdrant_url",),
    order=310,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["mcp-server-qdrant@0.8.1"]
DEFAULT_TOOL = "qdrant-find"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["QDRANT_URL"] = config_value(config, "qdrant_url")
    for key, env in (("qdrant_api_key", "QDRANT_API_KEY"), ("collection_name", "COLLECTION_NAME")):
        value = config_value(config, key)
        if value:
            env_vars[env] = value
    call_args = config.get("arguments") or {"query": input_text.strip()}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
