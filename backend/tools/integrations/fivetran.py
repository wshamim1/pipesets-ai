"""Fivetran — built-in tool `fivetran` (Fivetran REST API, /v1/connections).

Input: a connection id reads that connection (setup / sync state, last success and failure, open
tasks and warnings); otherwise lists the connections — those in ``group_id`` when set — with broken,
failing and paused ones first. Auth is HTTP basic with the API key and secret. Read-only.
"""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

LABEL = "[Fivetran]"
API = "https://api.fivetran.com/v1"

TOOL = ToolSpec(
    id="fivetran",
    name="Fivetran",
    icon="🔵",
    category="APIs & Integrations",
    description="Checks Fivetran connections: sync and setup state, last success and failure, open tasks and warnings. Input: a connection id, or empty to list connections (broken and failing first).",
    default_config={"api_key": "", "api_secret": "", "group_id": "", "max_results": 50},
    order=99,
    required=("api_key", "api_secret"),
    parameters=params({}, {"connection_id": {"type": "string", "description": "A connection id; empty to list connections"},
                           "group_id": {"type": "string", "description": "Only list connections in this group (destination)"}}),
    input_param="connection_id",
    is_new=True,
)


def _health(c: Dict[str, Any]) -> str:
    st = c.get("status") or {}
    if st.get("setup_state") == "broken":
        return "BROKEN"
    if c.get("failed_at") and (not c.get("succeeded_at") or c["failed_at"] > c["succeeded_at"]):
        return "FAILING"
    if c.get("paused"):
        return "paused"
    return st.get("sync_state") or "ok"


def _when(ts: Optional[str]) -> str:
    return (ts or "never")[:16].replace("T", " ")


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    key, secret = (cfg.get("api_key") or "").strip(), (cfg.get("api_secret") or "").strip()
    if not key or not secret:
        return f"{LABEL} api_key and api_secret are required in config."
    conn_id = inp.strip().strip("'\"")
    try:
        async with httpx.AsyncClient(timeout=20.0, auth=(key, secret),
                                     headers={"Accept": "application/json;version=2"}) as client:
            if conn_id:
                resp = await client.get(f"{API}/connections/{conn_id}")
            else:
                q: Dict[str, Any] = {"limit": max(1, min(int(cfg.get("max_results") or 50), 1000))}
                if (cfg.get("group_id") or "").strip():
                    q["group_id"] = cfg["group_id"].strip()
                resp = await client.get(f"{API}/connections", params=q)
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach Fivetran: {e}"
    if resp.status_code in (401, 403):
        return f"{LABEL} HTTP {resp.status_code} — check api_key and api_secret."
    if resp.status_code == 404:
        return f"{LABEL} Connection '{conn_id}' not found."
    if resp.status_code >= 400:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:300]}"
    data = resp.json().get("data") or {}

    if not conn_id:
        items = data.get("items") or []
        if not items:
            return f"{LABEL} No connections" + (f" in group {cfg.get('group_id')}." if cfg.get("group_id") else ".")
        rank = {"BROKEN": 0, "FAILING": 1, "paused": 3}
        items.sort(key=lambda c: rank.get(_health(c), 2))
        return f"{LABEL} {len(items)} connection(s)\n" + "\n".join(
            f"- {c.get('id')} · {c.get('schema')} ({c.get('service')}) · {_health(c)} · last success {_when(c.get('succeeded_at'))}"
            for c in items)

    st = data.get("status") or {}
    lines = [f"{LABEL} {data.get('schema')} ({data.get('service')}) · {_health(data)}",
             f"  Setup: {st.get('setup_state')} · Sync: {st.get('sync_state')} · Schedule: {st.get('update_state')}"
             + (" · historical sync running" if st.get("is_historical_sync") else ""),
             f"  Last success: {_when(data.get('succeeded_at'))} · Last failure: {_when(data.get('failed_at'))}",
             f"  Sync every {data.get('sync_frequency')} min" + (" · PAUSED" if data.get("paused") else "")]
    for kind in ("tasks", "warnings"):
        for t in st.get(kind) or []:
            lines.append(f"  {kind[:-1].capitalize()}: {t.get('code')} — {t.get('message')}")
    return "\n".join(lines)
