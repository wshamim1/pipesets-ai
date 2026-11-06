"""MCP dbt — built-in MCP server `mcp_dbt` (dbt-mcp, by dbt Labs; version pinned).

The dbt platform: jobs and runs (with the error of a failed run), the Discovery API (models, sources,
lineage, model health and performance), the Semantic Layer (metrics) and SQL. The host, token, account
and production environment go in ``DBT_HOST`` / ``DBT_TOKEN`` / ``DBT_ACCOUNT_ID`` /
``DBT_PROD_ENV_ID``. The local dbt CLI, LSP and codegen toolsets are switched off — they need a dbt
project on the backend machine. ``read_only`` (on by default) disables triggering, cancelling and
retrying job runs. The default tool lists the account's jobs.
"""

from typing import Any, Dict

from tools.base import Select, ToolSpec
from tools.mcp._stdio import config_value, stdio_server

WRITE_TOOLS = "trigger_job_run,cancel_job_run,retry_job_run"

TOOL = ToolSpec(
    id="mcp_dbt",
    name="MCP dbt",
    type="mcp",
    icon="🟧",
    group="mcp_servers",
    category="Databases & Data",
    description="dbt platform: job runs and their errors, model lineage, health and performance, Semantic Layer metrics and SQL.",
    default_config={
        "transport": "stdio",
        "command": "uvx",
        "args": ["dbt-mcp@2.10.1"],
        "dbt_host": "cloud.getdbt.com",
        "dbt_token": "",
        "dbt_account_id": "",
        "dbt_prod_env_id": "",
        "read_only": "on",
    },
    required=("dbt_token", "dbt_account_id"),
    selects={"read_only": Select("Read-only", (("on", "On — no job triggers"), ("off", "Off — trigger, cancel, retry runs")))},
    order=455,
    is_new=True,
)

COMMAND = "uvx"
ARGS = ["dbt-mcp@2.10.1"]
DEFAULT_TOOL = "list_jobs"


def prepare(config: Dict[str, Any], input_text: str, args: list, env_vars: Dict[str, Any], defaults: Dict[str, Any]):
    """Node config → env vars, and the MCP tool to call with its arguments."""
    for key in ("dbt_host", "dbt_token", "dbt_account_id", "dbt_prod_env_id"):
        value = config_value(config, key)
        if value:
            env_vars[key.upper()] = value
    env_vars.update({"DISABLE_DBT_CLI": "true", "DISABLE_LSP": "true", "DISABLE_DBT_CODEGEN": "true",
                     "DO_NOT_TRACK": "1", "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"})
    if str(config.get("read_only", "on")).lower() not in ("off", "false", "no", "0"):
        env_vars["DISABLE_TOOLS"] = WRITE_TOOLS
    tool_name = config.get("tool_name") or defaults["default_tool"]
    call_args = config.get("arguments") or {}
    return args, tool_name, call_args


run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare, TOOL.required)
