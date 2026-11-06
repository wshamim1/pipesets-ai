"""MCP Kafka — built-in MCP server `mcp_kafka`."""

import os
from typing import Any, Dict

from tools.base import ToolSpec
from tools.mcp._stdio import stdio_server

TOOL = ToolSpec(
    id="mcp_kafka",
    name="MCP Kafka",
    type="mcp",
    icon="🪄",
    group="mcp_servers",
    category="Databases & Data",
    description="Produce/consume messages, list topics, and manage consumer groups on any Kafka cluster via the Confluent MCP server.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@confluentinc/mcp-confluent@1.6.1"],
        "env_vars": {"CONFLUENT_CLOUD_API_KEY": "", "CONFLUENT_CLOUD_API_SECRET": "", "BOOTSTRAP_SERVERS": "localhost:9092"},
    },
    order=270,
)

COMMAND = "npx"
ARGS = ["-y", "@confluentinc/mcp-confluent@1.6.1"]
DEFAULT_TOOL = "list-topics"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    api_key = (
        config.get("confluent_cloud_api_key")
        or config.get("CONFLUENT_CLOUD_API_KEY")
        or os.environ.get("CONFLUENT_CLOUD_API_KEY", "")
    )
    api_secret = (
        config.get("confluent_cloud_api_secret")
        or config.get("CONFLUENT_CLOUD_API_SECRET")
        or os.environ.get("CONFLUENT_CLOUD_API_SECRET", "")
    )
    bootstrap = (
        config.get("kafka_bootstrap_servers")
        or config.get("KAFKA_BOOTSTRAP_SERVERS")
        or os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    )
    if api_key:
        env_vars["CONFLUENT_CLOUD_API_KEY"] = api_key
    if api_secret:
        env_vars["CONFLUENT_CLOUD_API_SECRET"] = api_secret
    env_vars["BOOTSTRAP_SERVERS"] = bootstrap   # the name mcp-confluent reads
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"query": input_text.strip()}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
