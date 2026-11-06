"""
workflows.py — conversational, pausable workflows built from wf_step nodes.

POST /api/workflows/{app_id}/start      — begin a run of a published app
POST /api/workflows/runs/{run_id}/reply — answer the question the run is waiting on
GET  /api/workflows/runs/{run_id}       — current state of a run
POST /api/workflows/preview             — run the unsaved Build canvas (stateless; nothing persisted)

Each response has the same shape:
  {run_id, status: waiting_input|completed|failed, messages: [...], input: {...}|null,
   variables, error}
A run pins the flow snapshot it started with, so republishing the app mid-conversation
does not break it.  Runs are private to the user (and tenant/project) that started them.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db import get_db_connection
from services.acl import require_access
from services.request_context import get_request_context
from services.workflow_engine import advance, new_state

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class WorkflowStartRequest(BaseModel):
    message: str = ""                                   # opening user message, exposed as {{initial_message}}
    variables: Dict[str, Any] = Field(default_factory=dict)   # pre-filled answers; matching Ask steps are skipped


class WorkflowReplyRequest(BaseModel):
    message: Optional[str] = None
    choice: Optional[str] = None


class WorkflowPreviewRequest(BaseModel):
    flow: Dict[str, Any]                       # {nodes, edges} straight from the canvas
    state: Optional[Dict[str, Any]] = None     # state returned by the previous call; omit to start
    message: Optional[str] = None
    choice: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _response(run_id: str, state: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "status": result["status"],
        "messages": result["messages"],
        "input": result["input"],
        "variables": state["variables"],
        "error": result["error"],
    }


def _save(conn, run_id: str, status: str, state: Dict[str, Any]) -> None:
    conn.execute(
        "UPDATE workflow_runs SET status = ?, current_node = ?, variables = ?, history = ?, updated_at = ? "
        "WHERE run_id = ?",
        (status, state["current_node"], json.dumps(state["variables"]), json.dumps(state["history"]), _now(), run_id),
    )
    conn.commit()


def _load_run(conn, run_id: str, ctx) -> Any:
    row = conn.execute(
        "SELECT * FROM workflow_runs WHERE run_id = ? AND tenant_id = ? AND project_id = ? AND user_id = ?",
        (run_id, ctx.tenant_id, ctx.project_id, ctx.user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return row


@router.post("/{app_id}/start")
async def start_workflow(app_id: str, req: WorkflowStartRequest, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")

    conn = get_db_connection()
    try:
        app = conn.execute(
            "SELECT name, flow_data, status, version FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?",
            (app_id, ctx.tenant_id, ctx.project_id),
        ).fetchone()
        if not app:
            raise HTTPException(status_code=404, detail="Workflow not found")
        if app["status"] != "published":
            raise HTTPException(status_code=409, detail="Workflow is not published. Publish it to run it.")
        try:
            flow = json.loads(app["flow_data"] or "{}")
        except json.JSONDecodeError:
            raise HTTPException(status_code=422, detail="Workflow has corrupt flow data")
        if not any(n.get("type") == "wf_step" for n in flow.get("nodes", [])):
            raise HTTPException(status_code=422, detail="This app has no Workflow Step nodes to run.")

        state = new_state({**req.variables, "initial_message": req.message.strip()})
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        now = _now()
        conn.execute(
            "INSERT INTO workflow_runs (run_id, app_id, app_version, tenant_id, project_id, user_id, status, "
            "flow_data, current_node, variables, history, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'running', ?, NULL, '{}', '[]', ?, ?)",
            (run_id, app_id, app["version"] or 0, ctx.tenant_id, ctx.project_id, ctx.user_id,
             json.dumps(flow), now, now),
        )
        conn.commit()

        result = await advance(flow, state)
        _save(conn, run_id, result["status"], state)
        return _response(run_id, state, result)
    finally:
        conn.close()


@router.post("/preview")
async def preview_workflow(req: WorkflowPreviewRequest, request: Request):
    """Test-run the canvas from the Build view without publishing.

    The client keeps the run state and sends it back with each reply, so drafts never
    touch the workflow_runs table.
    """
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    if not any(n.get("type") == "wf_step" for n in req.flow.get("nodes", [])):
        raise HTTPException(status_code=422, detail="This canvas has no Workflow Step nodes to run.")

    if req.state is None:
        state = new_state({"initial_message": (req.message or "").strip()})
        result = await advance(req.flow, state)
    else:
        if req.message is None and req.choice is None:
            raise HTTPException(status_code=422, detail="Provide 'message' or 'choice'")
        state = {
            "variables": dict(req.state.get("variables") or {}),
            "current_node": req.state.get("current_node"),
            "history": list(req.state.get("history") or []),
        }
        result = await advance(req.flow, state, {"message": req.message, "choice": req.choice})
    return {**_response("preview", state, result), "state": state}


@router.post("/runs/{run_id}/reply")
async def reply_workflow(run_id: str, req: WorkflowReplyRequest, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    if req.message is None and req.choice is None:
        raise HTTPException(status_code=422, detail="Provide 'message' or 'choice'")

    conn = get_db_connection()
    try:
        row = _load_run(conn, run_id, ctx)
        if row["status"] != "waiting_input":
            raise HTTPException(status_code=409, detail=f"Run is {row['status']}, not waiting for input")
        state = {
            "variables": json.loads(row["variables"]),
            "current_node": row["current_node"],
            "history": json.loads(row["history"]),
        }
        result = await advance(json.loads(row["flow_data"]), state, {"message": req.message, "choice": req.choice})
        _save(conn, run_id, result["status"], state)
        return _response(run_id, state, result)
    finally:
        conn.close()


@router.get("/runs/{run_id}")
def get_workflow_run(run_id: str, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    conn = get_db_connection()
    try:
        row = _load_run(conn, run_id, ctx)
    finally:
        conn.close()
    return {
        "run_id": row["run_id"],
        "app_id": row["app_id"],
        "app_version": row["app_version"],
        "status": row["status"],
        "current_node": row["current_node"],
        "variables": json.loads(row["variables"]),
        "history": json.loads(row["history"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
