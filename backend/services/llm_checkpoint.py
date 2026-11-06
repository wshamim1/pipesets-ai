"""
llm_checkpoint.py — checkpointed single-LLM runs.

A streamed LLM run with a run id (``PromptRunRequest.run_id``) gets a row in ``agent_runs`` with
kind "llm" and saves each finished step through ``services.checkpoint.Checkpointer``: retrieval,
the pre-parsed document, the loaded memory, every model turn and every tool result.

A resume re-sends the same request with ``resume_from``. The runner goes through the run from the
top; saved steps come back instantly (their text and tool events are streamed again, so the
answer arrives complete) and execution continues from the first step that never finished. No
finished model call is paid for twice and no finished tool call runs twice, which matters for
tools that write. A step that failed was never saved, so it runs again.

The lifecycle is the Master Agent one: a heartbeat keeps the row 'running', a cancel request from
any replica stops it, a run whose caller went away is 'interrupted', and one that stopped
heartbeating (crash, restart) is marked interrupted by services/gates.py.

Runs without an id save nothing: nested pipelines, evals and marketplace previews. A Checkpointer
node on the flow can turn saving off or make resumes start over (``PromptRunRequest.checkpoint``).
Provider keys never enter the checkpoint — a resume re-sends them with the request.
"""

import asyncio
import hashlib
import json
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from db import IntegrityError, get_db_connection
from models import PromptRunRequest
from services import shared_state
from services.checkpoint import RESUMABLE, Checkpointer, cancel_flag, heartbeat, options, set_status

KIND = "llm"


class NotResumable(Exception):
    """A run id that can't be started or resumed; ``status`` is the HTTP status to answer with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def fingerprint(req: PromptRunRequest) -> str:
    """Hash of everything that shapes the run's steps (never keys). A resume must match it, so
    saved steps are never replayed into a node whose prompt, model or tools have changed."""
    cfg = req.config
    shape = {
        "prompt": req.prompt.strip(), "retrieval_query": req.retrieval_query,
        "app_id": req.app_id, "node_id": req.node_id,
        "model": [cfg.provider, cfg.model, cfg.system_prompt, cfg.temperature, cfg.max_tokens, cfg.top_p] if cfg else None,
        "tools": [[t.get("toolId"), t.get("label")] for t in req.attached_tools or []],
        "skills": [s.get("skill_id") or s.get("name") or s.get("label") for s in req.attached_skills or []],
        "skill_mode": req.skill_mode or "on_demand",
        "retriever": [(req.retriever_config or {}).get(k) for k in ("collection_name", "top_k")],
        "parser": (req.output_parser or {}).get("parser_type"),
    }
    return hashlib.sha256(json.dumps(shape, sort_keys=True, default=str).encode()).hexdigest()


def _owner() -> Optional[Tuple[str, str, str, str]]:
    """(tenant, project, user, end user) of the run in progress, None outside a request or run."""
    from services.pipeline_runner import current_scope
    from services.request_context import request_user
    from services.secret_store import request_scope

    scope = current_scope.get()
    if scope:
        return scope.tenant_id, scope.project_id, scope.user_id, scope.end_user or ""
    rs = request_scope.get()
    if rs:
        user = request_user.get() or ""
        return rs[0], rs[1], user, user
    return None


def _insert(req: PromptRunRequest, owner: Tuple[str, str, str, str], state: Dict[str, Any], goal: str = "") -> None:
    tenant, project, user, _ = owner
    now = datetime.utcnow().isoformat()
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO agent_runs (run_id, kind, goal, strategy, final_answer, steps, success, status, app_id, "
            "tenant_id, project_id, user_id, fingerprint, checkpoint, created_at, updated_at) "
            "VALUES (?, ?, ?, 'single', '', '[]', 0, 'running', ?, ?, ?, ?, ?, ?, ?, ?)",
            (req.run_id, KIND, goal, req.app_id, tenant, project, user, fingerprint(req), json.dumps(state), now, now),
        )
        conn.commit()
    except IntegrityError:
        raise NotResumable(409, f"Run '{req.run_id}' already exists — use resume_from to continue it")
    finally:
        conn.close()


def start(req: PromptRunRequest) -> Optional[Checkpointer]:
    """Claim ``req.run_id`` for a new run. None when there's no tenant to own it (nothing saved)."""
    owner = _owner()
    if owner is None:
        return None
    # What a resume through /v1 needs to rebuild the request: the prompt is stored as the goal
    state = {"steps": {}, "gates": {}, "input": {"session_id": req.session_id, "end_user": owner[3]}}
    _insert(req, owner, state)
    return Checkpointer(req.run_id, None, state, keep_steps=options(req.checkpoint)[0])


def fork(req: PromptRunRequest, parent: Dict[str, Any], from_step: str,
         edited_output: Optional[str] = None) -> Checkpointer:
    """A new run (``req.run_id``) that starts as ``parent`` was just before step ``from_step``:
    every step saved before it is reused, that step and the ones after it run again. With
    ``edited_output`` a tool step is kept with that result instead, so the run continues from the
    next model call as if the tool had returned it ("what if"). The parent is left as it was."""
    owner = _owner()
    if owner is None:
        raise NotResumable(404, "Run not found")
    state = json.loads(parent["checkpoint"] or "{}")
    steps: Dict[str, Any] = state.get("steps", {})
    if from_step not in steps:
        raise NotResumable(409, f"Step '{from_step}' wasn't saved with this run (a Checkpointer node with "
                                "Save steps off keeps none), so the run can't be re-run from it")
    keys = list(steps)   # in the order they finished
    kept = {k: steps[k] for k in keys[:keys.index(from_step)]}
    if edited_output is not None:
        if not from_step.startswith("tool:"):
            raise NotResumable(400, "Only a tool step's result can be edited; re-run a model step without edits")
        kept[from_step] = edited_output
    new_state = {"steps": kept, "gates": {}, "input": state.get("input", {}),
                 "forked_from": {"run_id": parent["run_id"], "step": from_step, "edited": edited_output is not None}}
    _insert(req, owner, new_state, goal=parent["goal"])
    return Checkpointer(req.run_id, None, new_state)


def claim(req: PromptRunRequest) -> Checkpointer:
    """Validate a resume of ``req.resume_from`` and atomically flip the run back to running."""
    owner = _owner()
    if owner is None:
        raise NotResumable(404, "Run not found")
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM agent_runs WHERE run_id = ? AND tenant_id = ? AND project_id = ?",
                           (req.resume_from, owner[0], owner[1])).fetchone()
        if not row:
            raise NotResumable(404, "Run not found")
        if row["kind"] != KIND:
            raise NotResumable(409, "This is a Master Agent run — resume it through /api/agents/run")
        if row["status"] not in RESUMABLE:
            raise NotResumable(409, f"Run is {row['status']}; only interrupted or failed runs can resume")
        if row["fingerprint"] != fingerprint(req):
            raise NotResumable(409, "The node changed since this run started (prompt, model or tools), so its "
                                    "saved steps can't be reused. Start a new run.")
        claimed = conn.execute(
            "UPDATE agent_runs SET status = 'running', error = NULL, updated_at = ? WHERE run_id = ? AND status = ?",
            (datetime.utcnow().isoformat(), row["run_id"], row["status"]),
        ).rowcount
        conn.commit()
    finally:
        conn.close()
    if not claimed:
        raise NotResumable(409, "Run was resumed by another request")
    state = json.loads(row["checkpoint"] or "{}")
    save_steps, restore = options(req.checkpoint)
    if not restore:
        state["steps"] = {}   # the Checkpointer node says a resume starts over
    return Checkpointer(row["run_id"], None, state, keep_steps=save_steps)


def record_prompt(cp: Checkpointer, prompt: str) -> None:
    """Store the prompt once it has passed the guardrails (a blocked prompt is never written)."""
    conn = get_db_connection()
    try:
        conn.execute("UPDATE agent_runs SET goal = ? WHERE run_id = ? AND goal = ''", (prompt, cp.run_id))
        conn.commit()
    finally:
        conn.close()


def _finish(cp: Checkpointer, status: str, final: str, error: Optional[str]) -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE agent_runs SET final_answer = ?, success = ?, error = ?, status = ?, checkpoint = ?, "
            "updated_at = ? WHERE run_id = ?",
            (final, 1 if status == "completed" else 0, error, status, json.dumps(cp.state),
             datetime.utcnow().isoformat(), cp.run_id),
        )
        conn.commit()
    finally:
        conn.close()


def _sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def drive(cp: Checkpointer, events: AsyncIterator[str]) -> AsyncIterator[str]:
    """Stream ``events`` (the run's SSE chunks) while keeping its row up to date: heartbeat and
    cancel signals while it runs, then its outcome. The steps run in their own task, so a cancel
    stops them without cancelling the response, and a caller that goes away leaves the run
    'interrupted' with its checkpoint, ready to resume."""
    queue: asyncio.Queue = asyncio.Queue()

    async def pump() -> None:
        try:
            async for chunk in events:
                queue.put_nowait(chunk)
        finally:
            queue.put_nowait(None)

    work = asyncio.create_task(pump())
    cancelled: List[bool] = []
    beat = asyncio.create_task(heartbeat(cp.run_id, work, cancelled))
    text: List[str] = []
    error: Optional[str] = None
    paused = False   # stopped at a debugger breakpoint (services/debug_run.py)
    finished = False
    try:
        yield _sse({"type": "run", "run_id": cp.run_id, "resumed_steps": cp.resumed_count()})
        while (chunk := await queue.get()) is not None:
            if chunk.startswith("data: "):
                try:
                    ev = json.loads(chunk[6:])
                except json.JSONDecodeError:
                    ev = {}
                if ev.get("type") == "token":
                    text.append(ev.get("text", ""))
                elif ev.get("type") == "error":
                    error = ev.get("message") or "Unknown error"
                    if ev.get("retract"):
                        text.clear()
                elif ev.get("type") == "debug_paused":
                    paused = True
            yield chunk
        finished = True
        crashed = not cancelled and not work.cancelled() and work.exception() is not None
        if cancelled:
            status, error = "cancelled", "Cancelled by request"
            await asyncio.to_thread(shared_state.clear_flag, cancel_flag(cp.run_id))
        elif crashed:
            status, error = "failed", str(work.exception())
        elif paused and not error:
            status = "paused"   # resumed with resume_from, like an interrupted run
        else:
            status = "failed" if error else "completed"
        await asyncio.to_thread(_finish, cp, status, "".join(text), error)
        if cancelled or crashed:   # the steps stopped without closing the stream themselves
            yield _sse({"type": "error", "message": error, "run_id": cp.run_id})
            yield _sse({"type": "done"})
    finally:
        beat.cancel()
        if not finished:   # the caller disconnected or timed out: keep the checkpoint, resumable
            work.cancel()
            set_status(cp.run_id, "interrupted")
