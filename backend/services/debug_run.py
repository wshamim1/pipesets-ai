"""
debug_run.py — step-through debugging of a canvas run in the Prompt Runner (plan.md F6).

The editor sends ``PromptRunRequest.debug``:

  breakpoints  node ids: pause before each step of these nodes (every model call of an LLM node,
               every call of a Tool node, the retrieval of a Retriever node)
  step         pause before every step
  overrides    step key → edited input for that step: ``{"input": ...}`` for a tool (its arguments
               as JSON for typed tools), ``{"messages": [...]}`` for a model call, ``{"query": ...}``
               for the retrieval
  pins         node id → output to use instead of running the node (no model call, no tool run)

A pause is a checkpointed run that stops: before a breakpoint's step runs, the run saves
``debug_paused`` in its checkpoint, emits ``{"type": "debug_paused", ...}`` with the step's input and
ends ``paused`` (llm_checkpoint.drive). Continue re-sends the request with ``resume_from``: finished
steps replay from the checkpoint, the paused step runs (with its override, if any) and the run goes
on to the next breakpoint. Only checkpointed runs (a run id, steps saved) can pause; pins work on
any run.

Nothing here reaches published runs: ``/v1``, schedules, webhooks, batches and chat links build
their requests on the server (services/pipeline_runner.py) and never set ``debug``.
"""

import json
from typing import Any, Dict, List, Optional

from services.checkpoint import Checkpointer

MAX_INPUT_CHARS = 20000


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_INPUT_CHARS:
        return value[:MAX_INPUT_CHARS] + "…"
    if isinstance(value, list):
        return [{**m, "content": _clip(m.get("content"))} if isinstance(m, dict) else m for m in value]
    return value


class Debugger:
    def __init__(self, debug: Optional[Dict[str, Any]], cp: Optional[Checkpointer]):
        d = debug or {}
        self.cp = cp
        self.breakpoints = set(d.get("breakpoints") or [])
        self.every_step = bool(d.get("step"))
        self.overrides: Dict[str, Dict[str, Any]] = d.get("overrides") or {}
        self.pins: Dict[str, str] = {k: v for k, v in (d.get("pins") or {}).items() if isinstance(v, str)}
        # Pausing needs a checkpoint that keeps steps, or Continue would start the run over
        self.can_pause = cp is not None and cp.keep_steps and (self.every_step or bool(self.breakpoints))
        # The step this run paused at last time: it runs now instead of pausing again
        self.resume_at = (cp.state.pop("debug_paused", None) or {}).get("step") if cp else None

    def pause(self, key: str, node_id: Optional[str], kind: str, label: str, step_input: Any) -> Optional[Dict[str, Any]]:
        """The ``debug_paused`` event to stop the run with before step ``key``, or None to go on."""
        if not self.can_pause or self.cp.saved(key) is not None:
            return None
        if key == self.resume_at:
            self.resume_at = None
            return None
        if not (self.every_step or (node_id and node_id in self.breakpoints)):
            return None
        info = {"step": key, "node_id": node_id, "kind": kind, "label": label}
        self.cp.state["debug_paused"] = info
        self.cp.save()
        return {"type": "debug_paused", "run_id": self.cp.run_id, **info, "input": _clip(step_input)}

    def override(self, key: str) -> Dict[str, Any]:
        return self.overrides.get(key) or {}

    def pin(self, node_id: Optional[str]) -> Optional[str]:
        return self.pins.get(node_id) if node_id else None


def tool_input(override: Dict[str, Any], tool_input: str, tool_args: Optional[Dict[str, Any]]):
    """(input text, typed arguments) for a tool call, with an edited input applied. A typed tool's
    edit is its arguments as JSON; text that isn't a JSON object is passed as one input string."""
    if "input" not in override:
        return tool_input, tool_args
    text = str(override["input"])
    if tool_args is not None:
        try:
            args = json.loads(text)
        except json.JSONDecodeError:
            args = None
        if isinstance(args, dict):
            return text, args
    return text, None


def tool_node_id(func_name: str, tool_id: Optional[str], attached_tools: List[Dict[str, Any]],
                 func_name_of) -> Optional[str]:
    """The canvas node a tool call came from (a Toolkit's sub-tools belong to the Toolkit node, an
    MCP server's tools to the MCP node)."""
    for t in attached_tools:
        names = [func_name_of(st) for st in t.get("subTools", [])] if "subTools" in t else [func_name_of(t)]
        if func_name in names or t.get("toolId") in (func_name, tool_id):
            return t.get("nodeId")
    return None


def pinned_turn(text: str, cfg: Any) -> Dict[str, Any]:
    """A model turn that answers with a pinned output, in the shape of a saved one (llm_runner._turn)."""
    return {"provider": cfg.provider, "model": cfg.model, "attempt_count": 1, "used_fallback": False,
            "cost_usd": 0.0, "backend": "pinned", "text": text, "tool_calls": [], "thinking": [],
            "finish_reason": "stop", "usage": {}}
