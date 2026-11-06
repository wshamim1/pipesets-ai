"""
Tool-backed built-in agents (plan.md C11 step 4, backend/agents/) run as dropped: a child with the
agent's prompt and a tool node per need (labelled with the tool's catalog name, as the canvas does) is
offered those tools, calls one and answers. Scripted model; how well real models do is what each
agent's eval set (``evals``) measures.
"""

import json
import re

import pytest

import agents
import tools
from helpers import hdr
from services import llm_runner

ADMIN = hdr()
BUILTINS = [s for s in agents.all_specs() if not s.starter]


def _func_name(label: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-zA-Z0-9_]", "_", label.strip())).strip("_")[:64]


class _Delta:
    def __init__(self, name, arguments):
        self.index, self.id, self.name, self.arguments = 0, f"call_{name}", name, arguments


class _Chunk:
    def __init__(self, text="", tool_call=None, finish=None):
        self.text, self.thinking_blocks, self.finish_reason = text, [], finish
        self.tool_calls = [tool_call] if tool_call else []


class _Stream:
    usage, backend, cost_usd = None, "fake", 0.0

    def __init__(self, chunks):
        self._chunks = chunks

    async def __aiter__(self):
        for c in self._chunks:
            yield c


def dropped_tools(spec):
    """Tool nodes as a drop makes them: the first option of every need, labelled with its catalog name."""
    tools._load()
    out = []
    for need in spec.tools:
        t = tools.get_spec(need.ids[0])
        out.append({"toolId": t.id, "label": t.name, "toolType": t.type, "config": dict(t.default_config)})
    return out


def test_there_are_tool_backed_builtins():
    assert {s.id for s in BUILTINS} >= {"web_researcher", "sql_analyst", "airflow_dag_doctor",
                                        "databricks_job_triage", "snowflake_cost_optimizer", "incident_responder"}


@pytest.mark.parametrize("spec", BUILTINS, ids=lambda s: s.id)
def test_builtin_runs_with_its_tools(client, env, spec):
    attached = dropped_tools(spec)
    first = attached[0]
    calls, runs = [], []

    async def start(cfg, messages, tools=None, tool_choice=None):
        calls.append({"tools": [t["function"]["name"] for t in tools or []], "system": messages[0]["content"]})
        if len(calls) == 1:
            return _Stream([_Chunk(tool_call=_Delta(_func_name(first["label"]), json.dumps({"input": "x"})),
                                   finish="tool_calls")]), cfg, 1, False
        return _Stream([_Chunk(text="Done.", finish="stop")]), cfg, 1, False

    async def run_tool(tool_id, tool_input, cfg=None, args=None):
        runs.append(tool_id)
        return "evidence"

    env.setattr(llm_runner, "_start_stream_with_policy", start)
    env.setattr(llm_runner, "execute_tool_real", run_tool)
    r = client.post("/api/agents/run", headers=ADMIN, json={
        "goal": spec.evals[0].prompt, "provider": "mock", "model": "mock-gpt-4", "strategy": "sequential",
        "children": [{"agent_id": "c", "label": spec.name, "role": spec.role, "provider": "openai", "model": "gpt-x",
                      "api_key": "sk-test", "system_prompt": spec.system_prompt, "attached_tools": attached}]})
    assert r.status_code == 200, r.text

    assert calls[0]["system"].startswith(spec.system_prompt)
    assert sorted(calls[0]["tools"]) == sorted(_func_name(t["label"]) for t in attached), "one function per tool node"
    assert runs == [first["toolId"]]
    step = r.json()["steps"][1]
    assert step["output"] == "Done." and [c["tool_id"] for c in step["tool_calls"]] == [first["toolId"]]
