"""Databricks run job — built-in tool `databricks_run_job`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, params
from tools.data._databricks import missing, report, request

LABEL = "Databricks Run Job"

TOOL = ToolSpec(
    id="databricks_run_job",
    name=LABEL,
    icon="🚀",
    category="Data & Files",
    description="Triggers a run of an existing Databricks job (run-now), optionally with job parameters, and returns the run ID.",
    default_config={"host": "", "token": "", "job_id": ""},
    required=("host", "token"),
    order=315,
    parameters=params(
        {"job_id": {"type": "string", "description": "Databricks job ID to run"}},
        {
            "job_parameters": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Job-level parameters as name → value",
            }
        },
    ),
    input_param="job_id",
    config_args=("job_parameters",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    job_id = (inp or str(cfg.get("job_id") or "")).strip()
    problem = missing(LABEL, job_id=job_id)
    if problem:
        return problem
    body: Dict[str, Any] = {"job_id": int(job_id) if job_id.isdigit() else job_id}
    if cfg.get("job_parameters"):
        body["job_parameters"] = cfg["job_parameters"]
    data, error = await request(LABEL, cfg, "POST", "/api/2.1/jobs/run-now", body=body)
    if error:
        return error
    return report(LABEL, {"job_id": job_id, "run_id": data.get("run_id"), "number_in_job": data.get("number_in_job")})
