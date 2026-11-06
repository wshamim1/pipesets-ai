"""
MCP server nodes with typed tools: discovery (tools/list) through the real stdio runner against a
small MCP server, each discovered tool offered to the model as its own function, arguments going
straight to tools/call, and custom servers looked up in the run's project only.
"""

import asyncio
import json
import sys
import textwrap

import pytest

import tools
from helpers import hdr
from services import llm_runner
from tools.mcp._stdio import stdio_server

SERVER = textwrap.dedent('''
    import json, sys
    TOOLS = [{"name": "add", "description": "Add two numbers",
              "inputSchema": {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object",
                              "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]}},
             {"name": "shout", "description": "Upper-case text", "inputSchema": {"properties": {"text": {"type": "string"}}}}]
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg:
            continue
        if msg["method"] == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "t"}}
        elif msg["method"] == "tools/list":
            result = {"tools": TOOLS}
        else:
            name, args = msg["params"]["name"], msg["params"]["arguments"]
            text = str(args["a"] + args["b"]) if name == "add" else args["text"].upper()
            result = {"content": [{"type": "text", "text": text}]}
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
''')


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    path = tmp_path_factory.mktemp("mcp") / "server.py"
    path.write_text(SERVER)
    return stdio_server(sys.executable, [str(path)], "add")


def test_discovery_lists_the_servers_tools(server):
    listed = asyncio.run(server.discover({}, "mcp_test"))
    assert [t["name"] for t in listed] == ["add", "shout"]
    assert listed[0]["inputSchema"]["required"] == ["a", "b"]


def test_a_call_sets_the_tool_and_its_arguments(server):
    assert asyncio.run(server("", {"tool_name": "add", "arguments": {"a": 2, "b": 3}}, "mcp_test")) == "5"
    assert asyncio.run(server("", {"tool_name": "shout", "arguments": {"text": "hi"}}, "mcp_test")) == "HI"


def test_schemas_become_plain_object_parameters():
    assert llm_runner._mcp_schema({"$schema": "x", "properties": {"t": {}}}) == {"type": "object", "properties": {"t": {}}}
    assert llm_runner._mcp_schema(None) == {"type": "object", "properties": {}}


# ── The model calls each MCP tool with arguments ──────────────────────────────

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
def run(client, env, server):
    """POST /api/run/stream with one MCP node; the model calls ``call`` with ``args``."""
    def go(node, call, args, project="proj_research"):
        calls = []

        async def start(cfg, messages, tools=None, tool_choice=None):
            calls.append({"messages": [dict(m) for m in messages], "tools": tools})
            if len(calls) == 1:
                return _Stream([_Chunk(tool_call=_Delta(call, json.dumps(args)), finish="tool_calls")]), cfg, 1, False
            return _Stream([_Chunk(text="Done.", finish="stop")]), cfg, 1, False
        env.setattr(llm_runner, "_start_stream_with_policy", start)
        tools._load()   # before patching, or the first load would put the real runner back
        env.setitem(tools._runners, "mcp_fetch", server)   # the test server stands in for a built-in MCP server
        client.post("/api/run/stream", headers=hdr(project=project), json={
            "prompt": "Add 2 and 3", "config": {"provider": "openai", "model": "gpt-x", "api_key": "sk-test"},
            "attached_tools": [node]})
        return calls
    return go


LISTED = [{"name": "add", "description": "Add two numbers",
           "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}}},
          {"name": "shout", "inputSchema": {"properties": {"text": {"type": "string"}}}}]


def test_each_stored_mcp_tool_is_a_function(run):
    calls = run({"toolId": "mcp_fetch", "toolType": "mcp", "label": "calc", "config": {"mcp_tools": LISTED}},
                "calc__add", {"a": 2, "b": 3})
    names = [t["function"]["name"] for t in calls[0]["tools"]]
    assert names == ["calc__add", "calc__shout"], "one function per MCP tool, no generic 'input' one"
    assert calls[0]["tools"][0]["function"]["parameters"]["properties"]["a"] == {"type": "number"}
    assert next(m for m in calls[1]["messages"] if m["role"] == "tool")["content"] == "5"


def test_a_node_without_stored_tools_keeps_one_input(run):
    calls = run({"toolId": "mcp_fetch", "toolType": "mcp", "label": "calc", "config": {}}, "calc", {"input": "x"})
    assert [t["function"]["name"] for t in calls[0]["tools"]] == ["calc"]
    assert calls[0]["tools"][0]["function"]["parameters"]["required"] == ["input"]


def test_custom_servers_offer_their_discovered_tools_in_their_project_only(client, run):
    from db import get_db_connection
    conn = get_db_connection()
    conn.execute("INSERT INTO custom_mcp_servers (id, tenant_id, project_id, owner_user_id, name, icon, description, "
                 "transport, command, args, env_vars, url, headers, tools_cache, created_at, updated_at) VALUES "
                 "('custom_mcp_t1', 'tenant_demo', 'proj_research', 'user_admin', 'calc', '🔌', '', 'stdio', 'none', "
                 "'[]', '{}', '', '{}', ?, 'x', 'x')", (json.dumps(LISTED),))
    conn.commit()
    conn.close()
    node = {"toolId": "custom_mcp_t1", "toolType": "mcp", "label": "mine", "config": {}}
    calls = run(node, "mine__add", {"a": 1, "b": 1})
    assert [t["function"]["name"] for t in calls[0]["tools"]] == ["mine__add", "mine__shout"]
    other = run(node, "mine", {"input": "x"}, project="proj_support")
    assert [t["function"]["name"] for t in other[0]["tools"]] == ["mine"], "another project's server isn't found"
    result = next(m for m in other[1]["messages"] if m["role"] == "tool")["content"]
    assert "not found" in result


def test_the_discover_endpoint(client, env, server):
    tools._load()
    env.setitem(tools._runners, "mcp_fetch", server)
    r = client.post("/api/tools/discover", headers=hdr(), json={"tool_type": "mcp_fetch", "config": {}})
    assert r.status_code == 200 and [t["name"] for t in r.json()["tools"]] == ["add", "shout"]
    assert client.post("/api/tools/discover", headers=hdr(), json={"tool_type": "calculator"}).status_code == 404
    assert client.post("/api/tools/discover", headers=hdr("user_viewer", project="proj_support"),
                       json={"tool_type": "mcp_fetch"}).status_code == 403
