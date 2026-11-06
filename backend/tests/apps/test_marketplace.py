"""The pipeline marketplace end to end: publish, browse, try, import, versions. The LLM stream
is stubbed and records what each run received. The tests are steps of one scenario, in order."""
import json

import pytest

from services import pipeline_runner, secret_store

runs = []
state = {}

FLOW_NODES = [
    {"id": "start-1", "type": "start", "position": {"x": 0, "y": 0}, "data": {"label": "Start"}},
    {"id": "mem-1", "type": "memory", "position": {"x": 200, "y": 200}, "data": {
        "label": "Memory", "strategy": "last_k", "token_budget": 2000, "session_id": "publisher-private-session"}},
    {"id": "stop-1", "type": "stop", "position": {"x": 600, "y": 0}, "data": {"label": "Stop"}},
]


@pytest.fixture(scope="module", autouse=True)
def _setup(env):
    env.setenv("AUTH_MODE", "session")
    env.delenv("MARKETPLACE_TRY_SERVER_KEYS", raising=False)

    async def fake_consume_stream(req):
        runs.append(req)
        return f"echo: {req.prompt}", None, {"model": req.config.model, "provider": req.config.provider}

    env.setattr(pipeline_runner, "_consume_stream", fake_consume_stream)


def signup(client, email, name):
    data = client.post("/api/auth/signup", json={"email": email, "password": "password123", "display_name": name}).json()
    t = data["tenants"][0]
    return {"Authorization": f"Bearer {data['token']}", "x-tenant-id": t["id"], "x-project-id": t["projects"][0]["id"]}


@pytest.fixture(scope="module")
def P(client):
    return signup(client, "publisher@example.com", "Pat Publisher")


@pytest.fixture(scope="module")
def I(client):
    return signup(client, "importer@example.com", "Ivy Importer")


@pytest.fixture(scope="module")
def secret_ref(client, P):
    """Flows hold credentials only as vault refs or sealed values (plaintext is refused on save)."""
    return client.post("/api/secrets", json={"name": "OpenAI", "value": "sk-live-SUPERSECRET", "kind": "llm",
                                             "provider": "openai"}, headers=P).json()["ref"]


@pytest.fixture(scope="module")
def flow(secret_ref):
    return {"nodes": [
        *FLOW_NODES,
        {"id": "llm-1", "type": "llm", "position": {"x": 200, "y": 0}, "data": {
            "label": "Answer", "provider": "openai", "model": "gpt-4o", "api_key": secret_ref,
            "system_prompt": "Be helpful", "max_tokens": 512, "isSelected": True}},
        {"id": "tool-1", "type": "tool", "position": {"x": 400, "y": 0}, "data": {
            "label": "Slack", "toolId": "slack", "toolType": "tool",
            "config": {"webhook_url": secret_store.seal("https://hooks.slack/x"), "channel": "#ops"}}},
    ], "edges": [{"id": "e1", "source": "start-1", "target": "llm-1"}, {"id": "e2", "source": "llm-1", "target": "mem-1"},
                 {"id": "e3", "source": "llm-1", "target": "stop-1"}]}


@pytest.fixture(scope="module")
def app(client, P, flow):
    return client.post("/api/apps", json={"name": "Support Triage", "description": "Routes tickets", "flow_data": flow},
                       headers=P).json()


@pytest.fixture(scope="module")
def listing(client, P, I, app):
    assert client.post("/api/marketplace/listings", json={"app_id": app["id"], "summary": "Triage tickets"},
                       headers=P).status_code == 409, "draft apps can't be listed"
    client.post(f"/api/apps/{app['id']}/publish", headers=P)
    assert client.post("/api/marketplace/listings", json={"app_id": app["id"]}, headers=I).status_code == 404, \
        "someone else can't list my app"
    assert client.post("/api/marketplace/listings", json={"app_id": app["id"], "category": "nope"},
                       headers=P).status_code == 400
    r = client.post("/api/marketplace/listings", json={"app_id": app["id"], "summary": "Triage tickets",
                                                       "category": "customer_support", "tags": ["Support", "triage!"]},
                    headers=P)
    assert r.status_code == 201
    return r.json()


def test_publishing_rules(client, P, app, listing):
    assert listing["tags"] == ["support", "triage"]
    assert client.post("/api/marketplace/listings", json={"app_id": app["id"]}, headers=P).status_code == 409
    reqs = listing["requirements"]
    assert any(r["kind"] == "provider_key" and r["provider"] == "openai" for r in reqs)
    assert "secret" in {r["kind"] for r in reqs}, "tool secret requirement recorded"
    assert listing["can_try"]


def test_sanitisation(client, I, listing, secret_ref):
    detail = client.get(f"/api/marketplace/listings/{listing['id']}", headers=I).json()
    dump = json.dumps(detail)
    assert secret_ref not in dump and "SUPERSECRET" not in dump, "the key never leaves the publisher"
    assert "enc://" not in dump, "webhook stripped"
    assert '"channel": "#ops"' in dump, "non-secret tool config kept"
    assert "publisher-private-session" not in dump
    assert '"token_budget": 2000' in dump and '"max_tokens": 512' in dump
    assert detail["source_app_id"] is None
    assert detail["publisher"]["user_name"] == "Pat Publisher"


def test_browse(client, I, listing):
    get = lambda q: client.get(f"/api/marketplace/listings{q}", headers=I).json()["listings"]  # noqa: E731
    assert any(x["id"] == listing["id"] for x in get(""))
    assert len(get("?q=triage")) == 1
    assert len(get("?category=rag")) == 0
    assert len(get("?mine=1")) == 0


def test_try(client, I, listing):
    url = f"/api/marketplace/listings/{listing['id']}/try"
    r = client.post(url, json={"prompt": "hi"}, headers=I)
    assert r.status_code == 400 and "openai" in r.json()["detail"], "needs the caller's own key"
    r = client.post(url, json={"prompt": "hi", "provider_keys": {"openai": "sk-importer"}}, headers=I)
    assert r.status_code == 200 and r.json()["ok"] and r.json()["output"] == "echo: hi"
    assert runs[-1].config.api_key == "sk-importer", "the importer's key, not the publisher's"
    assert (runs[-1].session_id or "").startswith("try-")
    assert client.get(f"/api/marketplace/listings/{listing['id']}", headers=I).json()["try_count"] == 1


def test_import(client, P, I, listing):
    r = client.post(f"/api/marketplace/listings/{listing['id']}/import", json={}, headers=I)
    assert r.status_code == 201
    state["imported"] = r.json()["app_id"]
    got = client.get(f"/api/apps/{state['imported']}", headers=I).json()
    assert got["status"] == "draft" and got["tenant_id"] == I["x-tenant-id"]
    assert "SUPERSECRET" not in json.dumps(got["flow_data"]) and "secret://" not in json.dumps(got["flow_data"])
    assert client.get(f"/api/apps/{state['imported']}", headers=P).status_code == 404
    imports = client.get("/api/marketplace/imports", headers=I).json()["imports"]
    assert len(imports) == 1 and not imports[0]["update_available"]


def test_custom_tools_bundled_and_copied(client, P, I, app, flow, listing):
    tool = client.post("/api/custom-tools", json={"name": "shout", "description": "upper-cases",
                                                  "code": "def run(input_text, config):\n    return input_text.upper()\n",
                                                  "requirements": ["requests>=2"]},
                       headers=P)
    assert tool.status_code in (200, 201)
    tool_id = tool.json()["id"]
    flow2 = json.loads(json.dumps(flow))
    flow2["nodes"].append({"id": "tool-2", "type": "tool", "position": {"x": 0, "y": 300}, "data": {
        "label": "Shout", "toolId": f"custom_{tool_id}", "toolType": "tool", "config": {}}})
    flow2["edges"].append({"id": "e4", "source": "llm-1", "target": "tool-2"})
    client.post(f"/api/apps/{app['id']}/edit", headers=P)
    client.put(f"/api/apps/{app['id']}", json={"flow_data": flow2}, headers=P)
    versions = f"/api/marketplace/listings/{listing['id']}/versions"
    assert client.post(versions, json={"changelog": "x"}, headers=P).status_code == 409, "needs a re-published app"
    client.post(f"/api/apps/{app['id']}/publish", headers=P)
    r = client.post(versions, json={"changelog": "Adds shouting"}, headers=P)
    assert r.status_code == 201 and r.json()["latest_version"] == 2
    assert not r.json()["can_try"], "v2 with custom code isn't tryable"
    assert client.post(versions, json={}, headers=I).status_code == 403

    v2 = client.get(f"/api/marketplace/listings/{listing['id']}", headers=I).json()
    assert v2["bundled_tools"][0]["code"].startswith("def run"), "bundled code shown before import"
    assert client.get(f"/api/marketplace/listings/{listing['id']}?version=1", headers=I).json()["version"] == 1
    assert client.get("/api/marketplace/imports", headers=I).json()["imports"][0]["update_available"]
    assert client.post(f"/api/marketplace/listings/{listing['id']}/try",
                       json={"prompt": "x", "provider_keys": {"openai": "k"}}, headers=I).status_code == 409

    r = client.post(f"/api/marketplace/listings/{listing['id']}/import", json={"name": "My triage"}, headers=I).json()
    assert len(r["created_tools"]) == 1
    new_tool_id = r["created_tools"][0]["id"]
    mine = client.get("/api/custom-tools", headers=I).json()
    mine = mine if isinstance(mine, list) else mine.get("tools", mine.get("custom_tools", []))
    assert next(t for t in mine if t["id"] == new_tool_id)["requirements"] == ["requests>=2"], \
        "requirements travel with the bundled tool"
    flow_in = client.get(f"/api/apps/{r['app_id']}", headers=I).json()["flow_data"]
    tool_ids = [n["data"].get("toolId") for n in flow_in["nodes"] if n["type"] == "tool"]
    assert f"custom_{new_tool_id}" in tool_ids and f"custom_{tool_id}" not in tool_ids, "rewired to the copy"
    mem = next(n for n in flow_in["nodes"] if n["type"] == "memory")
    assert mem["data"]["session_id"].startswith("session-")


def test_private_data_references_are_cut(client, P, I):
    rag_flow = {"nodes": [
        {"id": "llm-1", "type": "llm", "position": {"x": 0, "y": 0}, "data": {"label": "LLM", "provider": "ollama",
                                                                              "model": "llama3"}},
        {"id": "ret-1", "type": "retriever", "position": {"x": 0, "y": 0}, "data": {
            "label": "Retriever", "collection_name": "publisher_private_docs", "embedding_provider": "local"}},
        {"id": "conn-1", "type": "connection", "position": {"x": 0, "y": 0}, "data": {
            "label": "Prod DB", "connection_type": "postgres", "connection_id": "c1",
            "config": {"host": "10.0.0.5", "user": "admin", "password": secret_store.seal("hunter2")}}},
    ], "edges": []}
    rag = client.post("/api/apps", json={"name": "Docs QA", "flow_data": rag_flow}, headers=P).json()
    client.post(f"/api/apps/{rag['id']}/publish", headers=P)
    r = client.post("/api/marketplace/listings", json={"app_id": rag["id"], "visibility": "tenant", "category": "rag"},
                    headers=P).json()
    state["rag_app"], state["rag_listing"] = rag["id"], r["id"]
    dump = json.dumps(client.get(f"/api/marketplace/listings/{r['id']}", headers=P).json())
    assert "publisher_private_docs" not in dump
    assert "hunter2" not in dump and "10.0.0.5" not in dump and "enc://" not in dump
    assert {"data_source", "connection"} <= {x["kind"] for x in r["requirements"]}
    assert not any(x["kind"] == "provider_key" for x in r["requirements"]), "keyless providers need no key"
    assert client.get(f"/api/marketplace/listings/{r['id']}", headers=I).status_code == 404, "tenant-only"
    assert all(x["id"] != r["id"] for x in client.get("/api/marketplace/listings", headers=I).json()["listings"])

    mcp_flow = {"nodes": [{"id": "llm-1", "type": "llm", "data": {"label": "LLM", "provider": "mock"}},
                          {"id": "t", "type": "tool", "data": {"label": "MCP", "toolId": "custom_mcp_abc"}}], "edges": []}
    mcp = client.post("/api/apps", json={"name": "MCP thing", "flow_data": mcp_flow}, headers=P).json()
    client.post(f"/api/apps/{mcp['id']}/publish", headers=P)
    assert client.post("/api/marketplace/listings", json={"app_id": mcp["id"]}, headers=P).status_code == 400


def test_manage(client, P, I, listing):
    url = f"/api/marketplace/listings/{listing['id']}"
    assert client.put(url, json={"name": "pwned"}, headers=I).status_code == 403
    client.put(url, json={"status": "unlisted"}, headers=P)
    assert client.get(url, headers=I).status_code == 404
    assert client.get(url, headers=P).status_code == 200
    assert client.delete(url, headers=P).status_code == 200
    assert client.get(f"/api/apps/{state['imported']}", headers=I).status_code == 200, "imports survive deletion"


def test_acls(client, P):
    client.post("/api/iam/users", json={"email": "viewer@example.com", "display_name": "V", "password": "password123"},
                headers=P)
    vtok = client.post("/api/auth/login", json={"email": "viewer@example.com", "password": "password123"}).json()["token"]
    V = {**P, "Authorization": f"Bearer {vtok}"}
    assert client.post("/api/marketplace/listings", json={"app_id": state["rag_app"]}, headers=V).status_code == 403
    assert client.post(f"/api/marketplace/listings/{state['rag_listing']}/import", json={},
                       headers=V).status_code == 403
