"""Databricks list SQL warehouses — built-in tool `databricks_list_warehouses`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, params
from tools.data._databricks import report, request

LABEL = "Databricks SQL Warehouses"

TOOL = ToolSpec(
    id="databricks_list_warehouses",
    name=LABEL,
    icon="🏭",
    category="Data & Files",
    description="Lists Databricks SQL warehouses with their state, size, type and the HTTP path used to connect.",
    default_config={"host": "", "token": ""},
    required=("host", "token"),
    order=335,
    parameters=params({}, {"name": {"type": "string", "description": "Only warehouses whose name contains this"}}),
    input_param="name",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    data, error = await request(LABEL, cfg, "GET", "/api/2.0/sql/warehouses")
    if error:
        return error
    needle = inp.lower()
    warehouses = [
        {
            "id": w.get("id"),
            "name": w.get("name"),
            "state": w.get("state"),
            "size": w.get("cluster_size"),
            "type": w.get("warehouse_type"),
            "serverless": w.get("enable_serverless_compute"),
            "http_path": (w.get("odbc_params") or {}).get("path"),
        }
        for w in data.get("warehouses") or []
        if needle in (w.get("name") or "").lower()
    ]
    return report(LABEL, {"count": len(warehouses), "warehouses": warehouses})
