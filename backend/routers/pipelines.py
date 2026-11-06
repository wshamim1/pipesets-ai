"""
pipelines.py — run published pipelines on their own, independent of any agent.

GET  /api/pipelines            — published pipelines in the caller's tenant/project
POST /api/pipelines/{id}/run   — execute one published pipeline with a prompt
POST /api/pipelines/run-flow   — execute an unsaved canvas flow (e.g. one that only calls pipelines)
POST /api/pipelines/summary    — models / tools / memory / cache a flow uses, incl. called pipelines

Execution reuses services.pipeline_runner (same executor the Pipeline child agent
uses), so RAG, tools, memory, cache, output parsers and nested agents all behave
identically.  Saved drafts never run by id.
"""

import json
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db import get_db_connection
from services.acl import require_access
from services.pipeline_runner import (
    ERROR_PREFIX, RunScope, current_scope, run_flow, run_published_pipeline, summarize_flow,
)
from services.request_context import get_request_context

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


class PipelineRunRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    timeout_ms: int = Field(default=120000, ge=1000, le=600000)
    # provider -> API key from the browser's global key store (saved flows don't hold them)
    provider_keys: Dict[str, str] = Field(default_factory=dict)
    version: int = Field(default=0, ge=0)   # pinned published version (0 = current)


class FlowSummaryRequest(BaseModel):
    flow_data: Dict[str, Any] = Field(default_factory=dict)
    app_id: str = ""


class FlowRunRequest(PipelineRunRequest):
    flow_data: Dict[str, Any] = Field(default_factory=dict)
    app_id: str = ""   # the canvas's own app — guards against it calling itself


def _summarise(row) -> Dict:
    try:
        nodes = (json.loads(row["flow_data"] or "{}")).get("nodes", [])
    except json.JSONDecodeError:
        nodes = []
    types = [n.get("type") for n in nodes]
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"] or "",
        "version": row["version"] or 0,
        "updated_at": row["updated_at"],
        "node_count": len(nodes),
        "uses_agents": "master_agent" in types,
        "uses_rag": "retriever" in types,
        "runnable": "llm" in types or "master_agent" in types or any(
            n.get("type") == "child_agent" and n.get("data", {}).get("kind") == "pipeline" for n in nodes
        ),
    }


@router.get("")
def list_published_pipelines(request: Request) -> List[Dict]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, description, version, updated_at, flow_data FROM apps "
            "WHERE tenant_id = ? AND project_id = ? AND status = 'published' "
            "ORDER BY updated_at DESC",
            (ctx.tenant_id, ctx.project_id),
        ).fetchall()
    finally:
        conn.close()
    return [_summarise(r) for r in rows]


@router.post("/summary")
def summarize_canvas_flow(req: FlowSummaryRequest, request: Request):
    """Aggregate what a flow uses, following pipeline children into their pinned versions."""
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    scope = RunScope(tenant_id=ctx.tenant_id, project_id=ctx.project_id, user_id=ctx.user_id)
    return summarize_flow(req.flow_data, scope, req.app_id)


@router.post("/run-flow")
async def run_canvas_flow(req: FlowRunRequest, request: Request):
    """Run a canvas flow as-is. Used for flows the browser can't drive itself, such as
    Start → Pipeline → Stop, where every step is a published pipeline."""
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    token = current_scope.set(RunScope(
        tenant_id=ctx.tenant_id, project_id=ctx.project_id, user_id=ctx.user_id,
        provider_keys={k.lower(): v for k, v in req.provider_keys.items() if v},
    ))
    t0 = time.monotonic()
    try:
        output, telemetry = await run_flow(
            req.app_id or "canvas", "canvas", req.flow_data, req.prompt.strip(), "", req.timeout_ms,
        )
    finally:
        current_scope.reset(token)

    failed = output.startswith(ERROR_PREFIX)
    return {
        "ok": not failed,
        "output": output,
        "error": output if failed else None,
        "latency_ms": int((time.monotonic() - t0) * 1000),
        "provider": telemetry.get("effective_provider", ""),
        "model": telemetry.get("effective_model", ""),
    }


@router.post("/{app_id}/run")
async def run_pipeline(app_id: str, req: PipelineRunRequest, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")

    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT name, status, version FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?",
            (app_id, ctx.tenant_id, ctx.project_id),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    if row["status"] != "published" and not req.version:
        raise HTTPException(status_code=409, detail="Pipeline is not published. Publish it to run it here.")

    token = current_scope.set(RunScope(
        tenant_id=ctx.tenant_id, project_id=ctx.project_id, user_id=ctx.user_id,
        provider_keys={k.lower(): v for k, v in req.provider_keys.items() if v},
    ))
    t0 = time.monotonic()
    try:
        output, telemetry = await run_published_pipeline(app_id, req.prompt.strip(), "", req.timeout_ms, req.version)
    finally:
        current_scope.reset(token)

    failed = output.startswith(ERROR_PREFIX)
    return {
        "ok": not failed,
        "pipeline": row["name"],
        "version": req.version or row["version"] or 0,
        "output": output,
        "error": output if failed else None,
        "latency_ms": int((time.monotonic() - t0) * 1000),
        "provider": telemetry.get("effective_provider", ""),
    }
