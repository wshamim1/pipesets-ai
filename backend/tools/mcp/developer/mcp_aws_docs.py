"""MCP AWS Documentation — built-in MCP server `mcp_aws_docs` (awslabs.aws-documentation-mcp-server, by AWS; version pinned)."""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_aws_docs",
    name="MCP AWS Documentation",
    type="mcp",
    icon="📙",
    group="mcp_servers",
    category="Developer Tools",
    description="Search and read the AWS documentation. No AWS account needed.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["awslabs.aws-documentation-mcp-server@1.2.4"],
    },
    order=300,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["awslabs.aws-documentation-mcp-server@1.2.4"]
DEFAULT_TOOL = "search_documentation"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["FASTMCP_LOG_LEVEL"] = "ERROR"
    call_args = config.get("arguments") or {"search_phrase": input_text.strip()}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
