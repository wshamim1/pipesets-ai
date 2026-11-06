"""Databricks job logs — built-in tool `databricks_job_logs`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="databricks_job_logs",
    name="Databricks Job Logs",
    icon="📜",
    category="DevOps & Observability",
    description="Fetches recent logs for a Databricks job run so failures can be diagnosed quickly.",
    default_config={"host": "", "token": "", "run_id": "", "max_lines": 200},
    required=("host", "token"),
    order=290,
    parameters=params(
        {"run_id": {"type": "string", "description": "Databricks job run ID"}},
        {
            "max_lines": {
                "type": "integer",
                "minimum": 20,
                "maximum": 1000,
                "description": "Maximum number of log lines to return",
            }
        },
    ),
    input_param="run_id",
    config_args=("max_lines",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    host = (cfg.get("host") or "").strip().rstrip("/")
    token = (cfg.get("token") or "").strip()
    run_id = (inp or cfg.get("run_id") or "").strip()

    missing = [name for name, value in {"host": host, "token": token, "run_id": run_id}.items() if not value]
    if missing:
        return f"[Databricks Job Logs] Missing required config: {', '.join(missing)}"

    headers = {"Authorization": f"Bearer {token}"}
    max_lines = max(20, min(int(cfg.get("max_lines") or 200), 1000))

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(f"{host}/api/2.1/jobs/runs/get-output", params={"run_id": run_id, "limit": max_lines}, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        return f"[Databricks Job Logs] Error: {exc}"

    logs = payload.get("logs") or payload.get("output") or ""
    if isinstance(logs, dict):
        logs = logs.get("logs") or json.dumps(logs, indent=2, sort_keys=True)
    log_text = str(logs).strip()
    if not log_text:
        return f"[Databricks Job Logs] No logs returned for run {run_id}."

    lines = log_text.splitlines()
    return "\n".join(lines[:max_lines])
