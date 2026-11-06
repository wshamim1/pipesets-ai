"""
Saved agents (plan.md C11 step 2, routers/saved_agents.py): a child agent saved with its tool and skill
nodes, versioned on every save, credentials blanked (secret:// refs kept), scoped to its project.
"""

from helpers import hdr

ADMIN = hdr()
OTHER_PROJECT = hdr(project="proj_support")
VIEWER = hdr(user="user_viewer")


def spec(**child):
    return {
        "child": {"role": "SQL Analyst", "system_prompt": "Answer with SQL.", "provider": "openai", "model": "gpt-x",
                  "api_key": "sk-live-123", "fallback_api_key": "secret://proj/openai", "auth_header": "X-API-Key",
                  "onDelete": "not a field", "label": "ignored", **child},
        "tools": [
            {"type": "tool", "data": {"toolId": "sql_database", "label": "SQL", "config": {"password": "hunter2",
                                                                                         "max_tokens": "500", "dsn": ""}}},
            {"type": "toolkit", "data": {"toolkitId": "tk1", "label": "Kit",
                                         "subTools": [{"toolId": "calculator", "config": {"api_key": "k"}}]}},
            {"type": "tool", "data": {"label": "no tool id"}},
        ],
        "skills": [{"skill_id": "skill_snowflake_query_review", "skill_version": 1, "label": "Snowflake review"}],
    }


def test_save_strips_credentials_and_keeps_the_rest(client):
    r = client.post("/api/saved-agents", headers=ADMIN, json={"name": "SQL Analyst", "icon": "📊", "spec": spec()})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["id"].startswith("agent_") and a["version"] == 1
    child = a["spec"]["child"]
    assert child["api_key"] == "" and child["fallback_api_key"] == "secret://proj/openai"
    assert child["auth_header"] == "X-API-Key" and "onDelete" not in child and "label" not in child
    sql, kit = a["spec"]["tools"]
    assert sql["data"]["config"] == {"password": "", "max_tokens": "500", "dsn": ""}
    assert kit["type"] == "toolkit" and kit["data"]["subTools"][0]["config"]["api_key"] == ""
    assert a["spec"]["skills"] == [{"skill_id": "skill_snowflake_query_review", "skill_version": 1,
                                    "label": "Snowflake review"}]
    assert sorted(a["stripped"]) == ["child.api_key", "tools[0].data.config.password",
                                     "tools[1].data.subTools[0].config.api_key"]


def test_update_bumps_version_and_keeps_history(client):
    a = client.get("/api/saved-agents", headers=ADMIN).json()[0]
    r = client.put(f"/api/saved-agents/{a['id']}", headers=ADMIN,
                   json={"description": "Writes SQL", "spec": spec(system_prompt="v2 prompt")})
    assert r.status_code == 200 and r.json()["version"] == 2
    assert r.json()["name"] == "SQL Analyst" and r.json()["description"] == "Writes SQL"

    renamed = client.put(f"/api/saved-agents/{a['id']}", headers=ADMIN, json={"name": "SQL Pro"}).json()
    assert renamed["version"] == 3 and renamed["spec"]["child"]["system_prompt"] == "v2 prompt"

    versions = client.get(f"/api/saved-agents/{a['id']}/versions", headers=ADMIN).json()
    assert [v["version"] for v in versions] == [3, 2, 1]
    v1 = client.get(f"/api/saved-agents/{a['id']}/versions/1", headers=ADMIN).json()
    assert v1["version"] == 1 and v1["name"] == "SQL Analyst" and v1["spec"]["child"]["system_prompt"] == "Answer with SQL."
    assert client.get(f"/api/saved-agents/{a['id']}/versions/9", headers=ADMIN).status_code == 404


def test_other_projects_and_users_without_access_cant_see_it(client):
    a = client.get("/api/saved-agents", headers=ADMIN).json()[0]
    assert client.get("/api/saved-agents", headers=OTHER_PROJECT).json() == []
    for method in ("get", "delete"):
        assert getattr(client, method)(f"/api/saved-agents/{a['id']}", headers=OTHER_PROJECT).status_code == 404
    assert client.put(f"/api/saved-agents/{a['id']}", headers=OTHER_PROJECT, json={"name": "x"}).status_code == 404
    assert client.get("/api/saved-agents", headers=VIEWER).status_code == 403


def test_limits(client):
    big = spec()
    big["tools"] = [{"type": "tool", "data": {"toolId": f"t{i}"}} for i in range(51)]
    assert client.post("/api/saved-agents", headers=ADMIN, json={"name": "x", "spec": big}).status_code == 422
    huge = spec(system_prompt="x" * 300_000)
    assert client.post("/api/saved-agents", headers=ADMIN, json={"name": "x", "spec": huge}).status_code == 422
    assert client.post("/api/saved-agents", headers=ADMIN, json={"name": "", "spec": spec()}).status_code == 422


def test_delete_removes_versions(client):
    a = client.get("/api/saved-agents", headers=ADMIN).json()[0]
    assert client.delete(f"/api/saved-agents/{a['id']}", headers=ADMIN).json()["success"] is True
    assert client.get(f"/api/saved-agents/{a['id']}", headers=ADMIN).status_code == 404
    assert client.get(f"/api/saved-agents/{a['id']}/versions", headers=ADMIN).status_code == 404
