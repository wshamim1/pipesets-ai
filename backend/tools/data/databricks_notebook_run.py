"""Databricks notebook run — built-in tool `databricks_notebook_run`."""

import json
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="databricks_notebook_run",
    name="Databricks Notebook Run",
    icon="▶️",
    category="Data & Files",
    description="Runs a Databricks notebook or Python script in the workspace and returns the submitted run metadata.",
    default_config={"host": "", "token": "", "path": "", "cluster_id": ""},
    required=("host", "token", "cluster_id"),
    order=280,
    parameters=params(
        {"path": {"type": "string", "description": "Databricks workspace path to the notebook or script to run"}},
        {
            "cluster_id": {"type": "string", "description": "Databricks cluster ID to execute on"},
            "timeout_seconds": {"type": "integer", "minimum": 30, "maximum": 3600, "description": "Submission timeout in seconds"},
        },
    ),
    input_param="path",
    config_args=("cluster_id", "timeout_seconds"),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    host = (cfg.get("host") or "").strip().rstrip("/")
    token = (cfg.get("token") or "").strip()
    path = (inp or cfg.get("path") or "").strip()
    cluster_id = (cfg.get("cluster_id") or "").strip()

    missing = [name for name, value in {"host": host, "token": token, "path": path, "cluster_id": cluster_id}.items() if not value]
    if missing:
        return f"[Databricks Notebook Run] Missing required config: {', '.join(missing)}"

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "run_name": "pipesets-ai-notebook-run",
        "existing_cluster_id": cluster_id,
        "notebook_task": {"notebook_path": path},
    }
    timeout = int(cfg.get("timeout_seconds") or 300)

    try:
        async with httpx.AsyncClient(timeout=min(timeout, 30)) as client:
            resp = await client.post(f"{host}/api/2.1/jobs/runs/submit", json=payload, headers=headers)
            resp.raise_for_status()
            result = resp.json()
    except Exception as exc:
        return f"[Databricks Notebook Run] Error: {exc}"

    run_id = result.get("run_id") or "n/a"
    summary = {
        "run_id": run_id,
        "notebook_path": path,
        "cluster_id": cluster_id,
        "submitted": True,
    }
    return f"[Databricks Notebook Run]\n{json.dumps(summary, indent=2, sort_keys=True)}"
