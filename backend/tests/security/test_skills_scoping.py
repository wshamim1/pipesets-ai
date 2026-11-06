"""Skills are scoped to their tenant + project: another tenant can't list, read, edit, delete or run
them, and the built-ins are read-only for everyone."""
import asyncio

import pytest

from routers.agents import ChildAgentConfig, _child_skillset
from services.pipeline_runner import RunScope, current_scope


@pytest.fixture(scope="module", autouse=True)
def _setup(env):
    env.setenv("AUTH_MODE", "session")


def signup(client, email):
    data = client.post("/api/auth/signup", json={"email": email, "password": "password123",
                                                 "display_name": email.split("@")[0]}).json()
    t = data["tenants"][0]
    return {"Authorization": f"Bearer {data['token']}", "x-tenant-id": t["id"], "x-project-id": t["projects"][0]["id"]}


@pytest.fixture(scope="module")
def A(client):
    return signup(client, "skill-owner@example.com")


@pytest.fixture(scope="module")
def B(client):
    return signup(client, "skill-other@example.com")


@pytest.fixture(scope="module")
def skill(client, A):
    res = client.post("/api/skills", json={"name": "Licence renewal", "instructions": "SECRET-SOP"}, headers=A)
    assert res.status_code == 200
    return res.json()


def test_owner_sees_own_skill_and_builtins(client, A, skill):
    skills = client.get("/api/skills", headers=A).json()
    assert skill["id"] in [s["id"] for s in skills]
    assert {s["id"] for s in skills if s["builtin"]} == {"skill_airflow_triage", "skill_databricks_job_triage",
                                                         "skill_snowflake_query_review", "skill_kafka_lag"}
    assert client.get(f"/api/skills/{skill['id']}", headers=A).json()["instructions"] == "SECRET-SOP"


def test_other_tenant_cannot_list_read_edit_or_delete(client, A, B, skill):
    assert skill["id"] not in [s["id"] for s in client.get("/api/skills", headers=B).json()]
    assert client.get(f"/api/skills/{skill['id']}", headers=B).status_code == 404
    assert client.put(f"/api/skills/{skill['id']}", json={"instructions": "pwned"}, headers=B).status_code == 404
    assert client.delete(f"/api/skills/{skill['id']}", headers=B).status_code == 404
    assert client.get(f"/api/skills/{skill['id']}", headers=A).json()["instructions"] == "SECRET-SOP"


def test_builtins_are_read_only(client, A):
    assert client.get("/api/skills/skill_data_analysis", headers=A).json()["builtin"] is True
    assert client.put("/api/skills/skill_data_analysis", json={"instructions": "x"}, headers=A).status_code == 403
    assert client.delete("/api/skills/skill_data_analysis", headers=A).status_code == 403


def _child_prompt(skill_ids):
    return _child_skillset(ChildAgentConfig(skill_ids=skill_ids), can_call_tools=False).prompt_section()


def test_child_agent_only_loads_its_own_tenants_skills(A, B, skill):
    def load(headers):
        token = current_scope.set(RunScope(tenant_id=headers["x-tenant-id"], project_id=headers["x-project-id"],
                                           user_id="u"))
        try:
            return _child_prompt([skill["id"], "skill_code_reviewer"])
        finally:
            current_scope.reset(token)

    assert "SECRET-SOP" in load(A)
    other = load(B)
    assert "SECRET-SOP" not in other and "Code Review" in other
    assert "SECRET-SOP" not in _child_prompt([skill["id"]])   # no run scope
