"""Skill readiness (plan.md C10 step 3, reframed): a flow can't be published while a Skill node's
required tools aren't attached to its LLM node, or are attached without a setting they can't run
without. The tests are steps of one scenario, in order."""
import pytest

from helpers import hdr
from routers.skills import STARTER_SKILLS
from services import skills_runtime

ADMIN = hdr()
AIRFLOW_TOOLS = next(s for s in STARTER_SKILLS if s["id"] == "skill_airflow_triage")["tool_ids"]
state = {}


def flow(tools, skill=None, wire_skill=True):
    nodes = [{"id": "llm", "type": "llm", "data": {"label": "LLM", "provider": "mock", "model": "mock-gpt-4"}},
             {"id": "sk", "type": "skill", "data": skill or {"skill_id": "skill_airflow_triage", "label": "Airflow"}}]
    edges = [{"source": "llm", "target": "sk"}] if wire_skill else []
    for tid, cfg in tools.items():
        nodes.append({"id": f"t_{tid}", "type": "tool", "data": {"toolId": tid, "label": tid, "config": cfg}})
        edges.append({"source": "llm", "target": f"t_{tid}"})
    return {"nodes": nodes, "edges": edges}


def publish(client, app_id, flow_data):
    assert client.put(f"/api/apps/{app_id}", json={"name": "Triage", "flow_data": flow_data}, headers=ADMIN).status_code == 200
    return client.post(f"/api/apps/{app_id}/publish", headers=ADMIN)


@pytest.fixture(scope="module")
def app_id(client):
    return client.post("/api/apps", json={"name": "Triage", "flow_data": flow({})}, headers=ADMIN).json()["id"]


def test_missing_and_unconfigured_tools_block_publishing(client, app_id):
    r = publish(client, app_id, flow({"airflow": {"base_url": ""}, "airflow_task_logs": {"base_url": "http://af:8080"}}))
    assert r.status_code == 409
    detail = r.json()["detail"]
    [issue] = detail["skills"]
    assert issue["skill"] == "Airflow DAG triage" and issue["skill_node_id"] == "sk"
    assert issue["missing_tools"] == ["airflow_import_errors", "airflow_health"]
    assert issue["unconfigured_tools"] == [{"tool_id": "airflow", "node_id": "t_airflow", "label": "airflow",
                                            "missing_settings": ["base_url"]}]
    assert detail["message"] == ("Skill 'Airflow DAG triage' isn't ready: attach airflow_import_errors, airflow_health; "
                                 "set base_url on airflow")
    assert client.get(f"/api/apps/{app_id}", headers=ADMIN).json()["status"] != "published"


def test_a_ready_skill_publishes(client, app_id):
    r = publish(client, app_id, flow({t: {"base_url": "http://af:8080"} for t in AIRFLOW_TOOLS}))
    assert r.status_code == 200, r.text


def test_what_doesnt_count():
    # A skill that needs no tools, and one that isn't wired to an LLM node
    assert skills_runtime.readiness(**flow({}, skill={"label": "Plain", "instructions": "x"})) == []
    assert skills_runtime.readiness(**flow({}, wire_skill=False)) == []


def test_old_inline_skills_are_checked_too():
    issues = skills_runtime.readiness(**flow({}, skill={"label": "Legacy", "tool_ids": ["calculator"]}))
    assert [(i["skill"], i["missing_tools"]) for i in issues] == [("Legacy", ["calculator"])]
