"""
checkpoint.py — durable, resumable master-agent runs via step memoization.

Every step of a run (master plan, each child, each dynamic decision, synthesis)
executes through ``Checkpointer.step(key, fn)``. A finished step's result is saved
under its key in ``agent_runs.checkpoint`` right away. Resuming re-runs the strategy
from the top with the saved state: saved keys return instantly, so no LLM call is
repeated, and execution continues from the first step that never finished.

This works because a strategy is deterministic given its steps' outputs — the
context a later step sees is rebuilt from the saved outputs, so the same keys come
up in the same order. Only successful steps are saved; a step that failed (e.g. the
provider was down) runs again on resume.

Human gates pause a run: ``gate()`` raises ``RunPaused`` until a decision for that
gate is recorded, and the next resume carries the decision in.

Provider keys never enter the checkpoint — a resume re-sends the request.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Type, TypeVar

from pydantic import BaseModel

from db import get_db_connection
from services import shared_state

logger = logging.getLogger("pipesets-ai-backend")

T = TypeVar("T", bound=BaseModel)

GATE_ACTIONS = ("approve", "reject", "edit")
RESUMABLE = ("paused", "interrupted", "failed")


class RunPaused(Exception):
    """Raised at a human gate with no decision yet; the run stops and waits."""

    def __init__(self, gate: Dict[str, Any]):
        super().__init__(f"Waiting for human review at '{gate['agent']}'")
        self.gate = gate


class GateRejected(Exception):
    """A reviewer rejected the output at a human gate; the run fails."""


class GateUnsupported(Exception):
    """A human gate inside a run that cannot pause (a nested pipeline)."""


def options(cfg: Optional[Dict[str, Any]]) -> Tuple[bool, bool]:
    """(save_steps, restore_on_resume) from a Checkpointer node's config; both on without one.

    save_steps off: no model or tool output is kept, only the run's status (and gate decisions),
    so a resume starts over. restore_on_resume off: steps are kept (for inspection and re-runs
    from a step) but a resume of an interrupted or failed run starts over."""
    cfg = cfg or {}
    return cfg.get("save_steps", True) is not False, cfg.get("restore_on_resume", True) is not False


class Checkpointer:
    """Saves each finished step of one run. ``run_id=None`` makes it ephemeral:
    nothing is persisted and gates fail closed (used for nested pipeline runs,
    which cannot pause without pausing their parent). ``keep_steps=False`` keeps the run's
    row and gate decisions but no step output (a Checkpointer node with Save steps off)."""

    def __init__(self, run_id: Optional[str], model: Optional[Type[T]], state: Optional[Dict[str, Any]] = None,
                 keep_steps: bool = True):
        self.run_id = run_id
        self.model = model
        self.keep_steps = keep_steps
        self.state: Dict[str, Any] = state or {}
        self.state.setdefault("steps", {})   # key -> step dict, in completion order
        self.state.setdefault("gates", {})   # gate key -> decision dict

    @property
    def persistent(self) -> bool:
        return self.run_id is not None

    def completed_steps(self) -> List[T]:
        return [self.model.model_validate(s) for s in self.state["steps"].values()]

    def resumed_count(self) -> int:
        return len(self.state["steps"])

    async def step(self, key: str, fn: Callable[[], Awaitable[T]], ok: Callable[[T], bool] = lambda _: True) -> T:
        saved = self.state["steps"].get(key)
        if saved is not None:
            return self.model.model_validate(saved)
        result = await fn()
        if ok(result) and self.keep_steps:
            self.state["steps"][key] = result.model_dump()
            self.save()
        return result

    # Plain JSON values, for single-LLM runs (services/llm_checkpoint.py): ``value`` memoizes a
    # coroutine like ``step``; ``saved`` / ``put`` serve steps that stream while they run.

    def saved(self, key: str) -> Any:
        return self.state["steps"].get(key)

    def put(self, key: str, value: Any) -> None:
        if self.keep_steps:
            self.state["steps"][key] = value
            self.save()

    async def value(self, key: str, fn: Callable[[], Awaitable[Any]]) -> Any:
        if key in self.state["steps"]:
            return self.state["steps"][key]
        result = await fn()
        self.put(key, result)
        return result

    def gate(self, key: str, gate_cfg: Dict[str, Any], agent: str, output: str) -> str:
        """Return the output to continue with once the gate has a decision;
        raise RunPaused while it has none."""
        if not self.persistent:
            raise GateUnsupported(
                f"Human gate on '{agent}' can't pause inside a nested pipeline — run this flow directly instead."
            )
        decision = self.state["gates"].get(key)
        if decision is None:
            hours = float(gate_cfg.get("timeout_hours") or 0)
            now = datetime.utcnow()
            raise RunPaused({
                "key": key,
                "agent": agent,
                "gate_type": gate_cfg.get("gate_type", "approval"),
                "label": gate_cfg.get("label") or "Human review",
                "prompt_message": gate_cfg.get("prompt_message") or "Review this output before the run continues.",
                "output": output,
                "on_timeout": gate_cfg.get("on_timeout", "reject"),
                "paused_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=hours)).isoformat() if hours > 0 else None,
            })
        if decision["action"] == "reject":
            note = f": {decision['comment']}" if decision.get("comment") else ""
            raise GateRejected(f"Rejected at human gate on '{agent}'{note}")
        if decision["action"] == "edit" and decision.get("edited_output") is not None:
            return decision["edited_output"]
        return output

    def record_decision(self, gate_key: str, decision: Dict[str, Any]) -> None:
        self.state["gates"][gate_key] = {**decision, "decided_at": datetime.utcnow().isoformat()}

    def save(self) -> None:
        if not self.persistent:
            return
        conn = get_db_connection()
        try:
            conn.execute(
                "UPDATE agent_runs SET checkpoint = ?, updated_at = ? WHERE run_id = ?",
                (json.dumps(self.state), datetime.utcnow().isoformat(), self.run_id),
            )
            conn.commit()
        finally:
            conn.close()


def gate_expired(gate: Optional[Dict[str, Any]]) -> bool:
    return bool(gate and gate.get("expires_at")) and datetime.fromisoformat(gate["expires_at"]) <= datetime.utcnow()


# ── Run lifecycle (rows in agent_runs, Master Agent and single-LLM alike) ──────

def set_status(run_id: str, status: str) -> None:
    conn = get_db_connection()
    try:
        conn.execute("UPDATE agent_runs SET status = ?, updated_at = ? WHERE run_id = ?",
                     (status, datetime.utcnow().isoformat(), run_id))
        conn.commit()
    finally:
        conn.close()


# A running run's process touches updated_at this often; a run silent for STALE_SECONDS was cut off.
HEARTBEAT_SECONDS = float(os.getenv("AGENT_RUN_HEARTBEAT_SECONDS", "20"))
STALE_SECONDS = float(os.getenv("AGENT_RUN_STALE_SECONDS", "120"))
CANCEL_FLAG_SECONDS = 24 * 3600


def cancel_flag(run_id: str) -> str:
    return f"cancel:agent_run:{run_id}"


async def heartbeat(run_id: str, work: asyncio.Task, cancelled: List[bool]) -> None:
    """Touch updated_at every HEARTBEAT_SECONDS; between touches, check for a cancel request
    (set by any replica, services/shared_state.py) and stop ``work`` when there is one."""
    poll = min(HEARTBEAT_SECONDS, float(os.getenv("CANCEL_POLL_SECONDS", "2")))
    loop = asyncio.get_running_loop()
    last = loop.time()
    while True:
        await asyncio.sleep(poll)
        if await asyncio.to_thread(shared_state.has_flag, cancel_flag(run_id)):
            cancelled.append(True)
            work.cancel()
            return
        if loop.time() - last >= HEARTBEAT_SECONDS:
            last = loop.time()
            await asyncio.to_thread(_touch, run_id)


def _touch(run_id: str) -> None:
    conn = get_db_connection()
    try:
        conn.execute("UPDATE agent_runs SET updated_at = ? WHERE run_id = ? AND status = 'running'",
                     (datetime.utcnow().isoformat(), run_id))
        conn.commit()
    finally:
        conn.close()


def mark_interrupted_runs(stale_seconds: Optional[float] = None) -> int:
    """Runs still 'running' with no heartbeat for ``stale_seconds`` were cut off by a shutdown or
    crash: flag them so they can be resumed. Runs a live process is working on are left alone,
    so this is safe with several replicas (services/gates.py runs it periodically)."""
    stale = STALE_SECONDS if stale_seconds is None else stale_seconds
    now = datetime.utcnow()
    conn = get_db_connection()
    try:
        n = conn.execute(
            "UPDATE agent_runs SET status = 'interrupted', updated_at = ? WHERE status = 'running' AND updated_at < ?",
            (now.isoformat(), (now - timedelta(seconds=stale)).isoformat()),
        ).rowcount
        conn.commit()
    finally:
        conn.close()
    if n:
        logger.info(f"Marked {n} agent run(s) as interrupted — resumable via resume_from")
    return n
