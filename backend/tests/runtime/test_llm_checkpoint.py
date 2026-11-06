"""
Checkpointed single-LLM runs (services/llm_checkpoint.py): a run with a run id saves each model
turn and tool result; a resume continues from the first step that never finished, without paying
for a finished model call again or running a finished tool twice.
"""

import asyncio
import json
import uuid

import pytest

from db import get_db_connection
from helpers import hdr
from models import PromptRunRequest
from services import api_keys, llm_runner, scheduler
from services.pipeline_runner import RunScope, current_scope
from services.request_context import RequestContext


def _run(run_id):
    conn = get_db_connection()
    try:
        return dict(conn.execute("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone())
    finally:
        conn.close()


# ── A scripted model and a counting tool ──────────────────────────────────────

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
            if c == "hang":
                await asyncio.Event().wait()
            yield c


class Script:
    """Step 1 calls the ``lookup`` tool; step 2 answers. ``fail`` makes the next answer step
    raise (the provider is down); ``hang`` makes it hang (so a caller can go away mid-run)."""

    def __init__(self):
        self.model_calls, self.tool_calls, self.fail, self.hang = [], [], 0, False

    async def start(self, cfg, messages, tools=None, tool_choice=None):
        self.model_calls.append([dict(m) for m in messages])
        if not any(m["role"] == "tool" for m in messages):
            return _Stream([_Chunk(text="Looking it up. ", tool_call=_Delta("lookup", '{"input": "x"}'),
                                   finish="tool_calls")]), cfg, 1, False
        if self.fail:
            self.fail -= 1
            raise RuntimeError("provider is down")
        if self.hang:
            return _Stream(["hang"]), cfg, 1, False
        return _Stream([_Chunk(text="The answer is 42.", finish="stop")]), cfg, 1, False

    async def tool(self, tool_id, tool_input, cfg=None, args=None):
        self.tool_calls.append(tool_id)
        return "42"


@pytest.fixture
def script(env):
    s = Script()
    env.setattr(llm_runner, "_start_stream_with_policy", s.start)
    env.setattr(llm_runner, "execute_tool_real", s.tool)
    yield s


BODY = {"prompt": "What is the answer?", "config": {"provider": "openai", "model": "gpt-x", "api_key": "sk-test"},
        "attached_tools": [{"toolId": "lookup", "label": "lookup", "config": {}}]}


def _stream(client, **fields):
    r = client.post("/api/run/stream", headers=hdr(), json={**BODY, **fields})
    if r.status_code != 200:
        return r.status_code, r.json()
    return 200, [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


def _text(events):
    return "".join(e["text"] for e in events if e["type"] == "token")


# ── Resume after a failure ────────────────────────────────────────────────────

def test_a_failed_run_resumes_without_repeating_finished_steps(client, script):
    run_id = str(uuid.uuid4())
    script.fail = 1
    _, events = _stream(client, run_id=run_id)
    assert events[0] == {"type": "run", "run_id": run_id, "resumed_steps": 0}
    assert any(e["type"] == "error" and "provider is down" in e["message"] for e in events)
    row = _run(run_id)
    assert (row["kind"], row["status"], row["goal"]) == ("llm", "failed", "What is the answer?")
    assert script.tool_calls == ["lookup"] and len(script.model_calls) == 2

    _, events = _stream(client, resume_from=run_id)
    assert events[0]["resumed_steps"] >= 2, "memory, the first model turn and the tool result"
    assert script.tool_calls == ["lookup"], "the tool did not run again"
    assert len(script.model_calls) == 3, "only the step that failed called the model again"
    assert _text(events) == "Looking it up. The answer is 42.", "the whole answer, replayed part included"
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["run_id"] == run_id and meta["cost_usd"] == pytest.approx(0.02), "both turns' spend"
    row = _run(run_id)
    assert row["status"] == "completed" and row["final_answer"] == "Looking it up. The answer is 42."


def test_only_interrupted_or_failed_runs_of_the_same_node_resume(client, script):
    run_id = str(uuid.uuid4())
    _stream(client, run_id=run_id)
    assert _run(run_id)["status"] == "completed"
    assert _stream(client, resume_from=run_id)[0] == 409, "a finished run doesn't resume"
    assert _stream(client, run_id=run_id)[0] == 409, "nor can its id be reused"
    assert _stream(client, resume_from="no-such-run")[0] == 404

    failed = str(uuid.uuid4())
    script.fail = 1
    _stream(client, run_id=failed)
    status, body = _stream(client, resume_from=failed, prompt="Something else?")
    assert status == 409 and "changed" in body["detail"]
    assert _stream(client, resume_from=failed)[0] == 200, "the unchanged request still can"


def test_runs_without_an_id_save_nothing(client, script):
    conn = get_db_connection()
    try:
        before = conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0]
    finally:
        conn.close()
    _, events = _stream(client)
    assert events[0]["type"] != "run" and _text(events).endswith("42.")
    conn = get_db_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == before
    finally:
        conn.close()


# ── A caller that goes away, a cancel from elsewhere ─────────────────────────

SCOPE = RunScope(tenant_id="tenant_demo", project_id="proj_research", user_id="user_admin")


def _request(**fields):
    return PromptRunRequest(**{**BODY, **fields})


def test_a_caller_that_goes_away_leaves_the_run_interrupted_and_resumable(script):
    run_id = str(uuid.uuid4())
    script.hang = True

    async def go():
        token = current_scope.set(SCOPE)
        try:
            stream = llm_runner.run_stream(_request(run_id=run_id))
            async for chunk in stream:
                if '"type": "tool"' in chunk:
                    break       # the caller disconnects while the model writes its answer
            await stream.aclose()
        finally:
            current_scope.reset(token)

    asyncio.run(go())
    assert _run(run_id)["status"] == "interrupted"

    script.hang = False

    async def resume():
        token = current_scope.set(SCOPE)
        try:
            return [c async for c in llm_runner.run_stream(_request(resume_from=run_id))]
        finally:
            current_scope.reset(token)

    chunks = asyncio.run(resume())
    assert script.tool_calls == ["lookup"] and "The answer is 42." in "".join(chunks)
    assert _run(run_id)["status"] == "completed"


def test_a_cancel_from_another_request_stops_a_running_run(script, env):
    from routers.agents import request_cancel
    env.setenv("CANCEL_POLL_SECONDS", "0.05")
    run_id = str(uuid.uuid4())
    script.hang = True

    async def go():
        token = current_scope.set(SCOPE)
        try:
            out = []
            async for chunk in llm_runner.run_stream(_request(run_id=run_id)):
                out.append(chunk)
                if '"type": "tool"' in chunk:
                    assert await asyncio.to_thread(request_cancel, run_id, "tenant_demo", "proj_research") == "cancelling"
            return out
        finally:
            current_scope.reset(token)

    chunks = asyncio.run(asyncio.wait_for(go(), 10))
    assert "Cancelled by request" in "".join(chunks)
    assert _run(run_id)["status"] == "cancelled"
    script.hang = False


# ── /v1 and automated runs ────────────────────────────────────────────────────

FLOW = {"nodes": [
    {"id": "llm", "type": "llm", "data": {"provider": "openai", "model": "gpt-x"}},
    {"id": "t", "type": "tool", "data": {"toolId": "lookup", "label": "lookup", "config": {}}},
    {"id": "m", "type": "memory", "data": {"session_id": "default", "strategy": "sliding_window"}},
], "edges": [{"id": "e", "source": "t", "target": "llm"}, {"id": "e2", "source": "m", "target": "llm"}]}


@pytest.fixture(scope="module")
def app_id(client, env):
    env.setenv("OPENAI_API_KEY", "sk-test")   # the server's own key: flows can't hold plaintext ones
    aid = client.post("/api/apps", headers=hdr(), json={"name": "Lookup", "description": "", "flow_data": FLOW}).json()["id"]
    assert client.post(f"/api/apps/{aid}/publish", headers=hdr()).status_code == 200
    return aid


@pytest.fixture(scope="module")
def key():
    plaintext, _ = api_keys.create_key(RequestContext(tenant_id="tenant_demo", project_id="proj_research",
                                                      user_id="user_admin"), "ck", ["apps:read", "apps:run"],
                                       rate_limit_rpm=0)
    return {"Authorization": f"Bearer {plaintext}"}


def test_v1_runs_are_checkpointed_and_resume(client, script, app_id, key):
    script.fail = 1
    r = client.post(f"/v1/apps/{app_id}/run", headers=key,
                    json={"prompt": "What is the answer?", "stream": False, "session_id": "s-1", "user": "ana"}).json()
    assert r["status"] == "failed" and r["run_id"]
    saved = json.loads(_run(r["run_id"])["checkpoint"])["input"]
    assert saved == {"session_id": "s-1", "end_user": "ana"}, "what a resume needs to rebuild the request"

    res = client.post(f"/v1/runs/{r['run_id']}/resume", headers=key, json={}).json()
    assert res["status"] == "completed" and res["output"] == "Looking it up. The answer is 42.", res["error"]
    assert script.tool_calls == ["lookup"]
    conn = get_db_connection()
    try:
        turns = conn.execute("SELECT role FROM memory_messages WHERE session_id = 's-1' ORDER BY id").fetchall()
    finally:
        conn.close()
    assert [t["role"] for t in turns] == ["user", "assistant"], "the resumed run saved to the caller's session"
    again = client.post(f"/v1/runs/{r['run_id']}/resume", headers=key, json={})
    assert again.status_code == 409


def test_a_retried_automated_run_picks_up_where_the_last_attempt_stopped(script, app_id):
    source = {"id": "sched-1", "app_id": app_id, "tenant_id": "tenant_demo", "project_id": "proj_research",
              "owner_user_id": "user_admin", "version": 0}
    row_id = str(uuid.uuid4())
    script.fail = 1
    _, first = asyncio.run(scheduler.run_published(source, "What is the answer?", 30000, run_id=row_id))
    assert first["status"] == "failed" and _run(row_id)["status"] == "failed"
    _, second = asyncio.run(scheduler.run_published(source, "What is the answer?", 30000, run_id=row_id))
    assert second["status"] == "completed" and second["output"].endswith("The answer is 42.")
    assert script.tool_calls == ["lookup"], "the retry reused the first attempt's tool result"


# ── The Checkpointer node ─────────────────────────────────────────────────────

def test_save_steps_off_keeps_no_step_output_and_a_resume_starts_over(client, script):
    run_id = str(uuid.uuid4())
    script.fail = 1
    _stream(client, run_id=run_id, checkpoint={"save_steps": False})
    assert json.loads(_run(run_id)["checkpoint"])["steps"] == {}, "no tool output or model turn kept"
    _, events = _stream(client, resume_from=run_id, checkpoint={"save_steps": False})
    assert events[0]["resumed_steps"] == 0 and _text(events).endswith("The answer is 42.")
    assert script.tool_calls == ["lookup", "lookup"], "nothing saved, so the tool ran again"


def test_restore_on_resume_off_keeps_steps_but_a_resume_starts_over(client, script):
    run_id = str(uuid.uuid4())
    script.fail = 1
    _stream(client, run_id=run_id, checkpoint={"restore_on_resume": False})
    assert "tool:1:0" in json.loads(_run(run_id)["checkpoint"])["steps"], "kept, for inspection"
    _stream(client, resume_from=run_id, checkpoint={"restore_on_resume": False})
    assert script.tool_calls == ["lookup", "lookup"]
    assert _run(run_id)["status"] == "completed"


def test_a_flow_with_a_human_gate_always_saves_its_steps():
    from routers.agents import ChildAgentConfig, MasterAgentRunRequest, _checkpoint_options
    off = {"save_steps": False, "restore_on_resume": False}
    assert _checkpoint_options(MasterAgentRunRequest(goal="g", checkpoint=off)) == (False, False)
    gated = MasterAgentRunRequest(goal="g", checkpoint=off, children=[ChildAgentConfig(human_gate={"gate_type": "approval"})])
    assert _checkpoint_options(gated) == (True, True), "a decision must apply to the output that was reviewed"


def test_the_node_on_a_published_flow_applies_to_v1_runs():
    from services.pipeline_runner import _build_llm_request, _build_master_request
    node = {"id": "cp", "type": "checkpointer", "data": {"save_steps": False, "restore_on_resume": True}}
    req = _build_llm_request("hi", "app", FLOW["nodes"] + [node], FLOW["edges"], {})
    assert req.checkpoint == {"save_steps": False, "restore_on_resume": True}, "applies even when not wired"
    assert _build_llm_request("hi", "app", FLOW["nodes"], FLOW["edges"], {}).checkpoint is None
    master = {"id": "ma", "type": "master_agent", "data": {"provider": "mock", "model": "mock-gpt-4"}}
    sub = _build_master_request("g", [master, node], [{"id": "e", "source": "cp", "target": "ma"}], {})
    assert sub.checkpoint == {"save_steps": False, "restore_on_resume": True}


# ── Time travel: re-run from a step ───────────────────────────────────────────

@pytest.fixture
def finished_run(client, script, app_id, key):
    r = client.post(f"/v1/apps/{app_id}/run", headers=key, json={"prompt": "What is the answer?", "stream": False}).json()
    assert r["status"] == "completed"
    return r["run_id"]


def test_spans_name_the_saved_step_they_came_from(client, finished_run):
    conn = get_db_connection()
    try:
        spans = json.loads(conn.execute("SELECT spans_json FROM traces WHERE run_id = ?", (finished_run,)).fetchone()[0])
    finally:
        conn.close()
    assert [s["checkpoint_key"] for s in spans] == ["llm:1", "tool:1:0", "llm:2"]
    run = client.get(f"/api/agents/runs/{finished_run}", headers=hdr()).json()
    assert run["kind"] == "llm" and run["rerunnable"] and run["tool_results"] == {"tool:1:0": "42"}


def test_a_tool_result_can_be_edited_and_the_run_continues_from_there(client, script, finished_run):
    r = client.post(f"/api/agents/runs/{finished_run}/rerun", headers=hdr(),
                    json={"from_step": "tool:1:0", "edited_output": "41"}).json()
    assert r["status"] == "completed" and r["run_id"] != finished_run, r
    assert script.tool_calls == ["lookup"], "the edited result replaced the tool call"
    assert len(script.model_calls) == 3, "the first model turn was reused, the second ran again"
    assert next(m for m in script.model_calls[-1] if m["role"] == "tool")["content"] == "41"
    fork = client.get(f"/api/agents/runs/{r['run_id']}", headers=hdr()).json()
    assert fork["forked_from"] == {"run_id": finished_run, "step": "tool:1:0", "edited": True}
    assert client.get(f"/api/agents/runs/{finished_run}", headers=hdr()).json()["tool_results"] == {"tool:1:0": "42"}, \
        "the original run is unchanged"


def test_a_model_step_re_runs_against_the_current_flow(client, script, finished_run):
    r = client.post(f"/api/agents/runs/{finished_run}/rerun", headers=hdr(), json={"from_step": "llm:2"}).json()
    assert r["status"] == "completed" and r["output"] == "Looking it up. The answer is 42."
    assert script.tool_calls == ["lookup"] and len(script.model_calls) == 3


def test_re_runs_refuse_what_they_cant_do(client, finished_run):
    bad = client.post(f"/api/agents/runs/{finished_run}/rerun", headers=hdr(), json={"from_step": "llm:1", "edited_output": "x"})
    assert bad.status_code == 400
    assert client.post(f"/api/agents/runs/{finished_run}/rerun", headers=hdr(), json={"from_step": "tool:9:9"}).status_code == 409
    assert client.post("/api/agents/runs/nope/rerun", headers=hdr(), json={"from_step": "llm:1"}).status_code == 404
    other = client.post(f"/api/agents/runs/{finished_run}/rerun", headers=hdr(project="proj_support"), json={"from_step": "llm:1"})
    assert other.status_code == 404, "another project's run isn't visible"
