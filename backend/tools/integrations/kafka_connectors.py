"""Kafka Connect — built-in tool `kafka_connectors` (Connect REST API; self-managed or Confluent Cloud).

``base_url`` is the Connect REST root: ``http://connect:8083`` for self-managed Connect, or
``https://api.confluent.cloud/connect/v1/environments/<env-id>/clusters/<lkc-id>`` on Confluent Cloud
(with a Cloud API key and secret).
"""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params
from tools.integrations import _kafka as k

LABEL = "Kafka Connect"

TOOL = ToolSpec(
    id="kafka_connectors",
    name="Kafka Connectors",
    icon="🔌",
    category="APIs & Integrations",
    description="Check Kafka Connect: list connectors with their state and failed tasks, or show one connector's status and error trace. Works with self-managed Connect and Confluent Cloud. Input: a connector name, or empty to list.",
    default_config={"base_url": "http://localhost:8083", "api_key": "", "api_secret": ""},
    order=44,
    required=("base_url",),
    parameters=params({}, {"connector": {"type": "string", "description": "A connector to inspect; leave out to list connectors"}}),
    input_param="connector",
)


def _trace(status: Dict[str, Any]) -> str:
    """The first failed task's error: the last line of its stack trace (the root cause is at the end)."""
    for task in status.get("tasks", []):
        if task.get("state") == "FAILED":
            lines = (task.get("trace") or "").strip().splitlines()
            return f"task {task.get('id')}: {lines[-1].strip() if lines else 'failed'}"
    return ""


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    base = k.base_url(cfg)
    if not base:
        return "[Kafka Connect] base_url (the Connect REST endpoint) is required in config."
    name = inp.strip()
    try:
        async with k.client(cfg) as client:
            if name:
                resp = await client.get(f"{base}/connectors/{name}/status")
            else:
                resp = await client.get(f"{base}/connectors", params={"expand": "status"})
            if err := k.failed(resp, LABEL):
                return err
            data = resp.json()
    except httpx.HTTPError as e:
        return f"[Kafka Connect] Error: {e}"

    if name:
        tasks = data.get("tasks", [])
        lines = [f"[Kafka Connect] {data.get('name', name)} [{(data.get('connector') or {}).get('state', 'unknown')}]"
                 f" — {len(tasks)} task(s)"]
        lines += [f"  task {t.get('id')}: {t.get('state')}" for t in tasks]
        for t in tasks:
            if t.get("state") == "FAILED" and t.get("trace"):
                lines.append(f"  Error (task {t.get('id')}): {t['trace'].strip().splitlines()[-1].strip()}")
                break
        return "\n".join(lines)

    if not data:
        return "[Kafka Connect] No connectors."
    rows = []
    for connector, info in data.items():
        status = (info or {}).get("status") or {}
        state = (status.get("connector") or {}).get("state", "unknown")
        failed_tasks = sum(1 for t in status.get("tasks", []) if t.get("state") == "FAILED")
        broken = state == "FAILED" or failed_tasks > 0
        rows.append((not broken, connector, state, failed_tasks, _trace(status)))
    rows.sort()
    bad = sum(1 for r in rows if not r[0])
    lines = [f"[Kafka Connect] {len(rows)} connector(s), " + (f"{bad} failing" if bad else "all healthy")]
    for _, connector, state, failed_tasks, trace in rows:
        lines.append(f"  {connector} [{state}]" + (f", {failed_tasks} failed task(s)" if failed_tasks else "")
                     + (f" — {trace}" if trace else ""))
    return "\n".join(lines)
