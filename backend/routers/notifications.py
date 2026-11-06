"""
notifications.py — where unattended-run alerts go (see services/notifier.py).

GET    /api/notifications               — channels in the caller's tenant/project
POST   /api/notifications               — add a Slack or webhook channel
PATCH  /api/notifications/{id}          — change name / url / events / pipeline / enabled
DELETE /api/notifications/{id}          — remove a channel
POST   /api/notifications/{id}/test     — send a test message now and report the result
"""

import json
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db import get_db_connection
from services import notifier, secret_store
from services.acl import require_access
from services.request_context import RequestContext, get_request_context
from services.scheduler import now_iso

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

KINDS = ("slack", "webhook")


class ChannelCreate(BaseModel):
    name: str = Field(default="", max_length=200)
    kind: str = Field(default="slack")
    url: str = Field(..., min_length=1, max_length=2000)
    events: List[str] = Field(default_factory=lambda: list(notifier.EVENTS))
    app_id: Optional[str] = Field(default=None, description="only this pipeline; omit for every pipeline")
    enabled: bool = True


class ChannelUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    url: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    events: Optional[List[str]] = None
    app_id: Optional[str] = Field(default=None, description="'' = every pipeline")
    enabled: Optional[bool] = None


def _validate(kind: Optional[str], url: Optional[str], events: Optional[List[str]]) -> None:
    if kind is not None and kind not in KINDS:
        raise HTTPException(status_code=422, detail=f"kind must be one of {', '.join(KINDS)}")
    if url is not None:
        u = urlparse(url.strip())
        if u.scheme not in ("http", "https") or not u.netloc:
            raise HTTPException(status_code=422, detail="url must be an http(s) URL")
    if events is not None:
        bad = [e for e in events if e not in notifier.EVENTS]
        if bad:
            raise HTTPException(status_code=422, detail=f"Unknown events {bad} — use {', '.join(notifier.EVENTS)}")
        if not events:
            raise HTTPException(status_code=422, detail="Pick at least one event")


def _mask_url(url: str) -> str:
    """Channel URLs are credentials (stored sealed): responses show only scheme + host."""
    u = urlparse(url or "")
    return f"{u.scheme}://{u.netloc}/…" if u.netloc else "…"


def _to_response(row) -> Dict[str, Any]:
    d = dict(row)
    d["url"] = _mask_url(secret_store.open_sealed(d["url"]))
    d["enabled"] = bool(d["enabled"])
    try:
        d["events"] = json.loads(d["events"] or "[]")
    except json.JSONDecodeError:
        d["events"] = []
    return d


def _get_raw(channel_id: str, ctx: RequestContext) -> Dict[str, Any]:
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM notification_channels WHERE id = ? AND tenant_id = ? AND project_id = ?",
            (channel_id, ctx.tenant_id, ctx.project_id),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Notification channel not found")
    return dict(row)


def _get(channel_id: str, ctx: RequestContext) -> Dict[str, Any]:
    return _to_response(_get_raw(channel_id, ctx))


def _check_app(app_id: Optional[str], ctx: RequestContext) -> None:
    if not app_id:
        return
    conn = get_db_connection()
    try:
        found = conn.execute("SELECT 1 FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?",
                             (app_id, ctx.tenant_id, ctx.project_id)).fetchone()
    finally:
        conn.close()
    if not found:
        raise HTTPException(status_code=404, detail="Pipeline not found")


@router.get("")
def list_channels(request: Request) -> List[Dict[str, Any]]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM notification_channels WHERE tenant_id = ? AND project_id = ? ORDER BY created_at DESC",
            (ctx.tenant_id, ctx.project_id),
        ).fetchall()
    finally:
        conn.close()
    return [_to_response(r) for r in rows]


@router.post("", status_code=201)
def create_channel(body: ChannelCreate, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    _validate(body.kind, body.url, body.events)
    _check_app(body.app_id, ctx)
    channel_id = f"nch_{uuid.uuid4().hex[:12]}"
    now = now_iso()
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO notification_channels (id, tenant_id, project_id, app_id, name, kind, url, events, enabled, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (channel_id, ctx.tenant_id, ctx.project_id, body.app_id or None,
             body.name.strip() or f"{body.kind.capitalize()} alerts", body.kind, secret_store.seal(body.url.strip()),
             json.dumps(sorted(set(body.events))), int(body.enabled), now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return _get(channel_id, ctx)


@router.patch("/{channel_id}")
def update_channel(channel_id: str, body: ChannelUpdate, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    cur = _get(channel_id, ctx)
    _validate(None, body.url, body.events)
    _check_app(body.app_id, ctx)
    fields: Dict[str, Any] = body.model_dump(exclude_unset=True, exclude_none=True)
    if "name" in fields:
        fields["name"] = fields["name"].strip() or cur["name"]
    if "url" in fields:
        fields["url"] = secret_store.seal(fields["url"].strip())
    if "events" in fields:
        fields["events"] = json.dumps(sorted(set(fields["events"])))
    if "app_id" in fields:
        fields["app_id"] = fields["app_id"] or None
    if "enabled" in fields:
        fields["enabled"] = int(fields["enabled"])
    fields["updated_at"] = now_iso()
    conn = get_db_connection()
    try:
        conn.execute(
            f"UPDATE notification_channels SET {', '.join(f'{k} = ?' for k in fields)} "
            "WHERE id = ? AND tenant_id = ? AND project_id = ?",
            (*fields.values(), channel_id, ctx.tenant_id, ctx.project_id),
        )
        conn.commit()
    finally:
        conn.close()
    return _get(channel_id, ctx)


@router.delete("/{channel_id}")
def delete_channel(channel_id: str, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    _get(channel_id, ctx)
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM notification_channels WHERE id = ? AND tenant_id = ? AND project_id = ?",
                     (channel_id, ctx.tenant_id, ctx.project_id))
        conn.commit()
    finally:
        conn.close()
    return {"deleted": True, "id": channel_id}


@router.post("/{channel_id}/test")
async def test_channel(channel_id: str, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    channel = _get_raw(channel_id, ctx)
    error = await notifier.deliver(channel, "test", {
        "source": "test", "source_name": channel["name"], "app_id": channel.get("app_id"),
        "message": "If you can read this, the channel works.",
    })
    return {"ok": error is None, "error": error}
