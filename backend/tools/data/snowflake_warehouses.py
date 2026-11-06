"""Snowflake warehouses — built-in tool `snowflake_warehouses`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, params
from tools.data import _snowflake as sf

LABEL = "Snowflake Warehouses"

TOOL = ToolSpec(
    id="snowflake_warehouses",
    name=LABEL,
    icon="🏭",
    category="Data & Files",
    description="Lists Snowflake virtual warehouses with their state, size, type and auto-suspend settings.",
    default_config=dict(sf.DEFAULT_CONFIG),
    required=sf.REQUIRED,
    selects={"token_type": sf.TOKEN_SELECT},
    order=375,
    parameters=params({}, {"name": {"type": "string", "description": "Only warehouses whose name contains this"}}),
    input_param="name",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    query = {"like": f"%{inp}%"} if inp else None
    data, error = await sf.request(LABEL, cfg, "GET", "/api/v2/warehouses", params=query)
    if error:
        return error
    warehouses = [
        {
            "name": w.get("name"),
            "state": w.get("state"),
            "size": w.get("warehouse_size"),
            "type": w.get("warehouse_type"),
            "auto_suspend": w.get("auto_suspend"),
            "auto_resume": w.get("auto_resume"),
            "running": w.get("running"),
            "queued": w.get("queued"),
        }
        for w in (data if isinstance(data, list) else [])
    ]
    return sf.report(LABEL, {"count": len(warehouses), "warehouses": warehouses})
