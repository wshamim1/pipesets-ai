"""
Typed custom tools and versions (C6 step 1): the parameter schema read from code, versions and
rollback, the model calling a tool with real arguments, and /v1/tools for deploying from code.
Tools run for real in the local sandbox (on the backend's Python).
"""

import json

import pytest

from helpers import hdr
from services import api_keys, llm_runner
from services.request_context import RequestContext
from services.tool_signature import ToolCodeError, analyze, validate_args

WEATHER = '''
from typing import Literal
from pipesets import tool

@tool(description="Current weather for a city", secrets=["weather_token"])
def weather(city: str, units: Literal["metric", "imperial"] = "metric", *, config) -> dict:
    """Weather.

    Args:
        city: City name, e.g. Berlin
    """
    return {"city": city, "units": units, "token_set": bool(config.get("weather_token"))}
'''

LEGACY = "def run(input_text, config):\n    return 'legacy got ' + input_text\n"


# ── Signatures ────────────────────────────────────────────────────────────────

def test_the_schema_comes_from_the_signature():
    sig = analyze(WEATHER)
    assert (sig.entrypoint, sig.legacy, sig.takes_config, sig.secrets) == ("weather", False, True, ["weather_token"])
    assert sig.parameters == {
        "type": "object", "additionalProperties": False, "required": ["city"],
        "properties": {"city": {"type": "string", "description": "City name, e.g. Berlin"},
                       "units": {"enum": ["metric", "imperial"], "type": "string", "default": "metric"}}}
    assert sig.description == "Current weather for a city"
    assert analyze(LEGACY).legacy and analyze(LEGACY).parameters["required"] == ["input"]
    plain = analyze("def run(query: str, limit: int = 3):\n    return query\n")
    assert not plain.legacy and plain.parameters["required"] == ["query"] and not plain.takes_config


@pytest.mark.parametrize("code, why", [
    ("def helper(): pass", "@tool"),
    ("def run(*args): pass", "args"),
    ("async def run(q: str): pass", "async"),
    ("from pipesets import tool\n@tool\ndef a(x: str): pass\n@tool\ndef b(y: str): pass", "One @tool"),
    ("from pipesets import tool\nX = ['a']\n@tool(secrets=X)\ndef a(x: str): pass", "literal"),
    ("def run(x:", "Syntax error"),
])
def test_code_that_cant_be_a_tool_says_why(code, why):
    with pytest.raises(ToolCodeError, match=why):
        analyze(code)


def test_arguments_are_checked_against_the_schema():
    params = analyze(WEATHER).parameters
    assert validate_args(params, {"city": "Oslo"}) is None
    assert validate_args(params, {}) == "missing city"
    assert "must be one of" in validate_args(params, {"city": "Oslo", "units": "kelvin"})
    assert "unknown argument" in validate_args(params, {"city": "Oslo", "country": "NO"})
    assert validate_args(params, {"city": 3}) == "city must be string"


# ── Versions through the UI routes ────────────────────────────────────────────

@pytest.fixture(scope="module")
def tool(client):
    r = client.post("/api/custom-tools", headers=hdr(), json={"name": "weather", "code": WEATHER})
    assert r.status_code == 201, r.text
    return r.json()


def test_saving_creates_versions_only_when_content_changes(client, tool):
    assert tool["version"] == 1 and tool["parameters"]["required"] == ["city"]
    assert tool["config_keys"] == ["weather_token"], "@tool(secrets=...) become config keys"
    same = client.put(f"/api/custom-tools/{tool['id']}", headers=hdr(), json={"icon": "☀️"}).json()
    assert same["version"] == 1, "no content change, no version"
    v2 = client.put(f"/api/custom-tools/{tool['id']}", headers=hdr(),
                    json={"code": WEATHER.replace('"metric", "imperial"', '"metric", "imperial", "kelvin"')}).json()
    assert v2["version"] == 2 and "kelvin" in v2["parameters"]["properties"]["units"]["enum"]
    rolled = client.post(f"/api/custom-tools/{tool['id']}/rollback", headers=hdr(), json={"version": 1}).json()
    assert rolled["version"] == 3 and "kelvin" not in rolled["parameters"]["properties"]["units"]["enum"]
    versions = client.get(f"/api/custom-tools/{tool['id']}/versions", headers=hdr()).json()
    assert versions["current"] == 3 and [v["version"] for v in versions["versions"]] == [3, 2, 1]
    assert versions["versions"][0]["note"] == "Rollback to v1"
    assert "kelvin" in client.get(f"/api/custom-tools/{tool['id']}/versions/2", headers=hdr()).json()["code"]


def test_code_that_cant_be_a_tool_is_refused(client):
    r = client.post("/api/custom-tools", headers=hdr(), json={"name": "broken", "code": "def helper(): pass"})
    assert r.status_code == 422 and "@tool" in r.json()["detail"]
    assert client.post("/api/custom-tools/signature", headers=hdr(), json={"code": WEATHER}).json()["entrypoint"] == "weather"


def test_typed_tools_run_with_arguments(client, tool):
    r = client.post(f"/api/custom-tools/{tool['id']}/execute", headers=hdr(),
                    json={"args": {"city": "Oslo"}, "config": {"weather_token": "t"}}).json()
    assert r["success"], r
    assert json.loads(r["output"]) == {"city": "Oslo", "units": "metric", "token_set": True}, "dicts come back as JSON"
    bad = client.post(f"/api/custom-tools/{tool['id']}/execute", headers=hdr(), json={"args": {"units": "metric"}}).json()
    assert not bad["success"] and "missing city" in bad["output"]
    text = client.post(f"/api/custom-tools/{tool['id']}/execute", headers=hdr(), json={"input_text": "Lima"}).json()
    assert json.loads(text["output"])["city"] == "Lima", "plain text goes to the one required parameter"


def test_legacy_tools_still_work(client):
    legacy = client.post("/api/custom-tools", headers=hdr(), json={"name": "legacy", "code": LEGACY}).json()
    r = client.post(f"/api/custom-tools/{legacy['id']}/execute", headers=hdr(), json={"input_text": "hi"}).json()
    assert r == {"success": True, "output": "legacy got hi", "tool_id": legacy["id"]}


# ── The model calls typed tools with real arguments ───────────────────────────

class _Delta:
    def __init__(self, name, arguments):
        self.index, self.id, self.name, self.arguments = 0, "call_1", name, arguments


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


@pytest.fixture
def model(env):
    calls = []

    async def start(cfg, messages, tools=None, tool_choice=None):
        calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        if len(calls) == 1:   # first step: call the tool
            return _Stream([_Chunk(tool_call=_Delta("weather", json.dumps({"city": "Oslo", "units": "imperial"})),
                                   finish="tool_calls")]), cfg, 1, False
        return _Stream([_Chunk(text="It's mild.", finish="stop")]), cfg, 1, False
    env.setattr(llm_runner, "_start_stream_with_policy", start)
    return calls


def _stream_run(client, tool_id, config=None, project="proj_research"):
    body = {"prompt": "Weather in Oslo?", "config": {"provider": "openai", "model": "gpt-x", "api_key": "sk-test"},
            "attached_tools": [{"toolId": f"custom_{tool_id}", "label": "weather", "config": config or {}}]}
    r = client.post("/api/run/stream", headers=hdr(project=project), json=body)
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


def test_the_model_gets_the_schema_and_calls_with_arguments(client, tool, model):
    events = _stream_run(client, tool["id"])
    fn = model[0]["tools"][0]["function"]
    assert fn["name"] == "weather" and fn["parameters"]["required"] == ["city"], "a real function definition"
    tool_result = next(m for m in model[1]["messages"] if m["role"] == "tool")["content"]
    assert json.loads(tool_result) == {"city": "Oslo", "units": "imperial", "token_set": False}
    assert next(e for e in events if e["type"] == "tool_call")["input"] == '{"city": "Oslo", "units": "imperial"}'


def test_a_node_can_pin_a_version(client, tool, model):
    _stream_run(client, tool["id"], {"tool_version": 2})
    assert "kelvin" in model[0]["tools"][0]["function"]["parameters"]["properties"]["units"]["enum"]


def test_another_projects_tool_is_not_found(client, tool, model):
    _stream_run(client, tool["id"], project="proj_support")
    assert model[0]["tools"][0]["function"]["parameters"]["required"] == ["input"], "not looked up: no schema"
    result = next(m for m in model[1]["messages"] if m["role"] == "tool")["content"]
    assert result.startswith("[Custom tool not found"), result


# ── /v1/tools: deploying from code ────────────────────────────────────────────

def _key(scopes):
    plaintext, _ = api_keys.create_key(RequestContext(tenant_id="tenant_demo", project_id="proj_research",
                                                      user_id="user_admin"), "tools", scopes, rate_limit_rpm=0)
    return {"Authorization": f"Bearer {plaintext}"}


GREET = "from pipesets import tool\n\n@tool\ndef greet(name: str) -> str:\n    return f'hello {name}'\n"


def test_deploy_is_an_idempotent_upsert_by_name(client):
    key = _key(["tools:read", "tools:write", "tools:execute"])
    first = client.put("/v1/tools/greet", headers=key, json={"code": GREET, "note": "abc123"}).json()
    assert first["created"] and first["changed"] and first["version"] == 1 and first["source"] == "sdk"
    again = client.put("/v1/tools/greet", headers=key, json={"code": GREET}).json()
    assert not again["created"] and not again["changed"] and again["version"] == 1
    v2 = client.put("/v1/tools/greet", headers=key, json={"code": GREET.replace("hello", "hi")}).json()
    assert v2["changed"] and v2["version"] == 2

    run = client.post("/v1/tools/greet/run", headers=key, json={"args": {"name": "Ada"}}).json()
    assert run["ok"] and run["output"] == "hi Ada" and run["version"] == 2
    old = client.post("/v1/tools/greet/run", headers=key, json={"args": {"name": "Ada"}, "version": 1}).json()
    assert old["output"] == "hello Ada"
    assert [v["version"] for v in client.get("/v1/tools/greet/versions", headers=key).json()["data"]] == [2, 1]
    assert client.get("/v1/tools/greet/versions/1", headers=key).json()["note"] == "abc123"
    assert client.post("/v1/tools/greet/rollback", headers=key, json={"version": 1}).json()["version"] == 3
    assert "greet" in {t["name"] for t in client.get("/v1/tools", headers=key).json()["data"]}

    ui = client.get("/api/custom-tools", headers=hdr()).json()["tools"]
    deployed = next(t for t in ui if t["name"] == "greet")
    assert deployed["read_only"]
    assert client.put(f"/api/custom-tools/{deployed['id']}", headers=hdr(), json={"code": GREET}).status_code == 409
    fork = client.post(f"/api/custom-tools/{deployed['id']}/fork", headers=hdr()).json()
    assert fork["name"] == "greet (fork)" and not fork["read_only"] and fork["version"] == 1


def test_deploy_refuses_bad_code_and_needs_its_scope(client):
    key = _key(["tools:read", "tools:write"])
    r = client.put("/v1/tools/nope", headers=key, json={"code": "x = 1"})
    assert r.status_code == 422
    assert client.post("/v1/tools/greet/run", headers=key, json={"args": {"name": "x"}}).status_code == 403
    read_only = _key(["tools:read"])
    assert client.put("/v1/tools/greet", headers=read_only, json={"code": GREET}).status_code == 403
    default = _key(None)
    assert client.get("/v1/tools", headers=default).status_code == 403, "not in a key's default scopes"

    from db import get_db_connection
    conn = get_db_connection()
    try:
        actions = [r["action"] for r in conn.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'custom_tool.%' AND method = 'PUT'")]
    finally:
        conn.close()
    assert actions.count("custom_tool.deploy") == 2 and "custom_tool.rollback" in actions, "unchanged deploys aren't logged"
