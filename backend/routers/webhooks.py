"""
webhooks.py — start published pipelines from outside events (see services/webhooks.py).

GET    /api/webhooks                — webhooks in the caller's tenant/project (?app_id= filters)
POST   /api/webhooks                — create one; the response carries the URL token (shown once)
PATCH  /api/webhooks/{id}           — change name / prompt template / secret / enabled / timeout
DELETE /api/webhooks/{id}           — remove a webhook and its run history
POST   /api/webhooks/{id}/rotate    — issue a new URL token; the old one stops working
POST   /api/webhooks/{id}/test      — run it now with a sample body (as the caller)
GET    /api/webhooks/{id}/runs      — recent runs, newest first

POST   /v1/hooks/{token}            — public trigger: no login, the token is the credential

Webhook runs act as the user who last saved the webhook, so whoever edits it takes
responsibility for what it runs.
"""

import json
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db import get_db_connection
from services import jobs, scheduler, secret_store, webhooks
from services.acl import require_access
from services.request_context import RequestContext, get_request_context

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
public_router = APIRouter(prefix="/v1/hooks", tags=["v1"])


class WebhookCreate(BaseModel):
    app_id: str = Field(..., min_length=1)
    name: str = Field(default="", max_length=200)
    prompt_template: str = Field(default=webhooks.DEFAULT_TEMPLATE, min_length=1, max_length=20000)
    secret: str = Field(default="", max_length=256, description="optional HMAC-SHA256 signing secret")
    enabled: bool = True
    timeout_ms: int = Field(default=120000, ge=1000, le=600000)
    retries: Optional[int] = Field(default=None, ge=-1, le=jobs.MAX_RETRIES, description="retries after a failed or crashed run; -1 = until it succeeds; default JOB_MAX_RETRIES")


class WebhookUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    prompt_template: Optional[str] = Field(default=None, min_length=1, max_length=20000)
    secret: Optional[str] = Field(default=None, max_length=256, description="'' removes the signing secret")
    enabled: Optional[bool] = None
    timeout_ms: Optional[int] = Field(default=None, ge=1000, le=600000)
    retries: Optional[int] = Field(default=None, ge=-1, le=jobs.MAX_RETRIES, description="retries after a failed or crashed run; -1 = until it succeeds")


class WebhookTest(BaseModel):
    body: Any = Field(default_factory=dict, description="sample payload, as the caller would POST it")
    query: Dict[str, str] = Field(default_factory=dict)


_SELECT = (
    "SELECT w.*, a.name AS app_name, a.version AS app_version, a.status AS app_status "
    "FROM webhooks w LEFT JOIN apps a ON a.id = w.app_id AND a.tenant_id = w.tenant_id AND a.project_id = w.project_id "
)


def _to_response(row) -> Dict[str, Any]:
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    d["has_secret"] = bool(d.pop("secret", None))
    d.pop("token_hash", None)
    d["running"] = webhooks.inflight(d["id"])
    d["app_version"] = d.get("app_version") or 0
    return d


def _get_raw(webhook_id: str, ctx: RequestContext) -> Dict[str, Any]:
    conn = get_db_connection()
    try:
        row = conn.execute(_SELECT + "WHERE w.id = ? AND w.tenant_id = ? AND w.project_id = ?",
                           (webhook_id, ctx.tenant_id, ctx.project_id)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return dict(row)


def _get(webhook_id: str, ctx: RequestContext) -> Dict[str, Any]:
    return _to_response(_get_raw(webhook_id, ctx))


def _with_token(d: Dict[str, Any], token: str) -> Dict[str, Any]:
    return {**d, "token": token, "url_path": f"/v1/hooks/{token}"}


@router.get("")
def list_webhooks(request: Request, app_id: str = "") -> List[Dict[str, Any]]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    sql, params = _SELECT + "WHERE w.tenant_id = ? AND w.project_id = ? ", [ctx.tenant_id, ctx.project_id]
    if app_id:
        sql += "AND w.app_id = ? "
        params.append(app_id)
    conn = get_db_connection()
    try:
        rows = conn.execute(sql + "ORDER BY w.created_at DESC", tuple(params)).fetchall()
    finally:
        conn.close()
    return [_to_response(r) for r in rows]


@router.post("", status_code=201)
def create_webhook(body: WebhookCreate, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    conn = get_db_connection()
    try:
        app = conn.execute("SELECT name, version FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?",
                           (body.app_id, ctx.tenant_id, ctx.project_id)).fetchone()
        if not app:
            raise HTTPException(status_code=404, detail="Pipeline not found")
        if not app["version"]:
            raise HTTPException(status_code=409, detail="Publish the pipeline before adding a webhook")
        webhook_id = f"hook_{uuid.uuid4().hex[:12]}"
        token = webhooks.new_token()
        now = scheduler.now_iso()
        conn.execute(
            "INSERT INTO webhooks (id, tenant_id, project_id, owner_user_id, app_id, name, token_hash, token_prefix, "
            "secret, prompt_template, enabled, timeout_ms, retries, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (webhook_id, ctx.tenant_id, ctx.project_id, ctx.user_id, body.app_id,
             body.name.strip() or f"{app['name']} webhook", webhooks.hash_token(token), token[:12],
             secret_store.seal(body.secret) if body.secret else None, body.prompt_template, int(body.enabled), body.timeout_ms,
             jobs.default_retries() if body.retries is None else body.retries, now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return _with_token(_get(webhook_id, ctx), token)


@router.patch("/{webhook_id}")
def update_webhook(webhook_id: str, body: WebhookUpdate, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    cur = _get(webhook_id, ctx)
    fields: Dict[str, Any] = body.model_dump(exclude_unset=True, exclude_none=True)
    if "name" in fields:
        fields["name"] = fields["name"].strip() or cur["name"]
    if "secret" in fields:
        fields["secret"] = secret_store.seal(fields["secret"]) if fields["secret"] else None
    if "enabled" in fields:
        fields["enabled"] = int(fields["enabled"])
    fields["owner_user_id"] = ctx.user_id
    fields["updated_at"] = scheduler.now_iso()
    conn = get_db_connection()
    try:
        conn.execute(
            f"UPDATE webhooks SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ? AND tenant_id = ? AND project_id = ?",
            (*fields.values(), webhook_id, ctx.tenant_id, ctx.project_id),
        )
        conn.commit()
    finally:
        conn.close()
    return _get(webhook_id, ctx)


@router.delete("/{webhook_id}")
def delete_webhook(webhook_id: str, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    _get(webhook_id, ctx)
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM webhook_runs WHERE webhook_id = ?", (webhook_id,))
        conn.execute("DELETE FROM webhooks WHERE id = ? AND tenant_id = ? AND project_id = ?",
                     (webhook_id, ctx.tenant_id, ctx.project_id))
        conn.commit()
    finally:
        conn.close()
    return {"deleted": True, "id": webhook_id}


@router.post("/{webhook_id}/rotate")
def rotate_webhook_token(webhook_id: str, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    _get(webhook_id, ctx)
    token = webhooks.new_token()
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE webhooks SET token_hash = ?, token_prefix = ?, owner_user_id = ?, updated_at = ? "
            "WHERE id = ? AND tenant_id = ? AND project_id = ?",
            (webhooks.hash_token(token), token[:12], ctx.user_id, scheduler.now_iso(),
             webhook_id, ctx.tenant_id, ctx.project_id),
        )
        conn.commit()
    finally:
        conn.close()
    return _with_token(_get(webhook_id, ctx), token)


@router.post("/{webhook_id}/test", status_code=202)
async def test_webhook(webhook_id: str, body: WebhookTest, request: Request) -> Dict[str, Any]:
    """Run as the caller (not the saved owner) with a sample payload — skips the signature
    check, since the caller is already logged in. Async so the run lands on the server loop."""
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    hook = _get_raw(webhook_id, ctx)
    if webhooks.inflight(webhook_id) >= webhooks.MAX_INFLIGHT:
        raise HTTPException(status_code=429, detail="Too many runs of this webhook in progress")
    prompt = webhooks.render_prompt(hook["prompt_template"], body.body, body.query)
    if not prompt:
        raise HTTPException(status_code=422, detail="The prompt template rendered empty for this payload")
    run_row_id = webhooks.launch({**hook, "owner_user_id": ctx.user_id}, "manual", prompt,
                                 webhooks._as_text(body.body))
    return {"run_id": run_row_id, "status": "queued", "prompt": prompt}


@router.get("/{webhook_id}/runs")
def list_webhook_runs(webhook_id: str, request: Request, limit: int = 20) -> List[Dict[str, Any]]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    _get(webhook_id, ctx)
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM webhook_runs WHERE webhook_id = ? ORDER BY started_at DESC",
            (webhook_id,),
        ).fetchmany(max(1, min(limit, 200)))
    finally:
        conn.close()
    return [dict(r) for r in rows]


# ── Public trigger ────────────────────────────────────────────────────────────

@public_router.post("/{token}", status_code=202)
async def trigger_webhook(token: str, request: Request) -> Dict[str, Any]:
    hook = webhooks.find_by_token(token)
    if not hook:
        raise HTTPException(status_code=404, detail="Unknown webhook")
    if not hook["enabled"]:
        raise HTTPException(status_code=403, detail="This webhook is disabled")

    raw = await request.body()
    if len(raw) > webhooks.MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail=f"Body larger than {webhooks.MAX_BODY_BYTES} bytes")
    if hook["secret"] and not webhooks.signature_ok(secret_store.open_sealed(hook["secret"]), raw, request.headers):
        raise HTTPException(status_code=401, detail="Missing or invalid signature (X-Hub-Signature-256 / X-Pipesets-Signature)")
    if webhooks.inflight(hook["id"]) >= webhooks.MAX_INFLIGHT:
        raise HTTPException(status_code=429, detail="Too many runs of this webhook in progress",
                            headers={"Retry-After": "30"})

    payload = webhooks.parse_body(raw)
    prompt = webhooks.render_prompt(hook["prompt_template"], payload, dict(request.query_params))
    if not prompt:
        raise HTTPException(status_code=422, detail="The prompt template rendered empty for this payload")
    preview = raw.decode("utf-8", errors="replace") if not isinstance(payload, (dict, list)) else json.dumps(payload)
    run_row_id = webhooks.launch(hook, "webhook", prompt, preview)
    return {"accepted": True, "run_id": run_row_id, "status": "queued"}
