"""dbt Cloud — built-in tool `dbt_cloud` (dbt Cloud Administrative API v2).

Actions: ``jobs`` (the account's jobs), ``runs`` (recent runs, of one job when the input is a job id),
``run`` (one run with its steps; failed steps include the end of their logs) and ``trigger`` (start a
job). Auth is a service or personal token (``Authorization: Token …``). ``base_url`` is the account's
access URL — https://cloud.getdbt.com, or a regional / cell URL such as https://ab123.us1.dbt.com.
"""

from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[dbt Cloud]"
ACTIONS = ("runs", "run", "jobs", "trigger")
STATUS = {1: "Queued", 2: "Starting", 3: "Running", 10: "Success", 20: "Error", 30: "Cancelled"}
LOG_TAIL = 3000

TOOL = ToolSpec(
    id="dbt_cloud",
    name="dbt Cloud",
    icon="🟧",
    category="APIs & Integrations",
    description="Lists dbt Cloud jobs and runs, reads a run's steps with the logs of the failed ones, or triggers a job. Input: a job id (runs, trigger) or a run id (run).",
    default_config={"base_url": "https://cloud.getdbt.com", "account_id": "", "api_token": "", "action": "runs",
                    "max_results": 10},
    order=98,
    required=("account_id", "api_token"),
    selects={"action": Select("Action", (("runs", "Recent runs"), ("run", "One run with its steps"),
                                         ("jobs", "List jobs"), ("trigger", "Trigger a job")))},
    parameters=params({"id": {"type": "string", "description": "Job id (runs, trigger) or run id (run); empty for all runs / jobs"}},
                      {"action": enum(list(ACTIONS), "What to do"),
                       "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "description": "How many runs or jobs"}}),
    input_param="id",
    is_new=True,
)


def _status(run: Dict[str, Any]) -> str:
    return run.get("status_humanized") or STATUS.get(run.get("status"), str(run.get("status")))


def _run_line(r: Dict[str, Any]) -> str:
    job = (r.get("job") or {}).get("name") or f"job {r.get('job_definition_id')}"
    when = (r.get("finished_at") or r.get("created_at") or "")[:16].replace("T", " ")
    return f"- run {r.get('id')} · {job} · {_status(r)} · {when} · {r.get('duration_humanized') or ''}".rstrip(" ·")


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    account = str(cfg.get("account_id") or "").strip()
    token = (cfg.get("api_token") or "").strip()
    if not account or not token:
        return f"{LABEL} account_id and api_token are required in config."
    action = cfg.get("action") or "runs"
    if action not in ACTIONS:
        return f"{LABEL} Action is one of {', '.join(ACTIONS)} — got '{action}'."
    ident = inp.strip().strip("'\"#")
    if action in ("run", "trigger") and not ident.isdigit():
        return f"{LABEL} Provide the {'run' if action == 'run' else 'job'} id (a number)."
    limit = max(1, min(int(cfg.get("max_results") or 10), 50))
    api = f"{(cfg.get('base_url') or 'https://cloud.getdbt.com').strip().rstrip('/')}/api/v2/accounts/{account}"
    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"Authorization": f"Token {token}",
                                                            "Accept": "application/json"}) as client:
            if action == "jobs":
                resp = await client.get(f"{api}/jobs/", params={"limit": limit, "order_by": "name"})
            elif action == "runs":
                q: Dict[str, Any] = {"order_by": "-id", "limit": limit, "include_related": '["job"]'}
                if ident.isdigit():
                    q["job_definition_id"] = ident
                resp = await client.get(f"{api}/runs/", params=q)
            elif action == "run":
                resp = await client.get(f"{api}/runs/{ident}/", params={"include_related": '["run_steps","job"]'})
            else:
                resp = await client.post(f"{api}/jobs/{ident}/run/", json={"cause": "Triggered from Pipesets"})
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach dbt Cloud: {e}"
    if resp.status_code in (401, 403):
        return f"{LABEL} HTTP {resp.status_code} — check api_token, and that it can access account {account}."
    if resp.status_code == 404:
        return f"{LABEL} Not found — check account_id, and the {'run' if action == 'run' else 'job'} id."
    if resp.status_code >= 400:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:300]}"
    data = resp.json().get("data")

    if action == "jobs":
        if not data:
            return f"{LABEL} No jobs in account {account}."
        return f"{LABEL} {len(data)} job(s)\n" + "\n".join(
            f"- {j.get('id')} · {j.get('name')} · {'active' if j.get('state') == 1 else 'inactive'}"
            + (f" · {(j.get('schedule') or {}).get('cron')}" if (j.get("triggers") or {}).get("schedule") else "")
            for j in data)
    if action == "runs":
        if not data:
            return f"{LABEL} No runs" + (f" for job {ident}." if ident else ".")
        return f"{LABEL} {len(data)} recent run(s)" + (f" of job {ident}" if ident else "") + "\n" + "\n".join(map(_run_line, data))
    if action == "trigger":
        return f"{LABEL} Triggered job {ident}: run {data.get('id')} is {_status(data)}.\n{data.get('href') or ''}".rstrip()

    lines = [f"{LABEL} Run {data.get('id')} · {(data.get('job') or {}).get('name') or ''} · {_status(data)}",
             f"  Started : {(data.get('started_at') or data.get('created_at') or '')[:19]}",
             f"  Duration: {data.get('duration_humanized') or ''}  Branch: {data.get('git_branch') or ''}",
             f"  URL     : {data.get('href') or ''}"]
    for step in data.get("run_steps") or []:
        lines.append(f"  - {step.get('name')}: {step.get('status_humanized') or STATUS.get(step.get('status'), '')}")
        if step.get("status") == 20 or (step.get("status_humanized") or "").lower() == "error":
            logs = step.get("logs") or step.get("truncated_debug_logs") or ""
            if logs:
                lines.append("    Log (end):\n" + "\n".join("      " + ln for ln in logs[-LOG_TAIL:].splitlines()))
    return "\n".join(lines)
