import asyncio
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import llm
from db import get_db_connection, upsert
from models import (
    AppCreateRequest, AppDocsGenerateRequest, AppDocsUpdateRequest, AppRenameRequest, AppUpdateRequest, AppResponse,
)
from services import pipeline_docs, publish_gate, secret_store
from services.acl import require_access
from services.flow_summary import pick_generator_llm
from services.pipeline_runner import RunScope, walk_flows
from services.request_context import get_request_context
from services.secret_store import request_scope

router = APIRouter(prefix="/api/apps", tags=["apps"])


def _row_to_response(row) -> AppResponse:
    try:
        flow = json.loads(row["flow_data"])
    except Exception:
        flow = {}
    return AppResponse(
        id=row["id"],
        tenant_id=row["tenant_id"] if "tenant_id" in row.keys() and row["tenant_id"] else "tenant_demo",
        project_id=row["project_id"] if "project_id" in row.keys() and row["project_id"] else "proj_research",
        owner_user_id=row["owner_user_id"] if "owner_user_id" in row.keys() and row["owner_user_id"] else "user_admin",
        name=row["name"],
        description=row["description"] or "",
        flow_data=flow,
        status=row["status"] if row["status"] else "draft",
        version=row["version"] if row["version"] else 0,
        docs=row["docs"] if "docs" in row.keys() and row["docs"] else "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("", response_model=List[AppResponse])
def list_apps(request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM apps WHERE tenant_id = ? AND project_id = ? ORDER BY updated_at DESC",
        (ctx.tenant_id, ctx.project_id),
    )
    rows = cursor.fetchall()
    conn.close()
    return [_row_to_response(r) for r in rows]


def _refuse_plaintext_credentials(flow: Any) -> None:
    """Flows may hold credentials only as "secret://" refs (or sealed values), never as typed
    keys — those would sit in plain text in the DB, versions, exports and shares."""
    found = secret_store.plaintext_credentials(flow)
    if found:
        raise HTTPException(status_code=422, detail={
            "message": "Credentials can't be saved in plain text in a pipeline. Pick a key from Secrets "
                       "(or add one with '+ New key…') for: " + "; ".join(found[:5])
                       + (f" and {len(found) - 5} more" if len(found) > 5 else ""),
            "fields": found,
        })


@router.post("", response_model=AppResponse)
def create_app(req: AppCreateRequest, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    _refuse_plaintext_credentials(req.flow_data)
    app_id = f"app-{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()

    conn = get_db_connection()
    conn.execute(
        "INSERT INTO apps (id, tenant_id, project_id, owner_user_id, name, description, flow_data, status, version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (app_id, ctx.tenant_id, ctx.project_id, ctx.user_id, req.name.strip(), req.description or "",
         json.dumps(req.flow_data or {"nodes": [], "edges": []}), "draft", 0, now, now),
    )
    conn.commit()
    conn.close()

    return AppResponse(
        id=app_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        owner_user_id=ctx.user_id,
        name=req.name.strip(),
        description=req.description or "",
        flow_data=req.flow_data or {"nodes": [], "edges": []},
        status="draft",
        version=0,
        created_at=now,
        updated_at=now,
    )


@router.post("/docs/generate")
async def generate_app_docs(body: AppDocsGenerateRequest, request: Request):
    """Draft a README from the live canvas (plus the pipelines it calls). Nothing is saved —
    the caller reviews the draft and stores it with PUT /{app_id}/docs. Falls back to a
    fact-only template when there is no usable model."""
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    scope = RunScope(tenant_id=ctx.tenant_id, project_id=ctx.project_id, user_id=ctx.user_id)

    visited, _ = walk_flows(body.flow_data, scope, body.app_id)
    facts = pipeline_docs.collect_facts(body.flow_data)
    keys = {k.lower(): v for k, v in body.provider_keys.items() if v}
    cfg = pick_generator_llm(visited, keys)
    if cfg.provider == "mock" or (not cfg.api_key and cfg.provider not in ("ollama", "llamacpp", "jan", "local")):
        return {"docs": pipeline_docs.template_docs(body.name, body.description, visited, facts),
                "generated_by": "template",
                "note": "No model with an API key was found, so this draft lists only what the configuration shows."}

    try:
        completion = await llm.complete(llm.request_from_config(
            cfg,
            [{"role": "user", "content": pipeline_docs.docs_prompt(
                body.name, body.description, visited, facts, body.example_prompts)}],
            temperature=0.4,
            max_tokens=2000,
        ))
        raw = completion.text
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM call failed ({cfg.provider}/{cfg.model}): {e}")
    if not raw.strip():
        raise HTTPException(status_code=502, detail="The model returned an empty README.")
    return {"docs": pipeline_docs.strip_fence(raw), "generated_by": f"{cfg.provider}/{cfg.model}"}


@router.post("/{app_id}/duplicate", response_model=AppResponse)
def duplicate_app(app_id: str, request: Request):
    """Clone/fork an existing application with a new ID and (Copy) label."""
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?", (app_id, ctx.tenant_id, ctx.project_id))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"App '{app_id}' not found.")

    new_app_id = f"app-{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()
    orig_data = dict(row)
    new_name = f"{orig_data['name']} (Copy)"

    conn.execute(
        "INSERT INTO apps (id, tenant_id, project_id, owner_user_id, name, description, flow_data, status, version, docs, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (new_app_id, ctx.tenant_id, ctx.project_id, ctx.user_id, new_name, orig_data["description"] or "", orig_data["flow_data"], "draft", 0, orig_data.get("docs") or "", now, now),
    )
    conn.commit()
    cursor.execute("SELECT * FROM apps WHERE id = ?", (new_app_id,))
    new_row = cursor.fetchone()
    conn.close()

    return _row_to_response(new_row)


@router.get("/stats/summary")
def get_stats(request: Request):
    """Return aggregate counts for the admin dashboard."""
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    conn = get_db_connection()
    try:
        total_apps      = conn.execute("SELECT COUNT(*) FROM apps WHERE tenant_id = ? AND project_id = ?", (ctx.tenant_id, ctx.project_id)).fetchone()[0]
        published_apps  = conn.execute("SELECT COUNT(*) FROM apps WHERE tenant_id = ? AND project_id = ? AND status='published'", (ctx.tenant_id, ctx.project_id)).fetchone()[0]
        draft_apps      = conn.execute("SELECT COUNT(*) FROM apps WHERE tenant_id = ? AND project_id = ? AND status='draft'", (ctx.tenant_id, ctx.project_id)).fetchone()[0]
        total_traces    = conn.execute("SELECT COUNT(*) FROM traces WHERE app_id IN (SELECT id FROM apps WHERE tenant_id = ? AND project_id = ?)", (ctx.tenant_id, ctx.project_id)).fetchone()[0]
        total_cost      = conn.execute("SELECT COALESCE(SUM(cost_usd),0) FROM traces WHERE app_id IN (SELECT id FROM apps WHERE tenant_id = ? AND project_id = ?)", (ctx.tenant_id, ctx.project_id)).fetchone()[0]
        total_tokens    = conn.execute("SELECT COALESCE(SUM(total_tokens),0) FROM traces WHERE app_id IN (SELECT id FROM apps WHERE tenant_id = ? AND project_id = ?)", (ctx.tenant_id, ctx.project_id)).fetchone()[0]
        error_traces    = conn.execute("SELECT COUNT(*) FROM traces WHERE status='error' AND app_id IN (SELECT id FROM apps WHERE tenant_id = ? AND project_id = ?)", (ctx.tenant_id, ctx.project_id)).fetchone()[0]
        total_evals     = conn.execute("SELECT COUNT(*) FROM eval_runs WHERE tenant_id = ? AND project_id = ?", (ctx.tenant_id, ctx.project_id)).fetchone()[0]
        app_rows = conn.execute("""
            SELECT a.id, a.name, a.status, a.version,
                   COUNT(t.id) as run_count,
                   COALESCE(SUM(t.cost_usd), 0) as cost,
                   COALESCE(SUM(t.total_tokens), 0) as tokens,
                   MAX(t.created_at) as last_run
            FROM apps a
            LEFT JOIN traces t ON t.app_id = a.id
            WHERE a.tenant_id = ? AND a.project_id = ?
            GROUP BY a.id
            ORDER BY a.updated_at DESC
        """, (ctx.tenant_id, ctx.project_id)).fetchall()
    finally:
        conn.close()

    return {
        "totals": {
            "pipelines": total_apps,
            "published": published_apps,
            "drafts": draft_apps,
            "traces": total_traces,
            "errors": error_traces,
            "cost_usd": round(total_cost, 6),
            "tokens": total_tokens,
            "eval_runs": total_evals,
        },
        "pipelines": [
            {
                "id": r["id"],
                "name": r["name"],
                "status": r["status"],
                "version": r["version"],
                "run_count": r["run_count"],
                "cost_usd": round(r["cost"], 6),
                "tokens": r["tokens"],
                "last_run": r["last_run"],
            }
            for r in app_rows
        ],
    }


@router.get("/{app_id}", response_model=AppResponse)
def get_app(app_id: str, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?", (app_id, ctx.tenant_id, ctx.project_id))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="App not found")

    return _row_to_response(row)


@router.put("/{app_id}", response_model=AppResponse)
def update_app(app_id: str, req: AppUpdateRequest, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    _refuse_plaintext_credentials(req.flow_data)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?", (app_id, ctx.tenant_id, ctx.project_id))
    existing = cursor.fetchone()

    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="App not found")

    # Block direct edits to a published pipeline — must call /edit first
    if existing["status"] == "published":
        conn.close()
        raise HTTPException(
            status_code=409,
            detail="Pipeline is published. Click 'Edit' to create a new draft version before saving changes.",
        )

    now = datetime.utcnow().isoformat()
    name = req.name.strip() if req.name is not None else existing["name"]
    description = req.description if req.description is not None else existing["description"]
    flow_str = json.dumps(req.flow_data) if req.flow_data is not None else existing["flow_data"]

    conn.execute(
        "UPDATE apps SET name = ?, description = ?, flow_data = ?, updated_at = ? WHERE id = ? AND tenant_id = ? AND project_id = ?",
        (name, description, flow_str, now, app_id, ctx.tenant_id, ctx.project_id),
    )
    conn.commit()

    cursor.execute("SELECT * FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?", (app_id, ctx.tenant_id, ctx.project_id))
    updated_row = cursor.fetchone()
    conn.close()

    return _row_to_response(updated_row)


@router.put("/{app_id}/docs", response_model=AppResponse)
def update_app_docs(app_id: str, req: AppDocsUpdateRequest, request: Request):
    """Save the pipeline's README. Docs don't change how the pipeline runs, so unlike PUT /{app_id}
    this works on published apps too; the next publish snapshots them with the version."""
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE apps SET docs = ?, updated_at = ? WHERE id = ? AND tenant_id = ? AND project_id = ?",
        (req.docs, datetime.utcnow().isoformat(), app_id, ctx.tenant_id, ctx.project_id),
    )
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="App not found")
    conn.commit()
    cursor.execute("SELECT * FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?", (app_id, ctx.tenant_id, ctx.project_id))
    row = cursor.fetchone()
    conn.close()
    return _row_to_response(row)


@router.put("/{app_id}/rename", response_model=AppResponse)
def rename_app(app_id: str, req: AppRenameRequest, request: Request):
    """Rename a pipeline. The name doesn't change how it runs (callers use its id), so unlike
    PUT /{app_id} this works on published apps too; published versions keep their snapshot."""
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name can't be empty")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE apps SET name = ?, updated_at = ? WHERE id = ? AND tenant_id = ? AND project_id = ?",
        (name, datetime.utcnow().isoformat(), app_id, ctx.tenant_id, ctx.project_id),
    )
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="App not found")
    conn.commit()
    cursor.execute("SELECT * FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?", (app_id, ctx.tenant_id, ctx.project_id))
    row = cursor.fetchone()
    conn.close()
    return _row_to_response(row)


class PublishRequest(BaseModel):
    force: bool = False   # publish even when a blocking eval gate fails (recorded as "overridden")
    # provider -> API key from the browser's key store, for the gate's eval run
    provider_keys: Dict[str, str] = Field(default_factory=dict)


class PublishGateUpdate(BaseModel):
    dataset_id: str = Field(..., min_length=1)
    scorer: str = "contains"
    min_pass_rate: float = Field(default=0.8, ge=0.0, le=1.0)
    no_regression: bool = True
    regression_tolerance: float = Field(default=0.0, ge=0.0, le=1.0)
    mode: str = "block"
    enabled: bool = True
    timeout_ms: int = Field(default=120000, ge=1000, le=600000)


def _gate_scope(ctx, provider_keys: Dict[str, str]) -> RunScope:
    keys = {k.lower(): v for k, v in provider_keys.items() if v}
    return RunScope(tenant_id=ctx.tenant_id, project_id=ctx.project_id, user_id=ctx.user_id, provider_keys=keys)


async def _run_gate(app_id: str, row, gate: Dict[str, Any], ctx, provider_keys: Dict[str, str]) -> Dict[str, Any]:
    try:
        return await publish_gate.check(app_id, row["version"] or 0, gate, _gate_scope(ctx, provider_keys))
    except (LookupError, ValueError) as e:
        raise HTTPException(status_code=409, detail={
            "message": f"Eval gate could not run: {e}",
            "gate": {"status": "error", "mode": gate["mode"], "reasons": [str(e)]},
        })


@router.post("/{app_id}/publish", response_model=AppResponse)
async def publish_app(app_id: str, request: Request, body: Optional[PublishRequest] = None):
    """Snapshot the current draft as a published version (v1, v2, …).
    Saves the current flow_data as a versioned snapshot and marks the pipeline published.

    When the pipeline has an enabled eval gate (services/publish_gate.py) the draft is
    evaluated first; a failing blocking gate returns 409 with the gate result unless
    ``force`` is set.
    """
    body = body or PublishRequest()
    ctx = get_request_context(request)
    require_access(ctx, "apps", "publish")
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?",
                       (app_id, ctx.tenant_id, ctx.project_id)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="App not found")

    # A skill whose tools aren't attached or set up can't work for anyone using the published app
    from services import skills_runtime
    try:
        flow = json.loads(row["flow_data"] or "{}")
    except (TypeError, json.JSONDecodeError):
        flow = {}
    token = request_scope.set((ctx.tenant_id, ctx.project_id))   # skills resolve in this project
    try:
        not_ready = await asyncio.to_thread(skills_runtime.readiness, flow.get("nodes", []), flow.get("edges", []))
    finally:
        request_scope.reset(token)
    if not_ready:
        raise HTTPException(status_code=409, detail={
            "message": "; ".join(skills_runtime.describe(i) for i in not_ready), "skills": not_ready})

    gate_result: Optional[Dict[str, Any]] = None
    gate_status: Optional[str] = None
    gate = publish_gate.get_gate(app_id, ctx.tenant_id, ctx.project_id)
    if gate and gate["enabled"]:
        gate_result = await _run_gate(app_id, row, gate, ctx, body.provider_keys)
        if gate_result["status"] == "passed":
            gate_status = "passed"
        elif gate["mode"] == "warn":
            gate_status = "warned"
        elif body.force:
            gate_status = "overridden"
        else:
            raise HTTPException(status_code=409, detail={
                "message": "Eval gate failed — " + "; ".join(gate_result["reasons"]),
                "gate": gate_result,
            })

    conn = get_db_connection()
    try:
        # Re-read: the version may have moved while the gate ran
        row = conn.execute("SELECT * FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?",
                           (app_id, ctx.tenant_id, ctx.project_id)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="App not found")
        new_version = (row["version"] or 0) + 1
        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE apps SET status = 'published', version = ?, updated_at = ? WHERE id = ? AND tenant_id = ? AND project_id = ?",
            (new_version, now, app_id, ctx.tenant_id, ctx.project_id),
        )
        upsert(conn, "app_versions", {
            "app_id": app_id, "version": new_version, "tenant_id": ctx.tenant_id, "project_id": ctx.project_id,
            "name": row["name"], "description": row["description"] or "", "flow_data": row["flow_data"],
            "docs": row["docs"] or "", "created_at": now, "published_by": ctx.user_id, "gate_status": gate_status,
            "gate_pass_rate": gate_result["pass_rate"] if gate_result else None,
            "gate_eval_run_id": gate_result["eval_run_id"] if gate_result else None,
        }, key=("app_id", "version"))
        conn.commit()
        updated_row = conn.execute("SELECT * FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?",
                                   (app_id, ctx.tenant_id, ctx.project_id)).fetchone()
    finally:
        conn.close()
    if gate_result:
        publish_gate.label_run(gate_result["eval_run_id"], new_version)
        gate_result["status"] = gate_status

    resp = _row_to_response(updated_row)
    resp.publish_gate = gate_result
    return resp


# ── Publish gate config ───────────────────────────────────────────────────────

def _require_app(app_id: str, ctx) -> None:
    conn = get_db_connection()
    try:
        found = conn.execute("SELECT 1 FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?",
                             (app_id, ctx.tenant_id, ctx.project_id)).fetchone()
    finally:
        conn.close()
    if not found:
        raise HTTPException(status_code=404, detail="App not found")


@router.get("/{app_id}/publish-gate")
def get_publish_gate(app_id: str, request: Request):
    """The pipeline's eval gate, or null when it has none."""
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    _require_app(app_id, ctx)
    return publish_gate.get_gate(app_id, ctx.tenant_id, ctx.project_id)


@router.put("/{app_id}/publish-gate")
def put_publish_gate(app_id: str, body: PublishGateUpdate, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "apps", "publish")
    _require_app(app_id, ctx)
    if body.scorer not in publish_gate.SCORERS:
        raise HTTPException(status_code=422, detail=f"scorer must be one of {', '.join(publish_gate.SCORERS)}")
    if body.mode not in publish_gate.MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {', '.join(publish_gate.MODES)}")
    conn = get_db_connection()
    try:
        if not conn.execute("SELECT 1 FROM eval_datasets WHERE id = ? AND tenant_id = ? AND project_id = ?",
                            (body.dataset_id, ctx.tenant_id, ctx.project_id)).fetchone():
            raise HTTPException(status_code=404, detail="Eval dataset not found")
        values = (body.dataset_id, body.scorer, body.min_pass_rate, int(body.no_regression), body.regression_tolerance,
                  body.mode, int(body.enabled), body.timeout_ms, ctx.user_id, datetime.utcnow().isoformat())
        cur = conn.execute(
            "UPDATE publish_gates SET dataset_id = ?, scorer = ?, min_pass_rate = ?, no_regression = ?, "
            "regression_tolerance = ?, mode = ?, enabled = ?, timeout_ms = ?, updated_by = ?, updated_at = ? "
            "WHERE app_id = ? AND tenant_id = ? AND project_id = ?",
            (*values, app_id, ctx.tenant_id, ctx.project_id),
        )
        if cur.rowcount == 0:
            conn.execute(
                "INSERT INTO publish_gates (dataset_id, scorer, min_pass_rate, no_regression, regression_tolerance, mode, "
                "enabled, timeout_ms, updated_by, updated_at, app_id, tenant_id, project_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*values, app_id, ctx.tenant_id, ctx.project_id),
            )
        conn.commit()
    finally:
        conn.close()
    return publish_gate.get_gate(app_id, ctx.tenant_id, ctx.project_id)


@router.delete("/{app_id}/publish-gate")
def delete_publish_gate(app_id: str, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "apps", "publish")
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM publish_gates WHERE app_id = ? AND tenant_id = ? AND project_id = ?",
                     (app_id, ctx.tenant_id, ctx.project_id))
        conn.commit()
    finally:
        conn.close()
    return {"deleted": True, "app_id": app_id}


@router.post("/{app_id}/publish-gate/check")
async def check_publish_gate(app_id: str, request: Request, body: Optional[PublishRequest] = None):
    """Dry run: evaluate the current draft against the gate without publishing."""
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?",
                       (app_id, ctx.tenant_id, ctx.project_id)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="App not found")
    gate = publish_gate.get_gate(app_id, ctx.tenant_id, ctx.project_id)
    if not gate:
        raise HTTPException(status_code=404, detail="This pipeline has no eval gate")
    return await _run_gate(app_id, row, gate, ctx, (body or PublishRequest()).provider_keys)


@router.get("/{app_id}/versions")
def list_app_versions(app_id: str, request: Request):
    """Published snapshots of an app, newest first — what a pipeline child can pin to."""
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT version, name, description, flow_data, created_at, published_by, gate_status, gate_pass_rate, "
        "gate_eval_run_id FROM app_versions "
        "WHERE app_id = ? AND tenant_id = ? AND project_id = ? ORDER BY version DESC",
        (app_id, ctx.tenant_id, ctx.project_id),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            node_count = len(json.loads(r["flow_data"] or "{}").get("nodes", []))
        except Exception:
            node_count = 0
        out.append({
            "version": r["version"], "name": r["name"], "description": r["description"] or "",
            "node_count": node_count, "created_at": r["created_at"], "published_by": r["published_by"],
            "gate_status": r["gate_status"], "gate_pass_rate": r["gate_pass_rate"],
            "gate_eval_run_id": r["gate_eval_run_id"],
        })
    return out


@router.get("/{app_id}/versions/{version}")
def get_app_version(app_id: str, version: int, request: Request):
    """One published snapshot with its full flow — used to preview a pinned pipeline child."""
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    conn = get_db_connection()
    row = conn.execute(
        "SELECT version, name, description, flow_data, docs, created_at FROM app_versions "
        "WHERE app_id = ? AND version = ? AND tenant_id = ? AND project_id = ?",
        (app_id, version, ctx.tenant_id, ctx.project_id),
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Version v{version} not found")
    try:
        flow = json.loads(row["flow_data"] or "{}")
    except Exception:
        flow = {}
    return {
        "app_id": app_id, "version": row["version"], "name": row["name"],
        "description": row["description"] or "", "flow_data": flow, "docs": row["docs"] or "",
        "created_at": row["created_at"],
    }


@router.post("/{app_id}/edit", response_model=AppResponse)
def start_editing(app_id: str, request: Request):
    """Unlock a published pipeline for editing — bumps to vN-draft status.
    The version number is preserved so we know which published version is being revised.
    """
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?", (app_id, ctx.tenant_id, ctx.project_id))
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="App not found")

    if row["status"] != "published":
        conn.close()
        raise HTTPException(status_code=400, detail="App is not in published state.")

    now = datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE apps SET status = 'draft', updated_at = ? WHERE id = ? AND tenant_id = ? AND project_id = ?",
        (now, app_id, ctx.tenant_id, ctx.project_id),
    )
    conn.commit()

    cursor.execute("SELECT * FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?", (app_id, ctx.tenant_id, ctx.project_id))
    updated_row = cursor.fetchone()
    conn.close()

    return _row_to_response(updated_row)


@router.delete("/{app_id}")
def delete_app(app_id: str, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "apps", "delete")
    conn = get_db_connection()
    conn.execute("DELETE FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?", (app_id, ctx.tenant_id, ctx.project_id))
    conn.execute("DELETE FROM app_versions WHERE app_id = ? AND tenant_id = ? AND project_id = ?", (app_id, ctx.tenant_id, ctx.project_id))
    conn.execute("DELETE FROM schedule_runs WHERE app_id = ? AND tenant_id = ? AND project_id = ?", (app_id, ctx.tenant_id, ctx.project_id))
    conn.execute("DELETE FROM schedules WHERE app_id = ? AND tenant_id = ? AND project_id = ?", (app_id, ctx.tenant_id, ctx.project_id))
    conn.execute("DELETE FROM webhook_runs WHERE app_id = ? AND tenant_id = ? AND project_id = ?", (app_id, ctx.tenant_id, ctx.project_id))
    conn.execute("DELETE FROM webhooks WHERE app_id = ? AND tenant_id = ? AND project_id = ?", (app_id, ctx.tenant_id, ctx.project_id))
    conn.execute("DELETE FROM notification_channels WHERE app_id = ? AND tenant_id = ? AND project_id = ?", (app_id, ctx.tenant_id, ctx.project_id))
    conn.execute("DELETE FROM publish_gates WHERE app_id = ? AND tenant_id = ? AND project_id = ?", (app_id, ctx.tenant_id, ctx.project_id))
    conn.commit()
    conn.close()
    return {"success": True, "deleted_id": app_id}


@router.delete("")
def delete_all_apps(request: Request):
    """Bulk delete every pipeline (admin use)."""
    ctx = get_request_context(request)
    require_access(ctx, "apps", "delete")
    conn = get_db_connection()
    count = conn.execute("SELECT COUNT(*) FROM apps WHERE tenant_id = ? AND project_id = ?", (ctx.tenant_id, ctx.project_id)).fetchone()[0]
    conn.execute("DELETE FROM apps WHERE tenant_id = ? AND project_id = ?", (ctx.tenant_id, ctx.project_id))
    conn.execute("DELETE FROM app_versions WHERE tenant_id = ? AND project_id = ?", (ctx.tenant_id, ctx.project_id))
    conn.execute("DELETE FROM schedule_runs WHERE tenant_id = ? AND project_id = ?", (ctx.tenant_id, ctx.project_id))
    conn.execute("DELETE FROM schedules WHERE tenant_id = ? AND project_id = ?", (ctx.tenant_id, ctx.project_id))
    conn.execute("DELETE FROM webhook_runs WHERE tenant_id = ? AND project_id = ?", (ctx.tenant_id, ctx.project_id))
    conn.execute("DELETE FROM webhooks WHERE tenant_id = ? AND project_id = ?", (ctx.tenant_id, ctx.project_id))
    conn.execute("DELETE FROM notification_channels WHERE app_id IS NOT NULL AND tenant_id = ? AND project_id = ?", (ctx.tenant_id, ctx.project_id))
    conn.execute("DELETE FROM publish_gates WHERE tenant_id = ? AND project_id = ?", (ctx.tenant_id, ctx.project_id))
    conn.commit()
    conn.close()
    return {"success": True, "deleted_count": count}


