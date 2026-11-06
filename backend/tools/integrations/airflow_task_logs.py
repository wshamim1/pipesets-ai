"""Apache Airflow task logs — built-in tool `airflow_task_logs`.

Fetches the log of one task try (plain text), trimmed to the tail: the traceback is at the end.
"""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params
from tools.integrations import _airflow as af

MAX_CHARS = 6000

TOOL = ToolSpec(
    id="airflow_task_logs",
    name="Airflow Task Logs",
    icon="📜",
    category="APIs & Integrations",
    description="Read the log of an Apache Airflow task — the last part, where the error is. Input: the DAG id. The run defaults to the latest; the task defaults to the first failed one.",
    default_config={**af.CONNECTION_CONFIG, "max_chars": MAX_CHARS},
    order=31,
    required=("base_url",),
    selects={"api_version": af.VERSION_SELECT},
    parameters=params(
        {"dag_id": {"type": "string", "description": "The DAG id"}},
        {
            "dag_run_id": {"type": "string", "description": "A run id (default: the latest run)"},
            "task_id": {"type": "string", "description": "A task id (default: the first failed task of the run)"},
            "try_number": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Which try (default: the latest)"},
        },
    ),
    input_param="dag_id",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    api = af.api_url(cfg)
    if not api:
        return af.NO_BASE_URL
    dag_id = inp.strip()
    if not dag_id:
        return "[Airflow] Provide the DAG id."
    run_id = (cfg.get("dag_run_id") or "").strip()
    task_id = (cfg.get("task_id") or "").strip()
    try:
        limit = max(500, min(int(cfg.get("max_chars", MAX_CHARS)), 20000))
    except (TypeError, ValueError):
        limit = MAX_CHARS

    try:
        async with af.client(cfg) as client:
            if not run_id:
                run_id, err = await af.latest_run_id(client, api, dag_id)
                if err:
                    return err
            tries = cfg.get("try_number")
            if not task_id or not tries:
                resp = await client.get(f"{api}/dags/{dag_id}/dagRuns/{run_id}/taskInstances", params={"limit": 100})
                if err := af.failed(resp):
                    return err
                tasks = resp.json().get("task_instances", [])
                if task_id:
                    task = next((t for t in tasks if t.get("task_id") == task_id), None)
                else:
                    task = next((t for t in tasks if t.get("state") in ("failed", "upstream_failed")), None)
                    if task is None:
                        return f"[Airflow] No failed tasks in {dag_id} / {run_id}; give a task_id to read any task's log."
                    task_id = task["task_id"]
                if task is None:
                    return f"[Airflow] Task {task_id} isn't in {dag_id} / {run_id}."
                tries = tries or task.get("try_number") or 1

            # Airflow 2 answers plain text; Airflow 3 only JSON, whose content is a string or a list of log records
            v2 = cfg.get("api_version") == "v2"
            resp = await client.get(f"{api}/dags/{dag_id}/dagRuns/{run_id}/taskInstances/{task_id}/logs/{tries}",
                                    params={"full_content": "true"},
                                    headers={"Accept": "application/json" if v2 else "text/plain"})
            if err := af.failed(resp):
                return err
            text = resp.text
            if v2:
                content = resp.json().get("content", "")
                text = content if isinstance(content, str) else "\n".join(
                    str(r.get("event", r)) if isinstance(r, dict) else str(r) for r in content)
            text = text.strip()
            if not text:
                return f"[Airflow] No log for {dag_id} / {run_id} / {task_id} (try {tries}) yet."
            cut = len(text) > limit
            return (f"[Airflow Log] {dag_id} / {run_id} / {task_id}, try {tries}"
                    + (f" (last {limit} of {len(text)} characters)" if cut else "") + "\n" + text[-limit:])
    except httpx.HTTPError as e:
        return f"[Airflow] Error: {e}"
