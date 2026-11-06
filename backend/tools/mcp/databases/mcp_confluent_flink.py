"""MCP Confluent Flink — built-in MCP server `mcp_confluent_flink` (@confluentinc/mcp-confluent; version pinned).

The Flink SQL, Tableflow and metrics tools of Confluent's MCP server, and nothing else. Tableflow and metrics are
only available here; the built-in ``flink_statements`` tool covers just statement status. Flink SQL: statements, results,
exceptions, profiles, health, and the catalog / database / table browser. Tableflow: topics, catalog integrations,
regions. Metrics: the Confluent Cloud Metrics API (``query-metrics``). Read-only by default: every tool that
creates, changes or deletes something is blocked with ``--block-tools``.

Needs Node.js 22.23.4+ and a Confluent Cloud account; fill in only the settings of the part you use.
"""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server
from tools.mcp.databases.mcp_confluent import ARGS, COMMAND, WRITE_TOOLS

TOOL = ToolSpec(
    id="mcp_confluent_flink",
    name="MCP Confluent Flink",
    type="mcp",
    icon="🌊",
    group="mcp_servers",
    category="Databases & Data",
    description="Run and inspect Flink SQL on Confluent Cloud (statements, results, health, catalog), manage Tableflow topics and catalog integrations, and query cluster, topic and Flink metrics. Read-only by default. Needs Node.js 22.23.4+.",
    default_config={
        "transport": "stdio",
        "command": COMMAND,
        "args": list(ARGS),
        "flink_rest_endpoint": "",
        "flink_api_key": "",
        "flink_api_secret": "",
        "flink_org_id": "",
        "flink_env_id": "",
        "flink_compute_pool_id": "",
        "flink_catalog_name": "",
        "flink_database_name": "",
        "tableflow_api_key": "",
        "tableflow_api_secret": "",
        "confluent_cloud_api_key": "",
        "confluent_cloud_api_secret": "",
        "read_only": "true",
    },
    selects={"read_only": Select("Access", [("true", "Read-only"), ("false", "Read and write")])},
    order=272,
    is_new=True,
)

DEFAULT_TOOL = "list-flink-statements"

# Settings → the environment variable mcp-confluent reads. All optional: a missing block just leaves its tools off.
ENV = {
    "flink_rest_endpoint": "FLINK_REST_ENDPOINT",
    "flink_api_key": "FLINK_API_KEY",
    "flink_api_secret": "FLINK_API_SECRET",
    "flink_org_id": "FLINK_ORG_ID",
    "flink_env_id": "FLINK_ENV_ID",
    "flink_compute_pool_id": "FLINK_COMPUTE_POOL_ID",
    "flink_catalog_name": "FLINK_CATALOG_NAME",
    "flink_database_name": "FLINK_DATABASE_NAME",
    "tableflow_api_key": "TABLEFLOW_API_KEY",
    "tableflow_api_secret": "TABLEFLOW_API_SECRET",
    "confluent_cloud_api_key": "CONFLUENT_CLOUD_API_KEY",
    "confluent_cloud_api_secret": "CONFLUENT_CLOUD_API_SECRET",
    "kafka_cluster_id": "KAFKA_CLUSTER_ID",
    "kafka_env_id": "KAFKA_ENV_ID",
}

# The only tools this server offers (names from the package's tool list); discovery helpers included
ALLOWED_TOOLS = (
    # Flink SQL
    "create-flink-statement", "list-flink-statements", "get-flink-statement-results", "delete-flink-statements",
    "get-flink-statement-exceptions", "list-compute-pools",
    # Flink catalog
    "list-flink-catalogs", "list-flink-databases", "list-flink-tables", "describe-flink-table", "get-flink-table-info",
    # Flink diagnostics
    "check-flink-statement-health", "detect-flink-statement-issues", "get-flink-statement-profile",
    # Tableflow
    "list-tableflow-regions", "list-tableflow-topics", "read-tableflow-topic",
    "create-tableflow-topic", "update-tableflow-topic", "delete-tableflow-topic",
    "list-tableflow-catalog-integrations", "read-tableflow-catalog-integration",
    "create-tableflow-catalog-integration", "update-tableflow-catalog-integration",
    "delete-tableflow-catalog-integration",
    # Metrics
    "list-available-metrics", "query-metrics",
    # Finding the ids the settings above ask for
    "list-organizations", "list-environments", "list-clusters",
)


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    for key, name in ENV.items():
        # the raw env-var name works as a config key too; the process environment is the last resort
        value = config_value(config, key) or str(config.get(name) or "").strip()
        if value:
            env_vars[name] = value
    env_vars["DO_NOT_TRACK"] = "true"   # opt out of the package's anonymous telemetry
    args = [*args, "--allow-tools", ",".join(ALLOWED_TOOLS)]
    if str(config.get("read_only", "true")).lower() != "false":
        args = [*args, "--block-tools", ",".join(t for t in WRITE_TOOLS if t in ALLOWED_TOOLS)]
    tool_name = config.get("tool_name") or defaults["default_tool"]
    return args, tool_name, config.get("arguments") or {}


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
