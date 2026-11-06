"""Apache Airflow import errors — built-in tool `airflow_import_errors`.

Lists the DAG files the scheduler couldn't parse — the first thing to check when a DAG is missing.
"""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params
from tools.integrations import _airflow as af

TOOL = ToolSpec(
    id="airflow_import_errors",
    name="Airflow Import Errors",
    icon="🧩",
    category="APIs & Integrations",
    description="List the Apache Airflow DAG files that failed to import, with the error. Use it when a DAG is missing from the UI.",
    default_config={**af.CONNECTION_CONFIG, "max_results": 10},
    order=32,
    required=("base_url",),
    selects={"api_version": af.VERSION_SELECT},
    parameters=params(
        {},
        {"max_results": {"type": "integer", "minimum": 1, "maximum": 50, "description": "How many errors to return"}},
    ),
    input_param="",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    api = af.api_url(cfg)
    if not api:
        return af.NO_BASE_URL
    try:
        limit = max(1, min(int(cfg.get("max_results", 10)), 50))
    except (TypeError, ValueError):
        limit = 10
    try:
        async with af.client(cfg) as client:
            resp = await client.get(f"{api}/importErrors", params={"limit": limit, "order_by": "-timestamp"})
            if err := af.failed(resp):
                return err
            data = resp.json()
    except httpx.HTTPError as e:
        return f"[Airflow] Error: {e}"
    errors = data.get("import_errors", [])
    if not errors:
        return "[Airflow] No import errors — every DAG file parsed."
    total = data.get("total_entries", len(errors))
    lines = [f"[Airflow] {total} DAG file(s) failed to import" + (f" (showing {len(errors)})" if total > len(errors) else "")]
    for e in errors:
        # the traceback ends with the actual error
        trace = (e.get("stack_trace") or e.get("stacktrace") or "").strip().splitlines()
        lines.append(f"\n{e.get('filename')}  ({af.short(e.get('timestamp'))})\n  {trace[-1] if trace else 'no details'}")
    return "\n".join(lines)
