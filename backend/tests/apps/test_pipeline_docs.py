"""Pipeline docs: generate (template + stubbed LLM), save, publish snapshot, duplicate, README
export, and carrying docs through a marketplace listing and import."""
import pytest

import llm

seen = {}

FLOW = {"nodes": [
    {"id": "start-1", "type": "start", "position": {"x": 0, "y": 0}, "data": {"label": "Start"}},
    {"id": "llm-1", "type": "llm", "position": {"x": 200, "y": 0}, "data": {
        "label": "Triage", "provider": "openai", "model": "gpt-4o", "api_key": "", "system_prompt": "Triage Jira issues."}},
    {"id": "tool-jira", "type": "tool", "position": {"x": 400, "y": 0}, "data": {
        "label": "MCP Jira", "toolId": "mcp_jira", "toolType": "mcp", "description": "Jira issues",
        "config": {"env_vars": {"JIRA_URL": "", "JIRA_API_TOKEN": ""}}}},
    {"id": "tool-web", "type": "tool", "position": {"x": 400, "y": 100}, "data": {
        "label": "Web Search", "toolId": "web_search", "toolType": "tool", "config": {"api_key": "", "max_results": 5}}},
    {"id": "parser-1", "type": "output_parser", "position": {"x": 400, "y": 200}, "data": {
        "label": "JSON", "parser_type": "json", "schema_json": '{"priority": {"type": "string"}}', "strict": True}},
    {"id": "stop-1", "type": "stop", "position": {"x": 600, "y": 0}, "data": {"label": "Stop"}},
], "edges": [
    {"id": "e1", "source": "start-1", "target": "llm-1"}, {"id": "e2", "source": "llm-1", "target": "tool-jira"},
    {"id": "e3", "source": "llm-1", "target": "tool-web"}, {"id": "e4", "source": "llm-1", "target": "parser-1"},
    {"id": "e5", "source": "llm-1", "target": "stop-1"},
]}


@pytest.fixture(scope="module", autouse=True)
def _setup(env):
    env.setenv("AUTH_MODE", "session")

    async def fake_complete(req):
        seen.update(vars(req))
        return llm.LLMResponse(text="```markdown\n# Jira Triage\n\n## Overview\nRanks tickets.\n```")

    # Stub the backend, not llm.complete, so the gateway (key resolution) still runs
    env.setattr(llm.backend_for("openai"), "complete", fake_complete)


def signup(client, email, name):
    data = client.post("/api/auth/signup", json={"email": email, "password": "password123", "display_name": name}).json()
    t = data["tenants"][0]
    return {"Authorization": f"Bearer {data['token']}", "x-tenant-id": t["id"], "x-project-id": t["projects"][0]["id"]}


@pytest.fixture(scope="module")
def P(client):
    return signup(client, "docs-pub@example.com", "Pat Publisher")


@pytest.fixture(scope="module")
def I(client):
    return signup(client, "docs-imp@example.com", "Ivy Importer")


@pytest.fixture(scope="module")
def app(client, P):
    app = client.post("/api/apps", json={"name": "Jira Triage", "description": "Ranks new tickets.", "flow_data": FLOW},
                      headers=P).json()
    assert app.get("docs") == ""
    return app


def test_generate_template_without_key(client, P, app):
    r = client.post("/api/apps/docs/generate", json={"flow_data": FLOW, "app_id": app["id"], "name": "Jira Triage",
                                                     "description": "Ranks new tickets."}, headers=P).json()
    tpl = r["docs"]
    assert r["generated_by"] == "template"
    assert "API key for **openai**" in tpl
    assert "`JIRA_URL`, `JIRA_API_TOKEN`" in tpl
    assert "Web Search" not in tpl.split("## Setup")[1], "optional tool api_key not listed"
    assert '"priority"' in tpl


def test_generate_with_model(client, P):
    r = client.post("/api/apps/docs/generate", json={"flow_data": FLOW, "name": "Jira Triage",
                                                     "provider_keys": {"openai": "sk-x"}}, headers=P).json()
    assert r["generated_by"] == "openai/gpt-4o"
    assert r["docs"].startswith("# Jira Triage"), "code fence stripped"
    assert "JIRA_API_TOKEN" in seen["messages"][0]["content"], "prompt carries setup facts"


def test_save_publish_duplicate_export(client, P, I, app):
    r = client.put(f"/api/apps/{app['id']}/docs", json={"docs": "# v1 docs"}, headers=P)
    assert r.status_code == 200 and r.json()["docs"] == "# v1 docs"
    client.post(f"/api/apps/{app['id']}/publish", headers=P)
    r = client.put(f"/api/apps/{app['id']}/docs", json={"docs": "# v1 docs, edited"}, headers=P)
    assert r.status_code == 200 and r.json()["status"] == "published", "docs can change while published"
    assert client.get(f"/api/apps/{app['id']}/versions/1", headers=P).json()["docs"] == "# v1 docs", \
        "the published version keeps its snapshot"
    assert client.put(f"/api/apps/{app['id']}/docs", json={"docs": "x"}, headers=I).status_code == 404

    dup = client.post(f"/api/apps/{app['id']}/duplicate", headers=P).json()
    assert dup["docs"] == "# v1 docs, edited"

    exp = client.get(f"/api/export/{app['id']}?format=readme", headers=P)
    assert exp.status_code == 200 and exp.text == "# v1 docs, edited"
    assert "README.md" in exp.headers.get("content-disposition", "")
    blank = client.post("/api/apps", json={"name": "Blank", "flow_data": FLOW}, headers=P).json()
    exp = client.get(f"/api/export/{blank['id']}?format=readme", headers=P)
    assert exp.text.startswith("# Blank") and "## Setup" in exp.text, "falls back to the template"


def test_marketplace_carries_docs(client, P, I, app):
    r = client.post("/api/marketplace/listings", json={"app_id": app["id"], "summary": "Triage tickets"}, headers=P)
    assert r.status_code == 201
    listing_id = r.json()["id"]
    assert client.get(f"/api/marketplace/listings/{listing_id}", headers=I).json()["docs"] == "# v1 docs, edited"
    imported = client.post(f"/api/marketplace/listings/{listing_id}/import", json={}, headers=I).json()
    assert client.get(f"/api/apps/{imported['app_id']}", headers=I).json()["docs"] == "# v1 docs, edited"
