"""Databricks job runs — built-in tool `databricks_job_runs`."""

import json
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="databricks_job_runs",
    name="Databricks Job Runs",
    icon="🔄",
    category="DevOps & Observability",
    description="Lists recent runs for a Databricks job and summarizes their lifecycle and result states.",
    default_config={"host": "", "token": "", "job_id": "", "limit": 5},
    required=("host", "token"),
    order=260,
    parameters=params(
        {"job_id": {"type": "string", "description": "Databricks job ID"}},
        {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "description": "Maximum number of recent runs to fetch",
            }
        },
    ),
    input_param="job_id",
    config_args=("limit",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    host = (cfg.get("host") or "").strip().rstrip("/")
    token = (cfg.get("token") or "").strip()
    job_id = (inp or cfg.get("job_id") or "").strip()

    missing = [name for name, value in {"host": host, "token": token, "job_id": job_id}.items() if not value]
    if missing:
        return f"[Databricks Job Runs] Missing required config: {', '.join(missing)}"

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    limit = max(1, min(int(cfg.get("limit") or 5), 20))

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{host}/api/2.1/jobs/runs/list", params={"job_id": job_id, "limit": limit}, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        return f"[Databricks Job Runs] Error: {exc}"

    runs = payload.get("runs") or []
    if not runs:
        return f"[Databricks Job Runs] No recent runs found for job {job_id}."

    lines = [f"Job {job_id}: recent runs"]
    for run in runs[:limit]:
        state = run.get("state") or {}
        lines.append(
            f"- run_id={run.get('run_id')}, state={state.get('life_cycle_state')}, result={state.get('result_state')}, "
            f"start={run.get('start_time')}"
        )
    return "\n".join(lines)
