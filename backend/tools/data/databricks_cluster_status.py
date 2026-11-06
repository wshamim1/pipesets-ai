"""Databricks cluster status — built-in tool `databricks_cluster_status`."""

import json
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="databricks_cluster_status",
    name="Databricks Cluster Status",
    icon="⚙️",
    category="DevOps & Observability",
    description="Fetches the current status and sizing details for a Databricks cluster using the workspace REST API.",
    default_config={"host": "", "token": "", "cluster_id": ""},
    required=("host", "token"),
    order=230,
    parameters=params(
        {"cluster_id": {"type": "string", "description": "Databricks cluster ID to inspect"}},
        {"include_state": {"type": "boolean", "description": "Include the cluster state in the output"}},
    ),
    input_param="cluster_id",
    config_args=("include_state",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    host = (cfg.get("host") or "").strip().rstrip("/")
    token = (cfg.get("token") or "").strip()
    cluster_id = (inp or cfg.get("cluster_id") or "").strip()

    missing = [name for name, value in {"host": host, "token": token, "cluster_id": cluster_id}.items() if not value]
    if missing:
        return f"[Databricks Cluster Status] Missing required config: {', '.join(missing)}"

    url = f"{host}/api/2.0/clusters/get"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params={"cluster_id": cluster_id}, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        return f"[Databricks Cluster Status] Error: {exc}"

    cluster = payload.get("cluster_attributes", {}) or payload.get("cluster", {}) or payload
    state = cluster.get("state") or cluster.get("state_message") or "unknown"
    node_type = cluster.get("node_type_id") or cluster.get("node_type") or "n/a"
    spark_version = cluster.get("spark_version") or "n/a"
    driver = cluster.get("driver", {})
    driver_node = driver.get("node_id") or driver.get("instance_id") or "n/a"
    runtime = json.dumps({
        "cluster_id": cluster.get("cluster_id") or cluster_id,
        "state": state,
        "node_type_id": node_type,
        "spark_version": spark_version,
        "driver_node_id": driver_node,
    }, indent=2, sort_keys=True)
    return f"[Databricks Cluster Status]\n{runtime}"
