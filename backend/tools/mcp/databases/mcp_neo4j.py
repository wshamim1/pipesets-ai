"""MCP Neo4j — built-in MCP server `mcp_neo4j` (mcp-neo4j-cypher, by Neo4j; version pinned)."""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_neo4j",
    name="MCP Neo4j",
    type="mcp",
    icon="🕸️",
    group="mcp_servers",
    category="Databases & Data",
    description="Read the schema of a Neo4j graph and run Cypher queries. Read-only unless you turn it off.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-neo4j-cypher@0.6.0"],
        "neo4j_uri": "bolt://localhost:7687",
        "neo4j_username": "neo4j",
        "neo4j_password": "",
        "neo4j_database": "neo4j",
        "read_only": "true",
    },
    required=("neo4j_uri", "neo4j_password"),
    selects={"read_only": Select("Access", [("true", "Read-only"), ("false", "Read and write")])},
    order=330,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["mcp-neo4j-cypher@0.6.0"]
DEFAULT_TOOL = "read_neo4j_cypher"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    for key in ("neo4j_uri", "neo4j_username", "neo4j_password", "neo4j_database"):
        value = config_value(config, key)
        if value:
            env_vars[key.upper()] = value
    env_vars["NEO4J_READ_ONLY"] = "false" if str(config.get("read_only", "true")).lower() == "false" else "true"
    call_args = config.get("arguments") or {"query": input_text.strip()}
    tool_name = config.get("tool_name") or defaults["default_tool"]
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
