"""Snowflake pipe status — built-in tool `snowflake_pipe_status`: a Snowpipe's execution state,
pending files and last error, from ``SYSTEM$PIPE_STATUS``."""

import json
from typing import Any, Dict, Optional

from tools.base import ToolSpec, params
from tools.data import _snowflake as sf

LABEL = "Snowflake Pipe Status"

TOOL = ToolSpec(
    id="snowflake_pipe_status",
    name=LABEL,
    icon="🚰",
    category="Data & Files",
    description="Checks a Snowpipe's execution state, pending file count and last ingest error.",
    default_config=dict(sf.DEFAULT_CONFIG),
    required=sf.REQUIRED,
    selects={"token_type": sf.TOKEN_SELECT},
    order=400,
    parameters=params({"pipe_name": {"type": "string", "description": "Fully qualified pipe name: db.schema.pipe"}}),
    input_param="pipe_name",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    problem = sf.credentials_missing(LABEL, cfg) or sf.missing(LABEL, pipe_name=inp)
    if problem:
        return problem
    parts = sf.name_parts(inp, 3)
    if not parts:
        return f"[{LABEL}] Expected db.schema.pipe, got '{inp}'"
    name = ".".join(parts)
    rows, error = await sf.statement(LABEL, cfg, f"SELECT SYSTEM$PIPE_STATUS({sf.sql_string(name)}) AS status")
    if error:
        return error
    raw = (rows or [{}])[0].get("STATUS") or "{}"
    try:
        status = json.loads(raw)
    except ValueError:
        status = raw
    return sf.report(LABEL, {"pipe": name, "status": status})
