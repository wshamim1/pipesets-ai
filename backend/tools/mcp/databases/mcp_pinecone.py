"""MCP Pinecone — built-in MCP server `mcp_pinecone` (@pinecone-database/mcp, by Pinecone; version pinned)."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_pinecone",
    name="MCP Pinecone",
    type="mcp",
    icon="🌲",
    group="mcp_servers",
    category="Databases & Data",
    description="Pinecone indexes: list, describe, upsert, search and rerank records, and search the Pinecone docs.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@pinecone-database/mcp@0.4.0"],
        "pinecone_api_key": "",
    },
    required=("pinecone_api_key",),
    order=340,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@pinecone-database/mcp@0.4.0"]
DEFAULT_TOOL = "list-indexes"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["PINECONE_API_KEY"] = config_value(config, "pinecone_api_key")
    call_args = config.get("arguments") or {}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
