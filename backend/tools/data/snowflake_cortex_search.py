"""Snowflake Cortex Search — built-in tool `snowflake_cortex_search`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, params
from tools.data import _snowflake as sf

LABEL = "Snowflake Cortex Search"

TOOL = ToolSpec(
    id="snowflake_cortex_search",
    name=LABEL,
    icon="🔎",
    category="Data & Files",
    description="Searches a Snowflake Cortex Search service (hybrid vector + keyword) and returns the best-matching rows.",
    default_config={**sf.DEFAULT_CONFIG, "search_service": "", "columns": "", "limit": 5},
    required=(*sf.REQUIRED, "search_service"),
    selects={"token_type": sf.TOKEN_SELECT},
    order=420,
    parameters=params(
        {"query": {"type": "string", "description": "What to search for"}},
        {"limit": {"type": "integer", "minimum": 1, "maximum": 50, "description": "How many results to return"}},
    ),
    input_param="query",
    config_args=("limit",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    service = (cfg.get("search_service") or "").strip()
    problem = sf.credentials_missing(LABEL, cfg) or sf.missing(LABEL, search_service=service, query=inp)
    if problem:
        return problem
    parts = sf.name_parts(service, 3)
    if not parts:
        return f"[{LABEL}] search_service must be db.schema.service, got '{service}'"
    columns = cfg.get("columns") or ""
    if isinstance(columns, str):
        columns = [c.strip() for c in columns.split(",") if c.strip()]
    body: Dict[str, Any] = {"query": inp, "limit": int(cfg.get("limit") or 5)}
    if columns:
        body["columns"] = columns
    db, schema, name = (sf.url_part(p) for p in parts)
    data, error = await sf.request(
        LABEL, cfg, "POST", f"/api/v2/databases/{db}/schemas/{schema}/cortex-search-services/{name}:query",
        body=body, timeout=60.0)
    if error:
        return error
    results = data.get("results") or []
    return sf.report(LABEL, {"service": ".".join(parts), "count": len(results), "results": results})
