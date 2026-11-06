"""MCP Apache Airflow — built-in MCP server `mcp_airflow` (mcp-server-apache-airflow; version pinned).

Wraps the Airflow REST API (DAGs, runs, tasks, logs, variables, connections, pools, XComs, datasets,
health). Credentials go in the environment; ``--read-only`` hides every tool that writes (pause,
trigger, clear, delete, ...) and is on by default.
"""

import os
from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

TOOL = ToolSpec(
    id="mcp_airflow",
    name="MCP Apache Airflow",
    type="mcp",
    icon="🌬️",
    group="mcp_servers",
    category="DevOps & Observability",
    description="Manage Apache Airflow: list DAGs, runs and task logs, inspect variables, connections and pools, and (read-write only) trigger or clear runs. Read-only by default.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-apache-airflow@0.2.10"],
        "airflow_host": "http://localhost:8080",
        "airflow_api_version": "v1",
        "airflow_username": "",
        "airflow_password": "",
        "airflow_jwt_token": "",
        "read_only": "true",
    },
    selects={
        "airflow_api_version": Select("REST API version", [("v1", "v1 (Airflow 2.x)"), ("v2", "v2 (Airflow 3.x)")]),
        "read_only": Select("Access", [("true", "Read-only"), ("false", "Read and write")]),
    },
    order=20,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["mcp-server-apache-airflow@0.2.10"]
DEFAULT_TOOL = "fetch_dags"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → extra launch args / env vars, and the MCP tool to call with its arguments."""
    env_vars["AIRFLOW_HOST"] = config_value(config, "airflow_host", "http://localhost:8080")
    env_vars["AIRFLOW_API_VERSION"] = config_value(config, "airflow_api_version", "v1")
    jwt = config_value(config, "airflow_jwt_token")
    username = config_value(config, "airflow_username")
    password = str(config.get("airflow_password") or os.environ.get("AIRFLOW_PASSWORD", ""))
    if jwt:  # the server prefers a token over basic auth
        env_vars["AIRFLOW_JWT_TOKEN"] = jwt
    elif username:
        env_vars["AIRFLOW_USERNAME"] = username
        env_vars["AIRFLOW_PASSWORD"] = password
    if str(config.get("read_only", "true")).lower() != "false":
        args = [*args, "--read-only"]
    tool_name = config.get("tool_name") or defaults["default_tool"]
    text = input_text.strip()
    call_args = config.get("arguments") or ({"dag_id_pattern": text} if text else {})
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)
