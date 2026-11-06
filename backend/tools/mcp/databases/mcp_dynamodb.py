"""MCP DynamoDB — built-in MCP server `mcp_dynamodb` (awslabs.dynamodb-mcp-server, by AWS Labs;
version pinned).

The official AWS Labs server focuses on DynamoDB data modeling: it gathers requirements, designs
tables and access patterns, validates them against DynamoDB Local and generates CDK / access-layer
code. Credentials and the region are read from the standard AWS environment variables.
"""

from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_dynamodb",
    name="MCP DynamoDB",
    type="mcp",
    icon="🧩",
    group="mcp_servers",
    category="Databases & Data",
    description="Design DynamoDB data models, validate access patterns and generate CDK/access-layer code.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["--from", "awslabs.dynamodb-mcp-server@2.1.9", "awslabs.dynamodb-mcp-server"],
        "aws_region": "",
        "aws_profile": "",
        "aws_access_key_id": "",
        "aws_secret_access_key": "",
        "aws_session_token": "",
    },
    required=("aws_region",),
    order=420,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["--from", "awslabs.dynamodb-mcp-server@2.1.9", "awslabs.dynamodb-mcp-server"]
DEFAULT_TOOL = "dynamodb_data_modeling"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    for key in ("aws_region", "aws_profile", "aws_access_key_id", "aws_secret_access_key", "aws_session_token"):
        value = config_value(config, key)
        if value:
            env_vars[key.upper()] = value
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
