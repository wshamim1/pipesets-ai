"""Databricks cancel run — built-in tool `databricks_cancel_run`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, params
from tools.data._databricks import missing, report, request

LABEL = "Databricks Cancel Run"

TOOL = ToolSpec(
    id="databricks_cancel_run",
    name=LABEL,
    icon="⏹️",
    category="Data & Files",
    description="Cancels an active Databricks job run. Cancellation is asynchronous; check the run status afterwards.",
    default_config={"host": "", "token": "", "run_id": ""},
    required=("host", "token"),
    order=320,
    parameters=params({"run_id": {"type": "string", "description": "Databricks run ID to cancel"}}),
    input_param="run_id",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    run_id = (inp or str(cfg.get("run_id") or "")).strip()
    problem = missing(LABEL, run_id=run_id)
    if problem:
        return problem
    body = {"run_id": int(run_id) if run_id.isdigit() else run_id}
    _, error = await request(LABEL, cfg, "POST", "/api/2.1/jobs/runs/cancel", body=body)
    if error:
        return error
    return report(LABEL, {"run_id": run_id, "cancel_requested": True})
