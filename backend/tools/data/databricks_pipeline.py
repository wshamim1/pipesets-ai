"""Databricks pipeline — built-in tool `databricks_pipeline`: status of a Lakeflow Declarative
(Delta Live Tables) pipeline and its recent updates, or start a new update."""

from typing import Any, Dict, Optional

from tools.base import Select, ToolSpec, enum, params
from tools.data._databricks import missing, report, request

LABEL = "Databricks Pipeline"

TOOL = ToolSpec(
    id="databricks_pipeline",
    name=LABEL,
    icon="🔀",
    category="Data & Files",
    description="Shows a Databricks Lakeflow / Delta Live Tables pipeline's state and recent updates, or starts an update.",
    default_config={"host": "", "token": "", "pipeline_id": "", "action": "status", "full_refresh": False},
    required=("host", "token"),
    selects={"action": Select("Action", [("status", "Status"), ("start", "Start update")])},
    order=365,
    parameters=params(
        {"pipeline_id": {"type": "string", "description": "Pipeline ID"}},
        {
            "action": enum(["status", "start"], "Read the status, or start a new update"),
            "full_refresh": {"type": "boolean", "description": "With start: reprocess all data from scratch"},
        },
    ),
    input_param="pipeline_id",
    config_args=("action", "full_refresh"),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    pipeline_id = (inp or cfg.get("pipeline_id") or "").strip()
    problem = missing(LABEL, pipeline_id=pipeline_id)
    if problem:
        return problem
    base = f"/api/2.0/pipelines/{pipeline_id}"

    if str(cfg.get("action") or "status").lower() == "start":
        data, error = await request(LABEL, cfg, "POST", f"{base}/updates",
                                    body={"full_refresh": bool(cfg.get("full_refresh"))})
        if error:
            return error
        return report(LABEL, {"pipeline_id": pipeline_id, "update_id": data.get("update_id"), "started": True})

    data, error = await request(LABEL, cfg, "GET", base)
    if error:
        return error
    updates, error = await request(LABEL, cfg, "GET", f"{base}/updates", params={"max_results": 5})
    if error:
        return error
    return report(LABEL, {
        "pipeline_id": pipeline_id,
        "name": data.get("name"),
        "state": data.get("state"),
        "health": data.get("health"),
        "creator": data.get("creator_user_name"),
        "latest_updates": [{"update_id": u.get("update_id"), "state": u.get("state"),
                            "creation_time": u.get("creation_time"), "full_refresh": u.get("full_refresh")}
                           for u in updates.get("updates") or []],
    })
