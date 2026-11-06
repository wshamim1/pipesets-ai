"""Databricks cluster control — built-in tool `databricks_cluster_control`."""

from typing import Any, Dict, Optional

from tools.base import Select, ToolSpec, enum, params
from tools.data._databricks import missing, report, request

LABEL = "Databricks Cluster Control"

# action → clusters API endpoint ("delete" terminates; it does not remove the cluster)
ACTIONS = {"start": "/api/2.0/clusters/start", "restart": "/api/2.0/clusters/restart",
           "terminate": "/api/2.0/clusters/delete"}

TOOL = ToolSpec(
    id="databricks_cluster_control",
    name=LABEL,
    icon="🎛️",
    category="Data & Files",
    description="Starts, restarts or terminates a Databricks cluster. Terminating keeps the cluster configuration.",
    default_config={"host": "", "token": "", "cluster_id": "", "action": "start"},
    required=("host", "token"),
    selects={"action": Select("Action", [("start", "Start"), ("restart", "Restart"), ("terminate", "Terminate")])},
    order=330,
    parameters=params(
        {"cluster_id": {"type": "string", "description": "Databricks cluster ID"}},
        {"action": enum(list(ACTIONS), "What to do with the cluster")},
    ),
    input_param="cluster_id",
    config_args=("action",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    cluster_id = (inp or cfg.get("cluster_id") or "").strip()
    action = str(cfg.get("action") or "start").lower()
    problem = missing(LABEL, cluster_id=cluster_id)
    if problem:
        return problem
    if action not in ACTIONS:
        return f"[{LABEL}] Unknown action '{action}'. Use one of: {', '.join(ACTIONS)}"
    _, error = await request(LABEL, cfg, "POST", ACTIONS[action], body={"cluster_id": cluster_id})
    if error:
        return error
    return report(LABEL, {"cluster_id": cluster_id, "action": action, "requested": True})
