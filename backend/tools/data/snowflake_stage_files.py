"""Snowflake stage files — built-in tool `snowflake_stage_files`: ``LIST`` the files in a stage."""

import re
from typing import Any, Dict, Optional

from tools.base import ToolSpec, params
from tools.data import _snowflake as sf

LABEL = "Snowflake Stage Files"

TOOL = ToolSpec(
    id="snowflake_stage_files",
    name=LABEL,
    icon="📁",
    category="Data & Files",
    description="Lists files in a Snowflake internal or external stage, optionally under a path, with size and timestamps.",
    default_config={**sf.DEFAULT_CONFIG, "max_results": 100},
    required=sf.REQUIRED,
    selects={"token_type": sf.TOKEN_SELECT},
    order=410,
    parameters=params(
        {"stage": {"type": "string", "description": "Stage and optional path, e.g. @db.schema.stage/2026/11/"}},
        {"max_results": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "Most files to return"}},
    ),
    input_param="stage",
    config_args=("max_results",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    problem = sf.credentials_missing(LABEL, cfg) or sf.missing(LABEL, stage=inp)
    if problem:
        return problem
    name, _, path = inp.lstrip("@").partition("/")
    parts = sf.name_parts(name, 3)
    if not parts or not re.fullmatch(r"[\w./=-]*", path):
        return f"[{LABEL}] Expected @db.schema.stage[/path], got '{inp}'"
    location = "@" + ".".join(parts) + (f"/{path}" if path else "")
    limit = int(cfg.get("max_results") or 100)
    rows, error = await sf.statement(LABEL, cfg, f"LIST {location}", max_rows=limit)
    if error:
        return error
    files = [{"name": r.get("name"), "size": r.get("size"), "last_modified": r.get("last_modified")} for r in rows]
    return sf.report(LABEL, {"stage": location, "count": len(files), "files": files})
