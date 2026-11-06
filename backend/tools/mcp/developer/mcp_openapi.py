"""MCP OpenAPI — built-in MCP server `mcp_openapi` (@ivotoby/openapi-mcp-server; version pinned).

The earlier `@modelcontextprotocol/server-openapi` package never existed on npm. In ``dynamic``
mode (the default here) the server offers three tools for any API: list-api-endpoints,
get-api-endpoint-schema and invoke-api-endpoint; ``all`` turns every endpoint into its own tool.
"""

import os
from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_openapi",
    name="MCP OpenAPI",
    type="mcp",
    icon="📡",
    group="mcp_servers",
    category="Developer Tools",
    description="Calls any REST API described by an OpenAPI spec: list its endpoints, read their schema, invoke them.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@ivotoby/openapi-mcp-server@1.16.1"],
        "openapi_spec_url": "",
        "api_base_url": "",
        "api_token": "",
        "tools_mode": "dynamic",
    },
    required=("openapi_spec_url", "api_base_url"),
    selects={"tools_mode": Select("Tools", [("dynamic", "Three generic tools (list, describe, invoke)"),
                                            ("all", "One tool per endpoint")])},
    order=260,
)

COMMAND = "npx"
ARGS = ["-y", "@ivotoby/openapi-mcp-server@1.16.1"]
DEFAULT_TOOL = "list-api-endpoints"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["OPENAPI_SPEC_PATH"] = config_value(config, "openapi_spec_url") or os.environ.get("OPENAPI_SPEC_PATH", "")
    env_vars["API_BASE_URL"] = config_value(config, "api_base_url")
    env_vars["TOOLS_MODE"] = "all" if config.get("tools_mode") == "all" else "dynamic"
    token = config_value(config, "api_token")
    if token:
        env_vars["API_HEADERS"] = f"Authorization:Bearer {token}"
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
