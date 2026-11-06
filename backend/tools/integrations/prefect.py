"""Prefect — built-in tool `prefect` (Prefect REST API: Prefect Cloud or a self-hosted server).

``api_url`` is the workspace API — https://api.prefect.cloud/api/accounts/<account>/workspaces/<workspace>
for Cloud, http://<host>:4200/api for a server. Input: a flow run id reads that run and its last log
lines; otherwise lists recent flow runs (``state`` filters, e.g. failed / crashed). ``api_key`` is
needed for Cloud only. Read-only.
"""

from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[Prefect]"
STATES = {"failed": ["FAILED", "CRASHED"], "running": ["RUNNING"], "completed": ["COMPLETED"],
          "scheduled": ["SCHEDULED", "PENDING"], "cancelled": ["CANCELLED", "CANCELLING"], "any": []}
LOG_LINES = 40

TOOL = ToolSpec(
    id="prefect",
    name="Prefect",
    icon="🌀",
    category="APIs & Integrations",
    description="Lists recent Prefect flow runs (e.g. failed or crashed ones), or reads one run with its state and last log lines. Input: a flow run id, or empty to list runs.",
    default_config={"api_url": "", "api_key": "", "state": "failed", "max_results": 10},
    order=101,
    required=("api_url",),
    selects={"state": Select("Runs to list", (("failed", "Failed or crashed"), ("running", "Running"),
                                              ("completed", "Completed"), ("scheduled", "Scheduled"),
                                              ("cancelled", "Cancelled"), ("any", "Any state")))},
    parameters=params({}, {"flow_run_id": {"type": "string", "description": "A flow run id; empty to list runs"},
                           "state": enum(list(STATES), "Which runs to list")}),
    input_param="flow_run_id",
    is_new=True,
)


def _when(ts: Optional[str]) -> str:
    return (ts or "")[:16].replace("T", " ")


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    api = (cfg.get("api_url") or "").strip().rstrip("/")
    if not api:
        return f"{LABEL} api_url is required in config (Cloud: https://api.prefect.cloud/api/accounts/<id>/workspaces/<id>)."
    state = cfg.get("state") or "failed"
    if state not in STATES:
        return f"{LABEL} state is one of {', '.join(STATES)} — got '{state}'."
    key = (cfg.get("api_key") or "").strip()
    run_id = inp.strip().strip("'\"")
    limit = max(1, min(int(cfg.get("max_results") or 10), 50))
    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"Authorization": f"Bearer {key}"} if key else {}) as client:
            if run_id:
                resp = await client.get(f"{api}/flow_runs/{run_id}")
                logs = None
                if resp.status_code < 400:
                    logs = await client.post(f"{api}/logs/filter", json={
                        "logs": {"flow_run_id": {"any_": [run_id]}}, "sort": "TIMESTAMP_DESC", "limit": LOG_LINES})
            else:
                body: Dict[str, Any] = {"sort": "START_TIME_DESC", "limit": limit}
                if STATES[state]:
                    body["flow_runs"] = {"state": {"type": {"any_": STATES[state]}}}
                resp = await client.post(f"{api}/flow_runs/filter", json=body)
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach {api}: {e}"
    if resp.status_code in (401, 403):
        return f"{LABEL} HTTP {resp.status_code} — check api_key and that api_url is the right workspace."
    if resp.status_code == 404:
        return f"{LABEL} Not found — check api_url" + (f" and flow run '{run_id}'." if run_id else ".")
    if resp.status_code >= 400:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:300]}"
    data = resp.json()

    if not run_id:
        if not data:
            return f"{LABEL} No {'' if state == 'any' else state + ' '}flow runs."
        return f"{LABEL} {len(data)} {'' if state == 'any' else state + ' '}flow run(s), newest first\n" + "\n".join(
            f"- {r.get('id')} · {r.get('name')} · {r.get('state_name') or r.get('state_type')} · {_when(r.get('start_time') or r.get('expected_start_time'))}"
            for r in data)
    st = data.get("state") or {}
    lines = [f"{LABEL} Flow run {data.get('name')} ({data.get('id')}) · {data.get('state_name') or data.get('state_type')}",
             f"  Started: {_when(data.get('start_time'))} · Ended: {_when(data.get('end_time'))} · "
             f"Runtime: {round(data.get('total_run_time') or 0)}s",
             f"  Deployment: {data.get('deployment_id') or '—'}"]
    if st.get("message"):
        lines.append(f"  State message: {st['message']}")
    entries = logs.json() if logs is not None and logs.status_code < 400 else []
    if entries:
        lines.append("  Last log lines:")
        lines += [f"    {_when(e.get('timestamp'))} {e.get('message')}" for e in reversed(entries)]
    return "\n".join(lines)
