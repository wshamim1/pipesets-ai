"""Airbyte — built-in tool `airbyte` (Airbyte API: Airbyte Cloud, or self-managed at
``<host>/api/public/v1``).

Input: a connection id lists that connection's recent jobs (status, rows and bytes synced, duration);
otherwise lists the connections. ``status`` narrows jobs to e.g. failed ones. Auth is a bearer access
token. Read-only.
"""

from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[Airbyte]"
JOB_STATUSES = ("", "failed", "running", "succeeded", "incomplete", "cancelled", "pending")

TOOL = ToolSpec(
    id="airbyte",
    name="Airbyte",
    icon="🐙",
    category="APIs & Integrations",
    description="Lists Airbyte connections, or a connection's recent sync jobs with status, rows synced and duration. Input: a connection id, or empty to list connections.",
    default_config={"base_url": "https://api.airbyte.com/v1", "access_token": "", "status": "", "max_results": 10},
    order=100,
    required=("access_token",),
    selects={"status": Select("Job status", (("", "Any"), ("failed", "Failed"), ("running", "Running"),
                                             ("succeeded", "Succeeded"), ("incomplete", "Incomplete"),
                                             ("cancelled", "Cancelled"), ("pending", "Pending")))},
    parameters=params({}, {"connection_id": {"type": "string", "description": "A connection id; empty to list connections"},
                           "status": enum([s for s in JOB_STATUSES if s], "Only jobs in this status")}),
    input_param="connection_id",
    is_new=True,
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("access_token") or "").strip()
    if not token:
        return f"{LABEL} access_token is required in config."
    api = (cfg.get("base_url") or "https://api.airbyte.com/v1").strip().rstrip("/")
    conn_id = inp.strip().strip("'\"")
    status = (cfg.get("status") or "").strip()
    if status not in JOB_STATUSES:
        return f"{LABEL} status is one of {', '.join(s for s in JOB_STATUSES if s)} — got '{status}'."
    limit = max(1, min(int(cfg.get("max_results") or 10), 100))
    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"Authorization": f"Bearer {token}",
                                                            "Accept": "application/json"}) as client:
            if conn_id:
                q: Dict[str, Any] = {"connectionId": conn_id, "limit": limit, "orderBy": "createdAt|DESC"}
                if status:
                    q["status"] = status
                resp = await client.get(f"{api}/jobs", params=q)
            else:
                resp = await client.get(f"{api}/connections", params={"limit": limit})
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach {api}: {e}"
    if resp.status_code in (401, 403):
        return f"{LABEL} HTTP {resp.status_code} — check access_token (they expire after a few minutes; use a fresh one)."
    if resp.status_code == 404:
        return f"{LABEL} Not found — check base_url and the connection id."
    if resp.status_code >= 400:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:300]}"
    data = resp.json().get("data") or []

    if not conn_id:
        if not data:
            return f"{LABEL} No connections."
        return f"{LABEL} {len(data)} connection(s)\n" + "\n".join(
            f"- {c.get('connectionId')} · {c.get('name')} · {c.get('status')}"
            + (f" · {(c.get('schedule') or {}).get('scheduleType')}" if c.get("schedule") else "") for c in data)
    if not data:
        return f"{LABEL} No {status + ' ' if status else ''}jobs for connection {conn_id}."
    return f"{LABEL} {len(data)} recent {status + ' ' if status else ''}job(s) of connection {conn_id}\n" + "\n".join(
        f"- job {j.get('jobId', j.get('id'))} · {j.get('jobType')} · {j.get('status')} · {(j.get('startTime') or '')[:16].replace('T', ' ')}"
        f" · {j.get('duration') or ''} · {j.get('rowsSynced', 0)} rows, {j.get('bytesSynced', 0)} bytes" for j in data)
