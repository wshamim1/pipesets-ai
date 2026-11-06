"""Databricks vector search — built-in tool `databricks_vector_search`."""

from typing import Any, Dict, Optional
from urllib.parse import quote

from tools.base import ToolSpec, params
from tools.data._databricks import missing, report, request

LABEL = "Databricks Vector Search"

TOOL = ToolSpec(
    id="databricks_vector_search",
    name=LABEL,
    icon="🧭",
    category="Data & Files",
    description="Runs a similarity search against a Databricks Vector Search index and returns the closest rows.",
    default_config={"host": "", "token": "", "index_name": "", "columns": "", "num_results": 5},
    required=("host", "token", "index_name", "columns"),
    order=355,
    parameters=params(
        {"query": {"type": "string", "description": "Text to search the index for"}},
        {"num_results": {"type": "integer", "minimum": 1, "maximum": 50, "description": "How many rows to return"}},
    ),
    input_param="query",
    config_args=("num_results",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    index_name = (cfg.get("index_name") or "").strip()
    columns = cfg.get("columns") or ""
    if isinstance(columns, str):
        columns = [c.strip() for c in columns.split(",") if c.strip()]
    problem = missing(LABEL, index_name=index_name, columns=",".join(columns), query=inp)
    if problem:
        return problem

    body = {"query_text": inp, "columns": columns, "num_results": int(cfg.get("num_results") or 5)}
    data, error = await request(LABEL, cfg, "POST", f"/api/2.0/vector-search/indexes/{quote(index_name, safe='.')}/query",
                                body=body, timeout=60.0)
    if error:
        return error
    names = [c.get("name") for c in (data.get("manifest") or {}).get("columns") or []]
    rows = [dict(zip(names, row)) for row in (data.get("result") or {}).get("data_array") or []]
    return report(LABEL, {"index": index_name, "count": len(rows), "results": rows})
