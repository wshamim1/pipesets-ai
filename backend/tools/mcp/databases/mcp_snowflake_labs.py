"""MCP Snowflake (official) — built-in MCP server `mcp_snowflake_labs` (Snowflake-Labs' snowflake-labs-mcp;
version pinned).

Credentials go in the package's ``SNOWFLAKE_*`` environment variables, never on the command line.
The server also reads a service-config file (Cortex Search / Analyst services, tool groups, allowed
SQL statement types); it is generated from the node config into the temp directory, named by its
content hash, and passed in ``SERVICE_CONFIG_FILE``. It holds no secrets. JSON is valid YAML, so it
is written as JSON.

Read-only (the default) allows only SELECT and DESCRIBE statements and leaves out the object
manager, whose tools create, alter and drop objects.
"""

import hashlib
import json
import os
import tempfile
from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_snowflake_labs",
    name="MCP Snowflake (official)",
    type="mcp",
    icon="❄️",
    group="mcp_servers",
    category="Databases & Data",
    description="Snowflake's own MCP server: SQL, Cortex Search, Cortex Analyst, semantic views and object management.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["--from", "snowflake-labs-mcp@1.4.2", "snowflake-labs-mcp"],
        "snowflake_account": "",
        "snowflake_user": "",
        "snowflake_password": "",
        "snowflake_role": "",
        "snowflake_warehouse": "",
        "search_service": "",
        "semantic_model": "",
        "read_only": "true",
    },
    required=("snowflake_account", "snowflake_user", "snowflake_password"),
    selects={"read_only": Select("Access", [("true", "Read-only"), ("false", "Read and write")])},
    order=385,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["--from", "snowflake-labs-mcp@1.4.2", "snowflake-labs-mcp"]
DEFAULT_TOOL = "run_snowflake_query"
# No input: a connection check
WHOAMI = "SELECT CURRENT_ACCOUNT() AS account, CURRENT_USER() AS user, CURRENT_ROLE() AS role, CURRENT_WAREHOUSE() AS warehouse"


def service_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """The server's service-config document for this node."""
    read_only = str(config.get("read_only", "true")).lower() != "false"
    doc: Dict[str, Any] = {
        "other_services": {"object_manager": not read_only, "query_manager": True, "semantic_manager": True},
        # the server refuses any statement type not allowed here
        "sql_statement_permissions": [{"Select": True}, {"Describe": True}] if read_only else [{"All": True}],
    }
    search = str(config.get("search_service") or "").strip().split(".")
    if len(search) == 3 and all(search):
        doc["search_services"] = [{"service_name": search[2], "database_name": search[0], "schema_name": search[1],
                                   "description": "Cortex Search service configured on this node"}]
    semantic_model = str(config.get("semantic_model") or "").strip()
    if semantic_model:
        doc["analyst_services"] = [{"service_name": "analyst", "semantic_model": semantic_model,
                                    "description": "Cortex Analyst over the semantic model configured on this node"}]
    return doc


def write_service_config(doc: Dict[str, Any]) -> str:
    text = json.dumps(doc, indent=2, sort_keys=True)
    folder = os.path.join(tempfile.gettempdir(), "pipesets-mcp")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"snowflake-{hashlib.sha256(text.encode()).hexdigest()[:16]}.yaml")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return path


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    for key in ("snowflake_account", "snowflake_user", "snowflake_password", "snowflake_role", "snowflake_warehouse"):
        value = config_value(config, key)
        if value:
            env_vars[key.upper()] = value
    env_vars["SERVICE_CONFIG_FILE"] = write_service_config(service_config(config))
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {"statement": input_text.strip() or WHOAMI}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
