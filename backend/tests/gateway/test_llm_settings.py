"""Settings → Model backends: the API, access rules, project / workspace / env precedence, that
the gateway and the model catalog follow the settings, and the Test call (httpx.MockTransport)."""
import httpx
import pytest

import llm
from helpers import hdr
from models import LLMConfig
from routers import run as run_router
from services import llm_settings, secret_store


@pytest.fixture(scope="module", autouse=True)
def _no_backend_env(env):
    for var in ("LLM_BACKEND", "LLM_BACKEND_OPENAI", "LLM_BACKEND_OLLAMA"):
        env.delenv(var, raising=False)


@pytest.fixture(scope="module")
def api(client):
    class Api:
        def get(self, user="user_admin", project="proj_research"):
            return client.get("/api/llm-settings", headers=hdr(user, project))

        def put(self, pid, user="user_admin", project="proj_research", **body):
            return client.put(f"/api/llm-settings/{pid}", json=body, headers=hdr(user, project))

        def provider(self, pid, project="proj_research"):
            return next(p for p in self.get(project=project).json()["providers"] if p["id"] == pid)

        def migrate(self, user="user_admin", project="proj_research", **params):
            q = "&".join(f"{k}={v}" for k, v in params.items())
            suffix = f"?{q}" if q else ""
            return client.post(f"/api/llm-settings/migrate-litellm{suffix}", headers=hdr(user, project))
    return Api()


def in_scope(project, fn):
    token = secret_store.request_scope.set(("tenant_demo", project))
    try:
        return fn()
    finally:
        secret_store.request_scope.reset(token)


@pytest.fixture
def compat(monkeypatch):
    """The gateway's openai_compat backend, with a settable stand-in transport."""
    backend = next(b for b in llm.backends.BACKENDS if b.id == "openai_compat")
    monkeypatch.setattr(backend, "transport", None)
    return backend


def test_listing(api):
    r = api.get()
    d = r.json()
    assert r.status_code == 200 and d["can_edit"] is True
    ids = [p["id"] for p in d["providers"]]
    assert "openai" in ids and "ollama" in ids and "mock" not in ids
    assert {"litellm", "openai_compat"} <= {b["id"] for b in d["backends"]}
    assert api.provider("ollama")["backends"] == ["openai_compat", "ollama", "litellm"], "auto order: our adapter first"
    assert api.provider("anthropic")["backends"] == ["anthropic", "litellm"], "only backends that can serve it"
    assert api.provider("mistral")["backends"] == ["openai_compat", "mistral", "litellm"]
    assert api.provider("watsonx")["backends"] == ["watsonx", "litellm"]
    assert api.provider("ollama")["local"] and not api.provider("openai")["local"]
    assert api.provider("ollama")["default_base_url"] == "http://localhost:11434"
    assert api.provider("openai")["default_base_url"] == "https://api.openai.com/v1"
    assert api.provider("mistral")["default_base_url"] == "https://api.mistral.ai/v1"
    assert api.provider("perplexity")["default_base_url"] == "https://api.perplexity.ai"
    assert api.provider("watsonx")["default_base_url"].startswith("https://")
    assert next(b["label"] for b in d["backends"] if b["id"] == "watsonx").startswith("Built-in")
    eff = api.provider("openai")["effective"]
    assert eff["backend"] == "auto" and eff["backend_source"] == "default" and eff["serving_backend"] == "openai_compat"


def test_access(api):
    assert api.get("user_viewer", "proj_support").status_code == 403
    assert api.put("openai", "user_viewer", "proj_support", backend="openai_compat").status_code == 403
    assert api.migrate("user_viewer", "proj_support").status_code == 403
    assert api.get("user_analyst").status_code == 200 and api.get("user_analyst").json()["can_edit"] is True


def test_validation(api):
    r = api.put("anthropic", backend="openai_compat")
    assert r.status_code == 400 and "can't serve anthropic" in r.json()["detail"]
    assert api.put("openai", backend="nope").status_code == 400
    assert api.put("ollama", base_url="localhost:11434").status_code == 400
    assert api.put("acme", backend="litellm").status_code == 404


def test_migrate_litellm_overrides(api):
    assert api.put("openai", backend="litellm", scope="project").status_code == 200
    assert api.put("typesafe", backend="litellm", scope="project").status_code == 200
    dry = api.migrate(scope="project", dry_run="true").json()
    assert dry["dry_run"] is True and dry["updated_count"] == 1
    assert dry["updated"][0]["provider"] == "openai" and dry["updated"][0]["serving_backend"] == "openai_compat"
    run = api.migrate(scope="project").json()
    assert run["updated_count"] == 1 and run["updated"][0]["provider"] == "openai"
    assert api.provider("openai")["project"] is None, "auto+no-url removes explicit litellm row"
    assert api.provider("typesafe")["project"]["backend"] == "litellm", "providers without adapters stay unchanged"


def test_precedence(api, client, monkeypatch):
    assert api.put("ollama", base_url="http://gpu-box:11434/", scope="workspace").json()["base_url"] == "http://gpu-box:11434"
    assert api.put("ollama", backend="openai_compat").status_code == 200
    p = api.provider("ollama")
    assert p["project"]["backend"] == "openai_compat" and p["workspace"]["base_url"] == "http://gpu-box:11434"
    eff = p["effective"]
    assert eff["backend"] == "openai_compat" and eff["backend_source"] == "project"
    assert eff["base_url"] == "http://gpu-box:11434" and eff["base_url_source"] == "workspace", "each field on its own"
    assert eff["serving_backend"] == "openai_compat"
    p2 = api.provider("ollama", project="proj_support")
    assert p2["project"] is None and p2["effective"]["backend"] == "auto"
    assert p2["effective"]["base_url"] == "http://gpu-box:11434"
    assert api.put("ollama", base_url="http://laptop:11434").status_code == 200
    assert api.provider("ollama")["effective"]["base_url"] == "http://laptop:11434", "project URL beats workspace"

    monkeypatch.setenv("LLM_BACKEND_OPENAI", "openai_compat")
    eff = api.provider("openai")["effective"]
    assert eff["backend"] == "openai_compat" and eff["backend_source"] == "env:LLM_BACKEND_OPENAI"
    api.put("openai", backend="litellm")
    eff = api.provider("openai")["effective"]
    assert eff["backend"] == "litellm" and eff["backend_source"] == "project", "project beats env"
    api.put("openai", backend="auto", scope="project")
    assert api.provider("openai")["project"] is None, "saving 'auto' with no URL removes the row"
    assert api.provider("openai")["effective"]["backend_source"] == "env:LLM_BACKEND_OPENAI"
    monkeypatch.delenv("LLM_BACKEND_OPENAI")

    r = client.delete("/api/llm-settings/ollama?scope=workspace", headers=hdr())
    p2 = api.provider("ollama", project="proj_support")
    assert r.status_code == 204 and p2["workspace"] is None and p2["effective"]["base_url"] == ""
    assert api.provider("ollama")["project"]["base_url"] == "http://laptop:11434", "project row stays"


def test_gateway_follows_settings(api, monkeypatch):
    monkeypatch.setattr(llm.backends, "ADAPTER_FIRST", set())   # so `auto` (LiteLLM) differs from the setting
    assert in_scope("proj_research", lambda: llm.backend_for("ollama").id) == "openai_compat"
    assert in_scope("proj_support", lambda: llm.backend_for("ollama").id) == "litellm"
    assert llm.backend_for("ollama").id == "litellm", "no scope (e.g. CLI) → default"
    req = llm.LLMRequest(provider="ollama", model="m", messages=[])
    assert in_scope("proj_research", lambda: llm._resolved(req).base_url) == "http://laptop:11434"
    own = llm.LLMRequest(provider="ollama", model="m", messages=[], base_url="http://node:1")
    assert in_scope("proj_research", lambda: llm._resolved(own).base_url) == "http://node:1", "a node's URL wins"
    assert LLMConfig(provider="jan", model="m").base_url in (None, ""), "Jan's address isn't baked in"

    llm_settings.clear_cache()
    queries = {"n": 0}
    real_conn = llm_settings.get_db_connection

    def counting_conn():
        queries["n"] += 1
        return real_conn()

    monkeypatch.setattr(llm_settings, "get_db_connection", counting_conn)
    for _ in range(5):
        in_scope("proj_research", lambda: llm.backend_for("ollama"))
    assert queries["n"] == 1, "settings are cached"
    api.put("ollama", backend="litellm")
    assert in_scope("proj_research", lambda: llm.backend_for("ollama").id) == "litellm", "writes are seen at once"
    monkeypatch.undo()
    api.put("ollama", backend="openai_compat")


def test_catalog_asks_the_configured_server(api, client, monkeypatch):
    seen = {}

    async def fake_ollama(base_url="http://localhost:11434"):
        seen["ollama"] = base_url
        return ["qwen3:latest"]

    monkeypatch.setattr(run_router, "_fetch_ollama_models", fake_ollama)
    models = client.get("/api/models", headers=hdr()).json()
    assert seen["ollama"] == "http://laptop:11434"
    assert next(p for p in models["providers"] if p["id"] == "ollama")["models"] == ["qwen3:latest"]
    api.put("ollama", base_url="http://laptop:11434/v1")
    client.get("/api/models", headers=hdr())
    assert seen["ollama"] == "http://laptop:11434", "no /v1 for Ollama's native API"


def test_test_call(client, compat, monkeypatch):
    async def fake_ollama(base_url="http://localhost:11434"):
        return ["qwen3:latest"]

    monkeypatch.setattr(run_router, "_fetch_ollama_models", fake_ollama)
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 9, "completion_tokens": 1, "total_tokens": 10}})

    compat.transport = httpx.MockTransport(handler)
    r = client.post("/api/llm-settings/ollama/test", json={}, headers=hdr()).json()
    assert r["ok"] and r["backend"] == "openai_compat" and r["model"] == "qwen3:latest"
    assert str(sent[-1].url) == "http://laptop:11434/v1/chat/completions"
    r = client.post("/api/llm-settings/ollama/test", json={"base_url": "http://other:11434"}, headers=hdr()).json()
    assert r["ok"] and str(sent[-1].url) == "http://other:11434/v1/chat/completions", "unsaved base URL"
    assert isinstance(r["latency_ms"], int) and r["message"] == "OK"

    compat.transport = httpx.MockTransport(lambda request: httpx.Response(401, json={"error": {"message": "bad key"}}))
    r = client.post("/api/llm-settings/openai/test", json={"backend": "openai_compat", "model": "gpt-4o"},
                    headers=hdr()).json()
    assert r["ok"] is False and "bad key" in r["message"] and r["backend"] == "openai_compat"
    r = client.post("/api/llm-settings/anthropic/test", json={"backend": "openai_compat"}, headers=hdr())
    assert r.status_code == 200 and r.json()["backend"] == "anthropic", "falls back to an engine that can serve it"
    assert client.post("/api/llm-settings/openai/test", json={},
                       headers=hdr("user_viewer", "proj_support")).status_code == 403
