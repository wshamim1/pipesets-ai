"""
The remote MCP server at /v1/mcp (routers/v1_mcp.py): the protocol, API-key auth and scopes,
and the tools running real (mock-model) published apps.
"""

import pytest

from helpers import hdr, mock_flow
from services import api_keys
from services.request_context import RequestContext

GATED_FLOW = {
    "nodes": [{"id": "m", "type": "master_agent", "data": {"provider": "mock", "model": "mock-gpt-4"}},
              {"id": "c", "type": "child_agent", "data": {"provider": "mock", "model": "mock-gpt-4", "role": "writer",
                                                           "label": "W"}},
              {"id": "g", "type": "human_gate", "data": {"label": "Review"}}],
    "edges": [{"source": "m", "target": "c"}, {"source": "g", "target": "m"}],
}


def _key(scopes=None, rpm=0):
    plaintext, _ = api_keys.create_key(
        RequestContext(tenant_id="tenant_demo", project_id="proj_research", user_id="user_admin"),
        "mcp", scopes, rate_limit_rpm=rpm)
    return plaintext


@pytest.fixture(scope="module")
def key():
    return _key()


@pytest.fixture(scope="module")
def apps(client):
    out = {}
    for name, flow in (("Echo", mock_flow()), ("Gated", GATED_FLOW)):
        aid = client.post("/api/apps", headers=hdr(), json={"name": name, "description": "", "flow_data": flow}).json()["id"]
        assert client.post(f"/api/apps/{aid}/publish", headers=hdr()).status_code == 200
        out[name] = aid
    out["draft"] = client.post("/api/apps", headers=hdr(), json={"name": "Draft", "description": "",
                                                                 "flow_data": mock_flow()}).json()["id"]
    return out


def _post(client, key, body, **headers):
    return client.post("/v1/mcp", json=body, headers={"Authorization": f"Bearer {key}",
                                                     "Accept": "application/json, text/event-stream", **headers})


def _rpc(client, key, method, params=None, msg_id=1):
    r = _post(client, key, {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})
    assert r.status_code == 200, r.text
    return r.json()


def _call(client, key, tool, **arguments):
    return _rpc(client, key, "tools/call", {"name": tool, "arguments": arguments})["result"]


# ── Protocol ──────────────────────────────────────────────────────────────────

def test_initialize_negotiates_the_protocol_version(client, key):
    res = _rpc(client, key, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                           "clientInfo": {"name": "test", "version": "1"}})["result"]
    assert res["protocolVersion"] == "2025-06-18"
    assert res["capabilities"] == {"tools": {"listChanged": False}}
    assert res["serverInfo"]["name"] == "pipesets-ai"
    newer = _rpc(client, key, "initialize", {"protocolVersion": "2099-01-01"})["result"]
    assert newer["protocolVersion"] == "2025-11-25", "unknown versions get our latest"


def test_notifications_get_202_and_no_body(client, key):
    r = _post(client, key, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202 and r.content == b""


def test_protocol_errors(client, key):
    assert _rpc(client, key, "resources/list")["error"]["code"] == -32601
    assert _rpc(client, key, "ping")["result"] == {}
    bad = client.post("/v1/mcp", content=b"{not json", headers={"Authorization": f"Bearer {key}"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == -32700
    assert _post(client, key, {"id": 1, "method": "ping"}).json()["error"]["code"] == -32600, "jsonrpc missing"
    assert _post(client, key, {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                 **{"MCP-Protocol-Version": "1999-01-01"}).status_code == 400


def test_batches_answer_each_request(client, key):
    r = _post(client, key, [{"jsonrpc": "2.0", "id": "a", "method": "ping"},
                            {"jsonrpc": "2.0", "method": "notifications/initialized"},
                            {"jsonrpc": "2.0", "id": "b", "method": "tools/list"}])
    assert [m["id"] for m in r.json()] == ["a", "b"]


def test_no_session_stream(client):
    assert client.get("/v1/mcp").status_code == 405
    assert client.delete("/v1/mcp").status_code == 405


# ── Auth ──────────────────────────────────────────────────────────────────────

def test_a_key_is_required(client, key):
    r = client.post("/v1/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert _post(client, "psk_wrong", {"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 403
    assert _post(client, key, {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                 Origin="https://evil.example").status_code == 403, "browsers refused unless allow-listed"


def test_allowed_origins(client, key, env):
    env.setenv("MCP_ALLOWED_ORIGINS", "https://app.example, https://other.example")
    assert _post(client, key, {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                 Origin="https://app.example").status_code == 200
    env.delenv("MCP_ALLOWED_ORIGINS")


def test_tools_follow_the_keys_scopes(client, key):
    assert {t["name"] for t in _rpc(client, key, "tools/list")["result"]["tools"]} == \
        {"list_apps", "get_app", "run_app", "resume_run", "cancel_run"}
    read_only = _key(["apps:read"])
    assert {t["name"] for t in _rpc(client, read_only, "tools/list")["result"]["tools"]} == {"list_apps", "get_app"}
    err = _rpc(client, read_only, "tools/call", {"name": "run_app", "arguments": {"app_id": "x", "prompt": "hi"}})
    assert err["error"]["code"] == -32602, "a tool outside the key's scopes doesn't exist for it"


def test_every_request_counts_against_the_rate_limit(client):
    limited = _key(rpm=2)
    assert _post(client, limited, {"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 200
    assert _post(client, limited, {"jsonrpc": "2.0", "id": 2, "method": "ping"}).status_code == 200
    assert _post(client, limited, {"jsonrpc": "2.0", "id": 3, "method": "ping"}).status_code == 429


# ── Tools ─────────────────────────────────────────────────────────────────────

def test_list_and_get_published_apps_only(client, key, apps):
    listed = _call(client, key, "list_apps")
    ids = {a["id"] for a in listed["structuredContent"]["apps"]}
    assert {apps["Echo"], apps["Gated"]} <= ids and apps["draft"] not in ids
    app = _call(client, key, "get_app", app_id=apps["Echo"])
    assert app["structuredContent"]["name"] == "Echo" and "flow_data" not in app["structuredContent"]
    missing = _call(client, key, "get_app", app_id=apps["draft"])
    assert missing["isError"] and "not published" in missing["content"][0]["text"]


def test_run_app_returns_the_answer(client, key, apps):
    res = _call(client, key, "run_app", app_id=apps["Echo"], prompt="hello there")
    assert not res["isError"]
    assert "hello there" in res["content"][0]["text"]
    assert res["structuredContent"]["status"] == "completed" and res["structuredContent"]["app_id"] == apps["Echo"]


def test_run_app_errors_are_tool_errors(client, key, apps):
    assert _call(client, key, "run_app", app_id=apps["Echo"])["isError"], "prompt missing"
    assert _call(client, key, "run_app", app_id="app_nope", prompt="hi")["content"][0]["text"] == "App not found"
    slow = _call(client, key, "run_app", app_id=apps["Echo"], prompt="hi", timeout_ms=5)
    assert slow["isError"] and "Invalid arguments" in slow["content"][0]["text"]


def test_a_human_gate_pauses_and_cant_be_approved_by_the_model(client, key, apps):
    res = _call(client, key, "run_app", app_id=apps["Gated"], prompt="draft a reply")
    assert not res["isError"] and res["structuredContent"]["status"] == "paused"
    assert "Paused for human review" in res["content"][0]["text"]
    run_id = res["structuredContent"]["run_id"]

    resumed = _call(client, key, "resume_run", run_id=run_id)
    assert resumed["isError"] and "Pipesets UI" in resumed["content"][0]["text"]

    # A person approves it through the REST API; it completes
    r = client.post(f"/v1/runs/{run_id}/resume", json={"gate_decision": {"action": "approve"}},
                    headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text


# ── Write tools ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def writer():
    return _key(["apps:read", "apps:run", "apps:write", "apps:publish"])


def _audit_rows(action):
    from db import get_db_connection
    conn = get_db_connection()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM audit_log WHERE action = ? ORDER BY created_at",
                                              (action,)).fetchall()]
    finally:
        conn.close()


def test_new_keys_get_no_write_scopes_unless_asked(client):
    r = client.post("/api/api-keys", headers=hdr(), json={"name": "default"})
    assert sorted(r.json()["scopes"]) == ["apps:read", "apps:run"]
    tools = {t["name"] for t in _rpc(client, r.json()["key"], "tools/list")["result"]["tools"]}
    assert not tools & {"create_app", "update_app", "publish_app", "list_drafts", "get_flow"}


def test_write_and_publish_are_separate_scopes(client):
    drafts_only = _key(["apps:read", "apps:write"])
    tools = {t["name"] for t in _rpc(client, drafts_only, "tools/list")["result"]["tools"]}
    assert {"create_app", "update_app", "list_drafts", "get_flow"} <= tools and "publish_app" not in tools


def test_build_a_draft_publish_it_and_run_it(client, writer):
    created = _call(client, writer, "create_app", name="From MCP", description="made by a model",
                    flow_data=mock_flow("mcp"))
    assert not created["isError"], created
    app = created["structuredContent"]
    assert app["status"] == "draft" and app["version"] == 0 and app["node_count"] == 1
    assert app["id"] in {a["id"] for a in _call(client, writer, "list_drafts")["structuredContent"]["apps"]}
    assert _call(client, writer, "run_app", app_id=app["id"], prompt="hi")["isError"], "drafts don't run"

    renamed = _call(client, writer, "update_app", app_id=app["id"], name="From MCP v1")["structuredContent"]
    assert renamed["name"] == "From MCP v1" and renamed["node_count"] == 1, "omitted fields kept"
    flow = _call(client, writer, "get_flow", app_id=app["id"])["structuredContent"]["flow_data"]
    assert flow["nodes"][0]["id"] == "mcp"

    published = _call(client, writer, "publish_app", app_id=app["id"])["structuredContent"]
    assert published["status"] == "published" and published["version"] == 1
    assert "hi there" in _call(client, writer, "run_app", app_id=app["id"], prompt="hi there")["content"][0]["text"]

    again = _call(client, writer, "publish_app", app_id=app["id"])
    assert again["isError"] and "already published" in again["content"][0]["text"]
    live = _call(client, writer, "update_app", app_id=app["id"], name="sneaky")
    assert live["isError"] and "never changes what is live" in live["content"][0]["text"]

    for action, tool in (("app.create", "create_app"), ("app.update", "update_app"), ("app.publish", "publish_app")):
        row = _audit_rows(action)[-1]
        assert row["actor"] == "user_admin" and row["target_id"] == app["id"] and row["method"] == "MCP"
        assert f"{tool} · key mcp" in row["path"]


def test_publish_goes_through_the_eval_gate_with_no_override(client, writer):
    app = _call(client, writer, "create_app", name="Gated by evals", flow_data=mock_flow("g"))["structuredContent"]
    ds = client.post("/api/eval/datasets", headers=hdr(), json={"name": "strict", "app_id": app["id"]}).json()["id"]
    client.post(f"/api/eval/datasets/{ds}/cases", headers=hdr(), json={"prompt": "hello", "expected_output": "goodbye"})
    assert client.put(f"/api/apps/{app['id']}/publish-gate", headers=hdr(),
                      json={"dataset_id": ds, "min_pass_rate": 1.0}).status_code == 200

    res = _call(client, writer, "publish_app", app_id=app["id"], force=True)
    assert res["isError"] and "Eval gate failed" in res["content"][0]["text"]
    assert client.get(f"/api/apps/{app['id']}", headers=hdr()).json()["status"] == "draft"
    denied = _audit_rows("app.publish")[-1]
    assert denied["outcome"] == "denied" and denied["target_id"] == app["id"]


def test_flows_with_plaintext_keys_are_refused_both_ways(client, writer):
    leaky = mock_flow("k")
    leaky["nodes"][0]["data"]["api_key"] = "sk-live-1234567890abcdef"
    res = _call(client, writer, "create_app", name="Leaky", flow_data=leaky)
    assert res["isError"] and "plain text" in res["content"][0]["text"]
    bad = _call(client, writer, "create_app", name="Bad", flow_data={"nodes": "x"})
    assert bad["isError"] and "nodes" in bad["content"][0]["text"]


def test_write_tools_follow_the_owners_access(client):
    from db import get_db_connection
    viewer_key, _ = api_keys.create_key(
        RequestContext(tenant_id="tenant_demo", project_id="proj_support", user_id="user_viewer"),
        "viewer", ["apps:read", "apps:write"], rate_limit_rpm=0)
    res = _call(client, viewer_key, "create_app", name="Nope")
    assert res["isError"] and "Access denied" in res["content"][0]["text"], "the owner has apps:read only"
    conn = get_db_connection()
    try:
        assert not conn.execute("SELECT 1 FROM apps WHERE name = 'Nope'").fetchone()
    finally:
        conn.close()
