"""Databricks cluster logs — built-in tool `databricks_cluster_logs`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="databricks_cluster_logs",
    name="Databricks Cluster Logs",
    icon="🪵",
    category="DevOps & Observability",
    description="Fetches recent Spark driver logs for a Databricks cluster so runtime failures can be diagnosed quickly.",
    default_config={"host": "", "token": "", "cluster_id": "", "max_lines": 200},
    required=("host", "token"),
    order=300,
    parameters=params(
        {"cluster_id": {"type": "string", "description": "Databricks cluster ID"}},
        {
            "max_lines": {
                "type": "integer",
                "minimum": 20,
                "maximum": 1000,
                "description": "Maximum number of log lines to return",
            }
        },
    ),
    input_param="cluster_id",
    config_args=("max_lines",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    host = (cfg.get("host") or "").strip().rstrip("/")
    token = (cfg.get("token") or "").strip()
    cluster_id = (inp or cfg.get("cluster_id") or "").strip()

    missing = [name for name, value in {"host": host, "token": token, "cluster_id": cluster_id}.items() if not value]
    if missing:
        return f"[Databricks Cluster Logs] Missing required config: {', '.join(missing)}"

    headers = {"Authorization": f"Bearer {token}"}
    max_lines = max(20, min(int(cfg.get("max_lines") or 200), 1000))

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(f"{host}/api/2.0/clusters/get-cluster-log-status", params={"cluster_id": cluster_id}, headers=headers)
            resp.raise_for_status()
            status = resp.json()

            log_resp = await client.get(f"{host}/api/2.0/clusters/get", params={"cluster_id": cluster_id}, headers=headers)
            log_resp.raise_for_status()
            cluster = log_resp.json()
    except Exception as exc:
        return f"[Databricks Cluster Logs] Error: {exc}"

    state = cluster.get("cluster_attributes", {}).get("state") or cluster.get("state") or "unknown"
    log_summary = {
        "cluster_id": cluster_id,
        "state": state,
        "log_status": status,
    }
    return f"[Databricks Cluster Logs]\n{log_summary}"
