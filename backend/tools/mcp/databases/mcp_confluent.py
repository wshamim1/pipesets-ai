"""MCP Confluent Cloud — built-in MCP server `mcp_confluent` (@confluentinc/mcp-confluent; version pinned).

Confluent's open-source MCP server, configured for Confluent Cloud: Kafka topics / messages / consumer
groups, Schema Registry, Flink SQL, Connect, environments and clusters. (``mcp_kafka`` is the same package
pointed at a self-managed cluster.) Credentials go in the environment. Read-only by default: every tool
that creates, changes or deletes something is blocked with ``--block-tools``.

Needs Node.js 22.23.4+; each block of settings enables the tools that depend on it, so fill in only what you use.
"""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_confluent",
    name="MCP Confluent Cloud",
    type="mcp",
    icon="☁️",
    group="mcp_servers",
    category="Databases & Data",
    description="Work with Confluent Cloud: topics, messages and consumer lag, Schema Registry, Flink SQL, connectors, environments and clusters. Read-only by default. Needs Node.js 22.23.4+.",
    default_config={
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@confluentinc/mcp-confluent@1.6.1"],
        "confluent_cloud_api_key": "",
        "confluent_cloud_api_secret": "",
        "kafka_bootstrap_servers": "",
        "kafka_api_key": "",
        "kafka_api_secret": "",
        "kafka_rest_endpoint": "",
        "kafka_cluster_id": "",
        "kafka_env_id": "",
        "schema_registry_endpoint": "",
        "schema_registry_api_key": "",
        "schema_registry_api_secret": "",
        "read_only": "true",
    },
    selects={"read_only": Select("Access", [("true", "Read-only"), ("false", "Read and write")])},
    order=271,
    is_new=True,
)

COMMAND = "npx"
ARGS = ["-y", "@confluentinc/mcp-confluent@1.6.1"]
DEFAULT_TOOL = "list-topics"

# Settings → the environment variable mcp-confluent reads. All optional: a missing block just leaves its tools off.
ENV = {
    "confluent_cloud_api_key": "CONFLUENT_CLOUD_API_KEY",
    "confluent_cloud_api_secret": "CONFLUENT_CLOUD_API_SECRET",
    "kafka_bootstrap_servers": "BOOTSTRAP_SERVERS",
    "kafka_api_key": "KAFKA_API_KEY",
    "kafka_api_secret": "KAFKA_API_SECRET",
    "kafka_rest_endpoint": "KAFKA_REST_ENDPOINT",
    "kafka_cluster_id": "KAFKA_CLUSTER_ID",
    "kafka_env_id": "KAFKA_ENV_ID",
    "schema_registry_endpoint": "SCHEMA_REGISTRY_ENDPOINT",
    "schema_registry_api_key": "SCHEMA_REGISTRY_API_KEY",
    "schema_registry_api_secret": "SCHEMA_REGISTRY_API_SECRET",
    "flink_rest_endpoint": "FLINK_REST_ENDPOINT",
    "flink_api_key": "FLINK_API_KEY",
    "flink_api_secret": "FLINK_API_SECRET",
    "flink_env_id": "FLINK_ENV_ID",
    "flink_org_id": "FLINK_ORG_ID",
    "flink_compute_pool_id": "FLINK_COMPUTE_POOL_ID",
}

# Every tool that creates, changes or deletes something (names from the package's tool list)
WRITE_TOOLS = (
    "create-topics", "delete-topics", "produce-message", "alter-topic-config",
    "create-flink-statement", "delete-flink-statements",
    "create-schema", "delete-schema",
    "create-connector", "delete-connector", "pause-connector", "resume-connector", "restart-connector",
    "update-connector-config",
    "create-topic-tags", "delete-tag", "remove-tag-from-entity", "add-tags-to-topic",
    "create-tableflow-topic", "update-tableflow-topic", "delete-tableflow-topic",
    "create-tableflow-catalog-integration", "update-tableflow-catalog-integration",
    "delete-tableflow-catalog-integration",
)


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    for key, name in ENV.items():
        # the raw env-var name works as a config key too; the process environment is the last resort
        value = config_value(config, key) or str(config.get(name) or "").strip()
        if value:
            env_vars[name] = value
    env_vars["DO_NOT_TRACK"] = "true"   # opt out of the package's anonymous telemetry
    if str(config.get("read_only", "true")).lower() != "false":
        args = [*args, "--block-tools", ",".join(WRITE_TOOLS)]
    tool_name = config.get("tool_name") or defaults["default_tool"]
    return args, tool_name, config.get("arguments") or {}


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
