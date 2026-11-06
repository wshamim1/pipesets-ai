"""Databricks cluster events — built-in tool `databricks_cluster_events`."""

import json
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="databricks_cluster_events",
    name="Databricks Cluster Events",
    icon="📣",
    category="DevOps & Observability",
    description="Fetches recent lifecycle and runtime events for a Databricks cluster to diagnose startup, health, and failover issues.",
    default_config={"host": "", "token": "", "cluster_id": "", "max_events": 20},
    required=("host", "token"),
    order=305,
    parameters=params(
        {"cluster_id": {"type": "string", "description": "Databricks cluster ID"}},
        {
            "max_events": {
                "type": "integer",
                "minimum": 5,
                "maximum": 200,
                "description": "Maximum number of recent events to return",
            }
        },
    ),
    input_param="cluster_id",
    config_args=("max_events",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    host = (cfg.get("host") or "").strip().rstrip("/")
    token = (cfg.get("token") or "").strip()
    cluster_id = (inp or cfg.get("cluster_id") or "").strip()

    missing = [name for name, value in {"host": host, "token": token, "cluster_id": cluster_id}.items() if not value]
    if missing:
        return f"[Databricks Cluster Events] Missing required config: {', '.join(missing)}"

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    max_events = max(5, min(int(cfg.get("max_events") or 20), 200))

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{host}/api/2.0/clusters/events",
                params={"cluster_id": cluster_id, "limit": max_events},
                headers=headers,
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        return f"[Databricks Cluster Events] Error: {exc}"

    events = payload.get("events") if isinstance(payload, dict) else payload
    if isinstance(events, dict):
        events = events.get("items") or events.get("results") or []
    if not isinstance(events, list):
        events = []
    if not events:
        return f"[Databricks Cluster Events] No events returned for cluster {cluster_id}."

    lines = []
    for event in events[:max_events]:
        if isinstance(event, dict):
            ts = event.get("timestamp") or event.get("event_time") or event.get("time") or "n/a"
            event_type = event.get("type") or event.get("event_type") or event.get("category") or "event"
            details = event.get("details") or event.get("message") or event.get("content") or event
            if isinstance(details, (dict, list)):
                details = json.dumps(details, sort_keys=True, ensure_ascii=False)
            line = f"{ts} | {event_type} | {details}"
        else:
            line = str(event)
        lines.append(line)

    return "[Databricks Cluster Events]\n" + "\n".join(lines[:max_events])
