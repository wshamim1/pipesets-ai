"""
Typed parameters for built-in tools (tools/base.py ToolSpec.parameters): the schemas are well formed
and never let the model set credentials or endpoints, arguments map to the tool's input and config,
and the model gets them as real function definitions.
"""

import asyncio
import json

import pytest

import tools
from services import llm_runner

tools._load()
TYPED = sorted(i for i, spec in tools._specs.items() if spec.parameters)
# Node settings the model must never choose: arguments override config keys of the same name
NEVER_ARGUMENTS = {
    # credentials
    "api_key", "token", "github_token", "api_token", "access_token", "auth_token", "bot_token", "password", "app_id",
    "aws_access_key_id", "aws_secret_access_key", "account_sid", "routing_key",
    # endpoints and connections
    "base_url", "api_base", "connection_string", "dsn", "headers", "method", "webhook_url", "server", "smtp_host",
    "smtp_port", "subdomain", "region", "bucket",
    # recipients and destinations: the model can write a message, not choose who gets it
    "to_address", "from_address", "to_number", "from_number", "chat_id", "channel", "topic", "email", "username",
    "project_key", "space_key", "parent_page_id", "dedup_key", "team_key", "list_id", "board_id", "base_id", "table",
    # sandboxing and files
    "read_only", "allowed_dir", "allowed_commands", "output_dir", "file_name",
}


def test_the_most_used_tools_are_typed():
    untyped = [i for i, spec in tools._specs.items()
               if not spec.parameters and not spec.hidden and spec.type == "tool" and spec.category]
    assert untyped == [], f"every built-in tool (not MCP servers or frameworks) has typed parameters: {untyped}"


@pytest.mark.parametrize("tool_id", TYPED)
def test_schemas_are_well_formed_and_safe(tool_id):
    spec = tools.get_spec(tool_id)
    p = spec.parameters
    props = p["properties"]
    assert p["type"] == "object" and p["additionalProperties"] is False
    assert set(p.get("required", [])) <= set(props)
    assert spec.to_input or spec.input_param in props or spec.input_param == "", \
        "the input comes from an argument (or the tool takes none, like the password generator)"
    assert not set(props) & NEVER_ARGUMENTS, f"{tool_id} lets the model set {set(props) & NEVER_ARGUMENTS}"
    assert tools.get_spec(tool_id).catalog_entry()["parameters"] == p, "the catalog shows the schema"


def test_arguments_become_the_input_and_config_overrides():
    weather = tools.get_spec("weather")
    assert weather.call_input({"city": "Oslo", "units": "imperial"}) == ("Oslo", {"units": "imperial"})
    assert tools.get_spec("currency_converter").call_input(
        {"amount": 100, "from_currency": "USD", "to_currency": "EUR"}) == ("100 USD to EUR", {})
    assert tools.get_spec("datetime_tool").call_input({}) == ("", {}), "optional input left out"


def test_json_tools_get_their_arguments_as_json():
    assert tools.get_spec("text_diff").call_input({"before": "a", "after": "b"}) == ('{"before": "a", "after": "b"}', {})
    assert tools.get_spec("json_transformer").call_input({"data": {"x": [1]}, "filter": ".x"}) == ('{"x": [1]}', {"filter": ".x"})
    assert tools.get_spec("json_schema_validator").call_input({"data": 3})[0] == "3"
    assert tools.get_spec("statistics_tool").call_input({"numbers": [1, 2.5]})[0] == "1, 2.5"
    assert tools.get_spec("public_holidays").call_input({"country": "US"})[0] == "US"
    assert asyncio.run(tools.execute("text_diff", "", {}, {"before": "a\n", "after": "b\n"})).count("-a") == 1
    assert "2.5" in asyncio.run(tools.execute("statistics_tool", "", {}, {"numbers": [1, 2.5, 4]}))


def test_more_general_tools_are_registered():
    assert tools.get_spec("json_formatter") is not None
    assert tools.get_spec("url_fetcher") is not None
    assert tools.get_spec("markdown_to_html") is not None
    assert tools.get_spec("slugify_tool") is not None
    assert tools.get_spec("databricks_sql") is not None
    assert tools.get_spec("databricks_cluster_status") is not None
    assert tools.get_spec("databricks_job_status") is not None
    assert tools.get_spec("databricks_workspace_files") is not None
    assert tools.get_spec("databricks_job_runs") is not None
    assert tools.get_spec("databricks_notebook_status") is not None
    assert tools.get_spec("databricks_notebook_run") is not None
    assert tools.get_spec("databricks_job_logs") is not None
    assert tools.get_spec("databricks_cluster_logs") is not None
    assert tools.get_spec("databricks_cluster_events") is not None
    assert tools.get_spec("json_formatter").parameters["required"] == ["json_text"]
    assert tools.get_spec("url_fetcher").parameters["required"] == ["url"]
    assert tools.get_spec("markdown_to_html").parameters["required"] == ["markdown"]
    assert tools.get_spec("slugify_tool").parameters["required"] == ["text"]
    assert tools.get_spec("databricks_sql").parameters["required"] == ["query"]
    assert tools.get_spec("databricks_cluster_status").parameters["required"] == ["cluster_id"]
    assert tools.get_spec("databricks_job_status").parameters["required"] == ["job_id"]
    assert tools.get_spec("databricks_workspace_files").parameters["required"] == ["path"]
    assert tools.get_spec("databricks_job_runs").parameters["required"] == ["job_id"]
    assert tools.get_spec("databricks_notebook_status").parameters["required"] == ["path"]
    assert tools.get_spec("databricks_notebook_run").parameters["required"] == ["path"]
    assert tools.get_spec("databricks_job_logs").parameters["required"] == ["run_id"]
    assert tools.get_spec("databricks_cluster_logs").parameters["required"] == ["cluster_id"]
    assert tools.get_spec("databricks_cluster_events").parameters["required"] == ["cluster_id"]


def test_execute_validates_then_runs():
    assert asyncio.run(tools.execute("calculator", "", {}, {"expression": "(2 + 3) * 4"})) == "(2 + 3) * 4 = 20"
    assert "missing expression" in asyncio.run(tools.execute("calculator", "", {}, {}))
    sneaky = asyncio.run(tools.execute("web_search", "", {}, {"query": "x", "api_key": "mine"}))
    assert "unknown argument" in sneaky, "undeclared arguments never reach the config"
    assert "between 1 and 20" in asyncio.run(tools.execute("web_search", "", {}, {"query": "x", "max_results": 500}))
    assert asyncio.run(tools.execute("calculator", "1 + 1", {})) == "1 + 1 = 2", "plain input still works"


# ── The model calls built-ins with real arguments ─────────────────────────────

class _Delta:
    def __init__(self, arguments):
        self.index, self.id, self.name, self.arguments = 0, "call_1", "calculator", arguments


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


def _run(client, env, arguments):
    calls = []

    async def start(cfg, messages, tools=None, tool_choice=None):
        calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        if len(calls) == 1:
            return _Stream([_Chunk(tool_call=_Delta(json.dumps(arguments)), finish="tool_calls")]), cfg, 1, False
        return _Stream([_Chunk(text="Done.", finish="stop")]), cfg, 1, False
    env.setattr(llm_runner, "_start_stream_with_policy", start)
    from helpers import hdr
    r = client.post("/api/run/stream", headers=hdr(), json={
        "prompt": "What is 6 * 7?", "config": {"provider": "openai", "model": "gpt-x", "api_key": "sk-test"},
        "attached_tools": [{"toolId": "calculator", "label": "calculator", "config": {}}]})
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    return calls, events


def test_the_model_gets_the_schema_and_calls_with_arguments(client, env):
    calls, events = _run(client, env, {"expression": "6 * 7"})
    fn = calls[0]["tools"][0]["function"]
    assert fn["parameters"]["required"] == ["expression"]
    assert next(m for m in calls[1]["messages"] if m["role"] == "tool")["content"] == "6 * 7 = 42"
    assert next(e for e in events if e["type"] == "tool_call")["input"] == '{"expression": "6 * 7"}'


def test_the_old_single_input_call_still_works(client, env):
    calls, _ = _run(client, env, {"input": "6 * 7"})
    assert next(m for m in calls[1]["messages"] if m["role"] == "tool")["content"] == "6 * 7 = 42"
