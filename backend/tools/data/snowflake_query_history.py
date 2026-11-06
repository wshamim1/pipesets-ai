"""Snowflake query history — built-in tool `snowflake_query_history`: recent queries from
``INFORMATION_SCHEMA.QUERY_HISTORY`` (last 7 days, the queries the token's role can see)."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, enum, params
from tools.data import _snowflake as sf

LABEL = "Snowflake Query History"
STATUSES = {"all": "", "failed": "FAILED_WITH_ERROR", "running": "RUNNING", "success": "SUCCESS"}

TOOL = ToolSpec(
    id="snowflake_query_history",
    name=LABEL,
    icon="🕘",
    category="Data & Files",
    description="Shows recent Snowflake queries with status, user, warehouse, duration and errors — handy for failed jobs.",
    default_config={**sf.DEFAULT_CONFIG, "limit": 20},
    required=sf.REQUIRED,
    selects={"token_type": sf.TOKEN_SELECT},
    order=390,
    parameters=params(
        {},
        {
            "status": enum(list(STATUSES), "Only queries with this outcome"),
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "description": "How many queries to return"},
        },
    ),
    input_param="status",
    config_args=("limit",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    problem = sf.credentials_missing(LABEL, cfg)
    if problem:
        return problem
    status = STATUSES.get((inp or "all").lower())
    if status is None:
        return f"[{LABEL}] Unknown status '{inp}'. Use one of: {', '.join(STATUSES)}"
    limit = min(max(int(cfg.get("limit") or 20), 1), 200)
    where = f"WHERE execution_status = {sf.sql_string(status)} " if status else ""
    sql = ("SELECT query_id, LEFT(query_text, 300) AS query_text, user_name, role_name, warehouse_name, "
           "execution_status, error_message, start_time, total_elapsed_time "
           f"FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(RESULT_LIMIT => 10000)) {where}"
           f"ORDER BY start_time DESC LIMIT {limit}")
    rows, error = await sf.statement(LABEL, cfg, sql, max_rows=limit)
    if error:
        return error
    return sf.report(LABEL, {"status": inp or "all", "count": len(rows), "queries": rows})
