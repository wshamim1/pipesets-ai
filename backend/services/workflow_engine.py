"""
workflow_engine.py — pausable, resumable conversational workflows.

A workflow is a saved Build-canvas flow made of ``wf_step`` nodes (plus optional
``start`` / ``stop`` nodes) joined by edges.  Unlike a pipeline run, a workflow run
can *pause* to wait for the user and later resume from the same node:

* ask / choice / confirm -> emit a prompt, save state, return ``waiting_input``
* tool_call / message    -> run straight through (a tool_call with no variable shows its result)

Run state is plain JSON (``variables``, ``current_node``, ``history``) so the caller
(routers/workflows.py) can persist it between HTTP requests.  The engine itself does
no I/O besides invoking tools.

Safety: a single ``advance`` call executes at most ``MAX_STEPS`` nodes, which stops
loops such as confirm -> "no" -> choice -> confirm from spinning forever.
"""

import json
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

MAX_STEPS = 50
PAUSING = {"ask", "choice", "confirm"}
YES = {"yes", "y", "true", "confirm", "ok", "approve"}
NO = {"no", "n", "false", "cancel", "reject"}

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_]\w*(?:\.\w+|\[\d+\])*)\s*\}\}")
_MISSING = object()


# ── Templating ────────────────────────────────────────────────────────────────

def _lookup(path: str, variables: Dict[str, Any]) -> Any:
    cur: Any = variables
    for part in re.findall(r"[^.\[\]]+", path):
        if isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if idx < len(cur) else _MISSING
        elif isinstance(cur, dict):
            cur = cur.get(part, _MISSING)
        else:
            return _MISSING
        if cur is _MISSING:
            return _MISSING
    return cur


def render(text: str, variables: Dict[str, Any]) -> str:
    """Replace ``{{var}}`` / ``{{var.field}}`` / ``{{var[0].field}}``; unknown names become ''."""
    def sub(m: "re.Match[str]") -> str:
        val = _lookup(m.group(1), variables)
        if val is _MISSING or val is None:
            return ""
        return json.dumps(val) if isinstance(val, (dict, list)) else str(val)
    return _PLACEHOLDER.sub(sub, text or "")


# ── Tools ─────────────────────────────────────────────────────────────────────

async def _run_tool(tool_id: str, input_text: str, config: Dict[str, Any]) -> Any:
    """Run a catalog tool with a plain-text input. JSON output is parsed so Choice steps can list it."""
    from routers.tools import execute_tool_real  # lazy: routers import heavy deps
    out = await execute_tool_real(tool_id, input_text, config)
    try:
        return json.loads(out)
    except (TypeError, json.JSONDecodeError):
        return out


# ── Graph helpers ─────────────────────────────────────────────────────────────

def _edge_label(edge: Dict[str, Any]) -> str:
    label = edge.get("label") or (edge.get("data") or {}).get("label") or ""
    return str(label).strip().lower()


def _branch_of(label: str) -> Optional[str]:
    return "yes" if label in YES else "no" if label in NO else None


FLOW_NODE_TYPES = {"wf_step", "start", "stop"}


class _Flow:
    def __init__(self, flow: Dict[str, Any]):
        self.nodes: Dict[str, Dict[str, Any]] = {n["id"]: n for n in flow.get("nodes", []) if n.get("id")}
        self.edges: List[Dict[str, Any]] = flow.get("edges", [])
        # Only edges between workflow nodes define the step order; edges to tool / LLM nodes are attachments.
        self._flow_edges = [e for e in self.edges if self._is_flow(e.get("source")) and self._is_flow(e.get("target"))]

    def _is_flow(self, node_id: Optional[str]) -> bool:
        return (self.nodes.get(node_id or "") or {}).get("type") in FLOW_NODE_TYPES

    def _out(self, node_id: str) -> List[Dict[str, Any]]:
        return [e for e in self._flow_edges if e.get("source") == node_id]

    def linked_tool(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Data of a tool node wired to this step (either direction), like an LLM node's attached tools."""
        for e in self.edges:
            other = e.get("target") if e.get("source") == node_id else e.get("source") if e.get("target") == node_id else None
            node = self.nodes.get(other or "")
            if node and node.get("type") == "tool":
                return node.get("data") or {}
        return None

    def entry(self) -> Optional[str]:
        start = next((n for n in self.nodes.values() if n.get("type") == "start"), None)
        if start:
            return self.next_id(start["id"])
        targets = {e.get("target") for e in self._flow_edges}
        roots = [n for n in self.nodes.values() if n.get("type") == "wf_step" and n["id"] not in targets]
        roots.sort(key=lambda n: ((n.get("position") or {}).get("x", 0), (n.get("position") or {}).get("y", 0)))
        return roots[0]["id"] if roots else None

    def next_id(self, node_id: str, branch: Optional[str] = None) -> Optional[str]:
        edges = self._out(node_id)
        if branch:
            for e in edges:
                if _branch_of(_edge_label(e)) == branch:
                    return e["target"]
            if branch == "yes":
                plain = [e for e in edges if not _edge_label(e)]
                return plain[0]["target"] if plain else None
            return None  # "no" with no explicit "no" edge ends the run
        return edges[0]["target"] if edges else None


# ── Step helpers ──────────────────────────────────────────────────────────────

def _var(data: Dict[str, Any], node_id: str) -> str:
    return (data.get("variable") or "").strip() or re.sub(r"\W", "_", node_id)


def _options(data: Dict[str, Any], variables: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = variables.get((data.get("options_source") or "").strip())
    if not isinstance(items, list):
        return []
    label_f, value_f = data.get("option_label_field") or "", data.get("option_value_field") or ""
    out = []
    for item in items:
        if isinstance(item, dict):
            label = item.get(label_f) if label_f else next((item[k] for k in ("name", "label", "title") if k in item), None)
            label = str(label if label is not None else json.dumps(item))
            value = item.get(value_f) if value_f else item.get("id", label)
        else:
            label, value = str(item), item
        out.append({"value": value, "label": label, "item": item})
    return out


def _public_options(opts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"value": o["value"], "label": o["label"]} for o in opts]


def _prompt_for(data: Dict[str, Any], node_id: str, variables: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """The message + input descriptor for a pausing step."""
    st, var = data.get("step_type"), _var(data, node_id)
    if st == "ask":
        text = render(data.get("prompt", ""), variables) or f"Please provide {var}."
        return text, {"type": data.get("input_kind") or "text", "variable": var}
    if st == "choice":
        text = render(data.get("prompt", ""), variables) or "Please choose one:"
        return text, {"type": "choice", "variable": var, "options": _public_options(_options(data, variables))}
    text = render(data.get("prompt", ""), variables) or "Do you want to continue?"
    return text, {"type": "confirm", "variable": var,
                  "options": [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}]}


def _apply_reply(data: Dict[str, Any], node_id: str, variables: Dict[str, Any],
                 reply: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """Validate and store a user reply. Returns (error_message, confirm_branch)."""
    st, var = data.get("step_type"), _var(data, node_id)
    raw = reply.get("choice") if reply.get("choice") is not None else reply.get("message")
    raw = "" if raw is None else str(raw).strip()
    if not raw:
        return "Please enter a reply.", None

    if st == "ask":
        kind = data.get("input_kind") or "text"
        if kind == "number":
            try:
                num = float(raw)
            except ValueError:
                return f"'{raw}' is not a number. Please try again.", None
            variables[var] = int(num) if num.is_integer() else num
        elif kind == "date":
            try:
                variables[var] = date.fromisoformat(raw).isoformat()
            except ValueError:
                return f"'{raw}' is not a valid date (use YYYY-MM-DD). Please try again.", None
        else:
            variables[var] = raw
        return None, None

    if st == "choice":
        opts = _options(data, variables)
        pick = next((o for o in opts if str(o["value"]) == raw), None) \
            or next((o for o in opts if o["label"].lower() == raw.lower()), None) \
            or (opts[int(raw) - 1] if raw.isdigit() and 1 <= int(raw) <= len(opts) else None)
        if pick is None:
            return "That's not one of the options. Please choose from the list.", None
        variables[var] = pick["value"]
        variables[f"{var}_item"] = pick["item"]
        return None, None

    low = raw.lower()  # confirm
    if low in YES:
        variables[var] = True
        return None, "yes"
    if low in NO:
        variables[var] = False
        return None, "no"
    return "Please answer yes or no.", None


# ── Public API ────────────────────────────────────────────────────────────────

def new_state(variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"variables": dict(variables or {}), "current_node": None, "history": []}


async def advance(flow_data: Dict[str, Any], state: Dict[str, Any],
                  reply: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run until the workflow pauses, completes or fails. Mutates ``state`` in place.

    ``reply`` is None for the first call; afterwards it carries the user's answer
    ({"message": ...} and/or {"choice": ...}) to the node recorded in ``state['current_node']``.
    Returns {"status", "messages", "input", "error"}.
    """
    flow = _Flow(flow_data)
    variables: Dict[str, Any] = state["variables"]
    messages: List[str] = []

    def finish(status: str, input_desc: Optional[Dict[str, Any]] = None, error: Optional[str] = None):
        state["history"].extend({"role": "bot", "text": m} for m in messages)
        return {"status": status, "messages": messages, "input": input_desc, "error": error}

    def fail(msg: str):
        state["current_node"] = None
        messages.append(msg)
        return finish("failed", error=msg)

    if reply is not None:
        node = flow.nodes.get(state.get("current_node") or "")
        if node is None or node.get("type") != "wf_step":
            return fail("This workflow is not waiting for input.")
        data = node.get("data", {})
        state["history"].append({"role": "user", "text": str(reply.get("choice") or reply.get("message") or ""),
                                 "node": node["id"]})
        err, branch = _apply_reply(data, node["id"], variables, reply)
        if err:
            text, desc = _prompt_for(data, node["id"], variables)
            messages.extend([err, text])
            return finish("waiting_input", desc)
        node_id = flow.next_id(node["id"], branch)
        if node_id is None and branch == "no":
            messages.append("Okay, I've stopped here.")
    else:
        node_id = flow.entry()
        if node_id is None:
            return fail("This workflow has no steps to run.")

    steps = 0
    while node_id:
        steps += 1
        if steps > MAX_STEPS:
            return fail(f"Stopped after {MAX_STEPS} steps (possible loop).")
        node = flow.nodes[node_id]
        ntype = node.get("type")
        if ntype == "stop":
            break
        if ntype == "start":
            node_id = flow.next_id(node_id)
            continue

        data = node.get("data", {})
        st = data.get("step_type")
        var = _var(data, node_id)

        if st == "message":
            messages.append(render(data.get("prompt", ""), variables))
        elif st == "tool_call":
            linked = flow.linked_tool(node_id)
            tool_id = (linked or {}).get("toolId") or (data.get("tool_id") or "").strip()
            if not tool_id:
                return fail(f"Step '{data.get('label', node_id)}' has no tool: link a tool node or set a Tool ID.")
            try:
                result = await _run_tool(tool_id, render(data.get("tool_input", ""), variables),
                                         dict((linked or {}).get("config") or {}))
            except Exception as e:
                return fail(f"Step '{data.get('label', node_id)}' failed: {e}")
            if (data.get("variable") or "").strip():
                variables[var] = result
            else:  # nowhere to store it, so show it rather than silently drop it
                messages.append(result if isinstance(result, str) else json.dumps(result, indent=2))
        elif st in PAUSING:
            answered_here = any(h.get("node") == node_id for h in state["history"])
            if st == "ask" and variables.get(var) not in (None, "") and not answered_here:
                node_id = flow.next_id(node_id)   # pre-filled, skip; a loop back to an answered step asks again
                continue
            if st == "choice" and not _options(data, variables):
                return fail(f"No options available for '{data.get('label', node_id)}'.")
            text, desc = _prompt_for(data, node_id, variables)
            messages.append(text)
            state["current_node"] = node_id
            return finish("waiting_input", desc)
        else:
            return fail(f"Unknown step type '{st}'.")

        last_id, node_id = node_id, flow.next_id(node_id)
        if node_id is None:
            # Ending at a dead end while a Stop exists or a waiting step was never reached is
            # usually a wiring mistake (e.g. an edge drawn in the wrong direction), so say where it ended
            answered = {h.get("node") for h in state["history"]}
            unreached = [n.get("data", {}).get("label", nid) for nid, n in flow.nodes.items()
                         if n.get("type") == "wf_step" and n.get("data", {}).get("step_type") in PAUSING
                         and nid not in answered]
            has_stop = any(n.get("type") == "stop" for n in flow.nodes.values())
            if has_stop or unreached:
                msg = (f"⚠ The workflow ended after '{flow.nodes[last_id].get('data', {}).get('label', last_id)}' "
                       "because that step has no outgoing connection.")
                if unreached:
                    msg += f" Never reached: {', '.join(repr(u) for u in unreached)} — check the edge arrows."
                messages.append(msg)

    state["current_node"] = None
    return finish("completed")
