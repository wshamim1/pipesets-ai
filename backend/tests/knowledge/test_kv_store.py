"""
Key-value store (services/kv_store.py) and its agent tool ``key_value_store``: entries scoped by
tenant / project / namespace / end user, TTL, limits, read-only nodes, forgetting a user — and an
agent that stores a value in one run and reads it back in the next.
"""

import asyncio
import json


import tools
from helpers import hdr
from services import kv_store, llm_runner
from services.pipeline_runner import RunScope, current_scope


def _call(args, cfg=None, tenant="tenant_demo", project="proj_research", user="alice"):
    """Run the tool as a run's agent would, inside a run scope."""
    async def go():
        token = current_scope.set(RunScope(tenant, project, "user_admin", end_user=user))
        try:
            out = await tools.execute("key_value_store", "", {"namespace": "prefs", **(cfg or {})}, args)
        finally:
            current_scope.reset(token)
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return out
    return asyncio.run(go())


def test_set_get_list_delete():
    assert _call({"action": "set", "key": "lang", "value": {"code": "fr", "tags": [1, 2]}})["stored"] is True
    assert _call({"action": "get", "key": "lang"}) == {"key": "lang", "found": True, "value": {"code": "fr", "tags": [1, 2]}}
    _call({"action": "set", "key": "lang", "value": "de"})
    assert _call({"action": "get", "key": "lang"})["value"] == "de", "set replaces"
    _call({"action": "set", "key": "theme", "value": "dark"})
    _call({"action": "set", "key": "lan_%", "value": 1})
    assert [k["key"] for k in _call({"action": "list"})["keys"]] == ["lan_%", "lang", "theme"]
    assert [k["key"] for k in _call({"action": "list", "prefix": "lan_"})["keys"]] == ["lan_%"], "wildcards are literal"
    assert _call({"action": "delete", "key": "theme"}) == {"key": "theme", "deleted": True}
    assert _call({"action": "get", "key": "theme"})["found"] is False
    assert _call({"action": "delete", "key": "theme"})["deleted"] is False


def test_entries_are_per_user_namespace_and_project():
    _call({"action": "set", "key": "color", "value": "blue"}, user="alice")
    assert _call({"action": "get", "key": "color"}, user="bob")["found"] is False
    assert _call({"action": "get", "key": "color"}, cfg={"namespace": "other"})["found"] is False
    assert _call({"action": "get", "key": "color"}, project="proj_other")["found"] is False
    assert _call({"action": "get", "key": "color"}, tenant="tenant_other")["found"] is False
    assert _call({"action": "get", "key": "color"}, cfg={"scope": "project"})["found"] is False, \
        "shared entries are separate from per-user ones"


def test_shared_scope_and_runs_without_an_end_user():
    assert "no end user" in _call({"action": "get", "key": "x"}, user="")
    _call({"action": "set", "key": "motd", "value": "hi"}, cfg={"scope": "project"}, user="")
    assert _call({"action": "get", "key": "motd"}, cfg={"scope": "project"}, user="bob")["value"] == "hi"


def test_ttl_hides_and_purges_expired_entries(monkeypatch):
    out = _call({"action": "set", "key": "otp", "value": "1234", "ttl_seconds": 60})
    assert out["expires_at"]
    _call({"action": "set", "key": "session", "value": 1}, cfg={"default_ttl_seconds": "30"})
    assert _call({"action": "list", "prefix": "session"})["keys"][0]["expires_at"], "the node's default TTL applies"
    real_ts = kv_store._ts
    monkeypatch.setattr(kv_store, "_ts", lambda dt=None: real_ts(dt) if dt else "9999-01-01T00:00:00.000000Z")
    assert _call({"action": "get", "key": "otp"})["found"] is False
    assert _call({"action": "get", "key": "lang"})["found"] is True, "entries without a TTL never expire"
    assert kv_store.purge_expired() >= 2


def test_limits_and_bad_requests(monkeypatch):
    assert "between 1 and" in _call({"action": "set", "key": "k", "value": 1, "ttl_seconds": 0})
    assert "must be one of" in _call({"action": "drop", "key": "k"})
    assert "key is required" in _call({"action": "get"})
    assert "longer than" in _call({"action": "get", "key": "k" * 500})
    assert "set needs a value" in _call({"action": "set", "key": "k"})
    assert "larger than" in _call({"action": "set", "key": "big", "value": "x" * (kv_store.MAX_VALUE_BYTES + 1)})
    monkeypatch.setattr(kv_store, "MAX_KEYS", 2)
    _call({"action": "set", "key": "a", "value": 1}, user="carol")
    _call({"action": "set", "key": "b", "value": 1}, user="carol")
    assert "already holds 2 keys" in _call({"action": "set", "key": "c", "value": 1}, user="carol")
    assert _call({"action": "set", "key": "a", "value": 2}, user="carol")["stored"] is True, "replacing is allowed"


def test_read_only_store():
    ro = {"access": "read_only"}
    assert "read only" in _call({"action": "set", "key": "lang", "value": "x"}, cfg=ro)
    assert "read only" in _call({"action": "delete", "key": "lang"}, cfg=ro)
    assert _call({"action": "get", "key": "lang"}, cfg=ro)["value"] == "de"


def test_plain_json_input_and_no_scope():
    async def plain(inp):
        token = current_scope.set(RunScope("tenant_demo", "proj_research", "u", end_user="alice"))
        try:
            return await tools.execute("key_value_store", inp, {"namespace": "prefs"})
        finally:
            current_scope.reset(token)
    assert json.loads(asyncio.run(plain('{"action": "get", "key": "lang"}')))["value"] == "de"
    assert "Expected a JSON object" in asyncio.run(plain("what is my language?"))
    assert "outside a project run" in asyncio.run(tools.execute("key_value_store", "", {}, {"action": "list"}))


def test_forgetting_a_user_deletes_their_entries(client):
    r = client.delete("/api/memory/long-term/users/alice", headers=hdr())
    assert r.status_code == 200 and r.json()["store_entries_deleted"] >= 1
    assert _call({"action": "list"})["keys"] == []
    assert _call({"action": "get", "key": "motd"}, cfg={"scope": "project"}, user="bob")["found"] is True, \
        "shared entries stay"


# ── An agent stores a value in one run and reads it in the next ─────────────

class _Delta:
    def __init__(self, arguments):
        self.index, self.id, self.name, self.arguments = 0, "call_1", "store", arguments


class _Chunk:
    def __init__(self, text="", tool_call=None, finish=None):
        self.text, self.thinking_blocks, self.finish_reason = text, [], finish
        self.tool_calls = [tool_call] if tool_call else []


class _Stream:
    usage, cost_usd, backend = None, 0.0, "fake"

    def __init__(self, chunks):
        self._chunks = chunks

    async def __aiter__(self):
        for c in self._chunks:
            yield c


def test_an_agent_remembers_across_runs(client, env):
    def run(arguments):
        calls = []

        async def start(cfg, messages, tools=None, tool_choice=None):
            calls.append({"messages": [dict(m) for m in messages], "tools": tools})
            if len(calls) == 1:
                return _Stream([_Chunk(tool_call=_Delta(json.dumps(arguments)), finish="tool_calls")]), cfg, 1, False
            return _Stream([_Chunk(text="Done.", finish="stop")]), cfg, 1, False
        env.setattr(llm_runner, "_start_stream_with_policy", start)
        client.post("/api/run/stream", headers=hdr(), json={
            "prompt": "Remember my city", "config": {"provider": "openai", "model": "gpt-x", "api_key": "sk-test"},
            "attached_tools": [{"toolId": "key_value_store", "label": "store", "config": {"namespace": "agent"}}]})
        return calls

    calls = run({"action": "set", "key": "city", "value": "Lisbon"})
    assert calls[0]["tools"][0]["function"]["parameters"]["required"] == ["action"]
    calls = run({"action": "get", "key": "city"})
    result = next(m for m in calls[1]["messages"] if m["role"] == "tool")["content"]
    assert json.loads(result) == {"key": "city", "found": True, "value": "Lisbon"}


# ── Inspector: Monitor → Sessions → Store ─────────────────────────────────────

def test_the_inspector_lists_edits_and_deletes_entries(client):
    _call({"action": "set", "key": "plan", "value": {"tier": "pro"}, "ttl_seconds": 3600}, user="dana")
    subjects = client.get("/api/memory/store/subjects", headers=hdr()).json()["subjects"]
    assert subjects[0]["subject"] == "", "shared entries first"
    dana = next(s for s in subjects if s["subject"] == "dana")
    assert dana["entries"] == 1 and dana["namespaces"] == ["prefs"]

    entries = client.get("/api/memory/store/entries", params={"subject": "dana"}, headers=hdr()).json()["entries"]
    assert [(e["namespace"], e["key"], e["value"]) for e in entries] == [("prefs", "plan", {"tier": "pro"})]
    expires = entries[0]["expires_at"]

    r = client.put("/api/memory/store/entries", headers=hdr(),
                   json={"subject": "dana", "namespace": "prefs", "key": "plan", "value": {"tier": "team"}})
    assert r.status_code == 200 and r.json()["expires_at"] == expires, "an edit keeps the expiry"
    assert _call({"action": "get", "key": "plan"}, user="dana")["value"] == {"tier": "team"}
    r = client.put("/api/memory/store/entries", headers=hdr(),
                   json={"namespace": "flags", "key": "beta", "value": True})
    assert r.json()["expires_at"] is None
    assert _call({"action": "get", "key": "beta"}, cfg={"namespace": "flags", "scope": "project"})["value"] is True
    big = {"namespace": "prefs", "key": "big", "value": "x" * (kv_store.MAX_VALUE_BYTES + 1)}
    assert client.put("/api/memory/store/entries", headers=hdr(), json=big).status_code == 400

    params = {"subject": "dana", "namespace": "prefs", "key": "plan"}
    assert client.delete("/api/memory/store/entries", params=params, headers=hdr()).status_code == 200
    assert client.delete("/api/memory/store/entries", params=params, headers=hdr()).status_code == 404
    assert client.get("/api/memory/store/entries", params={"subject": "dana"}, headers=hdr()).json()["entries"] == []


def test_the_inspector_is_scoped_to_the_project(client):
    _call({"action": "set", "key": "lang", "value": "pt"}, user="erin", project="proj_support")
    research = client.get("/api/memory/store/subjects", headers=hdr()).json()["subjects"]
    support = client.get("/api/memory/store/subjects", headers=hdr(project="proj_support")).json()["subjects"]
    assert "erin" not in {s["subject"] for s in research}
    assert [s["subject"] for s in support] == ["erin"]
    r = client.delete("/api/memory/store/entries", params={"subject": "erin", "namespace": "prefs", "key": "lang"},
                      headers=hdr())
    assert r.status_code == 404, "another project's entry can't be deleted"


# ── Exported code: the same store in a local SQLite file ──────────────────────

def test_exported_tool_runs_without_the_platform(tmp_path, monkeypatch):
    from exporters.tool_bodies import tool_body_crewai, tool_body_langchain

    src = tool_body_langchain("store", "key_value_store", "Remembers things.",
                              {"namespace": "prefs", "scope": "user", "default_ttl_seconds": ""}, None)
    ns = {"tool": lambda f: f}
    exec(src, ns)
    store = ns["store"]
    monkeypatch.setenv("KV_STORE_PATH", str(tmp_path / "kv.db"))
    monkeypatch.setenv("KV_STORE_USER", "alice")
    store('{"action": "set", "key": "lang", "value": "en"}')
    assert json.loads(store('{"action": "set", "key": "lang", "value": {"code": "fr"}}'))["stored"] is True
    assert json.loads(store('{"action": "get", "key": "lang"}')) == {"key": "lang", "found": True, "value": {"code": "fr"}}
    store('{"action": "set", "key": "otp", "value": 1, "ttl_seconds": 0.001}')
    assert json.loads(store('{"action": "list", "prefix": "l"}'))["keys"] == ["lang"]
    monkeypatch.setenv("KV_STORE_USER", "bob")
    assert json.loads(store('{"action": "get", "key": "lang"}'))["found"] is False, "per user"
    assert "Expected a JSON object" in store("hello")
    assert "Remembers things." in store.__doc__ and '"action"' in store.__doc__

    ro = {}
    exec(tool_body_langchain("store", "key_value_store", "d", {"access": "read_only", "scope": "project"}, None),
         {"tool": lambda f: f}, ro)
    assert ro["store"]('{"action": "set", "key": "k", "value": 1}') == "This store is read only."
    compile(tool_body_crewai("Store", "store", "key_value_store", "store", "d", {}, None), "crewai", "exec")
