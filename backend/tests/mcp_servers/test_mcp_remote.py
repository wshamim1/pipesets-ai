"""
Remote MCP servers (tools/mcp/_http.py) over real HTTP: Streamable HTTP with JSON and SSE replies,
session ids and paging, falling back to the legacy HTTP+SSE transport, 401s, the SSRF guard, and
our own /v1/mcp as a real server. Custom servers saved with transport "http" run through it.
"""

import asyncio
import json

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

import main
from helpers import hdr, serve
from tools.mcp._http import MCPAuthRequired, MCPRemoteError, call_remote, discover_remote

TOOLS = [{"name": "add", "description": "Add two numbers",
          "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}}},
         {"name": "shout", "inputSchema": {"properties": {"text": {"type": "string"}}}}]

seen = {"sessions": [], "deleted": [], "versions": []}


def _result(msg):
    if msg["method"] == "initialize":
        return {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake"}}
    if msg["method"] == "tools/list":   # two pages
        cursor = (msg.get("params") or {}).get("cursor")
        return {"tools": TOOLS[1:]} if cursor else {"tools": TOOLS[:1], "nextCursor": "p2"}
    name, args = msg["params"]["name"], msg["params"]["arguments"]
    return {"content": [{"type": "text", "text": str(args["a"] + args["b"]) if name == "add" else args["text"].upper()}]}


def _sse(*messages):
    return "".join(f"event: message\ndata: {json.dumps(m)}\n\n" for m in messages)


async def streamable(request):
    if request.method == "DELETE":
        seen["deleted"].append(request.headers.get("mcp-session-id"))
        return Response(status_code=200)
    msg = await request.json()
    if msg["method"] == "initialize":
        return JSONResponse({"jsonrpc": "2.0", "id": msg["id"], "result": _result(msg)},
                            headers={"Mcp-Session-Id": "sess-1"})
    seen["sessions"].append(request.headers.get("mcp-session-id"))
    seen["versions"].append(request.headers.get("mcp-protocol-version"))
    if request.headers.get("mcp-session-id") != "sess-1":
        return Response(status_code=400)
    if "id" not in msg:
        return Response(status_code=202)
    # a progress notification first, then the reply — as an SSE stream
    note = {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 1}}
    return Response(_sse(note, {"jsonrpc": "2.0", "id": msg["id"], "result": _result(msg)}),
                    media_type="text/event-stream")


queues = {}


async def legacy_stream(request):
    if request.method == "POST":   # not a Streamable HTTP endpoint
        return Response(status_code=405)
    q = queues.setdefault("s1", asyncio.Queue())

    async def events():
        yield "event: endpoint\ndata: /legacy/messages?session=s1\n\n"
        while True:
            yield _sse(await q.get())
    return StreamingResponse(events(), media_type="text/event-stream")


async def legacy_messages(request):
    msg = await request.json()
    if "id" in msg:
        await queues[request.query_params["session"]].put({"jsonrpc": "2.0", "id": msg["id"], "result": _result(msg)})
    return Response(status_code=202)


async def needs_auth(request):
    return Response(status_code=401, headers={"WWW-Authenticate": 'Bearer resource_metadata="https://x/.well-known"'})


fake = Starlette(routes=[Route("/mcp", streamable, methods=["POST", "DELETE"]),
                         Route("/legacy/sse", legacy_stream, methods=["GET", "POST"]),
                         Route("/legacy/messages", legacy_messages, methods=["POST"]),
                         Route("/auth", needs_auth, methods=["POST", "GET"])])
fake.mount("/app", main.app)


@pytest.fixture(scope="module")
def base():
    yield from serve(fake)


@pytest.fixture(autouse=True)
def allow_local(env):
    env.setenv("EXTERNAL_AGENT_ALLOW_PRIVATE", "1")


def test_streamable_http_lists_every_page_and_calls_a_tool(base):
    listed = asyncio.run(discover_remote(f"{base}/mcp"))
    assert [t["name"] for t in listed] == ["add", "shout"], "both tools/list pages"
    assert asyncio.run(call_remote("t", f"{base}/mcp", {}, "http", "add", {"a": 2, "b": 3})) == "5"
    assert set(seen["sessions"]) == {"sess-1"}, "the session id goes with every request after initialize"
    assert set(seen["versions"]) == {"2025-06-18"}, "and the negotiated protocol version"
    assert seen["deleted"] and seen["deleted"][-1] == "sess-1", "the session is closed afterwards"


def test_an_endpoint_that_refuses_the_post_falls_back_to_legacy_sse(base):
    assert [t["name"] for t in asyncio.run(discover_remote(f"{base}/legacy/sse", transport="http"))] == ["add", "shout"]
    assert asyncio.run(call_remote("t", f"{base}/legacy/sse", {}, "sse", "shout", {"text": "hi"})) == "HI"


def test_a_401_asks_for_authorization(base):
    with pytest.raises(MCPAuthRequired) as e:
        asyncio.run(discover_remote(f"{base}/auth"))
    assert "resource_metadata" in e.value.www_authenticate
    assert "requires authorization" in asyncio.run(call_remote("t", f"{base}/auth", {}, "http", "add", {}))


def test_private_addresses_are_blocked_by_default(base, env):
    env.setenv("EXTERNAL_AGENT_ALLOW_PRIVATE", "0")
    with pytest.raises(MCPRemoteError, match="non-public"):
        asyncio.run(discover_remote(f"{base}/mcp"))


def test_our_own_v1_mcp_is_a_server_it_can_use(base):
    from services import api_keys
    from services.request_context import RequestContext
    key, _ = api_keys.create_key(RequestContext(tenant_id="tenant_demo", project_id="proj_research",
                                                user_id="user_admin"), "remote client")
    listed = asyncio.run(discover_remote(f"{base}/app/v1/mcp", {"Authorization": f"Bearer {key}"}))
    assert "list_apps" in [t["name"] for t in listed]
    out = asyncio.run(call_remote("t", f"{base}/app/v1/mcp", {"Authorization": f"Bearer {key}"}, "http",
                                  "list_apps", {}))
    assert not out.startswith("[t]"), out


def test_a_saved_http_server_discovers_and_runs(client, base):
    r = client.post("/api/custom-mcp", headers=hdr(), json={"name": "calc", "transport": "http", "url": f"{base}/mcp"})
    assert [t["name"] for t in r.json()["tools_cache"]] == ["add", "shout"]
    out = client.post(f"/api/custom-mcp/{r.json()['id']}/execute", headers=hdr(),
                      json={"tool_name": "add", "arguments": {"a": 4, "b": 5}}).json()
    assert out["output"] == "9"


def test_testing_a_connection_needs_write_access(client, base):
    assert client.post("/api/custom-mcp/test", headers=hdr("user_viewer", project="proj_support"),
                       json={"transport": "stdio", "command": "echo"}).status_code == 403
    ok = client.post("/api/custom-mcp/test", headers=hdr(), json={"transport": "http", "url": f"{base}/mcp"}).json()
    assert ok["success"] and ok["tool_count"] == 2
