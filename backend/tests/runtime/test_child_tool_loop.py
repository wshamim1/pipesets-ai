"""
Child agents run the tool loop (plan.md C11 step 1, services/child_tool_loop.py). A child with tool
nodes wired to it is offered those tools, its calls run and the results go back to the model; with
Skill nodes it loads skills on demand like an LLM node. Mock / keyless children keep the single
call with skills in the prompt. Published flows pass the wired tools and skills to their children.
"""

import json

import pytest

from helpers import hdr
from routers.skills import STARTER_SKILLS
from services import llm_runner
from services.pipeline_runner import _build_master_request

ADMIN = hdr()
AIRFLOW = next(s for s in STARTER_SKILLS if s["id"] == "skill_airflow_triage")


class _Delta:
    def __init__(self, name, arguments, i=0):
        self.index, self.id, self.name, self.arguments = i, f"call_{name}", name, arguments


class _Chunk:
    def __init__(self, text="", tool_call=None, finish=None):
        self.text, self.thinking_blocks, self.finish_reason = text, [], finish
        self.tool_calls = [tool_call] if tool_call else []


class _Stream:
    usage, backend = None, "fake"

    def __init__(self, chunks):
        self._chunks, self.cost_usd = chunks, 0.001

    async def __aiter__(self):
        for c in self._chunks:
            yield c


def call(name, args):
    return _Stream([_Chunk(tool_call=_Delta(name, json.dumps(args)), finish="tool_calls")])


def answer(text):
    return _Stream([_Chunk(text=text, finish="stop")])


class Script:
    def __init__(self, turns):
        self.turns, self.calls, self.tool_runs = list(turns), [], []

    async def start(self, cfg, messages, tools=None, tool_choice=None):
        self.calls.append({"tools": [t["function"]["name"] for t in tools or []],
                           "system": messages[0]["content"], "messages": [dict(m) for m in messages]})
        return self.turns[len(self.calls) - 1](messages), cfg, 1, False

    async def tool(self, tool_id, tool_input, cfg=None, args=None):
        self.tool_runs.append((tool_id, tool_input, cfg))
        if tool_id == "broken_tool":
            raise RuntimeError("upstream 500")
        return f"[{tool_id}] 42"


@pytest.fixture
def script(env):
    def make(*turns):
        s = Script(turns)
        env.setattr(llm_runner, "_start_stream_with_policy", s.start)
        env.setattr(llm_runner, "execute_tool_real", s.tool)
        return s
    return make


def child(**fields):
    return {"agent_id": "c1", "label": "Analyst", "role": "Data Analyst", "provider": "openai", "model": "gpt-x",
            "api_key": "sk-test", "system_prompt": "You analyse data.", **fields}


def run(client, *children):
    r = client.post("/api/agents/run", headers=ADMIN, json={
        "goal": "What is 6 x 7?", "provider": "mock", "model": "mock-gpt-4", "strategy": "sequential",
        "children": list(children)})
    assert r.status_code == 200, r.text
    return r.json()


def test_child_calls_its_tools_and_answers(client, script):
    s = script(lambda m: call("calculator", {"input": "6*7"}), lambda m: answer("6 x 7 = 42."))
    body = run(client, child(attached_tools=[{"toolId": "calculator", "label": "calculator", "config": {"p": 1}}]))

    assert s.calls[0]["tools"] == ["calculator"]
    assert s.calls[0]["system"].startswith("You analyse data.")
    assert s.tool_runs == [("calculator", "6*7", {"p": 1})]
    assert s.calls[1]["messages"][-1] == {"role": "tool", "tool_call_id": "call_calculator", "content": "[calculator] 42"}
    step = body["steps"][1]
    assert step["output"] == "6 x 7 = 42." and step["effective_model"] == "gpt-x"
    assert [c["tool_id"] for c in step["tool_calls"]] == ["calculator"]
    assert step["tool_calls"][0]["status"] == "success"


def test_tool_ids_only_still_work(client, script):
    """Older callers send allowed_tool_ids without the nodes' data."""
    s = script(lambda m: call("calculator", {"input": "6*7"}), lambda m: answer("42"))
    run(client, child(allowed_tool_ids=["calculator"]))
    assert s.calls[0]["tools"] == ["calculator"] and s.tool_runs[0][0] == "calculator"


def test_failing_tool_goes_back_to_the_model(client, script):
    s = script(lambda m: call("broken_tool", {"input": "x"}), lambda m: answer("The tool is down."))
    body = run(client, child(attached_tools=[{"toolId": "broken_tool", "label": "broken_tool", "config": {}}]))
    assert s.calls[1]["messages"][-1]["content"] == "Tool 'broken_tool' failed: upstream 500"
    assert body["steps"][1]["output"] == "The tool is down."
    assert body["steps"][1]["tool_calls"][0]["status"] == "error"


def test_child_loads_skills_on_demand(client, script):
    tools = [{"toolId": t, "label": t, "config": {}} for t in AIRFLOW["tool_ids"]]
    tools.append({"toolId": "calculator", "label": "calculator", "config": {}})
    s = script(
        lambda m: call("use_skill", {"name": "Airflow DAG triage"}),
        lambda m: call("airflow_task_logs", {"input": "orders_daily"}),
        lambda m: answer("extract_orders failed."),
    )
    body = run(client, child(attached_tools=tools,
                             attached_skills=[{"skill_id": AIRFLOW["id"], "label": AIRFLOW["name"]}]))

    assert sorted(s.calls[0]["tools"]) == ["calculator", "use_skill"], "skill tools hidden until loaded"
    assert "- Airflow DAG triage — " in s.calls[0]["system"]
    assert AIRFLOW["instructions"][:40] not in s.calls[0]["system"]
    assert sorted(s.calls[1]["tools"]) == sorted(["calculator", "use_skill", *AIRFLOW["tool_ids"]])
    assert [t[0] for t in s.tool_runs] == ["airflow_task_logs"]
    step = body["steps"][1]
    assert step["output"] == "extract_orders failed."
    assert [(u["name"], u["id"]) for u in step["skills_used"]] == [("Airflow DAG triage", AIRFLOW["id"])]
    assert [c["tool_id"] for c in step["tool_calls"]] == ["use_skill", "airflow_task_logs"]


def test_hidden_skill_tool_is_refused_until_loaded(client, script):
    tools = [{"toolId": t, "label": t, "config": {}} for t in AIRFLOW["tool_ids"]]
    s = script(lambda m: call("airflow_task_logs", {"input": "x"}), lambda m: answer("ok"))
    run(client, child(attached_tools=tools, attached_skills=[{"skill_id": AIRFLOW["id"]}]))
    assert s.tool_runs == []
    assert "load the skill 'Airflow DAG triage' with use_skill first" in s.calls[1]["messages"][-1]["content"]


def test_mock_child_keeps_single_call_with_skills_in_prompt(client, script):
    s = script()
    body = run(client, child(provider="mock", model="mock-gpt-4", api_key="",
                             attached_tools=[{"toolId": "calculator", "label": "calculator", "config": {}}],
                             attached_skills=[{"skill_id": AIRFLOW["id"]}]))
    assert s.calls == [] and s.tool_runs == []
    assert body["steps"][1]["output"].startswith("[Mock mock-gpt-4]")
    assert body["steps"][1]["tool_calls"] == []


def test_published_flow_passes_wired_tools_and_skills_to_children():
    nodes = [
        {"id": "m", "type": "master_agent", "data": {"provider": "mock", "model": "mock-gpt-4"}},
        {"id": "c", "type": "child_agent", "data": {"label": "Analyst", "provider": "openai", "model": "gpt-x"}},
        {"id": "t", "type": "tool", "data": {"toolId": "calculator", "label": "calculator", "config": {}}},
        {"id": "k", "type": "skill", "data": {"skill_id": AIRFLOW["id"]}},
        {"id": "t2", "type": "tool", "data": {"toolId": "weather", "label": "weather", "config": {}}},
    ]
    edges = [{"source": "m", "target": "c"}, {"source": "c", "target": "t"}, {"source": "k", "target": "c"},
             {"source": "m", "target": "t2"}]
    req = _build_master_request("goal", nodes, edges, {})
    c = req.children[0]
    assert [t["toolId"] for t in c.attached_tools] == ["calculator"], "only the child's own tool nodes"
    assert c.attached_skills == [{"skill_id": AIRFLOW["id"]}]
