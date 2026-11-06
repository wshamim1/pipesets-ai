"""Built-in agents and Settings → Agents (plan.md C11 step 3): the registry's specs point at real tools
and skills, starters are installed by default, install / uninstall / reset, installing with the tools
an agent still needs, readiness, "used in a pipeline", access rules and the audit log."""

import pytest

import agents
import tools
from agents.base import AgentSpec, ToolNeed
from helpers import hdr
from routers.skills import BUILTIN_SKILLS
from services import agent_packages, tool_packages

ADMIN = hdr()
VIEWER = hdr("user_viewer", "proj_support")

FAKE = AgentSpec(
    id="test_sql_analyst", name="SQL Analyst", icon="🧮", group="Data platform", role="SQL Analyst",
    description="Answers questions with SQL.", system_prompt="Write and run SQL.",
    tools=(ToolNeed(("snowflake_reader", "sql_database"), why="runs queries"),
           ToolNeed(("snowflake_catalog",), why="reads the schema"),
           ToolNeed(("statistics_tool",), optional=True)),
    skills=("skill_snowflake_query_review",),
)


@pytest.fixture(autouse=True)
def fresh(client):
    client.delete("/api/agent-catalog/packages", headers=ADMIN)
    client.delete("/api/tools/packages", headers=ADMIN)
    yield
    client.delete("/api/agent-catalog/packages", headers=ADMIN)
    client.delete("/api/tools/packages", headers=ADMIN)


@pytest.fixture
def fake_agent(env):
    agents._load()
    env.setitem(agents._specs, FAKE.id, FAKE)
    yield FAKE
    agents._specs.pop(FAKE.id, None)


def catalog(client, headers=ADMIN):
    r = client.get("/api/agent-catalog", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def by_id(client, headers=ADMIN):
    return {a["id"]: a for a in catalog(client, headers)["agents"]}


def test_specs_point_at_real_tools_skills_and_groups():
    tools._load()
    known_tools = {t["id"] for s in tools.catalog() for t in s["tools"]}
    skill_ids = {s["id"] for s in BUILTIN_SKILLS}
    specs = agents.all_specs()
    assert len({s.id for s in specs}) == len(specs)
    for s in specs:
        assert s.group in agents.GROUPS, s.id
        for need in s.tools:
            assert need.ids and set(need.ids) <= known_tools, (s.id, set(need.ids) - known_tools)
        assert set(s.skills) <= skill_ids, (s.id, set(s.skills) - skill_ids)
        if s.starter:
            assert not s.tools, f"{s.id}: starters have no tools"
        if s.starter and s.kind == "llm" and s.role != "Custom":
            assert s.system_prompt, s.id


def test_starters_are_installed_by_default_and_ready(client):
    data = catalog(client)
    assert data["groups"] == agents.GROUPS and data["can_edit"] and data["can_install_tools"]
    starters = [a for a in data["agents"] if a["starter"]]
    assert {a["role"] for a in starters} >= {"Researcher", "Writer", "Reviewer", "Custom", "External"}
    assert all(a["installed"] and a["source"] == "default" and a["ready"] for a in starters)
    assert by_id(client)["starter_researcher"]["system_prompt"].startswith("You are a research specialist.")


def test_uninstall_and_reset(client):
    r = client.put("/api/agent-catalog/packages", headers=ADMIN,
                   json={"agent_ids": ["starter_translator"], "installed": False})
    assert r.status_code == 200 and r.json()["agents"][0]["installed"] is False
    assert by_id(client)["starter_translator"]["source"] == "choice"
    client.delete("/api/agent-catalog/packages", headers=ADMIN)
    assert by_id(client)["starter_translator"]["installed"] is True


def test_tool_backed_agent_readiness_and_install_with_tools(client, fake_agent):
    a = by_id(client)[FAKE.id]
    assert a["installed"] is False and a["source"] is None
    sql, catalog_need, stats = a["tools"]
    assert sql["installed"] == "sql_database" and sql["use"] == "sql_database", "the installed alternative wins"
    assert catalog_need["installed"] is None and catalog_need["use"] == "snowflake_catalog"
    assert stats["optional"] is True
    assert sql["names"]["sql_database"] == tools.get_spec("sql_database").name
    assert a["ready"] is False and a["missing_tools"] == ["snowflake_catalog"]

    r = client.put("/api/agent-catalog/packages", headers=ADMIN,
                   json={"agent_ids": [FAKE.id], "installed": True, "with_tools": True})
    assert r.status_code == 200, r.text
    assert r.json()["tools_installed"] == ["snowflake_catalog"]
    a = r.json()["agents"][0]
    assert a["installed"] and a["ready"] and a["missing_tools"] == []
    assert "snowflake_catalog" in tool_packages.installed_ids("tenant_demo")


def test_install_without_tools_leaves_it_not_ready(client, fake_agent):
    r = client.put("/api/agent-catalog/packages", headers=ADMIN, json={"agent_ids": [FAKE.id], "installed": True})
    assert r.json()["tools_installed"] == [] and r.json()["agents"][0]["ready"] is False


def test_agents_used_by_a_pipeline_count_as_installed(client, fake_agent):
    flow = {"nodes": [{"id": "c", "type": "child_agent", "data": {"label": "SQL", "builtin_agent_id": FAKE.id}}],
            "edges": []}
    app_id = client.post("/api/apps", json={"name": "Uses SQL agent", "flow_data": flow}, headers=ADMIN).json()["id"]
    try:
        agent_packages.STORE.clear_cache()
        a = by_id(client)[FAKE.id]
        assert a["installed"] and a["source"] == "in_use" and a["in_use"]
    finally:
        client.delete(f"/api/apps/{app_id}", headers=ADMIN)


def test_unknown_ids_access_and_audit(client):
    r = client.put("/api/agent-catalog/packages", headers=ADMIN, json={"agent_ids": ["nope"], "installed": True})
    assert r.status_code == 404 and "nope" in r.json()["detail"]
    assert catalog(client, VIEWER)["can_edit"] is False
    r = client.put("/api/agent-catalog/packages", headers=VIEWER,
                   json={"agent_ids": ["starter_writer"], "installed": False})
    assert r.status_code == 403
    assert client.delete("/api/agent-catalog/packages", headers=VIEWER).status_code == 403

    client.put("/api/agent-catalog/packages", headers=ADMIN, json={"agent_ids": ["starter_writer"], "installed": False})
    entries = client.get("/api/audit-log?action=agent_package", headers=ADMIN).json()
    rows = entries.get("entries", entries) if isinstance(entries, dict) else entries
    assert any(e["action"] == "agent_package.update" for e in rows)


def test_tool_backed_agents_have_eval_sets():
    for s in agents.all_specs():
        if s.starter:
            continue
        assert len(s.evals) >= 5, f"{s.id}: a built-in agent needs an eval set (≥ 5 cases)"
        prompts = [c.prompt.strip().lower() for c in s.evals]
        assert len(set(prompts)) == len(prompts), s.id
        assert all(c.expected.strip() for c in s.evals), s.id
        assert any(t in c.tags for c in s.evals for t in ("safety", "adversarial", "no_answer")), \
            f"{s.id}: include at least one safety / no-answer case"


def test_create_eval_dataset_from_an_agent(client):
    r = client.post("/api/agent-catalog/sql_analyst/eval-dataset", headers=ADMIN, json={"app_id": "app-1"})
    assert r.status_code == 200, r.text
    body = r.json()
    spec = agents.get("sql_analyst")
    assert body["cases_created"] == len(spec.evals) and body["scorer"] == "llm_judge"
    cases = client.get(f"/api/eval/datasets/{body['dataset_id']}/cases", headers=ADMIN).json()
    assert {c["prompt"] for c in cases} == {c.prompt for c in spec.evals}
    assert all(c["source"] == "builtin" and c["expected_output"] for c in cases)
    ds = next(d for d in client.get("/api/eval/datasets", headers=ADMIN).json() if d["id"] == body["dataset_id"])
    assert ds["app_id"] == "app-1" and ds["name"] == "SQL Analyst — built-in eval"

    assert client.post("/api/agent-catalog/starter_writer/eval-dataset", headers=ADMIN, json={}).status_code == 400
    assert client.post("/api/agent-catalog/nope/eval-dataset", headers=ADMIN, json={}).status_code == 404
