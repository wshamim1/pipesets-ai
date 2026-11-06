"""
Step-through debugging (plan.md F6, services/debug_run.py): breakpoints pause a checkpointed run
before a node's step, Continue resumes it without repeating finished model calls, an edited input
reaches the step, Step pauses at every step, pinned outputs replace a tool / retriever / LLM / Child
agent at no cost, and published runs never read pins.
"""

import asyncio
import json
import uuid

import pytest

from db import get_db_connection
from helpers import hdr
from services import llm_runner


def _run(run_id):
    conn = get_db_connection()
    try:
        return dict(conn.execute("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone())
    finally:
        conn.close()


class _Delta:
    def __init__(self, name, arguments):
        self.index, self.id, self.name, self.arguments = 0, "call_1", name, arguments


class _Chunk:
    def __init__(self, text="", tool_call=None, finish=None):
        self.text, self.thinking_blocks, self.finish_reason = text, [], finish
        self.tool_calls = [tool_call] if tool_call else []


class _Stream:
    usage, backend = None, "fake"

    def __init__(self, chunks, cost=0.01):
        self._chunks, self.cost_usd = chunks, cost

    async def __aiter__(self):
        for c in self._chunks:
            yield c


class Script:
    """Step 1 calls the ``lookup`` tool with input "x"; step 2 answers with what the tool said."""

    def __init__(self):
        self.model_calls, self.tool_inputs = [], []

    async def start(self, cfg, messages, tools=None, tool_choice=None):
        self.model_calls.append([dict(m) for m in messages])
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        if not tool_msgs:
            return _Stream([_Chunk(text="Looking it up. ", tool_call=_Delta("lookup", '{"input": "x"}'),
                                   finish="tool_calls")]), cfg, 1, False
        return _Stream([_Chunk(text=f"The answer is {tool_msgs[-1]['content']}.", finish="stop")]), cfg, 1, False

    async def tool(self, tool_id, tool_input, cfg=None, args=None):
        self.tool_inputs.append(tool_input)
        return "42"


@pytest.fixture
def script(env):
    s = Script()
    env.setattr(llm_runner, "_start_stream_with_policy", s.start)
    env.setattr(llm_runner, "execute_tool_real", s.tool)
    yield s


BODY = {"prompt": "What is the answer?", "node_id": "llm1",
        "config": {"provider": "openai", "model": "gpt-x", "api_key": "sk-test"},
        "attached_tools": [{"toolId": "lookup", "label": "lookup", "config": {}, "nodeId": "t1"}]}


def _stream(client, **fields):
    r = client.post("/api/run/stream", headers=hdr(), json={**BODY, **fields})
    assert r.status_code == 200, r.text
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


def _text(events):
    return "".join(e["text"] for e in events if e["type"] == "token")


def _paused(events):
    return next((e for e in events if e["type"] == "debug_paused"), None)


def _spans(run_id):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT spans_json FROM traces WHERE run_id = ? ORDER BY created_at DESC", (run_id,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["spans_json"])


# ── Breakpoints ───────────────────────────────────────────────────────────────

def test_a_tool_breakpoint_pauses_before_the_call_and_continue_uses_the_edit(client, script):
    run_id = str(uuid.uuid4())
    events = _stream(client, run_id=run_id, debug={"breakpoints": ["t1"]})
    paused = _paused(events)
    assert paused == {"type": "debug_paused", "run_id": run_id, "step": "tool:1:0", "node_id": "t1",
                      "kind": "tool", "label": "lookup", "input": {"input": "x"}}
    assert script.tool_inputs == [] and len(script.model_calls) == 1
    assert _run(run_id)["status"] == "paused"

    events = _stream(client, resume_from=run_id,
                     debug={"breakpoints": ["t1"], "overrides": {"tool:1:0": {"input": "y"}}})
    assert _paused(events) is None
    assert script.tool_inputs == ["y"], "the edited input reached the tool"
    assert len(script.model_calls) == 2, "the first model call was replayed, not repeated"
    assert _text(events) == "Looking it up. The answer is 42."
    assert _run(run_id)["status"] == "completed"
    tool_span = next(s for s in _spans(run_id) if s["span_type"] == "tool")
    assert tool_span["edited"] and tool_span["node_id"] == "t1" and tool_span["input_preview"] == "y"


def test_an_llm_breakpoint_pauses_before_every_model_call(client, script):
    run_id = str(uuid.uuid4())
    paused = _paused(_stream(client, run_id=run_id, debug={"breakpoints": ["llm1"]}))
    assert paused["step"] == "llm:1" and paused["kind"] == "llm" and script.model_calls == []
    assert paused["input"]["messages"][-1] == {"role": "user", "content": "What is the answer?"}

    edited = [{"role": "user", "content": "What is the answer, briefly?"}]
    paused = _paused(_stream(client, resume_from=run_id,
                             debug={"breakpoints": ["llm1"], "overrides": {"llm:1": {"messages": edited}}}))
    assert script.model_calls[0] == edited, "the model got the edited messages"
    assert paused["step"] == "llm:2", "the next model call pauses too"

    events = _stream(client, resume_from=run_id, debug={"breakpoints": ["llm1"]})
    assert _paused(events) is None and _text(events).endswith("The answer is 42.")
    assert len(script.model_calls) == 2 and script.tool_inputs == ["x"]


def test_step_pauses_at_every_step(client, script):
    run_id = str(uuid.uuid4())
    steps = []
    events = _stream(client, run_id=run_id, debug={"step": True})
    while (p := _paused(events)):
        steps.append(p["step"])
        events = _stream(client, resume_from=run_id, debug={"step": True})
    assert steps == ["llm:1", "tool:1:0", "llm:2"]
    assert len(script.model_calls) == 2 and _run(run_id)["status"] == "completed"


def test_runs_without_a_run_id_cant_pause(client, script):
    events = _stream(client, debug={"breakpoints": ["t1", "llm1"]})
    assert _paused(events) is None and _text(events).endswith("42.")


# ── Pins ──────────────────────────────────────────────────────────────────────

def test_a_pinned_tool_isnt_called(client, script):
    events = _stream(client, debug={"pins": {"t1": "7"}})
    assert script.tool_inputs == [] and _text(events).endswith("The answer is 7.")


def test_a_pinned_llm_costs_nothing_and_still_goes_through_the_output_checks(client, script):
    run_id = str(uuid.uuid4())
    events = _stream(client, run_id=run_id, debug={"pins": {"llm1": "Pinned answer"}},
                     output_parser={"parser_type": "json", "strict": False})
    assert script.model_calls == [] and _text(events) == "Pinned answer"
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["cost_usd"] == 0
    llm_span = next(s for s in _spans(run_id) if s["span_type"] == "llm")
    assert llm_span["pinned"] and not llm_span["resumed"]


def test_a_pinned_retriever_supplies_the_context(client, script):
    _stream(client, debug={"pins": {"r1": "The lease ends 2031-06-30."}},
            retriever_config={"collection_name": "nope", "top_k": 3, "node_id": "r1"},
            config={**BODY["config"], "system_prompt": "Context: {{context}}"})
    assert script.model_calls[0][0]["content"] == "Context: The lease ends 2031-06-30."


def test_pins_and_breakpoints_work_on_the_mock_provider(client, script):
    body = {"config": {"provider": "mock", "model": "mock-gpt-4"}}
    run_id = str(uuid.uuid4())
    paused = _paused(_stream(client, run_id=run_id, debug={"breakpoints": ["t1"]}, **body))
    assert paused["step"] == "tool:0" and paused["input"] == {"input": "What is the answer?"}
    events = _stream(client, resume_from=run_id, debug={"breakpoints": ["t1"], "overrides": {"tool:0": {"input": "edited"}}},
                     **body)
    assert script.tool_inputs == ["edited"] and "[lookup]: 42" in _text(events)
    events = _stream(client, debug={"pins": {"t1": "pinned!"}}, **body)
    assert "[lookup]: pinned!" in _text(events) and script.tool_inputs == ["edited"]


def test_a_pinned_child_agent_answers_without_running():
    from routers.agents import ChildAgentConfig, _run_child_unguarded
    child = ChildAgentConfig(label="Researcher", provider="openai", model="gpt-x", pinned_output="Pinned findings")
    trace = asyncio.run(_run_child_unguarded(child, "Find it", "", 1))
    assert trace.output == "Pinned findings" and trace.cost_usd == 0 and trace.effective_model == "pinned"


# ── Published runs never read the editor's debug settings ─────────────────────

def test_published_runs_ignore_pins_and_breakpoints(client):
    from services.pipeline_runner import _build_llm_request, _build_master_request
    nodes = [
        {"id": "llm1", "type": "llm", "data": {"label": "LLM", "provider": "mock", "model": "mock-gpt-4",
                                               "debug_pin": {"output": "PINNED"}, "debug_breakpoint": True}},
    ]
    req = _build_llm_request("Hi", "app_x", nodes, [], {})
    assert req.debug is None
    master_nodes = [
        {"id": "m", "type": "master_agent", "data": {"provider": "mock", "model": "mock-gpt-4"}},
        {"id": "c", "type": "child_agent", "data": {"label": "C", "provider": "mock", "model": "mock-gpt-4",
                                                    "debug_pin": {"output": "PINNED"}}},
    ]
    sub = _build_master_request("Hi", master_nodes, [{"source": "m", "target": "c"}], {})
    assert sub.children[0].pinned_output is None

    app_id = client.post("/api/apps", json={"name": "Pinned", "flow_data": {"nodes": nodes, "edges": []}},
                         headers=hdr()).json()["id"]
    assert client.post(f"/api/apps/{app_id}/publish", headers=hdr()).status_code == 200
    key = client.post("/api/api-keys", json={"name": "dbg", "scopes": ["apps:run"]}, headers=hdr()).json()["key"]
    r = client.post(f"/v1/apps/{app_id}/run", json={"prompt": "Hi", "stream": False},
                    headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200 and r.json()["status"] == "completed"
    assert "PINNED" not in r.json()["output"]


def test_a_steps_full_output_can_be_read_for_pinning(client, script, env):
    long = "x" * 1000
    env.setattr(llm_runner, "execute_tool_real", lambda *a, **k: _long(long))
    run_id = str(uuid.uuid4())
    events = _stream(client, run_id=run_id)
    tool_ev = next(e for e in events if e["type"] == "tool")
    assert tool_ev["node_id"] == "t1" and tool_ev["step_key"] == "tool:1:0" and len(tool_ev["output"]) == 400
    r = client.get(f"/api/agents/runs/{run_id}/steps/tool:1:0", headers=hdr())
    assert r.status_code == 200 and r.json()["output"] == long
    assert client.get(f"/api/agents/runs/{run_id}/steps/llm:2", headers=hdr()).json()["output"].startswith("The answer is")
    assert client.get(f"/api/agents/runs/{run_id}/steps/tool:9:9", headers=hdr()).status_code == 404


async def _long(value):
    return value
