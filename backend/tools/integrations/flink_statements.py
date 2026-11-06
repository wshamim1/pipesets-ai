"""Flink SQL statements — built-in tool `flink_statements` (Confluent Cloud Flink REST API)."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, enum, params
from tools.integrations import _flink as f

PHASES = ("PENDING", "RUNNING", "COMPLETED", "DEGRADED", "FAILING", "FAILED", "STOPPING", "STOPPED")
UNHEALTHY = ("FAILED", "FAILING", "DEGRADED")

TOOL = ToolSpec(
    id="flink_statements",
    name="Flink SQL Statements",
    icon="🌊",
    category="APIs & Integrations",
    description="Check Flink SQL on Confluent Cloud: list statements with their phase (failing ones first), or show one statement's SQL, status and latest exceptions. Input: a statement name, or empty to list.",
    default_config={**f.CONNECTION_CONFIG, "max_results": 50},
    order=45,
    required=f.REQUIRED,
    parameters=params(
        {},
        {
            "statement_name": {"type": "string", "description": "A statement to inspect; leave out to list statements"},
            "phase": enum(PHASES, "Only list statements in this phase"),
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "description": "How many statements to list"},
        },
    ),
    input_param="statement_name",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    if err := f.missing(cfg):
        return err
    name = inp.strip()
    try:
        limit = max(1, min(int(cfg.get("max_results", 50)), 100))
    except (TypeError, ValueError):
        limit = 50
    phase = str(cfg.get("phase") or "").upper()
    url = f.statements_url(cfg)
    try:
        async with f.client(cfg) as client:
            if not name:
                # the server-side phase filter is unreliable, so filter here
                resp = await client.get(url, params={"page_size": 100})
                if err := f.failed(resp):
                    return err
                items = resp.json().get("data", [])
                if phase:
                    items = [s for s in items if (s.get("status") or {}).get("phase") == phase]
                if not items:
                    return f"[Flink] No statements{f' in phase {phase}' if phase else ''}."
                rows = sorted(((s.get("status") or {}).get("phase") not in UNHEALTHY, s["name"], s) for s in items)
                bad = sum(1 for r in rows if not r[0])
                lines = [f"[Flink] {len(rows)} statement(s), " + (f"{bad} unhealthy" if bad else "none unhealthy")
                         + (f" (showing {limit})" if len(rows) > limit else "")]
                for _, stmt_name, s in rows[:limit]:
                    status = s.get("status") or {}
                    detail = f.one_line(status.get("detail") or "", 100) if status.get("phase") in UNHEALTHY else ""
                    lines.append(f"  {stmt_name} [{status.get('phase', 'unknown')}] — "
                                 f"{f.one_line((s.get('spec') or {}).get('statement'), 70)}" + (f" — {detail}" if detail else ""))
                return "\n".join(lines)

            resp = await client.get(f"{url}/{name}")
            if err := f.failed(resp):
                return err
            s = resp.json()
            status, spec = s.get("status") or {}, s.get("spec") or {}
            lines = [f"[Flink Statement] {s.get('name', name)} [{status.get('phase', 'unknown')}]",
                     f"  Compute pool : {spec.get('compute_pool_id', '?')}",
                     f"  SQL          : {f.one_line(spec.get('statement'), 400)}"]
            if status.get("detail"):
                lines.append(f"  Detail       : {f.one_line(status['detail'], 300)}")
            if status.get("phase") in UNHEALTHY:
                resp = await client.get(f"{url}/{name}/exceptions")
                if resp.status_code == 200:
                    for e in resp.json().get("data", [])[:3]:
                        lines.append(f"  Exception ({e.get('timestamp', '?')}): {f.one_line(e.get('stacktrace') or e.get('name'), 300)}")
            return "\n".join(lines)
    except httpx.HTTPError as e:
        return f"[Flink] Error: {e}"
