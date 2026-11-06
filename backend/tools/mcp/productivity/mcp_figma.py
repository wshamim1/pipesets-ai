"""MCP Figma — built-in MCP server `mcp_figma` (figma-developer-mcp, by Framelink; version pinned).

The API key goes in ``FIGMA_API_KEY``. The node input may be a Figma file/design URL (the file key
and node id are extracted from it) or a bare file key.
"""

import re
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_figma",
    name="MCP Figma",
    type="mcp",
    icon="🎨",
    group="mcp_servers",
    category="Productivity",
    description="Read Figma files and nodes (layout, styles, text) and download images from a design.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "figma-developer-mcp@0.13.2", "--stdio"],
        "figma_api_key": "",
        "figma_file_key": "",
        "figma_node_id": "",
        "figma_depth": "",
    },
    required=("figma_api_key",),
    order=420,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "figma-developer-mcp@0.13.2", "--stdio"]
DEFAULT_TOOL = "get_figma_data"

FILE_KEY = re.compile(r"figma\.com/(?:file|design)/([A-Za-z0-9]+)")


def _figma_reference(text: str):
    """(file key, node id) from a Figma URL or a bare file key."""
    text = text.strip()
    match = FILE_KEY.search(text)
    if not match:
        return text, ""
    node_id = (parse_qs(urlparse(text).query).get("node-id") or [""])[0].replace("-", ":")
    return match.group(1), node_id


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["FIGMA_API_KEY"] = config_value(config, "figma_api_key")
    file_key, node_id = _figma_reference(input_text)
    file_key = file_key or config_value(config, "figma_file_key")
    node_id = node_id or config_value(config, "figma_node_id")
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments")
    if call_args is None:
        call_args = {"fileKey": file_key}
        if node_id:
            call_args["nodeId"] = node_id
        depth = config_value(config, "figma_depth")
        if depth:
            try:
                call_args["depth"] = int(depth)
            except ValueError:
                pass
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
