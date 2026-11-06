"""Databricks list clusters — built-in tool `databricks_list_clusters`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, enum, params
from tools.data._databricks import report, request

LABEL = "Databricks List Clusters"

TOOL = ToolSpec(
    id="databricks_list_clusters",
    name=LABEL,
    icon="🖧",
    category="Data & Files",
    description="Lists all-purpose and job clusters in a Databricks workspace with their state, runtime and size.",
    default_config={"host": "", "token": ""},
    required=("host", "token"),
    order=325,
    parameters=params(
        {},
        {"state": enum(["RUNNING", "TERMINATED", "PENDING", "RESTARTING", "RESIZING", "TERMINATING", "ERROR"],
                       "Only clusters in this state")},
    ),
    input_param="state",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    data, error = await request(LABEL, cfg, "GET", "/api/2.0/clusters/list")
    if error:
        return error
    state = inp.upper()
    clusters = [
        {
            "cluster_id": c.get("cluster_id"),
            "name": c.get("cluster_name"),
            "state": c.get("state"),
            "spark_version": c.get("spark_version"),
            "node_type": c.get("node_type_id"),
            "workers": c.get("num_workers"),
            "autoscale": c.get("autoscale"),
            "source": c.get("cluster_source"),
        }
        for c in data.get("clusters") or []
        if not state or c.get("state") == state
    ]
    return report(LABEL, {"count": len(clusters), "clusters": clusters})
