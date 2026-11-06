"""Snowflake SQL (REST) — built-in tool `snowflake_sql_api`: one read statement through the Snowflake
SQL API with a token, so it works without snowflake-connector-python (which `snowflake_reader` needs)."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, markdown_table, params
from tools.data import _snowflake as sf
from tools.data.snowflake_reader import READONLY, _first_keyword, _trunc

LABEL = "Snowflake SQL"

TOOL = ToolSpec(
    id="snowflake_sql_api",
    name="Snowflake SQL (REST)",
    icon="❄️",
    category="Data & Files",
    description=("Runs one read statement (SELECT / SHOW / DESCRIBE / WITH / EXPLAIN) through the Snowflake "
                 "SQL API with a programmatic access token. No driver install needed."),
    default_config={**sf.DEFAULT_CONFIG, "max_results": 50},
    required=sf.REQUIRED,
    selects={"token_type": sf.TOKEN_SELECT},
    order=370,
    parameters=params(
        {"sql": {"type": "string", "description": "One Snowflake statement — SELECT, SHOW, DESCRIBE, EXPLAIN or WITH"}},
        {"max_results": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Most rows to return"}},
    ),
    input_param="sql",
    config_args=("max_results",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    problem = sf.credentials_missing(LABEL, cfg) or sf.missing(LABEL, sql=inp)
    if problem:
        return problem
    keyword = _first_keyword(inp)
    if keyword not in READONLY and cfg.get("allow_write") is not True:
        return f"[{LABEL}] Only {', '.join(READONLY)} statements are allowed (read-only) — got {keyword.upper()}."
    limit = min(max(int(cfg.get("max_results") or 50), 1), 500)
    rows, error = await sf.statement(LABEL, cfg, inp, max_rows=limit + 1)
    if error:
        return error
    if not rows:
        return f"[{LABEL}] The query returned 0 rows."
    header = list(rows[0])
    out = [f"[{LABEL}] {min(len(rows), limit)} row(s)", "",
           markdown_table(header, [[_trunc(row[c]) for c in header] for row in rows[:limit]])]
    if len(rows) > limit:
        out.append(f"Showing the first {limit} rows — narrow the query for more.")
    return "\n".join(out)
