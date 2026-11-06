"""Snowflake catalog browser — built-in tool `snowflake_catalog`.

The input's depth picks what is listed: empty → databases, ``db`` → its schemas,
``db.schema`` → its tables, ``db.schema.table`` → that table's columns and details.
"""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, params
from tools.data import _snowflake as sf

LABEL = "Snowflake Catalog"

TOOL = ToolSpec(
    id="snowflake_catalog",
    name=LABEL,
    icon="🗂️",
    category="Data & Files",
    description="Browses Snowflake: lists databases, schemas or tables, or describes a table's columns, owner and size.",
    default_config={**sf.DEFAULT_CONFIG, "max_results": 100},
    required=sf.REQUIRED,
    selects={"token_type": sf.TOKEN_SELECT},
    order=385,
    parameters=params(
        {},
        {
            "name": {"type": "string",
                     "description": "Empty for databases, 'db' for schemas, 'db.schema' for tables, "
                                    "'db.schema.table' to describe a table"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Maximum items to list"},
        },
    ),
    input_param="name",
    config_args=("max_results",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    problem = sf.credentials_missing(LABEL, cfg)
    if problem:
        return problem
    depth = len(inp.split(".")) if inp else 0
    parts = sf.name_parts(inp, depth) if depth else []
    if parts is None or depth > 3:
        return f"[{LABEL}] Expected db, db.schema or db.schema.table, got '{inp}'"
    path = "/api/v2/databases" + "".join(
        f"/{sf.url_part(p)}/{child}" for p, child in zip(parts, ("schemas", "tables")))
    limit = int(cfg.get("max_results") or 100)

    if depth == 3:
        data, error = await sf.request(LABEL, cfg, "GET", f"{path}/{sf.url_part(parts[2])}")
        if error:
            return error
        return sf.report(LABEL, {
            "name": ".".join(parts),
            "kind": data.get("kind") or data.get("table_type"),
            "owner": data.get("owner"),
            "comment": data.get("comment"),
            "rows": data.get("rows"),
            "bytes": data.get("bytes"),
            "cluster_by": data.get("cluster_by"),
            "columns": [{"name": c.get("name"), "type": c.get("datatype"), "nullable": c.get("nullable"),
                         "comment": c.get("comment")} for c in data.get("columns") or []],
        })

    data, error = await sf.request(LABEL, cfg, "GET", path, params={"showLimit": limit})
    if error:
        return error
    key = ("databases", "schemas", "tables")[depth]
    fields = ("name", "kind", "owner", "comment", "created_on")
    items = [{f: item.get(f) for f in fields if item.get(f) is not None}
             for item in (data if isinstance(data, list) else [])[:limit]]
    return sf.report(LABEL, {key: items, "count": len(items)})
