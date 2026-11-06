"""
v1.py — the public, versioned API for external callers (API-key authenticated).

GET  /v1/health              — liveness, no auth
GET  /v1/apps                — published apps the key can see        (scope apps:read)
GET  /v1/apps/{app_id}       — one published app's summary           (scope apps:read)
POST /v1/apps/{app_id}/run   — run a published app, SSE or JSON      (scope apps:run)
POST /v1/runs/{run_id}/resume — continue a paused / interrupted / failed run      (scope apps:run)
POST /v1/runs/{run_id}/cancel — stop a running run, from any replica                (scope apps:run)
POST /v1/runs/{run_id}/feedback — 👍 / 👎 on a finished run, for your end user      (scope apps:run)
POST /v1/mcp                 — the same API as a remote MCP server (routers/v1_mcp.py)
/v1/tools …                  — custom tools as code (routers/v1_tools.py)

Contract rules: /v1 shapes only change additively; breaking changes go to /v2.
Flow data is never returned (saved flows can hold node-level provider keys).

Run behaviour
-------------
* Only published apps run; the key's tenant/project scopes the lookup and the key
  acts as its creator, so ACLs, budgets and middleware nodes all apply as usual.
* ``session_id`` replaces the one saved on the flow's Memory node, so each end
  user gets their own history. Ignored when the flow has no Memory node.
* ``user`` names the end user. With long-term memory on (Memory node + the tenant's opt-in), facts
  learned in their earlier sessions are recalled and new ones remembered; without it there is none.
* Provider keys: node-level keys on the flow win, then ``provider_keys`` from the
  request, then the server's environment (OPENAI_API_KEY, ...).
* ``stream: true`` (default) returns the same SSE events as /api/run/stream;
  Master Agent apps emit their final answer as a single token event.
* Every run is checkpointed. A run that was interrupted or failed (provider down, timeout) is
  continued with ``POST /v1/runs/{run_id}/resume``: finished model and tool calls are reused, not
  repeated. LLM apps announce their id first, ``{"type": "run", "run_id", "resumed_steps"}``.
* A human gate pauses a Master Agent run: the stream emits
  ``{"type": "paused", "run_id", "gate"}`` (JSON: ``status: "paused"``), and
  ``POST /v1/runs/{run_id}/resume`` with a ``gate_decision`` continues it.
"""

import asyncio
import json
import os
import time
import uuid
from dataclasses import replace
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from db import get_db_connection
from routers.pipelines import _summarise
from services.api_keys import ApiKeyPrincipal, require_scope
from services import llm_checkpoint, secret_store
from services.pipeline_runner import (
    RunScope, current_scope, _build_llm_request, _build_master_request, _load_published_app,
    master_resume_request,
)
from services.request_context import RequestContext

router = APIRouter(prefix="/v1", tags=["v1"])

# provider -> env var holding the server's own key for it
_ENV_PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY", "mistral": "MISTRAL_API_KEY", "cohere": "COHERE_API_KEY",
    "together": "TOGETHERAI_API_KEY", "fireworks": "FIREWORKS_AI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY", "xai": "XAI_API_KEY",
    "cerebras": "CEREBRAS_API_KEY", "perplexity": "PERPLEXITY_API_KEY",
    "huggingface": "HF_TOKEN", "azure": "AZURE_API_KEY", "typesafe": "TYPESAFE_API_KEY",
    "nvidia": "NVIDIA_NIM_API_KEY", "watsonx": "WATSONX_APIKEY",
}


class V1RunRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    session_id: Optional[str] = Field(default=None, max_length=200)
    user: Optional[str] = Field(default=None, max_length=255,
                                description="Your end user's id: long-term memory is about them; without it there is none")
    stream: bool = True
    timeout_ms: int = Field(default=120000, ge=1000, le=600000)
    provider_keys: Dict[str, str] = Field(default_factory=dict, description="provider -> key; bring your own")


def _provider_keys(override: Dict[str, str], scope: Optional[Tuple[str, str]] = None) -> Dict[str, str]:
    """Caller's keys, else the project's vault default (resolved later), else the server's env key."""
    keys = {p: os.environ[env] for p, env in _ENV_PROVIDER_KEYS.items()
            if os.environ.get(env) and not (scope and secret_store.default_ref(p, scope))}
    keys.update({k.lower(): v for k, v in override.items() if v})
    return keys


def _sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _published_row(app_id: str, p: ApiKeyPrincipal):
    conn = get_db_connection()
    try:
        return conn.execute(
            "SELECT id, name, description, version, updated_at, flow_data FROM apps "
            "WHERE id = ? AND tenant_id = ? AND project_id = ? AND status = 'published'",
            (app_id, p.ctx.tenant_id, p.ctx.project_id),
        ).fetchone()
    finally:
        conn.close()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/health")
def v1_health():
    return {"status": "ok", "api_version": "v1"}


@router.get("/apps")
def v1_list_apps(p: ApiKeyPrincipal = Depends(require_scope("apps:read"))):
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, description, version, updated_at, flow_data FROM apps "
            "WHERE tenant_id = ? AND project_id = ? AND status = 'published' ORDER BY updated_at DESC",
            (p.ctx.tenant_id, p.ctx.project_id),
        ).fetchall()
    finally:
        conn.close()
    return {"data": [_summarise(r) for r in rows]}


@router.get("/apps/{app_id}")
def v1_get_app(app_id: str, p: ApiKeyPrincipal = Depends(require_scope("apps:read"))):
    row = _published_row(app_id, p)
    if not row:
        raise HTTPException(status_code=404, detail="App not found or not published")
    return _summarise(row)


@router.post("/apps/{app_id}/run")
async def v1_run_app(app_id: str, body: V1RunRequest, p: ApiKeyPrincipal = Depends(require_scope("apps:run"))):
    scope = RunScope(
        tenant_id=p.ctx.tenant_id, project_id=p.ctx.project_id, user_id=p.ctx.user_id,
        provider_keys=_provider_keys(body.provider_keys, (p.ctx.tenant_id, p.ctx.project_id)),
        caller=f"key:{p.key_id}", end_user=(body.user or "").strip(),
    )
    # Load before streaming starts so lookup failures are real HTTP errors.
    try:
        app = _load_published_app(app_id, scope)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except LookupError:
        raise HTTPException(status_code=404, detail="App not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    types = {n.get("type") for n in app["flow"].get("nodes", [])}
    if not types & {"llm", "master_agent"}:
        raise HTTPException(status_code=422, detail=f"App '{app['name']}' has no LLM or Master Agent node to run")

    events = _run_events(app, body, scope)
    if body.stream:
        return StreamingResponse(
            (_sse(ev) async for ev in events),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return await _collect(app, events, body.timeout_ms)


class V1ResumeRequest(BaseModel):
    gate_decision: Optional[Dict[str, Any]] = Field(
        default=None, description='{"action": "approve" | "reject" | "edit", "edited_output": "...", "comment": "..."}',
    )
    timeout_ms: int = Field(default=120000, ge=1000, le=600000)
    provider_keys: Dict[str, str] = Field(default_factory=dict)


@router.post("/runs/{run_id}/resume")
async def v1_resume_run(run_id: str, body: V1ResumeRequest, p: ApiKeyPrincipal = Depends(require_scope("apps:run"))):
    """Continue a run that paused at a human gate (Master Agent apps), was interrupted or failed.
    Finished steps are reused from its checkpoint; the app must still be published
    with the same agents / LLM node, or the resume is refused (409)."""
    from routers.agents import GateDecision  # lazy: avoids circular import
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT kind, goal, app_id, checkpoint FROM agent_runs WHERE run_id = ? AND tenant_id = ? AND project_id = ?",
            (run_id, p.ctx.tenant_id, p.ctx.project_id),
        ).fetchone()
    finally:
        conn.close()
    if not row or not row["app_id"]:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["kind"] == llm_checkpoint.KIND:
        return await _resume_llm(run_id, row, body, p)

    scope = RunScope(tenant_id=p.ctx.tenant_id, project_id=p.ctx.project_id, user_id=p.ctx.user_id,
                     provider_keys=_provider_keys(body.provider_keys, (p.ctx.tenant_id, p.ctx.project_id)),
                     caller=f"key:{p.key_id}")
    try:
        app, sub = master_resume_request(run_id, row["goal"], row["app_id"], scope)
    except (LookupError, ValueError, PermissionError) as e:
        raise HTTPException(status_code=409, detail=f"Can't resume: {e}")
    if body.gate_decision:
        try:
            sub.gate_decision = GateDecision.model_validate(body.gate_decision)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"Invalid gate_decision: {e}")

    # Validation errors from the resume (wrong state, flow changed, missing decision)
    # are real HTTP errors here, so run it directly rather than through the event stream.
    from routers.agents import run_master
    t0 = time.monotonic()
    ctx = RequestContext(tenant_id=scope.tenant_id, project_id=scope.project_id, user_id=scope.user_id)
    try:
        res = await asyncio.wait_for(run_master(sub, ctx, app_id=app["id"]), timeout=body.timeout_ms / 1000.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"Timed out after {body.timeout_ms} ms — the run is checkpointed; resume it again")
    return {
        "ok": res.status == "completed",
        "status": res.status, "run_id": res.run_id,
        "app_id": app["id"], "app_name": app["name"], "version": app["version"],
        "output": res.final_answer if res.status == "completed" else "",
        "error": res.error,
        "pending_gate": res.pending_gate,
        "meta": {"steps": res.total_steps, "resumed_steps": res.resumed_steps,
                 "cost_usd": round(sum(s.cost_usd for s in res.steps), 6)},
        "latency_ms": int((time.monotonic() - t0) * 1000),
    }


async def _resume_llm(run_id: str, row: Any, body: V1ResumeRequest, p: ApiKeyPrincipal) -> Dict[str, Any]:
    """Resume a single-LLM run: rebuild its request from the published app and the saved input
    (prompt, session, end user), then run it from its checkpoint."""
    if body.gate_decision:
        raise HTTPException(status_code=400, detail="This run has no human gate; resume it without gate_decision")
    saved = json.loads(row["checkpoint"] or "{}").get("input", {})
    scope = RunScope(tenant_id=p.ctx.tenant_id, project_id=p.ctx.project_id, user_id=p.ctx.user_id,
                     provider_keys=_provider_keys(body.provider_keys, (p.ctx.tenant_id, p.ctx.project_id)),
                     caller=f"key:{p.key_id}", end_user=saved.get("end_user") or "")
    try:
        app = _load_published_app(row["app_id"], scope)
    except (LookupError, ValueError, PermissionError) as e:
        raise HTTPException(status_code=409, detail=f"Can't resume: {e}")
    req = _build_llm_request(row["goal"], app["id"], app["flow"].get("nodes", []), app["flow"].get("edges", []),
                             scope.provider_keys or {}, retrieval_query=row["goal"])
    if req is None:
        raise HTTPException(status_code=409, detail="Can't resume: the app no longer has an LLM node")
    if saved.get("session_id") and req.memory_config:
        req.session_id = saved["session_id"]
    req.resume_from = run_id

    from services.llm_runner import run_stream  # lazy: llm_runner imports routers
    run_scope = replace(scope, chain=(app["id"],))
    token = current_scope.set(run_scope)
    try:
        cp = llm_checkpoint.claim(req)
    except llm_checkpoint.NotResumable as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    finally:
        current_scope.reset(token)

    async def events() -> AsyncIterator[Dict[str, Any]]:
        token = current_scope.set(run_scope)
        try:
            async for chunk in run_stream(req, cp):
                if chunk.startswith("data: "):
                    yield json.loads(chunk[6:])
        finally:
            try:
                current_scope.reset(token)
            except ValueError:
                pass

    res = await _collect(app, events(), body.timeout_ms)
    res["run_id"] = run_id
    return res


@router.post("/runs/{run_id}/cancel")
def v1_cancel_run(run_id: str, p: ApiKeyPrincipal = Depends(require_scope("apps:run"))):
    """Stop a running run (status 'cancelling': it stops within seconds, wherever it runs), or
    close a paused / interrupted / failed one ('cancelled')."""
    from routers.agents import request_cancel  # lazy: avoids circular import
    try:
        status = request_cancel(run_id, p.ctx.tenant_id, p.ctx.project_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Run not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=f"{e}; only running, paused, interrupted or failed runs can be cancelled")
    return {"run_id": run_id, "status": status}


class V1FeedbackRequest(BaseModel):
    rating: int = Field(..., description="1 = 👍, -1 = 👎")
    comment: str = Field(default="", max_length=4000)
    correction: str = Field(default="", max_length=20000, description="what the answer should have been")
    user: str = Field(default="", max_length=255, description="your end user's id: one rating per run per user")


@router.post("/runs/{run_id}/feedback")
def v1_run_feedback(run_id: str, body: V1FeedbackRequest, p: ApiKeyPrincipal = Depends(require_scope("apps:run"))):
    """Rate a finished run on behalf of ``user``; rating again replaces it (services/feedback.py)."""
    from services import feedback
    try:
        fb = feedback.rate(p.ctx.tenant_id, p.ctx.project_id, run_id, "api", f"key:{p.key_id}:{body.user.strip()}",
                           body.rating, body.comment, body.correction)
    except feedback.FeedbackError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return {"id": fb["id"], "run_id": run_id, "rating": fb["rating"], "updated_at": fb["updated_at"]}


async def _collect(app: Dict[str, Any], events: AsyncIterator[Dict[str, Any]], timeout_ms: int) -> Dict[str, Any]:
    """Drain an event stream into the non-streaming JSON response."""
    t0 = time.monotonic()
    text: List[str] = []
    error: Optional[str] = None
    meta: Dict[str, Any] = {}
    paused: Optional[Dict[str, Any]] = None
    run_id: Optional[str] = None

    async def drain() -> None:
        nonlocal error, meta, paused, run_id
        async for ev in events:
            kind = ev.get("type")
            run_id = run_id or ev.get("run_id")   # announced first, so a failed run can still be resumed
            if kind == "token":
                text.append(ev.get("text", ""))
            elif kind == "error":
                error = ev.get("message") or "Unknown error"
                if ev.get("retract"):
                    text.clear()
            elif kind == "paused":
                paused = ev
            elif kind == "meta":
                meta = ev

    try:
        # A little slack so a master run's own timeout (which keeps its run id) fires first
        await asyncio.wait_for(drain(), timeout=timeout_ms / 1000.0 + 5)
    except asyncio.TimeoutError:
        error = f"Timed out after {timeout_ms} ms"
    status = "paused" if paused else ("failed" if error else "completed")
    return {
        "ok": status == "completed",
        "status": status,
        "run_id": meta.get("run_id") or run_id,
        "app_id": app["id"], "app_name": app["name"], "version": app["version"],
        "output": "".join(text),
        "error": error,
        "pending_gate": (paused or {}).get("gate"),
        "meta": {k: v for k, v in meta.items() if k != "type"},
        "latency_ms": int((time.monotonic() - t0) * 1000),
    }


async def _master_events(
    sub: Any, scope: RunScope, app_id: str, timeout_ms: int,
) -> AsyncIterator[Dict[str, Any]]:
    from routers.agents import run_master  # lazy: avoids circular import
    if not sub.resume_from and not sub.run_id:
        sub.run_id = str(uuid.uuid4())   # known up front, so a timeout can still say what to resume
    ctx = RequestContext(tenant_id=scope.tenant_id, project_id=scope.project_id, user_id=scope.user_id)
    try:
        res = await asyncio.wait_for(run_master(sub, ctx, app_id=app_id), timeout=timeout_ms / 1000.0)
    except HTTPException as e:
        yield {"type": "error", "message": str(e.detail)}
        yield {"type": "done"}
        return
    except asyncio.TimeoutError:
        run = sub.resume_from or sub.run_id
        yield {"type": "error", "message": f"Timed out after {timeout_ms} ms — resume with POST /v1/runs/{run}/resume", "run_id": run}
        yield {"type": "done"}
        return
    if res.status == "paused":
        yield {"type": "paused", "run_id": res.run_id, "gate": res.pending_gate}
    elif res.status == "failed":
        yield {"type": "error", "message": res.error or "Run failed", "run_id": res.run_id}
    else:
        yield {"type": "token", "text": res.final_answer}
    yield {"type": "meta", "run_id": res.run_id, "status": res.status, "provider": sub.provider, "model": sub.model,
           "steps": res.total_steps, "resumed_steps": res.resumed_steps,
           "cost_usd": round(sum(s.cost_usd for s in res.steps), 6),
           "middleware_flags": [f for s in res.steps for f in s.middleware_flags]}
    yield {"type": "done"}


def _exists(run_id: str) -> bool:
    conn = get_db_connection()
    try:
        return conn.execute("SELECT 1 FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone() is not None
    finally:
        conn.close()


def _resumable(run_id: Optional[str], scope: RunScope, fingerprint: str) -> bool:
    """Can ``run_id`` pick up from its checkpoint? Only an interrupted or failed run of the same flow."""
    if not run_id:
        return False
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT status, fingerprint FROM agent_runs WHERE run_id = ? AND tenant_id = ? AND project_id = ?",
                           (run_id, scope.tenant_id, scope.project_id)).fetchone()
    finally:
        conn.close()
    return bool(row) and row["status"] in ("interrupted", "failed") and row["fingerprint"] == fingerprint


async def _run_events(
    app: Dict[str, Any], body: V1RunRequest, scope: RunScope, run_id: Optional[str] = None,
    default_memory: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Run the app and yield SSE-shaped event dicts. Sets the run scope for the
    duration (inside the generator, so it holds while a StreamingResponse drains it).

    Runs are checkpointed under ``run_id`` (a new id when None). When ``run_id`` names an
    interrupted or failed run of the same flow, it resumes from its checkpoint instead: retries
    of scheduled and webhook runs pick up where the last attempt stopped.

    ``default_memory`` is the memory config an LLM app without a Memory node uses for
    ``body.session_id`` (chat links: the conversation is remembered either way)."""
    nodes = app["flow"].get("nodes", [])
    edges = app["flow"].get("edges", [])
    prompt = body.prompt.strip()
    # Top-level app goes in the cycle chain so a nested pipeline can't call it back.
    token = current_scope.set(replace(scope, chain=scope.chain + (app["id"],)))
    try:
        if any(n.get("type") == "master_agent" for n in nodes):
            # Master apps run checkpointed (resumable, can pause at human gates) and
            # produce one final answer, so they emit it as a single token event.
            sub = _build_master_request(prompt, nodes, edges, scope.provider_keys or {})
            sub.provider_keys = scope.provider_keys or {}
            if body.session_id:
                sub.session_id = body.session_id
            from routers.agents import _fingerprint  # lazy: avoids circular import
            if _resumable(run_id, scope, _fingerprint(sub)):
                sub.resume_from = run_id
            elif run_id and not _exists(run_id):
                sub.run_id = run_id
            async for ev in _master_events(sub, scope, app["id"], body.timeout_ms):
                yield ev
            return

        from services.llm_runner import run_stream  # lazy: llm_runner imports routers
        req = _build_llm_request(prompt, app["id"], nodes, edges, scope.provider_keys or {}, retrieval_query=prompt)
        if body.session_id and not req.memory_config and default_memory:
            req.memory_config = dict(default_memory)
        if body.session_id and req.memory_config:
            req.session_id = body.session_id
        if _resumable(run_id, scope, llm_checkpoint.fingerprint(req)):
            req.resume_from = run_id
        else:
            req.run_id = run_id if run_id and not _exists(run_id) else str(uuid.uuid4())
        async for chunk in run_stream(req):
            if chunk.startswith("data: "):
                try:
                    yield json.loads(chunk[6:])
                except json.JSONDecodeError:
                    continue
    finally:
        try:
            current_scope.reset(token)
        except ValueError:   # generator closed from another context (client disconnected)
            pass
