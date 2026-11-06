"""Databricks list jobs — built-in tool `databricks_list_jobs`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, params
from tools.data._databricks import report, request

LABEL = "Databricks List Jobs"

TOOL = ToolSpec(
    id="databricks_list_jobs",
    name=LABEL,
    icon="📋",
    category="Data & Files",
    description="Lists jobs in a Databricks workspace, optionally filtered by name, with their IDs and schedules.",
    default_config={"host": "", "token": "", "limit": 25},
    required=("host", "token"),
    order=310,
    parameters=params(
        {},
        {
            "name": {"type": "string", "description": "Only jobs whose name matches exactly (case-insensitive)"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Maximum jobs to return"},
        },
    ),
    input_param="name",
    config_args=("limit",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    query: Dict[str, Any] = {"limit": min(int(cfg.get("limit") or 25), 100)}
    if inp:
        query["name"] = inp
    data, error = await request(LABEL, cfg, "GET", "/api/2.1/jobs/list", params=query)
    if error:
        return error
    jobs = [
        {
            "job_id": job.get("job_id"),
            "name": (job.get("settings") or {}).get("name"),
            "creator": job.get("creator_user_name"),
            "schedule": ((job.get("settings") or {}).get("schedule") or {}).get("quartz_cron_expression"),
        }
        for job in data.get("jobs") or []
    ]
    return report(LABEL, {"count": len(jobs), "has_more": bool(data.get("has_more")), "jobs": jobs})
