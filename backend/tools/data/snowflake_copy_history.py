"""Snowflake copy history — built-in tool `snowflake_copy_history`: recent file loads into a table
(COPY INTO and Snowpipe) from ``INFORMATION_SCHEMA.COPY_HISTORY``."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, params
from tools.data import _snowflake as sf

LABEL = "Snowflake Copy History"

TOOL = ToolSpec(
    id="snowflake_copy_history",
    name=LABEL,
    icon="📥",
    category="Data & Files",
    description="Lists recent file loads into a Snowflake table (COPY INTO / Snowpipe) with status, row counts and errors.",
    default_config={**sf.DEFAULT_CONFIG, "hours": 24},
    required=sf.REQUIRED,
    selects={"token_type": sf.TOKEN_SELECT},
    order=405,
    parameters=params(
        {"table_name": {"type": "string", "description": "Fully qualified table name: db.schema.table"}},
        {"hours": {"type": "integer", "minimum": 1, "maximum": 336, "description": "How far back to look, in hours"}},
    ),
    input_param="table_name",
    config_args=("hours",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    problem = sf.credentials_missing(LABEL, cfg) or sf.missing(LABEL, table_name=inp)
    if problem:
        return problem
    parts = sf.name_parts(inp, 3)
    if not parts:
        return f"[{LABEL}] Expected db.schema.table, got '{inp}'"
    hours = min(max(int(cfg.get("hours") or 24), 1), 336)
    sql = ("SELECT file_name, status, row_count, row_parsed, error_count, first_error_message, last_load_time "
           f"FROM TABLE({parts[0]}.INFORMATION_SCHEMA.COPY_HISTORY(TABLE_NAME => {sf.sql_string('.'.join(parts))}, "
           f"START_TIME => DATEADD(hours, -{hours}, CURRENT_TIMESTAMP()))) ORDER BY last_load_time DESC LIMIT 100")
    rows, error = await sf.statement(LABEL, cfg, sql)
    if error:
        return error
    failed = sum(1 for r in rows if (r.get("STATUS") or "").upper() not in ("LOADED", ""))
    return sf.report(LABEL, {"table": ".".join(parts), "hours": hours, "files": len(rows), "not_loaded": failed,
                             "loads": rows})
