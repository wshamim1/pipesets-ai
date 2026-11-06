"""
jobs.py — the project's background jobs (services/jobs.py), for the dead-letter view.

GET    /api/jobs?status=dead&limit=100  — jobs in one status, most recently changed first, each with
                                          a readable ``label`` and the ``source`` it came from;
                                          plus ``counts`` per status
POST   /api/jobs/{job_id}/retry         — queue a dead job again with a fresh set of attempts
POST   /api/jobs/{job_id}/cancel        — stop a queued or running job, on whichever replica runs it;
                                          it ends dead, and its run is recorded as cancelled
DELETE /api/jobs/{job_id}               — discard a dead job

Reading needs ``apps:read``; retry, cancel and discard need ``apps:write`` (as for schedules and webhooks).
Payloads aren't returned: a notification's carries run output, and the label says what it is.
"""

import asyncio
import json
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from db import get_db_connection
from services import jobs
from services.acl import require_access
from services.request_context import get_request_context

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

# kind → (table, payload field with its id, what it is)
_SOURCES = {
    "schedule.run": ("schedules", "schedule_id", "Scheduled run"),
    "webhook.run": ("webhooks", "webhook_id", "Webhook run"),
    "notify.deliver": ("notification_channels", "channel_id", "Notification"),
    "batch.run": ("batch_runs", "batch_id", "Batch row"),
}


def _name(conn, table: str, row_id: str) -> Optional[str]:
    row = conn.execute(f"SELECT name FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return row["name"] if row else None


def _describe(conn, job: Dict[str, Any]) -> Dict[str, Any]:
    payload = json.loads(job["payload"] or "{}")
    label, source = job["kind"], None
    if job["kind"] in _SOURCES:
        table, field, what = _SOURCES[job["kind"]]
        source = {"type": table, "id": payload.get(field)}
        name = _name(conn, table, payload.get(field) or "")
        label = f"{what} · {name}" if name else f"{what} · (deleted)"
        if job["kind"] == "notify.deliver":
            label += f" · {payload.get('event')}"
    elif job["kind"] == "agent.resume":
        source = {"type": "agent_runs", "id": payload.get("run_id")}
        label = f"Resume after review timeout · run {payload.get('run_id')}"
    return {k: job[k] for k in ("id", "kind", "status", "attempts", "max_attempts", "last_error",
                                "created_at", "updated_at", "finished_at")} | {"label": label, "source": source}


@router.get("")
def list_jobs(request: Request, status: Literal["queued", "running", "done", "dead"] = "dead",
              limit: int = Query(100, ge=1, le=500)):
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    rows = jobs.list_jobs(ctx.tenant_id, ctx.project_id, status, limit)
    conn = get_db_connection()
    try:
        out: List[Dict[str, Any]] = [_describe(conn, r) for r in rows]
    finally:
        conn.close()
    return {"jobs": out, "counts": jobs.counts(ctx.tenant_id, ctx.project_id)}


@router.post("/{job_id}/retry")
def retry_job(job_id: str, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    if not jobs.retry(job_id, ctx.tenant_id, ctx.project_id):
        raise HTTPException(status_code=409, detail="Only dead jobs in this project can be retried")
    return {"id": job_id, "status": "queued"}


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    reason = f"Cancelled by {ctx.user_id}"
    try:
        queued = await asyncio.to_thread(jobs.cancel, job_id, ctx.tenant_id, ctx.project_id, reason)
    except LookupError:
        raise HTTPException(status_code=409, detail="Only queued or running jobs in this project can be cancelled")
    if queued:
        await jobs.bury_cancelled(queued, reason)
        return {"id": job_id, "status": "dead"}
    return {"id": job_id, "status": "cancelling"}


@router.delete("/{job_id}")
def discard_job(job_id: str, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    if not jobs.discard(job_id, ctx.tenant_id, ctx.project_id):
        raise HTTPException(status_code=409, detail="Only dead jobs in this project can be discarded")
    return {"id": job_id, "deleted": True}
