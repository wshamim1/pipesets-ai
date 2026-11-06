"""Databricks job status — built-in tool `databricks_job_status`."""

import json
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="databricks_job_status",
    name="Databricks Job Status",
    icon="🛠️",
    category="DevOps & Observability",
    description="Fetches the current status and recent run metadata for a Databricks job from the workspace API.",
    default_config={"host": "", "token": "", "job_id": ""},
    required=("host", "token"),
    order=240,
    parameters=params(
        {"job_id": {"type": "string", "description": "Databricks job ID to inspect"}},
        {
            "include_history": {
                "type": "boolean",
                "description": "Include the last few run states in the response",
            }
        },
    ),
    input_param="job_id",
    config_args=("include_history",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    host = (cfg.get("host") or "").strip().rstrip("/")
    token = (cfg.get("token") or "").strip()
    job_id = (inp or cfg.get("job_id") or "").strip()

    missing = [name for name, value in {"host": host, "token": token, "job_id": job_id}.items() if not value]
    if missing:
        return f"[Databricks Job Status] Missing required config: {', '.join(missing)}"

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            job_resp = await client.get(f"{host}/api/2.1/jobs/get", params={"job_id": job_id}, headers=headers)
            job_resp.raise_for_status()
            job_payload = job_resp.json()

            runs_resp = await client.get(f"{host}/api/2.1/jobs/runs/list", params={"job_id": job_id, "limit": 5}, headers=headers)
            runs_resp.raise_for_status()
            runs_payload = runs_resp.json()
    except Exception as exc:
        return f"[Databricks Job Status] Error: {exc}"

    job_name = job_payload.get("settings", {}).get("name") or job_payload.get("job_id") or job_id
    latest_run = (runs_payload.get("runs") or [{}])[0]
    state = latest_run.get("state", {})
    life_cycle = state.get("life_cycle_state") or "unknown"
    result_state = state.get("result_state") or "unknown"
    run_id = latest_run.get("run_id") or "n/a"
    start_time = latest_run.get("start_time") or "n/a"

    summary = {
        "job_id": str(job_id),
        "job_name": job_name,
        "latest_run_id": run_id,
        "latest_run_state": life_cycle,
        "latest_result_state": result_state,
        "latest_start_time": start_time,
    }

    if cfg.get("include_history"):
        history = []
        for run in (runs_payload.get("runs") or [])[:5]:
            s = run.get("state", {})
            history.append({
                "run_id": run.get("run_id"),
                "state": s.get("life_cycle_state"),
                "result": s.get("result_state"),
                "start_time": run.get("start_time"),
            })
        summary["history"] = history

    return f"[Databricks Job Status]\n{json.dumps(summary, indent=2, sort_keys=True)}"
