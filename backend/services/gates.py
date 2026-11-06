"""
gates.py — enforce Human Gate timeouts and close agent runs cut off by a crash, in the background.

A Master Agent run paused at a Human Gate with ``timeout_hours`` gets an ``expires_at``. Before
this sweep, the timeout only took effect when someone resumed the run. Every SWEEP_SECONDS one
process (``@jobs.periodic``) acts on every gate past its deadline, by its ``on_timeout``:

  reject     the run ends as 'rejected' ("Review timed out"); ``run.failed`` is sent
  approve    a run of a published app is resumed as approved by a job (kind ``agent.resume``),
             as the run's user, with the project's / server's provider keys. A run started from
             the editor (no app) can't be rebuilt here; its next resume applies the approval.
  escalate   ``gate.escalated`` is sent once; the run keeps waiting for a reviewer

Each gate is handled once: ``timed_out_at`` is stamped on its pending_gate, guarded by the old
value, so two sweeps never both act on it.

The same sweep marks runs 'interrupted' when they stopped heartbeating (routers.agents
``mark_interrupted_runs``), so a restart of one replica never touches another replica's live runs.

Env: GATE_SWEEP_SECONDS (60).
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List

from db import get_db_connection
from services import jobs
from services.checkpoint import gate_expired

logger = logging.getLogger("pipesets-ai-backend")

SWEEP_SECONDS = float(os.getenv("GATE_SWEEP_SECONDS", "60"))
JOB_KIND = "agent.resume"
TIMED_OUT = "Review timed out"


def _paused_runs() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT run_id, tenant_id, project_id, user_id, app_id, goal, pending_gate, checkpoint FROM agent_runs "
            "WHERE status = 'paused' AND pending_gate IS NOT NULL").fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _notify(event: str, row: Dict[str, Any], gate: Dict[str, Any], error: str = "") -> None:
    from services import notifier   # lazy: notifier imports scheduler

    if not row["app_id"]:
        return   # editor runs have no channels to go to
    notifier.queue_event(event, row["tenant_id"], row["project_id"], row["app_id"], {
        "source": "run", "source_id": row["run_id"], "app_id": row["app_id"], "status": "paused",
        "run_id": row["run_id"], "error": error or None, "pending_gate": gate,
    })


def _expire(row: Dict[str, Any]) -> str:
    """Act on one expired gate; returns what was done ('' when another sweep got there first)."""
    old = row["pending_gate"]
    gate = json.loads(old)
    action = gate.get("on_timeout", "reject")
    now = datetime.utcnow().isoformat()
    conn = get_db_connection()
    try:
        if action == "reject":
            state = json.loads(row["checkpoint"] or "{}")
            state.setdefault("gates", {})[gate["key"]] = {"action": "reject", "comment": TIMED_OUT,
                                                          "decided_by": "system", "decided_at": now}
            error = f"Rejected at human gate on '{gate['agent']}': {TIMED_OUT}"
            cur = conn.execute(
                "UPDATE agent_runs SET status = 'rejected', success = 0, error = ?, final_answer = ?, "
                "pending_gate = NULL, checkpoint = ?, updated_at = ? WHERE run_id = ? AND status = 'paused' "
                "AND pending_gate = ?", (error, f"✋ {error}", json.dumps(state), now, row["run_id"], old))
        else:
            cur = conn.execute(
                "UPDATE agent_runs SET pending_gate = ? WHERE run_id = ? AND status = 'paused' AND pending_gate = ?",
                (json.dumps({**gate, "timed_out_at": now}), row["run_id"], old))
            if cur.rowcount == 1 and action == "approve" and row["app_id"]:
                jobs.enqueue(JOB_KIND, {"run_id": row["run_id"]}, tenant_id=row["tenant_id"],
                             project_id=row["project_id"], dedupe_key=f"agent_run:{row['run_id']}", conn=conn)
        conn.commit()
    finally:
        conn.close()
    if cur.rowcount != 1:
        return ""
    if action == "reject":
        _notify("run.failed", row, gate, f"Rejected at human gate on '{gate['agent']}': {TIMED_OUT}")
    elif action == "approve":
        jobs.wake_workers()
    else:
        _notify("gate.escalated", row, gate)
    logger.info(f"Human gate on run {row['run_id']} timed out → {action}")
    return action


def sweep() -> Dict[str, int]:
    """Act on every expired gate not handled yet, and close runs that stopped heartbeating.
    Returns counts by outcome."""
    from routers.agents import mark_interrupted_runs   # lazy: routers import services

    done: Dict[str, int] = {}
    for row in _paused_runs():
        gate = json.loads(row["pending_gate"])
        if gate.get("timed_out_at") or not gate_expired(gate):
            continue
        action = _expire(row)
        if action:
            done[action] = done.get(action, 0) + 1
    if n := mark_interrupted_runs():
        done["interrupted"] = n
    return done


@jobs.periodic("gates.sweep", SWEEP_SECONDS)
async def _sweep() -> None:
    await asyncio.to_thread(sweep)


def _load(run_id: str) -> Dict[str, Any]:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else {}


class StillRunning(Exception):
    """The run is executing in some process; retry once it has finished or gone stale."""


@jobs.handler(JOB_KIND)
async def _resume_job(payload: Dict[str, Any], job: jobs.Job) -> None:
    """Continue a run whose gate timed out with on_timeout=approve (the resume applies it)."""
    from fastapi import HTTPException

    from routers.agents import RESUMABLE, run_master
    from routers.v1 import _provider_keys
    from services.notifier import queue_event
    from services.pipeline_runner import RunScope, master_resume_request
    from services.request_context import RequestContext

    row = await asyncio.to_thread(_load, payload["run_id"])
    if row.get("status") == "running":
        raise StillRunning(f"Run {payload['run_id']} is running")
    if row.get("status") not in RESUMABLE or not row.get("app_id"):
        return   # decided, cancelled or deleted meanwhile
    tenant = (row["tenant_id"], row["project_id"])
    scope = RunScope(tenant_id=row["tenant_id"], project_id=row["project_id"], user_id=row["user_id"],
                     provider_keys=_provider_keys({}, tenant), caller="gate-timeout")
    try:
        app, req = await asyncio.to_thread(master_resume_request, row["run_id"], row["goal"], row["app_id"], scope)
        ctx = RequestContext(tenant_id=row["tenant_id"], project_id=row["project_id"], user_id=row["user_id"])
        res = await run_master(req, ctx, app_id=app["id"])
    except (LookupError, ValueError, PermissionError, HTTPException) as e:
        # Unpublished, flow changed, no access: a retry can't fix it. The run stays as it is.
        logger.warning(f"Can't resume run {row['run_id']} after its gate timed out: {getattr(e, 'detail', e)}")
        return
    if res.status in ("paused", "failed"):
        await asyncio.to_thread(queue_event, f"run.{res.status}", row["tenant_id"], row["project_id"], row["app_id"], {
            "source": "run", "source_id": row["run_id"], "app_id": row["app_id"], "app_name": app.get("name"),
            "status": res.status, "run_id": row["run_id"], "error": res.error, "pending_gate": res.pending_gate,
            "output_preview": (res.final_answer or "")[:500] or None,
        })
