"""MCP Chroma — built-in MCP server `mcp_chroma` (chroma-mcp, by Chroma; version pinned)."""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_chroma",
    name="MCP Chroma",
    type="mcp",
    icon="🎨",
    group="mcp_servers",
    category="Databases & Data",
    description="Chroma collections and documents: create, add, query and inspect (self-hosted, Chroma Cloud or a local folder).",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["chroma-mcp@0.2.6"],
        "client_type": "http",
        "chroma_host": "localhost",
        "chroma_port": "8000",
        "chroma_data_dir": "",
        "chroma_tenant": "",
        "chroma_database": "",
        "chroma_api_key": "",
    },
    selects={"client_type": Select("Chroma server", [("http", "Self-hosted (host and port)"), ("cloud", "Chroma Cloud (tenant, database, API key)"), ("persistent", "Local folder (data dir)")])},
    order=320,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["chroma-mcp@0.2.6"]
DEFAULT_TOOL = "chroma_list_collections"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    client = str(config.get("client_type") or "http")
    env_vars["CHROMA_CLIENT_TYPE"] = client
    keys = {"http": ("chroma_host", "chroma_port"), "cloud": ("chroma_tenant", "chroma_database", "chroma_api_key"),
            "persistent": ("chroma_data_dir",)}.get(client, ())
    for key in keys:
        value = config_value(config, key)
        if value:
            env_vars[key.upper()] = value
    call_args = config.get("arguments") or {}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
