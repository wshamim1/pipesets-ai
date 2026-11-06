"""
schedules.py — run published pipelines on a cron schedule (see services/scheduler.py).

GET    /api/schedules               — schedules in the caller's tenant/project (?app_id= filters)
POST   /api/schedules               — create a schedule for a published pipeline
PATCH  /api/schedules/{id}          — change cron / prompt / timezone / enabled …
DELETE /api/schedules/{id}          — remove a schedule and its run history
POST   /api/schedules/{id}/run      — run it now (queued as a job; returns the run record)
GET    /api/schedules/{id}/runs     — recent runs, newest first
POST   /api/schedules/preview       — validate a cron + timezone and list the next firings

Scheduled runs act as the user who last saved the schedule, so whoever edits a
schedule takes responsibility for what it runs.
"""

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db import get_db_connection
from services import jobs, scheduler
from services.acl import require_access
from services.request_context import RequestContext, get_request_context

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


class ScheduleCreate(BaseModel):
    app_id: str = Field(..., min_length=1)
    name: str = Field(default="", max_length=200)
    cron: str = Field(..., min_length=1, max_length=128)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    prompt: str = Field(..., min_length=1, max_length=20000)
    enabled: bool = True
    timeout_ms: int = Field(default=120000, ge=1000, le=600000)
    max_failures: int = Field(default=3, ge=0, le=100, description="auto-pause after N failures in a row; 0 = never")
    retries: Optional[int] = Field(default=None, ge=-1, le=jobs.MAX_RETRIES, description="retries after a failed or crashed run; -1 = until it succeeds; default JOB_MAX_RETRIES")


class ScheduleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    cron: Optional[str] = Field(default=None, min_length=1, max_length=128)
    timezone: Optional[str] = Field(default=None, min_length=1, max_length=64)
    prompt: Optional[str] = Field(default=None, min_length=1, max_length=20000)
    enabled: Optional[bool] = None
    timeout_ms: Optional[int] = Field(default=None, ge=1000, le=600000)
    max_failures: Optional[int] = Field(default=None, ge=0, le=100)
    retries: Optional[int] = Field(default=None, ge=-1, le=jobs.MAX_RETRIES, description="retries after a failed or crashed run; -1 = until it succeeds")


class CronPreview(BaseModel):
    cron: str = Field(..., min_length=1, max_length=128)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)


_SELECT = (
    "SELECT s.*, a.name AS app_name, a.version AS app_version, a.status AS app_status "
    "FROM schedules s LEFT JOIN apps a ON a.id = s.app_id AND a.tenant_id = s.tenant_id AND a.project_id = s.project_id "
)


def _to_response(row) -> Dict[str, Any]:
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    d["running"] = scheduler.is_running(d["id"])
    d["app_version"] = d.get("app_version") or 0
    return d


def _get(schedule_id: str, ctx: RequestContext) -> Dict[str, Any]:
    conn = get_db_connection()
    try:
        row = conn.execute(_SELECT + "WHERE s.id = ? AND s.tenant_id = ? AND s.project_id = ?",
                           (schedule_id, ctx.tenant_id, ctx.project_id)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return _to_response(row)


def _validate(cron: str, tz: str) -> None:
    try:
        scheduler.validate_schedule(cron, tz)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("")
def list_schedules(request: Request, app_id: str = "") -> List[Dict[str, Any]]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    sql, params = _SELECT + "WHERE s.tenant_id = ? AND s.project_id = ? ", [ctx.tenant_id, ctx.project_id]
    if app_id:
        sql += "AND s.app_id = ? "
        params.append(app_id)
    conn = get_db_connection()
    try:
        rows = conn.execute(sql + "ORDER BY s.created_at DESC", tuple(params)).fetchall()
    finally:
        conn.close()
    return [_to_response(r) for r in rows]


@router.post("/preview")
def preview_cron(body: CronPreview) -> Dict[str, Any]:
    cron = body.cron.strip()
    _validate(cron, body.timezone)
    return {"cron": cron, "timezone": body.timezone,
            "next_runs": [scheduler.utc_iso(t) for t in scheduler.next_runs(cron, body.timezone, 5)]}


@router.post("", status_code=201)
def create_schedule(body: ScheduleCreate, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    cron = body.cron.strip()
    _validate(cron, body.timezone)

    conn = get_db_connection()
    try:
        app = conn.execute("SELECT name, version FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?",
                           (body.app_id, ctx.tenant_id, ctx.project_id)).fetchone()
        if not app:
            raise HTTPException(status_code=404, detail="Pipeline not found")
        if not app["version"]:
            raise HTTPException(status_code=409, detail="Publish the pipeline before scheduling it")
        schedule_id = f"sched_{uuid.uuid4().hex[:12]}"
        now = scheduler.now_iso()
        conn.execute(
            "INSERT INTO schedules (id, tenant_id, project_id, owner_user_id, app_id, name, cron, timezone, prompt, "
            "enabled, timeout_ms, max_failures, retries, consecutive_failures, next_run_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
            (schedule_id, ctx.tenant_id, ctx.project_id, ctx.user_id, body.app_id,
             body.name.strip() or f"{app['name']} schedule", cron, body.timezone, body.prompt,
             int(body.enabled), body.timeout_ms, body.max_failures,
             jobs.default_retries() if body.retries is None else body.retries,
             scheduler.next_run_iso(cron, body.timezone) if body.enabled else None, now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return _get(schedule_id, ctx)


@router.patch("/{schedule_id}")
def update_schedule(schedule_id: str, body: ScheduleUpdate, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    cur = _get(schedule_id, ctx)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    merged = {**cur, **changes}
    merged["cron"] = merged["cron"].strip()
    _validate(merged["cron"], merged["timezone"])

    fields: Dict[str, Any] = {k: v for k, v in changes.items() if k != "enabled"}
    fields["cron"] = merged["cron"]
    if "name" in fields:
        fields["name"] = fields["name"].strip() or cur["name"]
    fields["enabled"] = int(merged["enabled"])
    fields["next_run_at"] = scheduler.next_run_iso(merged["cron"], merged["timezone"]) if merged["enabled"] else None
    if merged["enabled"] and not cur["enabled"]:
        fields["consecutive_failures"] = 0   # resuming clears the auto-pause counter
    fields["owner_user_id"] = ctx.user_id
    fields["updated_at"] = scheduler.now_iso()

    conn = get_db_connection()
    try:
        conn.execute(
            f"UPDATE schedules SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ? AND tenant_id = ? AND project_id = ?",
            (*fields.values(), schedule_id, ctx.tenant_id, ctx.project_id),
        )
        conn.commit()
    finally:
        conn.close()
    return _get(schedule_id, ctx)


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: str, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    _get(schedule_id, ctx)
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM schedule_runs WHERE schedule_id = ?", (schedule_id,))
        conn.execute("DELETE FROM schedules WHERE id = ? AND tenant_id = ? AND project_id = ?",
                     (schedule_id, ctx.tenant_id, ctx.project_id))
        conn.commit()
    finally:
        conn.close()
    return {"deleted": True, "id": schedule_id}


@router.post("/{schedule_id}/run", status_code=202)
async def run_schedule_now(schedule_id: str, request: Request) -> Dict[str, Any]:
    """Runs as the caller (not the saved owner) — it's their click. Async so the run
    task lands on the server's event loop."""
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    sched = _get(schedule_id, ctx)
    if sched["running"]:
        raise HTTPException(status_code=409, detail="This schedule already has a run in progress")
    run_row_id = scheduler.launch({**sched, "owner_user_id": ctx.user_id}, "manual")
    return {"run_id": run_row_id, "status": "queued"}


@router.get("/{schedule_id}/runs")
def list_schedule_runs(schedule_id: str, request: Request, limit: int = 20) -> List[Dict[str, Any]]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    _get(schedule_id, ctx)
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM schedule_runs WHERE schedule_id = ? ORDER BY started_at DESC",
            (schedule_id,),
        ).fetchmany(max(1, min(limit, 200)))
    finally:
        conn.close()
    return [dict(r) for r in rows]
