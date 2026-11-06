"""
Skills on demand (plan.md C10 step 1, services/skills_runtime.py). An LLM node with the four starter
skills and all their tools attached first sees only use_skill and its directly attached tool; it
loads the Airflow skill, gets the Airflow tools, uses them and answers (the exit criterion, with a
scripted model). Also: "always" mode, unknown / repeated / over-the-cap loads, a hidden tool called
too early, resume restoring loaded skills, old inline-only graphs, pinned versions, tenant scoping.
"""

import json
import uuid

import pytest

from helpers import hdr
from routers.skills import STARTER_SKILLS
from services import llm_runner

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
    """Plays ``turns`` (functions of the messages so far) in order; records what each call offered."""

    def __init__(self, turns):
        self.turns, self.calls, self.tool_runs, self.fail_at = list(turns), [], [], None

    async def start(self, cfg, messages, tools=None, tool_choice=None):
        self.calls.append({"tools": [t["function"]["name"] for t in tools or []],
                           "system": messages[0]["content"] if messages[0]["role"] == "system" else "",
                           "messages": [dict(m) for m in messages]})
        if self.fail_at == len(self.calls):
            raise RuntimeError("provider is down")
        return self.turns[len(self.calls) - 1](messages), cfg, 1, False

    async def tool(self, tool_id, tool_input, cfg=None, args=None):
        self.tool_runs.append(tool_id)
        return f"[{tool_id}] Task extract_orders failed: KeyError 'customer_id'"


@pytest.fixture
def script(env):
    def make(*turns):
        s = Script(turns)
        env.setattr(llm_runner, "_start_stream_with_policy", s.start)
        env.setattr(llm_runner, "execute_tool_real", s.tool)
        return s
    return make


def starter_body(**fields):
    tools = [{"toolId": t, "label": t, "config": {}} for s in STARTER_SKILLS for t in s["tool_ids"]]
    tools.append({"toolId": "calculator", "label": "calculator", "config": {}})
    skills = [{"skill_id": s["id"], "label": s["name"]} for s in STARTER_SKILLS]
    return {"prompt": "Why did the orders_daily DAG fail last night?", "node_id": "llm",
            "config": {"provider": "openai", "model": "gpt-x", "api_key": "sk-test", "system_prompt": "You are on call."},
            "attached_tools": tools, "attached_skills": skills, **fields}


def stream(client, body, headers=ADMIN):
    r = client.post("/api/run/stream", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


def text(events):
    return "".join(e["text"] for e in events if e["type"] == "token")


# ── The exit criterion ────────────────────────────────────────────────────────

def test_only_use_skill_and_direct_tools_until_a_skill_loads(client, script):
    s = script(
        lambda m: call("use_skill", {"name": "Airflow DAG triage"}),
        lambda m: call("airflow_task_logs", {"input": "orders_daily extract_orders"}),
        lambda m: answer("extract_orders failed on KeyError 'customer_id'."),
    )
    events = stream(client, starter_body())
    assert len({t for sk in STARTER_SKILLS for t in sk["tool_ids"]}) == 15
    assert sorted(s.calls[0]["tools"]) == ["calculator", "use_skill"], "15 skill tools stay hidden"
    system = s.calls[0]["system"]
    assert "- Airflow DAG triage — When the user asks why an Airflow DAG run failed" in system
    assert AIRFLOW["instructions"][:40] not in system, "bodies aren't in the prompt until loaded"

    assert sorted(s.calls[1]["tools"]) == sorted(["calculator", "use_skill", *AIRFLOW["tool_ids"]])
    loaded = s.calls[1]["messages"][-1]
    assert loaded["role"] == "tool" and loaded["content"].startswith("# Skill loaded: Airflow DAG triage")
    assert "Work from evidence" in loaded["content"]
    assert s.tool_runs == ["airflow_task_logs"]
    assert text(events) == "extract_orders failed on KeyError 'customer_id'."

    skill_ev = next(e for e in events if e["type"] == "skill_loaded")
    assert skill_ev["name"] == "Airflow DAG triage" and skill_ev["id"] == "skill_airflow_triage"
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["skills_used"] == [{"name": "Airflow DAG triage", "id": "skill_airflow_triage", "version": 1}]


def test_always_mode_puts_every_skill_in_the_prompt(client, script):
    s = script(lambda m: answer("ok"))
    stream(client, starter_body(skill_mode="always"))
    assert "use_skill" not in s.calls[0]["tools"] and len(s.calls[0]["tools"]) == 16
    assert "## Activated Skills & SOPs" in s.calls[0]["system"] and AIRFLOW["instructions"][:40] in s.calls[0]["system"]


# ── Loading rules ─────────────────────────────────────────────────────────────

def test_unknown_repeated_and_over_the_cap(client, script):
    s = script(
        lambda m: call("use_skill", {"name": "Teleport"}),
        lambda m: call("use_skill", {"name": "kafka consumer lag investigation"}),   # any case
        lambda m: call("use_skill", {"name": "Kafka consumer lag investigation"}),
        lambda m: call("use_skill", {"name": "Airflow DAG triage"}),
        lambda m: answer("done"),
    )
    stream(client, starter_body(max_active_skills=1))
    results = [c["messages"][-1]["content"] for c in s.calls[1:]]
    assert results[0].startswith("Unknown skill 'Teleport'. Skills you can load: Airflow DAG triage")
    assert results[1].startswith("# Skill loaded: Kafka consumer lag investigation")
    assert "already loaded" in results[2]
    assert results[3].startswith("Can't load 'Airflow DAG triage': at most 1 skills per request")
    assert "airflow" not in s.calls[4]["tools"]


def test_a_hidden_tool_called_too_early_doesnt_run(client, script):
    s = script(lambda m: call("airflow", {"input": "x"}), lambda m: answer("ok"))
    stream(client, starter_body())
    assert s.tool_runs == []
    assert "load the skill 'Airflow DAG triage' with use_skill first" in s.calls[1]["messages"][-1]["content"]


def test_a_resumed_run_gets_its_loaded_skills_back(client, script):
    s = script(
        lambda m: call("use_skill", {"name": "Airflow DAG triage"}),
        lambda m: answer("never"),
        lambda m: answer("Found it."),
    )
    s.fail_at = 2
    run_id = str(uuid.uuid4())
    events = stream(client, starter_body(run_id=run_id))
    assert any(e["type"] == "error" for e in events)
    events = stream(client, starter_body(resume_from=run_id))
    assert len(s.calls) == 3, "the first call and the use_skill result were replayed"
    assert set(AIRFLOW["tool_ids"]) <= set(s.calls[2]["tools"]), "the skill's tools are back on"
    assert text(events) == "Found it."


# ── Where a skill comes from ──────────────────────────────────────────────────

def test_old_graphs_with_inline_skills_keep_working(client, script):
    s = script(lambda m: call("use_skill", {"name": "Legacy SOP"}), lambda m: answer("ok"))
    body = starter_body(attached_skills=[{"label": "Legacy SOP", "description": "When asked about the SOP.",
                                          "instructions": "Follow the legacy SOP.", "tool_ids": ["calculator"]}])
    stream(client, body)
    assert "calculator" not in s.calls[0]["tools"], "its tool waits for it"
    assert "Follow the legacy SOP." in s.calls[1]["messages"][-1]["content"]


def test_skills_are_read_live_and_can_be_pinned_to_a_version(client, script):
    sk = client.post("/api/skills", json={"name": "Refunds", "when_to_use": "When the user asks about a refund.",
                                          "instructions": "V1 RULES", "required_tools": ["calculator"]},
                     headers=ADMIN).json()
    assert sk["version"] == 1 and sk["required_tools"] == ["calculator"]
    sk = client.put(f"/api/skills/{sk['id']}", json={"instructions": "V2 RULES"}, headers=ADMIN).json()
    assert sk["version"] == 2
    assert [v["version"] for v in client.get(f"/api/skills/{sk['id']}/versions", headers=ADMIN).json()] == [2, 1]
    assert client.get(f"/api/skills/{sk['id']}/versions/1", headers=ADMIN).json()["instructions"] == "V1 RULES"
    assert client.post("/api/skills", json={"name": "x", "when_to_use": "w" * 301}, headers=ADMIN).status_code == 422

    s = script(lambda m: call("use_skill", {"name": "Refunds"}), lambda m: answer("ok"),
               lambda m: call("use_skill", {"name": "Refunds"}), lambda m: answer("ok"))
    stream(client, starter_body(attached_skills=[{"skill_id": sk["id"], "instructions": "STALE INLINE COPY"}]))
    assert "V2 RULES" in s.calls[1]["messages"][-1]["content"], "the database copy, not the node's"
    stream(client, starter_body(attached_skills=[{"skill_id": sk["id"], "skill_version": 1}]))
    assert "V1 RULES" in s.calls[3]["messages"][-1]["content"] and "(v1)" in s.calls[3]["messages"][-1]["content"]


def test_another_tenants_skill_doesnt_load(client, script):
    sk = client.post("/api/skills", json={"name": "Secret", "instructions": "SECRET-SOP"}, headers=ADMIN).json()
    tid = client.post("/api/iam/tenants", json={"name": "Other"}, headers=ADMIN).json()["id"]
    pid = client.post("/api/iam/projects", json={"name": "P"}, headers=hdr(tenant=tid)).json()["id"]
    s = script(lambda m: call("use_skill", {"name": "Secret"}), lambda m: answer("ok"))
    stream(client, starter_body(attached_skills=[{"skill_id": sk["id"], "label": "Secret"}]), headers=hdr(tenant=tid, project=pid))
    assert "SECRET-SOP" not in json.dumps(s.calls)


def test_saved_flows_pass_the_nodes_skill_settings():
    from services.pipeline_runner import _build_llm_request
    nodes = [{"id": "llm", "type": "llm", "data": {"provider": "mock", "model": "m", "skill_mode": "always",
                                                   "max_active_skills": 2}},
             {"id": "sk", "type": "skill", "data": {"skill_id": "skill_kafka_lag", "label": "Kafka"}}]
    req = _build_llm_request("hi", "app", nodes, [{"source": "llm", "target": "sk"}], {})
    assert (req.skill_mode, req.max_active_skills) == ("always", 2)
    assert req.attached_skills == [{"skill_id": "skill_kafka_lag", "label": "Kafka"}]
