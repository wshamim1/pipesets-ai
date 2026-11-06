"""Apache Airflow health — built-in tool `airflow_health`.

The metadatabase, scheduler, triggerer and DAG processor status, from ``/api/v1/health`` (Airflow 2) or
``/api/v2/monitor/health`` (Airflow 3).
"""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params
from tools.integrations import _airflow as af

TOOL = ToolSpec(
    id="airflow_health",
    name="Airflow Health",
    icon="🩺",
    category="APIs & Integrations",
    description="Check an Apache Airflow deployment: metadatabase, scheduler, triggerer and DAG processor status and last heartbeat.",
    default_config={**af.CONNECTION_CONFIG},
    order=33,
    required=("base_url",),
    selects={"api_version": af.VERSION_SELECT},
    parameters=params({}),
    input_param="",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    api = af.api_url(cfg)
    if not api:
        return af.NO_BASE_URL
    path = "/monitor/health" if cfg.get("api_version") == "v2" else "/health"
    try:
        async with af.client(cfg) as client:
            resp = await client.get(f"{api}{path}")
            if err := af.failed(resp):
                return err
            data = resp.json()
    except httpx.HTTPError as e:
        return f"[Airflow] Error: {e}"
    parts = {k: v for k, v in data.items() if isinstance(v, dict)}
    if not parts:
        return f"[Airflow] Unexpected health response: {str(data)[:300]}"
    unhealthy = [k for k, v in parts.items() if v.get("status") != "healthy"]
    lines = ["[Airflow] " + ("All components healthy" if not unhealthy else f"Unhealthy: {', '.join(unhealthy)}")]
    for name, part in parts.items():
        beat = part.get("latest_scheduler_heartbeat") or part.get("latest_triggerer_heartbeat") \
            or part.get("latest_dag_processor_heartbeat")
        lines.append(f"  {name}: {part.get('status') or 'unknown'}" + (f" (last heartbeat {af.short(beat)})" if beat else ""))
    return "\n".join(lines)
