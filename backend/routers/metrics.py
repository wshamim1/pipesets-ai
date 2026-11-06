"""
metrics.py — the project's run metrics over a time window, for Monitor → Metrics.

GET /api/metrics/overview?hours=24&app_id=…  — totals, a time series, and breakdowns by model, tool
                                               and run phase, plus Master Agent runs and the job queue

Computed from the app database (traces, agent_runs, jobs), so it needs no Prometheus and keeps its
history across restarts — the Prometheus counters on /metrics are per process and start at zero.
Scoped to the caller's tenant / project (traces through their app); reading needs ``apps:read``.
Aggregation happens here rather than in SQL, so SQLite and Postgres give the same answer.
"""

import json
import math
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from fastapi import APIRouter, Query, Request

from db import get_db_connection
from services.acl import require_access
from services.request_context import get_request_context

router = APIRouter(prefix="/api/metrics", tags=["metrics"])

# Window → bucket size: about 24–48 points per chart
_BUCKETS = {1: 5 * 60, 6: 15 * 60, 24: 60 * 60, 168: 6 * 60 * 60, 720: 24 * 60 * 60}
_MAX_ROWS = 50_000   # newest first; a window with more traces than this is reported as truncated
_PHASES = ("middleware", "retrieval", "embedding")


def _p(values: List[float], q: float) -> Optional[int]:
    """Nearest-rank percentile, or None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return int(ordered[max(0, math.ceil(q * len(ordered)) - 1)])


def _json(text: Optional[str], default: Any) -> Any:
    try:
        return json.loads(text) if text else default
    except (TypeError, ValueError):
        return default


def _parse(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(ts)).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _group(rows: Iterable[Dict[str, Any]], key: str) -> Dict[Any, List[Dict[str, Any]]]:
    out: Dict[Any, List[Dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r[key], []).append(r)
    return out


@router.get("/overview")
def overview(request: Request, hours: int = Query(default=24), app_id: Optional[str] = Query(default=None)):
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    hours = min(_BUCKETS, key=lambda h: abs(h - hours))   # snap to a supported window
    bucket = _BUCKETS[hours]
    now = datetime.utcnow()
    since = now - timedelta(hours=hours)
    scope = (ctx.tenant_id, ctx.project_id)

    conn = get_db_connection()
    try:
        sql = ("SELECT created_at, status, latency_ms, cost_usd, total_tokens, provider, model, "
               "effective_provider, effective_model, metadata_json, spans_json FROM traces "
               "WHERE created_at >= ? AND app_id IN (SELECT id FROM apps WHERE tenant_id = ? AND project_id = ?)")
        args: List[Any] = [since.isoformat(), *scope]
        if app_id:
            sql += " AND app_id = ?"
            args.append(app_id)
        traces = [dict(r) for r in conn.execute(sql + " ORDER BY created_at DESC LIMIT ?",
                                                (*args, _MAX_ROWS + 1)).fetchall()]
        agent_sql = ("SELECT status, created_at, updated_at FROM agent_runs WHERE tenant_id = ? AND project_id = ? "
                     "AND kind = 'master' AND created_at >= ?")
        agent_args: List[Any] = [*scope, since.isoformat()]
        if app_id:
            agent_sql += " AND app_id = ?"
            agent_args.append(app_id)
        agents = [dict(r) for r in conn.execute(agent_sql, tuple(agent_args)).fetchall()]
        jobs = [dict(r) for r in conn.execute(
            "SELECT status, run_after FROM jobs WHERE tenant_id = ? AND project_id = ? AND status IN ('queued', 'running', 'dead')",
            scope).fetchall()]
    finally:
        conn.close()

    truncated = len(traces) > _MAX_ROWS
    traces = traces[:_MAX_ROWS]
    for t in traces:
        t["at"] = _parse(t["created_at"])
        t["failed"] = t["status"] == "error"
        t["simulated"] = bool(_json(t["metadata_json"], {}).get("simulated"))
        t["spans"] = _json(t["spans_json"], [])
    traces = [t for t in traces if t["at"] is not None]

    # ── Time series ───────────────────────────────────────────────────────────
    start = since.replace(second=0, microsecond=0)
    n_buckets = math.ceil((now - start).total_seconds() / bucket) or 1
    slots: List[List[Dict[str, Any]]] = [[] for _ in range(n_buckets)]
    for t in traces:
        i = min(n_buckets - 1, max(0, int((t["at"] - start).total_seconds() // bucket)))
        slots[i].append(t)
    series = [{
        "t": (start + timedelta(seconds=i * bucket)).isoformat() + "Z",
        "runs": len(s), "failed": sum(t["failed"] for t in s),
        "p95_ms": _p([t["latency_ms"] or 0 for t in s], 0.95),
        "cost_usd": round(sum(t["cost_usd"] or 0 for t in s), 6),
        "tokens": sum(t["total_tokens"] or 0 for t in s),
    } for i, s in enumerate(slots)]

    # ── By model (real model calls only: a simulated run called none) ─────────
    real = [t for t in traces if not t["simulated"]]
    for t in real:
        t["model_key"] = (t["effective_provider"] or t["provider"] or "unknown", t["effective_model"] or t["model"] or "unknown")
    models = sorted(({
        "provider": key[0], "model": key[1], "runs": len(rows), "failed": sum(r["failed"] for r in rows),
        "p95_ms": _p([r["latency_ms"] or 0 for r in rows], 0.95),
        "cost_usd": round(sum(r["cost_usd"] or 0 for r in rows), 6),
        "tokens": sum(r["total_tokens"] or 0 for r in rows),
    } for key, rows in _group(real, "model_key").items()), key=lambda m: (-m["runs"], m["model"]))

    # ── By tool and run phase, from the recorded spans ────────────────────────
    spans = [s for t in traces for s in t["spans"] if isinstance(s, dict)]
    tool_spans = [dict(s, tool=s.get("name") or s.get("tool_id") or "tool") for s in spans if s.get("span_type") == "tool"]
    tools = sorted(({
        "name": name, "calls": len(rows), "failed": sum(r.get("status") == "error" for r in rows),
        "p95_ms": _p([r.get("latency_ms") or 0 for r in rows], 0.95),
    } for name, rows in _group(tool_spans, "tool").items()), key=lambda r: (-r["calls"], r["name"]))
    phases = [{
        "phase": phase, "count": len(rows), "p95_ms": _p([r.get("latency_ms") or 0 for r in rows], 0.95),
        "total_ms": sum(r.get("latency_ms") or 0 for r in rows),
    } for phase in _PHASES if (rows := [s for s in spans if s.get("span_type") == phase])]

    # ── Master Agent runs (they keep their steps in agent_runs, not traces) ───
    by_status: Dict[str, int] = {}
    for a in agents:
        by_status[a["status"]] = by_status.get(a["status"], 0) + 1

    # ── Job queue (now, not over the window) ──────────────────────────────────
    queued = [j for j in jobs if j["status"] == "queued"]
    due = [w for w in (_parse(j["run_after"]) for j in queued) if w is not None and w <= now]

    latencies = [t["latency_ms"] or 0 for t in traces]
    failed = sum(t["failed"] for t in traces)
    return {
        "hours": hours, "bucket_seconds": bucket, "app_id": app_id, "truncated": truncated,
        "totals": {
            "runs": len(traces), "failed": failed, "error_rate": failed / len(traces) if traces else None,
            "p50_ms": _p(latencies, 0.5), "p95_ms": _p(latencies, 0.95),
            "cost_usd": round(sum(t["cost_usd"] or 0 for t in traces), 6),
            "tokens": sum(t["total_tokens"] or 0 for t in traces),
            "simulated": sum(t["simulated"] for t in traces),
        },
        "series": series,
        "models": models,
        "tools": tools,
        "phases": phases,
        "agent_runs": {"total": len(agents), "by_status": by_status},
        "queue": {
            "queued": len(queued), "running": sum(j["status"] == "running" for j in jobs),
            "dead": sum(j["status"] == "dead" for j in jobs),
            "oldest_wait_s": int((now - min(due)).total_seconds()) if due else 0,
        },
    }
