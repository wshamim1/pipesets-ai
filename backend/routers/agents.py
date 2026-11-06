"""
agents.py — Master / Child multi-agent orchestration endpoints.

Architecture
------------
A **Master Agent** receives a high-level goal and a list of Child Agent
configs.  It uses its LLM to write a task plan, then dispatches each task
to the appropriate child.  Children execute independently (each with their
own LLM + optional tools) and return their result.  The master collects all
results and produces a final synthesised answer.

Endpoints
---------
POST /api/agents/run     — Execute a master + child agent flow.
GET  /api/agents/runs    — List recent agent run summaries.
GET  /api/agents/runs/{run_id} — Full trace for one run.

Strategies
----------
sequential — master calls children one at a time; each child receives the
             previous child's output as additional context.
parallel   — master calls all children simultaneously (asyncio.gather);
             master then synthesises the collected outputs.
dynamic    — master iteratively decides which child to call next based on
             the accumulated context (up to max_steps).
"""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import llm
from db import IntegrityError, get_db_connection
from routers.memory import rough_token_count
from routers.middleware import check_prompt_middleware, check_response_middleware, redact_pii
from models import LLMConfig
from services import child_tool_loop, shared_state, skills_runtime, telemetry
from services.checkpoint import (  # noqa: F401 — mark_interrupted_runs is used through this module
    CANCEL_FLAG_SECONDS, RESUMABLE, Checkpointer, GateRejected, GateUnsupported, RunPaused,
    cancel_flag, gate_expired, heartbeat, mark_interrupted_runs, set_status,
)
from services.checkpoint import options as checkpoint_options
from services.external_agent import ExternalAgentSpec, invoke_external_agent
from services.pipeline_runner import RunScope, current_scope, run_published_pipeline
from services.request_context import RequestContext, get_request_context

logger = logging.getLogger("pipesets-ai-backend")

router = APIRouter(prefix="/api/agents", tags=["agents"])


# ── Pydantic request / response ───────────────────────────────────────────────

class ChildAgentConfig(BaseModel):
    agent_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    label: str = "Child Agent"
    role: str = "Researcher"
    provider: str = "mock"
    model: str = "mock-gpt-4"
    api_key: str = ""
    timeout_ms: int = Field(default=45000, ge=1000, le=300000)
    max_retries: int = Field(default=1, ge=0, le=5)
    retry_backoff_ms: int = Field(default=500, ge=0, le=10000)
    fallback_provider: Optional[str] = None
    fallback_model: Optional[str] = None
    fallback_api_key: Optional[str] = None
    fallback_base_url: Optional[str] = None
    base_url: Optional[str] = None
    system_prompt: str = "You are a helpful specialist. Complete the task given to you."
    # Tool / Toolkit / MCP server and Skill nodes wired to the child, as an LLM node's attached_tools /
    # attached_skills: an llm child with any runs the tool loop (services/child_tool_loop.py)
    attached_tools: List[Dict[str, Any]] = Field(default_factory=list)
    attached_skills: List[Dict[str, Any]] = Field(default_factory=list)
    skill_mode: Optional[Literal["on_demand", "always"]] = None
    # Older callers name tools and skills by id only; used when attached_tools / attached_skills are empty
    allowed_tool_ids: List[str] = Field(default_factory=list)
    skill_ids: List[str] = Field(default_factory=list, description="IDs of skills attached to this agent")
    # kind: llm (default) | external (remote agent over HTTP) | pipeline (published app)
    kind: str = "llm"
    app_id: str = ""                  # pipeline: id of the published app to run
    app_version: int = 0              # pipeline: pinned published version (0 = current)
    endpoint_url: str = ""
    protocol: str = "openai"          # openai | rest | a2a  (kind == external)
    auth_type: str = "bearer"         # none | bearer | header
    auth_header: str = "X-API-Key"
    request_template: str = ""
    response_path: str = ""
    # middleware nodes wired to this child: [{type, config, enabled}] — guards its input and output
    middleware_configs: Optional[List[Dict[str, Any]]] = None
    # human_gate node wired to this child: pauses the run for review of its output
    human_gate: Optional[Dict[str, Any]] = None
    # Editor debugging (plan.md F6): answer with this instead of running the child. Only the Prompt
    # Runner sends it; the server's request builder never copies it from a node (the node keeps its
    # pin as ``debug_pin``), so published runs can't use a pin.
    pinned_output: Optional[str] = None


class GateDecision(BaseModel):
    action: Literal["approve", "reject", "edit"]
    edited_output: Optional[str] = None   # edit gates: replaces the reviewed output
    comment: Optional[str] = Field(default=None, max_length=2000)


class MasterAgentRunRequest(BaseModel):
    goal: str
    provider: str = "mock"
    model: str = "mock-gpt-4"
    api_key: str = ""
    timeout_ms: int = Field(default=45000, ge=1000, le=300000)
    max_retries: int = Field(default=1, ge=0, le=5)
    retry_backoff_ms: int = Field(default=500, ge=0, le=10000)
    fallback_provider: Optional[str] = None
    fallback_model: Optional[str] = None
    fallback_api_key: Optional[str] = None
    fallback_base_url: Optional[str] = None
    base_url: Optional[str] = None
    strategy: str = "sequential"   # sequential | parallel | dynamic
    max_steps: int = Field(default=5, ge=1, le=20)
    children: List[ChildAgentConfig] = Field(default_factory=list)
    session_id: Optional[str] = None
    # provider -> API key from the browser's global key store (used by pipeline children)
    provider_keys: Dict[str, str] = Field(default_factory=dict)
    # middleware nodes wired to the master: guards the goal and the final answer
    middleware_configs: Optional[List[Dict[str, Any]]] = None
    # human_gate node wired to the master: pauses for review of the final answer
    human_gate: Optional[Dict[str, Any]] = None
    # Client-chosen id, so the caller can resume even if the response never arrives
    run_id: Optional[str] = Field(default=None, max_length=64)
    # Resume a paused / interrupted / failed run: re-send the same request plus this id
    resume_from: Optional[str] = Field(default=None, max_length=64)
    gate_decision: Optional[GateDecision] = None   # required when resuming a paused run
    # Checkpointer node config {save_steps, restore_on_resume} (services/checkpoint.options)
    checkpoint: Optional[Dict[str, Any]] = None


class AgentStepTrace(BaseModel):
    step: int
    agent: str          # "master" | child label
    role: str
    input: str
    output: str
    duration_ms: int
    # When the step began (Unix seconds), so traces can place parallel steps; None on old checkpoints
    started_at: Optional[float] = None
    attempt_count: int = 1
    used_fallback: bool = False
    effective_provider: str = ""
    effective_model: str = ""
    total_tokens: int = 0
    cost_usd: float = 0.0
    middleware_flags: List[str] = Field(default_factory=list)
    # Child agents that ran the tool loop: one record per call, and the skills they loaded
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    skills_used: List[Dict[str, Any]] = Field(default_factory=list)


class MasterAgentRunResponse(BaseModel):
    run_id: str
    goal: str
    strategy: str
    final_answer: str
    steps: List[AgentStepTrace]
    total_steps: int
    retry_steps: int = 0
    fallback_steps: int = 0
    success: bool
    error: Optional[str] = None
    status: str = "completed"                     # completed | paused | failed | rejected | cancelled
    pending_gate: Optional[Dict[str, Any]] = None  # set while paused at a human gate
    resumed_steps: int = 0                         # steps reused from the checkpoint


class GuardrailBlocked(Exception):
    """A middleware node blocked the goal, a child's input/output or the final answer.

    Fails the whole run. status_code is set only for the master's goal check,
    which the endpoint surfaces as HTTP 400 / 429 like /api/run.
    """

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


# ── Run persistence (checkpointed — see services/checkpoint.py) ──────────────

def _fingerprint(req: MasterAgentRunRequest) -> str:
    """Hash of everything that shapes a run's steps (never keys). A resume must
    match it, so saved steps are never replayed into a flow that has changed."""
    def gate(g: Optional[Dict[str, Any]]) -> Optional[str]:
        return (g or {}).get("gate_type", "approval") if g else None
    shape = {
        "goal": req.goal, "strategy": req.strategy, "max_steps": req.max_steps,
        "master": [req.provider, req.model, gate(req.human_gate)],
        "children": [
            [c.agent_id, c.kind, c.role, c.provider, c.model, c.app_id, c.endpoint_url,
             c.system_prompt, sorted(c.skill_ids), gate(c.human_gate),
             sorted(t.get("toolId", "") for t in _child_tools(c)),
             sorted(sk.get("skill_id") or sk.get("label") or "" for sk in _child_skills(c)), c.skill_mode]
            for c in req.children
        ],
    }
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode()).hexdigest()


def _checkpoint_options(req: MasterAgentRunRequest) -> tuple[bool, bool]:
    """(save_steps, restore_on_resume). A flow with a human gate always saves and restores its
    steps: a reviewer's decision must apply to the output they reviewed, not to a re-run."""
    if req.human_gate or any(c.human_gate for c in req.children):
        return True, True
    return checkpoint_options(req.checkpoint)


def _insert_run(run_id: str, req: MasterAgentRunRequest, ctx: RequestContext, app_id: Optional[str]) -> None:
    """Claim the run id. The goal is left empty until it passes the guardrails
    (_set_goal), so a blocked goal is never written, not even to be overwritten."""
    now = datetime.utcnow().isoformat()
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO agent_runs (run_id, goal, strategy, final_answer, steps, success, status, app_id, "
            "tenant_id, project_id, user_id, fingerprint, checkpoint, created_at, updated_at) "
            "VALUES (?, '', ?, '', '[]', 0, 'running', ?, ?, ?, ?, ?, '{}', ?, ?)",
            (run_id, req.strategy, app_id, ctx.tenant_id, ctx.project_id, ctx.user_id,
             _fingerprint(req), now, now),
        )
        conn.commit()
    except IntegrityError:
        raise HTTPException(status_code=409, detail=f"Run '{run_id}' already exists — use resume_from to continue it")
    finally:
        conn.close()


def _claim_for_resume(req: MasterAgentRunRequest, ctx: RequestContext) -> Dict[str, Any]:
    """Validate a resume and atomically flip the run back to running.
    Returns the checkpoint state with any gate decision applied."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM agent_runs WHERE run_id = ? AND tenant_id = ? AND project_id = ?",
            (req.resume_from, ctx.tenant_id, ctx.project_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Run not found")
        if row["status"] not in RESUMABLE:
            raise HTTPException(status_code=409, detail=f"Run is {row['status']}; only paused, interrupted or failed runs can resume")
        if row["fingerprint"] != _fingerprint(req):
            raise HTTPException(status_code=409, detail="The flow changed since this run started (goal, agents, models or prompts), so its saved steps can't be reused. Start a new run.")

        state = json.loads(row["checkpoint"] or "{}")
        pending = json.loads(row["pending_gate"]) if row["pending_gate"] else None
        if row["status"] == "paused" and pending:
            decision = req.gate_decision.model_dump() if req.gate_decision else None
            if decision is None and gate_expired(pending):
                on_timeout = pending.get("on_timeout", "reject")
                if on_timeout in ("approve", "reject"):
                    decision = {"action": on_timeout, "comment": "Review timed out"}
                else:
                    raise HTTPException(status_code=409, detail=f"Review at '{pending['agent']}' timed out and was escalated — a reviewer must send gate_decision")
            if decision is None:
                raise HTTPException(status_code=400, detail=f"Run is waiting for review at '{pending['agent']}' — send gate_decision (approve, reject or edit)")
            if decision["action"] == "edit" and pending.get("gate_type") != "edit":
                raise HTTPException(status_code=400, detail="This gate is approve/reject only; 'edit' needs an edit gate")
            if decision["action"] == "edit" and decision.get("edited_output") is None:
                raise HTTPException(status_code=400, detail="An edit decision needs edited_output")
            state.setdefault("gates", {})[pending["key"]] = {**decision, "decided_by": ctx.user_id,
                                                            "decided_at": datetime.utcnow().isoformat()}
        elif not _checkpoint_options(req)[1]:
            state["steps"] = {}   # the Checkpointer node says a resume of a cut-off run starts over

        claimed = conn.execute(
            "UPDATE agent_runs SET status = 'running', pending_gate = NULL, error = NULL, checkpoint = ?, updated_at = ? "
            "WHERE run_id = ? AND status = ?",
            (json.dumps(state), datetime.utcnow().isoformat(), row["run_id"], row["status"]),
        ).rowcount
        conn.commit()
        if not claimed:
            raise HTTPException(status_code=409, detail="Run was resumed by another request")
        return state
    finally:
        conn.close()


def _finish_run(result: MasterAgentRunResponse, cp: Checkpointer) -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE agent_runs SET final_answer = ?, steps = ?, success = ?, error = ?, status = ?, "
            "pending_gate = ?, checkpoint = ?, updated_at = ? WHERE run_id = ?",
            (result.final_answer, json.dumps([s.model_dump() for s in result.steps]),
             1 if result.success else 0, result.error, result.status,
             json.dumps(result.pending_gate) if result.pending_gate else None,
             json.dumps(cp.state), datetime.utcnow().isoformat(), result.run_id),
        )
        conn.commit()
    finally:
        conn.close()


def _set_goal(run_id: str, goal: str) -> None:
    conn = get_db_connection()
    try:
        conn.execute("UPDATE agent_runs SET goal = ? WHERE run_id = ?", (goal, run_id))
        conn.commit()
    finally:
        conn.close()


# ── LLM call helper ───────────────────────────────────────────────────────────

async def _llm_call(
    provider: str,
    model: str,
    api_key: str,
    messages: List[Dict[str, str]],
    timeout_ms: int = 45000,
    max_retries: int = 1,
    retry_backoff_ms: int = 500,
    fallback_provider: Optional[str] = None,
    fallback_model: Optional[str] = None,
    fallback_api_key: Optional[str] = None,
    fallback_base_url: Optional[str] = None,
    base_url: Optional[str] = None,
) -> tuple[str, Dict[str, Any]]:
    """Call the model through the LLM gateway and return assistant text + reliability metadata."""

    def _provider_needs_key(p: str) -> bool:
        return p.lower() not in {"mock", "local", "ollama", "llamacpp", "jan"}

    candidates: List[Dict[str, Any]] = [{
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "is_fallback": False,
    }]
    if fallback_provider and fallback_model and fallback_provider.lower() != "mock":
        candidates.append({
            "provider": fallback_provider,
            "model": fallback_model,
            "api_key": fallback_api_key or api_key,
            "base_url": fallback_base_url or base_url,
            "is_fallback": True,
        })

    retries = max(0, int(max_retries or 0))
    backoff_ms = max(0, int(retry_backoff_ms or 0))
    timeout_s = max(1000, int(timeout_ms or 45000)) / 1000.0

    last_error: Optional[Exception] = None
    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")

    for candidate in candidates:
        p = str(candidate["provider"] or "").lower()
        m = str(candidate["model"] or "")
        key = str(candidate.get("api_key") or "")
        url = candidate.get("base_url") or None   # None = Settings → Model backends, then the provider default
        is_fallback = bool(candidate.get("is_fallback"))

        for attempt in range(1, retries + 2):
            if p == "mock" or (_provider_needs_key(p) and not key):
                if p == "mock" or not is_fallback:
                    return (
                        f"[Mock {m}] Processed: {last_user[:120]}",
                        {
                            "attempt_count": attempt,
                            "used_fallback": is_fallback,
                            "effective_provider": p,
                            "effective_model": m,
                        },
                    )
                last_error = RuntimeError(f"Missing API key for provider {p}")
            else:
                try:
                    resp = await asyncio.wait_for(
                        llm.complete(llm.LLMRequest(provider=p, model=m, messages=messages, api_key=key,
                                                    base_url=url, max_tokens=1024)),
                        timeout=timeout_s,
                    )
                    return (
                        resp.text,
                        {
                            "attempt_count": attempt,
                            "used_fallback": is_fallback,
                            "effective_provider": p,
                            "effective_model": m,
                            "total_tokens": resp.usage.total_tokens if resp.usage else 0,
                            "cost_usd": resp.cost_usd,
                        },
                    )
                except Exception as e:
                    last_error = e

            if attempt <= retries and backoff_ms > 0:
                await asyncio.sleep((backoff_ms * attempt) / 1000.0)

    logger.warning(f"LLM call failed [{provider}/{model}]: {last_error}")
    return (
        f"[Error from {model}]: {last_error}",
        {
            "attempt_count": retries + 1,
            "used_fallback": bool(fallback_provider and fallback_model),
            "effective_provider": provider,
            "effective_model": model,
        },
    )


# ── Tools and skills of a child ───────────────────────────────────────────────

def _child_tools(child: ChildAgentConfig) -> List[Dict[str, Any]]:
    return child.attached_tools or [{"toolId": t, "label": t, "config": {}} for t in child.allowed_tool_ids]


def _child_skills(child: ChildAgentConfig) -> List[Dict[str, Any]]:
    return child.attached_skills or [{"skill_id": s} for s in child.skill_ids]


def _child_skillset(child: ChildAgentConfig, can_call_tools: bool) -> skills_runtime.SkillSet:
    """The child's skills, read in the run's own tenant / project (built-ins otherwise)."""
    return skills_runtime.SkillSet(_child_skills(child), child.skill_mode, None, can_call_tools)


# ── Child execution ───────────────────────────────────────────────────────────

async def _run_child(
    child: ChildAgentConfig,
    task: str,
    context: str,
    step_num: int,
) -> AgentStepTrace:
    """Run a child behind its middleware nodes.

    The input check covers task + context, so injected text in an earlier
    child's output is caught before it reaches the next agent.
    """
    if not child.middleware_configs:
        return await _run_child_unguarded(child, task, context, step_num)

    rate_key = f"agent:{child.agent_id}"   # per-child bucket for the rate limiter
    user_content = f"Context from previous steps:\n{context}\n\nYour task:\n{task}" if context else task
    blocked, _, flags = check_prompt_middleware(child.middleware_configs, user_content, rate_key)
    if blocked:
        raise GuardrailBlocked(f"{child.label} input blocked — {blocked}")

    trace = await _run_child_unguarded(child, task, context, step_num)
    blocked, out_flags = check_response_middleware(
        child.middleware_configs, trace.output, rate_key,
        trace.total_tokens or rough_token_count(trace.output), trace.cost_usd,
    )
    if blocked:
        raise GuardrailBlocked(f"{child.label} output blocked — {blocked}")
    trace.middleware_flags = flags + out_flags
    return trace


def _epoch(t: datetime) -> float:
    """A naive UTC datetime (as ``datetime.utcnow()`` gives) as Unix seconds."""
    return t.replace(tzinfo=timezone.utc).timestamp()


async def _run_child_unguarded(
    child: ChildAgentConfig,
    task: str,
    context: str,
    step_num: int,
) -> AgentStepTrace:
    t0 = datetime.utcnow()

    if child.pinned_output is not None:   # pinned in the editor: no model, tool or pipeline call
        user_content = f"Context from previous steps:\n{context}\n\nYour task:\n{task}" if context else task
        return AgentStepTrace(step=step_num, agent=child.label, role=child.role, input=user_content,
                              output=child.pinned_output, duration_ms=0, started_at=_epoch(t0),
                              effective_provider="pinned", effective_model="pinned")

    if child.kind == "pipeline":
        output, telemetry = await run_published_pipeline(child.app_id, task, context, child.timeout_ms, child.app_version)
        user_content = f"Context from previous steps:\n{context}\n\nYour task:\n{task}" if context else task
        return AgentStepTrace(
            step=step_num,
            agent=child.label,
            role=child.role,
            input=user_content[:500],
            output=output,
            duration_ms=int((datetime.utcnow() - t0).total_seconds() * 1000), started_at=_epoch(t0),
            attempt_count=int(telemetry.get("attempt_count", 1)),
            used_fallback=False,
            effective_provider=str(telemetry.get("effective_provider", "pipeline")),
            effective_model=str(telemetry.get("effective_model", child.app_id)),
        )

    if child.kind == "external":
        spec = ExternalAgentSpec(
            endpoint_url=child.endpoint_url,
            protocol=child.protocol,
            api_key=child.api_key,
            auth_type=child.auth_type,
            auth_header=child.auth_header,
            model=child.model,
            system_prompt=child.system_prompt,
            request_template=child.request_template,
            response_path=child.response_path,
            timeout_ms=child.timeout_ms,
            max_retries=child.max_retries,
            retry_backoff_ms=child.retry_backoff_ms,
        )
        output, telemetry = await invoke_external_agent(spec, task, context)
        user_content = f"Context from previous steps:\n{context}\n\nYour task:\n{task}" if context else task
        return AgentStepTrace(
            step=step_num,
            agent=child.label,
            role=child.role,
            input=user_content[:500],
            output=output,
            duration_ms=int((datetime.utcnow() - t0).total_seconds() * 1000), started_at=_epoch(t0),
            attempt_count=int(telemetry.get("attempt_count", 1)),
            used_fallback=False,
            effective_provider=str(telemetry.get("effective_provider", "external")),
            effective_model=str(telemetry.get("effective_model", "")),
        )

    system = child.system_prompt or f"You are a specialist {child.role}."
    user_content = task
    if context:
        user_content = f"Context from previous steps:\n{context}\n\nYour task:\n{task}"

    tools = _child_tools(child)
    cfg = LLMConfig(provider=child.provider, model=child.model, api_key=child.api_key, base_url=child.base_url,
                    timeout_ms=child.timeout_ms, max_retries=child.max_retries,
                    retry_backoff_ms=child.retry_backoff_ms, fallback_provider=child.fallback_provider,
                    fallback_model=child.fallback_model, fallback_api_key=child.fallback_api_key,
                    fallback_base_url=child.fallback_base_url)
    looped = bool(tools or _child_skills(child)) and child_tool_loop.can_use_tools(cfg)
    skillset = _child_skillset(child, looped)

    if looped:
        try:
            output, telemetry = await child_tool_loop.run(cfg, system, user_content, tools, skillset)
        except Exception as e:
            logger.warning(f"Child tool loop failed [{child.provider}/{child.model}]: {e}")
            output, telemetry = f"[Error from {child.model}]: {e}", {}
    else:
        # Mock, keyless or no function calling: one call, every skill's instructions in the prompt
        messages = [
            {"role": "system", "content": system + skillset.prompt_section()},
            {"role": "user", "content": user_content},
        ]
        output, telemetry = await _llm_call(
            child.provider,
            child.model,
            child.api_key,
            messages,
            timeout_ms=child.timeout_ms,
            max_retries=child.max_retries,
            retry_backoff_ms=child.retry_backoff_ms,
            fallback_provider=child.fallback_provider,
            fallback_model=child.fallback_model,
            fallback_api_key=child.fallback_api_key,
            fallback_base_url=child.fallback_base_url,
            base_url=child.base_url,
        )
    duration = int((datetime.utcnow() - t0).total_seconds() * 1000)

    return AgentStepTrace(
        step=step_num,
        agent=child.label,
        role=child.role,
        input=user_content[:500],
        output=output,
        duration_ms=duration, started_at=_epoch(t0),
        attempt_count=int(telemetry.get("attempt_count", 1)),
        used_fallback=bool(telemetry.get("used_fallback", False)),
        effective_provider=str(telemetry.get("effective_provider", child.provider)),
        effective_model=str(telemetry.get("effective_model", child.model)),
        total_tokens=int(telemetry.get("total_tokens", 0)),
        cost_usd=float(telemetry.get("cost_usd", 0.0)),
        tool_calls=telemetry.get("tool_calls", []),
        skills_used=telemetry.get("skills_used", []),
    )


# ── Master planning helpers ────────────────────────────────────────────────────

async def _master_plan(req: MasterAgentRunRequest, context: str = "") -> tuple[str, Dict[str, Any]]:
    """Ask the master LLM to produce a task plan or delegation decision."""
    child_descriptions = "\n".join(
        f"- {c.label} ({c.role}): {c.system_prompt[:80]}"
        for c in req.children
    )
    user_msg = (
        f"Goal: {req.goal}\n\n"
        f"Available specialist agents:\n{child_descriptions or 'None'}\n\n"
        f"{'Current context:\n' + context + chr(10) + chr(10) if context else ''}"
        f"Write a brief task for each agent in order. Return as numbered list."
    )
    messages = [
        {"role": "system", "content": "You are a master orchestrator. Delegate tasks to specialist agents to achieve the goal."},
        {"role": "user", "content": user_msg},
    ]
    return await _llm_call(
        req.provider,
        req.model,
        req.api_key,
        messages,
        timeout_ms=req.timeout_ms,
        max_retries=req.max_retries,
        retry_backoff_ms=req.retry_backoff_ms,
        fallback_provider=req.fallback_provider,
        fallback_model=req.fallback_model,
        fallback_api_key=req.fallback_api_key,
        fallback_base_url=req.fallback_base_url,
        base_url=req.base_url,
    )


async def _master_synthesise(req: MasterAgentRunRequest, child_outputs: List[AgentStepTrace]) -> tuple[str, Dict[str, Any]]:
    """Ask the master to synthesise all child outputs into a final answer."""
    outputs_text = "\n\n".join(
        f"[{s.agent} — {s.role}]:\n{s.output}" for s in child_outputs
    )
    messages = [
        {"role": "system", "content": "You are a master orchestrator. Synthesise the specialist outputs into a single coherent final answer."},
        {"role": "user", "content": f"Goal: {req.goal}\n\nSpecialist outputs:\n{outputs_text}\n\nFinal answer:"},
    ]
    return await _llm_call(
        req.provider,
        req.model,
        req.api_key,
        messages,
        timeout_ms=req.timeout_ms,
        max_retries=req.max_retries,
        retry_backoff_ms=req.retry_backoff_ms,
        fallback_provider=req.fallback_provider,
        fallback_model=req.fallback_model,
        fallback_api_key=req.fallback_api_key,
        fallback_base_url=req.fallback_base_url,
        base_url=req.base_url,
    )


# ── Strategy executors ────────────────────────────────────────────────────────

def _master_trace(req: MasterAgentRunRequest, step: int, role: str, input_text: str,
                  output: str, meta: Dict[str, Any], t0: datetime) -> AgentStepTrace:
    return AgentStepTrace(
        step=step, agent="Master Agent", role=role, input=input_text, output=output,
        duration_ms=int((datetime.utcnow() - t0).total_seconds() * 1000), started_at=_epoch(t0),
        attempt_count=int(meta.get("attempt_count", 1)),
        used_fallback=bool(meta.get("used_fallback", False)),
        effective_provider=str(meta.get("effective_provider", req.provider)),
        effective_model=str(meta.get("effective_model", req.model)),
        total_tokens=int(meta.get("total_tokens", 0)),
        cost_usd=float(meta.get("cost_usd", 0.0)),
    )


def _step_ok(trace: AgentStepTrace) -> bool:
    """Only successful steps are checkpointed, so a failed one is retried on resume.
    LLM, external and pipeline agents all report failures as "[Error from ...]"."""
    return not trace.output.startswith("[Error from")


async def _plan_step(req: MasterAgentRunRequest, cp: Checkpointer) -> AgentStepTrace:
    async def plan() -> AgentStepTrace:
        t0 = datetime.utcnow()
        output, meta = await _master_plan(req)
        return _master_trace(req, 0, "Orchestrator", req.goal, output, meta, t0)
    return await cp.step("plan", plan, _step_ok)


async def _child_step(cp: Checkpointer, key: str, child: ChildAgentConfig,
                      task: str, context: str, step_num: int) -> AgentStepTrace:
    return await cp.step(key, lambda: _run_child(child, task, context, step_num), _step_ok)


def _gate_child(cp: Checkpointer, key: str, child: ChildAgentConfig, trace: AgentStepTrace) -> AgentStepTrace:
    """Pause for review of a child's output if a human gate is wired to it.
    An edit decision replaces the output that later steps see."""
    if not child.human_gate:
        return trace
    reviewed = cp.gate(f"gate:{key}", child.human_gate, child.label, trace.output)
    return trace if reviewed == trace.output else trace.model_copy(update={"output": reviewed})


async def _run_sequential(req: MasterAgentRunRequest, cp: Checkpointer) -> List[AgentStepTrace]:
    plan = await _plan_step(req, cp)
    steps = [plan]
    context = plan.output
    for i, child in enumerate(req.children, start=1):
        key = f"child:{child.agent_id}"
        trace = _gate_child(cp, key, child, await _child_step(cp, key, child, req.goal, context, i))
        steps.append(trace)
        context += f"\n\n[{child.role} output]:\n{trace.output}"
    return steps


async def _run_parallel(req: MasterAgentRunRequest, cp: Checkpointer) -> List[AgentStepTrace]:
    plan = await _plan_step(req, cp)
    # All children run in parallel; each is checkpointed as it finishes, so a
    # resume only re-runs the ones that hadn't. Gates are reviewed afterwards, in order.
    traces = await asyncio.gather(*[
        _child_step(cp, f"child:{child.agent_id}", child, req.goal, plan.output, i + 1)
        for i, child in enumerate(req.children)
    ])
    gated = [_gate_child(cp, f"child:{c.agent_id}", c, t) for c, t in zip(req.children, traces)]
    return [plan, *gated]


async def _run_dynamic(req: MasterAgentRunRequest, cp: Checkpointer) -> List[AgentStepTrace]:
    """Master decides at each step which child to call next."""
    steps: List[AgentStepTrace] = []
    context = ""
    children_by_role = {c.role.lower(): c for c in req.children}

    for step_num in range(req.max_steps):
        decision_prompt = (
            f"Goal: {req.goal}\n\n"
            f"Completed steps so far:\n{context or 'None'}\n\n"
            f"Available agents: {', '.join(c.role for c in req.children)}\n\n"
            "Which agent should act next, and what should their task be? "
            "Reply with JSON: {\"role\": \"<role>\", \"task\": \"<task>\"} "
            "or {\"done\": true, \"final\": \"<answer>\"} if the goal is complete."
        )

        async def decide() -> AgentStepTrace:
            t0 = datetime.utcnow()
            messages = [
                {"role": "system", "content": "You are an orchestrator. Return only valid JSON."},
                {"role": "user", "content": decision_prompt},
            ]
            output, meta = await _llm_call(
                req.provider,
                req.model,
                req.api_key,
                messages,
                timeout_ms=req.timeout_ms,
                max_retries=req.max_retries,
                retry_backoff_ms=req.retry_backoff_ms,
                fallback_provider=req.fallback_provider,
                fallback_model=req.fallback_model,
                fallback_api_key=req.fallback_api_key,
                fallback_base_url=req.fallback_base_url,
                base_url=req.base_url,
            )
            return _master_trace(req, step_num * 2, "Orchestrator", decision_prompt[:300], output, meta, t0)

        decision_trace = await cp.step(f"dyn:{step_num}:decide", decide, _step_ok)
        steps.append(decision_trace)
        decision_raw = decision_trace.output

        # Try to parse the decision
        try:
            decision = json.loads(decision_raw[decision_raw.find('{'):decision_raw.rfind('}') + 1])
        except Exception:
            # Can't parse — treat as done
            break

        if decision.get("done"):
            # Master signalled completion — inject final answer as last step
            steps.append(AgentStepTrace(
                step=step_num * 2 + 1, agent="Master Agent", role="Final Answer",
                input="synthesis", output=decision.get("final", decision_raw),
                duration_ms=0, started_at=time.time(),
            ))
            break

        role = decision.get("role", "").lower()
        task = decision.get("task", req.goal)
        child = next((c for key, c in children_by_role.items() if role in key or key in role), None)
        if not child and req.children:
            child = req.children[0]
        if not child:
            break

        key = f"dyn:{step_num}:child:{child.agent_id}"
        trace = _gate_child(cp, key, child, await _child_step(cp, key, child, task, context, step_num * 2 + 1))
        steps.append(trace)
        context += f"\n\n[{child.role} step {step_num + 1}]:\n{trace.output}"

    return steps


# ── Main endpoint ─────────────────────────────────────────────────────────────

async def _execute_master(
    req: MasterAgentRunRequest, cp: Optional[Checkpointer] = None,
    record_goal: Optional[Callable[[str], None]] = None,
) -> tuple[str, List[AgentStepTrace]]:
    """Run the configured strategy, then let the master synthesise the child outputs.

    The master's middleware guards the goal (before any LLM call) and the final
    answer; nested master pipelines come through here too, so they are covered.
    Without a checkpointer (nested pipelines) nothing is saved and human gates
    fail closed, since a nested run can't pause its parent.
    record_goal stores the goal with the run once checked — PII redacted if it was blocked.
    """
    cp = cp or Checkpointer(None, AgentStepTrace)
    goal_flags: List[str] = []
    if req.middleware_configs:
        blocked, throttled, goal_flags = check_prompt_middleware(req.middleware_configs, req.goal, req.session_id)
        if blocked:
            if record_goal:
                record_goal(redact_pii(req.goal))
            raise GuardrailBlocked(blocked, status_code=429 if throttled else 400)
    if record_goal:
        record_goal(req.goal)

    final, steps = await _execute_strategy(req, cp)

    if req.middleware_configs:
        blocked, final_flags = check_response_middleware(
            req.middleware_configs, final, req.session_id,
            sum(s.total_tokens for s in steps) or rough_token_count(final),
            sum(s.cost_usd for s in steps),
        )
        if blocked:
            raise GuardrailBlocked(f"Final answer blocked — {blocked}")
        if steps:
            steps[0].middleware_flags = goal_flags + steps[0].middleware_flags
            steps[-1].middleware_flags = steps[-1].middleware_flags + final_flags
    return final, steps


async def _execute_strategy(req: MasterAgentRunRequest, cp: Checkpointer) -> tuple[str, List[AgentStepTrace]]:
    if req.strategy == "parallel":
        steps = await _run_parallel(req, cp)
    elif req.strategy == "dynamic":
        steps = await _run_dynamic(req, cp)
    else:
        steps = await _run_sequential(req, cp)

    child_steps = [s for s in steps if s.agent != "Master Agent"]
    if child_steps:
        async def synthesise() -> AgentStepTrace:
            t0 = datetime.utcnow()
            output, meta = await _master_synthesise(req, child_steps)
            return _master_trace(req, len(steps), "Synthesiser", "Synthesise all child outputs", output, meta, t0)
        synth = await cp.step("synth", synthesise, _step_ok)
        steps.append(synth)
        final = synth.output
    else:
        # No children — master answers directly
        final = steps[-1].output if steps else f"[No children configured for goal: {req.goal}]"

    # A human gate on the master reviews the final answer (before the final guardrail check)
    if req.human_gate:
        final = cp.gate("gate:final", req.human_gate, "Master Agent", final)
    return final, steps


async def run_master(
    req: MasterAgentRunRequest, ctx: RequestContext, app_id: Optional[str] = None,
) -> MasterAgentRunResponse:
    """Start a checkpointed run, or resume one (req.resume_from). Used by /api/agents/run
    and the public /v1 API. Pauses at human gates come back as status='paused'."""
    if req.resume_from:
        state = _claim_for_resume(req, ctx)
        run_id = req.resume_from
    else:
        run_id = req.run_id or str(uuid.uuid4())
        _insert_run(run_id, req, ctx, app_id)
        state = None
    cp = Checkpointer(run_id, AgentStepTrace, state, keep_steps=_checkpoint_options(req)[0])
    started = time.time()
    resumed = cp.resumed_count()

    status, error, pending, final = "completed", None, None, ""
    steps: List[AgentStepTrace] = []
    scope_token = current_scope.set(RunScope(
        tenant_id=ctx.tenant_id, project_id=ctx.project_id, user_id=ctx.user_id,
        provider_keys={k.lower(): v for k, v in req.provider_keys.items() if v},
        # A run of a published app puts it in the cycle chain so nested pipelines can't call it back.
        chain=(app_id,) if app_id else (),
    ))
    http_error: Optional[HTTPException] = None
    # A resumed run's goal is already stored and was checked when it started.
    record_goal = None if req.resume_from else (lambda goal: _set_goal(run_id, goal))
    # The steps run in their own task, so a cancel request can stop them without cancelling this one
    work = asyncio.create_task(_execute_master(req, cp, record_goal))
    cancelled: List[bool] = []
    beat = asyncio.create_task(heartbeat(run_id, work, cancelled))
    try:
        final, steps = await work
    except asyncio.CancelledError:
        if not cancelled:
            # Caller timed out or disconnected mid-run: keep the checkpoint, mark it resumable.
            work.cancel()
            set_status(run_id, "interrupted")
            raise
        status, error, final = "cancelled", "Cancelled by request", "⏹ Run cancelled"
        steps = cp.completed_steps()
        shared_state.clear_flag(cancel_flag(run_id))
    except RunPaused as p:
        status, pending = "paused", p.gate
        steps = cp.completed_steps()
    except GateRejected as e:
        # Terminal: a reviewer said no, so the run is not resumable.
        status, error, final = "rejected", str(e), f"✋ {e}"
        steps = cp.completed_steps()
    except GateUnsupported as e:
        status, error, final = "failed", str(e), f"✋ {e}"
        steps = cp.completed_steps()
    except GuardrailBlocked as e:
        status, error, final = "failed", str(e), f"⚠ Blocked by guardrail: {e}"
        steps = cp.completed_steps()
        if e.status_code:
            http_error = HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as e:
        logger.error(f"Agent run error: {e}")
        status, error, final = "failed", str(e), f"Agent run failed: {e}"
        steps = cp.completed_steps()
    finally:
        beat.cancel()
        current_scope.reset(scope_token)

    result = MasterAgentRunResponse(
        run_id=run_id,
        goal=req.goal,
        strategy=req.strategy,
        final_answer=final,
        steps=steps,
        total_steps=len(steps),
        retry_steps=sum(1 for s in steps if s.attempt_count > 1),
        fallback_steps=sum(1 for s in steps if s.used_fallback),
        success=status == "completed",
        error=error,
        status=status,
        pending_gate=pending,
        resumed_steps=resumed,
    )
    _finish_run(result, cp)
    telemetry.record_agent_run(result, started, app_id)   # metrics + an OpenTelemetry trace when configured
    if http_error:
        raise http_error
    return result


@router.post("/run", response_model=MasterAgentRunResponse)
async def run_agent_flow(req: MasterAgentRunRequest, request: Request):
    return await run_master(req, get_request_context(request))


class ExternalAgentTestRequest(BaseModel):
    endpoint_url: str
    protocol: str = "openai"
    api_key: str = ""
    auth_type: str = "bearer"
    auth_header: str = "X-API-Key"
    model: str = ""
    request_template: str = ""
    response_path: str = ""
    timeout_ms: int = Field(default=15000, ge=1000, le=300000)


@router.post("/external/test")
async def test_external_agent(req: ExternalAgentTestRequest):
    """Send a ping task to an external agent so the UI can verify the config."""
    spec = ExternalAgentSpec(
        endpoint_url=req.endpoint_url, protocol=req.protocol, api_key=req.api_key,
        auth_type=req.auth_type, auth_header=req.auth_header, model=req.model,
        request_template=req.request_template, response_path=req.response_path,
        timeout_ms=req.timeout_ms, max_retries=0,
    )
    t0 = datetime.utcnow()
    output, _ = await invoke_external_agent(spec, "Reply with the single word: pong", "")
    ok = not output.startswith("[Error from external agent")
    return {
        "ok": ok,
        "latency_ms": int((datetime.utcnow() - t0).total_seconds() * 1000),
        "output": output[:500],
    }


def _run_row_to_dict(row, full: bool = False) -> Dict[str, Any]:
    pending = json.loads(row["pending_gate"]) if row["pending_gate"] else None
    if pending:
        pending["expired"] = gate_expired(pending)
    out = {
        "run_id": row["run_id"], "kind": row["kind"], "goal": row["goal"], "strategy": row["strategy"],
        "status": row["status"], "success": bool(row["success"]), "error": row["error"],
        "app_id": row["app_id"], "user_id": row["user_id"],
        "pending_gate": pending, "created_at": row["created_at"], "updated_at": row["updated_at"],
        "resumable": row["status"] in RESUMABLE,
    }
    if full:
        out["final_answer"] = row["final_answer"]
        out["steps"] = json.loads(row["steps"] or "[]")
        state = json.loads(row["checkpoint"] or "{}")
        out["checkpointed_steps"] = len(state.get("steps", {}))
        out["forked_from"] = state.get("forked_from")
        # LLM runs: what the trace drawer needs to re-run from a step (tool results to edit)
        out["rerunnable"] = row["kind"] == "llm" and bool(row["app_id"]) and bool(state.get("steps"))
        if row["kind"] == "llm":
            out["tool_results"] = {k: v[:20000] for k, v in state.get("steps", {}).items()
                                   if k.startswith("tool:") and isinstance(v, str)}
    return out


@router.get("/runs")
def list_runs(request: Request, limit: int = 20, status: Optional[str] = None, kind: Optional[str] = None):
    """Recent runs: Master Agent ("master") and checkpointed LLM-node runs ("llm")."""
    ctx = get_request_context(request)
    sql = "SELECT * FROM agent_runs WHERE tenant_id = ? AND project_id = ?"
    params: List[Any] = [ctx.tenant_id, ctx.project_id]
    if status:
        sql += " AND status = ?"
        params.append(status)
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    conn = get_db_connection()
    try:
        rows = conn.execute(sql + " ORDER BY created_at DESC LIMIT ?", (*params, limit)).fetchall()
    finally:
        conn.close()
    return {"runs": [_run_row_to_dict(r) for r in rows]}


@router.get("/runs/{run_id}/steps/{step_key}")
def get_step_output(run_id: str, step_key: str, request: Request):
    """The full output a single-LLM run saved for one step (``tool:…``, ``llm:N``, ``rag``): what the
    editor pins to a node (plan.md F6). Streamed tool events and trace spans carry only a preview."""
    ctx = get_request_context(request)
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT checkpoint FROM agent_runs WHERE run_id = ? AND tenant_id = ? AND project_id = ?",
                           (run_id, ctx.tenant_id, ctx.project_id)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    saved = json.loads(row["checkpoint"] or "{}").get("steps", {}).get(step_key)
    if saved is None:
        raise HTTPException(status_code=404, detail="That step wasn't saved with this run")
    if step_key.startswith("llm:"):
        output = saved.get("text", "") if isinstance(saved, dict) else str(saved)
    elif step_key == "rag":
        output = saved[0] if isinstance(saved, list) and saved else ""
    else:
        output = saved if isinstance(saved, str) else json.dumps(saved, ensure_ascii=False)
    return {"run_id": run_id, "step": step_key, "output": output}


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request):
    ctx = get_request_context(request)
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM agent_runs WHERE run_id = ? AND tenant_id = ? AND project_id = ?",
            (run_id, ctx.tenant_id, ctx.project_id),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_row_to_dict(row, full=True)


class RerunRequest(BaseModel):
    from_step: str = Field(..., max_length=128, description="checkpoint_key of a span in the run's trace")
    edited_output: Optional[str] = Field(default=None, description="A tool step's result to continue with")
    timeout_ms: int = Field(default=120000, ge=1000, le=600000)
    # provider -> API key from the browser's key store; the project's vault and the server's env otherwise
    provider_keys: Dict[str, str] = Field(default_factory=dict)


@router.post("/runs/{run_id}/rerun")
async def rerun_from_step(run_id: str, body: RerunRequest, request: Request):
    """Time travel: re-run an LLM-node run from one of its steps, as a new run. Steps saved before
    it are reused; that step and the ones after it run again against the app's current flow. A
    tool step can be given an edited result to continue with. The original run is unchanged."""
    from routers.v1 import _collect, _provider_keys  # lazy: v1 imports this module
    from services import llm_checkpoint
    from services.llm_runner import run_stream
    from services.pipeline_runner import llm_rerun_request

    ctx = get_request_context(request)
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM agent_runs WHERE run_id = ? AND tenant_id = ? AND project_id = ?",
                           (run_id, ctx.tenant_id, ctx.project_id)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["kind"] != llm_checkpoint.KIND:
        raise HTTPException(status_code=409, detail="Only LLM-node runs can be re-run from a step")
    if not row["app_id"]:
        raise HTTPException(status_code=409, detail="This run came from an unsaved canvas — save the app to re-run its runs from a step")
    if row["status"] == "running":
        raise HTTPException(status_code=409, detail="The run is still running")

    saved = json.loads(row["checkpoint"] or "{}").get("input", {})
    scope = RunScope(tenant_id=ctx.tenant_id, project_id=ctx.project_id, user_id=ctx.user_id,
                     provider_keys=_provider_keys(body.provider_keys, (ctx.tenant_id, ctx.project_id)),
                     end_user=saved.get("end_user") or "", chain=(row["app_id"],))
    try:
        req = llm_rerun_request(dict(row), scope)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    req.run_id = str(uuid.uuid4())
    token = current_scope.set(scope)
    try:
        cp = llm_checkpoint.fork(req, dict(row), body.from_step, body.edited_output)
    except llm_checkpoint.NotResumable as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    finally:
        current_scope.reset(token)

    async def events():
        token = current_scope.set(scope)
        try:
            async for chunk in run_stream(req, cp):
                if chunk.startswith("data: "):
                    yield json.loads(chunk[6:])
        finally:
            try:
                current_scope.reset(token)
            except ValueError:
                pass

    res = await _collect({"id": row["app_id"], "name": "", "version": 0}, events(), body.timeout_ms)
    return {"run_id": req.run_id, "forked_from": {"run_id": run_id, "step": body.from_step},
            "status": res["status"], "output": res["output"], "error": res["error"],
            "meta": res["meta"], "latency_ms": res["latency_ms"]}


def request_cancel(run_id: str, tenant_id: str, project_id: str) -> str:
    """Cancel a run. A paused / interrupted / failed one is closed here ('cancelled'); a running one
    gets a cancel signal its process picks up within seconds, on any replica ('cancelling').
    Raises LookupError when the run doesn't exist, ValueError when it has already finished."""
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT status FROM agent_runs WHERE run_id = ? AND tenant_id = ? AND project_id = ?",
                           (run_id, tenant_id, project_id)).fetchone()
        if not row:
            raise LookupError(run_id)
        if row["status"] == "running":
            shared_state.set_flag(cancel_flag(run_id), CANCEL_FLAG_SECONDS)
            return "cancelling"
        n = conn.execute(
            "UPDATE agent_runs SET status = 'cancelled', pending_gate = NULL, updated_at = ? "
            "WHERE run_id = ? AND tenant_id = ? AND project_id = ? AND status IN (?, ?, ?)",
            (datetime.utcnow().isoformat(), run_id, tenant_id, project_id, *RESUMABLE),
        ).rowcount
        conn.commit()
    finally:
        conn.close()
    if not n:
        raise ValueError(f"Run is {row['status']}")
    return "cancelled"


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, request: Request):
    """Stop a running run, or give up on a paused / interrupted / failed one (it can no longer resume)."""
    ctx = get_request_context(request)
    try:
        status = request_cancel(run_id, ctx.tenant_id, ctx.project_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Run not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=f"{e}; only running, paused, interrupted or failed runs can be cancelled")
    return {"run_id": run_id, "status": status}
