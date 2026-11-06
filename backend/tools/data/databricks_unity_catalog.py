"""Databricks Unity Catalog browser — built-in tool `databricks_unity_catalog`.

The input's depth picks what is listed: empty → catalogs, ``catalog`` → its schemas,
``catalog.schema`` → its tables, ``catalog.schema.table`` → that table's columns and details.
"""

from typing import Any, Dict, Optional
from urllib.parse import quote

from tools.base import ToolSpec, params
from tools.data._databricks import report, request

LABEL = "Databricks Unity Catalog"
UC = "/api/2.1/unity-catalog"

TOOL = ToolSpec(
    id="databricks_unity_catalog",
    name=LABEL,
    icon="🗂️",
    category="Data & Files",
    description="Browses Unity Catalog: lists catalogs, schemas or tables, or describes a table's columns, owner and storage.",
    default_config={"host": "", "token": "", "max_results": 100},
    required=("host", "token"),
    order=340,
    parameters=params(
        {},
        {
            "name": {
                "type": "string",
                "description": "Empty for catalogs, 'catalog' for schemas, 'catalog.schema' for tables, "
                               "'catalog.schema.table' to describe a table",
            },
            "max_results": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Maximum items to list"},
        },
    ),
    input_param="name",
    config_args=("max_results",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    parts = [p.strip("` ") for p in inp.split(".")] if inp else []
    limit = int(cfg.get("max_results") or 100)
    page = {"max_results": limit}

    if len(parts) == 0:
        data, error = await request(LABEL, cfg, "GET", f"{UC}/catalogs", params=page)
        key, fields = "catalogs", ("name", "owner", "comment", "catalog_type")
    elif len(parts) == 1:
        data, error = await request(LABEL, cfg, "GET", f"{UC}/schemas", params={**page, "catalog_name": parts[0]})
        key, fields = "schemas", ("full_name", "owner", "comment")
    elif len(parts) == 2:
        data, error = await request(LABEL, cfg, "GET", f"{UC}/tables",
                                    params={**page, "catalog_name": parts[0], "schema_name": parts[1]})
        key, fields = "tables", ("full_name", "table_type", "data_source_format", "owner", "comment")
    elif len(parts) == 3:
        data, error = await request(LABEL, cfg, "GET", f"{UC}/tables/{quote('.'.join(parts), safe='.')}")
        if error:
            return error
        return report(LABEL, {
            "full_name": data.get("full_name"),
            "table_type": data.get("table_type"),
            "format": data.get("data_source_format"),
            "owner": data.get("owner"),
            "comment": data.get("comment"),
            "storage_location": data.get("storage_location"),
            "columns": [{"name": c.get("name"), "type": c.get("type_text"), "nullable": c.get("nullable"),
                         "comment": c.get("comment")} for c in data.get("columns") or []],
        })
    else:
        return f"[{LABEL}] Expected at most catalog.schema.table, got '{inp}'"

    if error:
        return error
    items = [{f: item.get(f) for f in fields} for item in (data.get(key) or [])[:limit]]
    return report(LABEL, {key: items, "count": len(items), "has_more": bool(data.get("next_page_token"))})
