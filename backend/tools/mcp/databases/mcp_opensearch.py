"""MCP OpenSearch — built-in MCP server `mcp_opensearch` (opensearch-mcp-server-py, by the OpenSearch
project; version pinned).

Indices, mappings, search, cluster health, shard allocation and more for OpenSearch clusters. The URL
and basic-auth credentials go in ``OPENSEARCH_URL`` / ``OPENSEARCH_USERNAME`` / ``OPENSEARCH_PASSWORD``
(AWS-managed domains also read the standard AWS env vars). Write tools are off unless ``allow_write`` is
on (``OPENSEARCH_SETTINGS_ALLOW_WRITE``, which upstream defaults to true). The input lists the indices
matching a name or pattern.
"""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_opensearch",
    name="MCP OpenSearch",
    type="mcp",
    icon="🔍",
    group="mcp_servers",
    category="Databases & Data",
    description="OpenSearch clusters: list indices, mappings, search, cluster health and shard allocation; read-only unless writes are on.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["opensearch-mcp-server-py@0.12.0"],
        "opensearch_url": "",
        "opensearch_username": "",
        "opensearch_password": "",
        "ssl_verify": "on",
        "allow_write": "off",
        "aws_region": "",
    },
    required=("opensearch_url",),
    selects={"allow_write": Select("Write tools", (("off", "Off — read-only"), ("on", "On — index and settings changes"))),
             "ssl_verify": Select("Verify TLS", (("on", "On"), ("off", "Off (self-signed, dev only)")))},
    order=466,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["opensearch-mcp-server-py@0.12.0"]
DEFAULT_TOOL = "ListIndexTool"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    for key in ("opensearch_url", "opensearch_username", "opensearch_password", "aws_region"):
        value = config_value(config, key)
        if value:
            env_vars[key.upper()] = value
    if "OPENSEARCH_USERNAME" not in env_vars and "AWS_REGION" not in env_vars:
        env_vars["OPENSEARCH_NO_AUTH"] = "true"   # else it falls back to the AWS credential chain
    env_vars["OPENSEARCH_SETTINGS_ALLOW_WRITE"] = "true" if str(config.get("allow_write", "off")).lower() in ("on", "true", "yes", "1") else "false"
    if str(config.get("ssl_verify", "on")).lower() in ("off", "false", "no", "0"):
        env_vars["OPENSEARCH_SSL_VERIFY"] = "false"
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or ({"index": input_text.strip()} if input_text.strip() and tool_name == DEFAULT_TOOL else {})
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
