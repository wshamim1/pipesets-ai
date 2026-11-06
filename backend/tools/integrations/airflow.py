"""Apache Airflow — built-in tool `airflow` (stable REST API: v1 for Airflow 2, v2 for Airflow 3)."""

from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params
from tools.integrations import _airflow as af

TOOL = ToolSpec(
    id="airflow",
    name="Apache Airflow",
    icon="🌬️",
    category="APIs & Integrations",
    description="Inspect and trigger Apache Airflow DAGs: list DAGs, see recent runs and task states, or trigger a run (trigger must be enabled on the node). Input: the DAG id.",
    default_config={**af.CONNECTION_CONFIG, "action": "list_dags", "allow_trigger": False, "max_results": 10},
    order=30,
    required=("base_url",),
    selects={
        "api_version": af.VERSION_SELECT,
        "action": Select("Action", (("list_dags", "List DAGs"), ("dag_runs", "Recent runs of a DAG"),
                                    ("task_instances", "Task states of a run"), ("trigger", "Trigger a DAG run"))),
    },
    parameters=params(
        {},
        {
            "dag_id": {"type": "string", "description": "The DAG id (not needed to list DAGs)"},
            "action": enum(["list_dags", "dag_runs", "task_instances", "trigger"], "What to do"),
            "dag_run_id": {"type": "string", "description": "A run id; for task_instances, defaults to the latest run"},
            "conf": {"type": "object", "description": "JSON configuration to pass when triggering a run"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "description": "How many items to return"},
        },
    ),
    input_param="dag_id",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    api = af.api_url(cfg)
    if not api:
        return af.NO_BASE_URL
    action = cfg.get("action") or "list_dags"
    dag_id = inp.strip()
    run_id = (cfg.get("dag_run_id") or "").strip()
    try:
        limit = max(1, min(int(cfg.get("max_results", 10)), 100))
    except (TypeError, ValueError):
        limit = 10

    if action != "list_dags" and not dag_id:
        return f"[Airflow] Provide the DAG id for '{action}'."

    try:
        async with af.client(cfg) as client:
            if action == "list_dags":
                resp = await client.get(f"{api}/dags", params={"limit": limit, "order_by": "dag_id"})
                if err := af.failed(resp):
                    return err
                dags = resp.json().get("dags", [])
                if not dags:
                    return "[Airflow] No DAGs found."
                lines = [f"[Airflow] {len(dags)} DAG(s)"]
                for d in dags:
                    state = "paused" if d.get("is_paused") else "active"
                    lines.append(f"  {d.get('dag_id')} [{state}] — next run {af.short(d.get('next_dagrun')) or 'n/a'}")
                return "\n".join(lines)

            if action == "dag_runs":
                resp = await client.get(f"{api}/dags/{dag_id}/dagRuns", params={"limit": limit, "order_by": "-start_date"})
                if err := af.failed(resp):
                    return err
                runs = resp.json().get("dag_runs", [])
                if not runs:
                    return f"[Airflow] No runs for {dag_id}."
                lines = [f"[Airflow] Last {len(runs)} run(s) of {dag_id}"]
                for r in runs:
                    lines.append(f"  {r.get('dag_run_id')} [{r.get('state')}] started {af.short(r.get('start_date'))}"
                                 f" ended {af.short(r.get('end_date')) or '—'}")
                return "\n".join(lines)

            if action == "task_instances":
                if not run_id:
                    run_id, err = await af.latest_run_id(client, api, dag_id)
                    if err:
                        return err
                resp = await client.get(f"{api}/dags/{dag_id}/dagRuns/{run_id}/taskInstances", params={"limit": 100})
                if err := af.failed(resp):
                    return err
                tasks = resp.json().get("task_instances", [])
                lines = [f"[Airflow] {dag_id} / {run_id}: {len(tasks)} task(s)"]
                for t in tasks:
                    lines.append(f"  {t.get('task_id')} [{t.get('state') or 'no state'}] try {t.get('try_number')}"
                                 f" ended {af.short(t.get('end_date')) or '—'}")
                return "\n".join(lines)

            if action == "trigger":
                if cfg.get("allow_trigger") is not True:
                    return "[Airflow] Triggering runs is disabled; set allow_trigger to true on the node."
                body: Dict[str, Any] = {"conf": cfg.get("conf") or {}}
                if run_id:
                    body["dag_run_id"] = run_id
                if cfg.get("api_version") == "v2":
                    body["logical_date"] = None   # required (nullable) by the Airflow 3 API
                resp = await client.post(f"{api}/dags/{dag_id}/dagRuns", json=body)
                if err := af.failed(resp):
                    return err
                r = resp.json()
                return f"[Airflow] Triggered {dag_id}: run {r.get('dag_run_id')} is {r.get('state')}"

            return f"[Airflow] Unknown action '{action}'."
    except httpx.HTTPError as e:
        return f"[Airflow] Error: {e}"
