"""
OAuth sign-in for remote custom MCP servers (services/mcp_oauth.py) against a fake protected MCP
server and authorization server over real HTTP: discovery from the 401, dynamic registration,
PKCE, the single-use callback, tokens kept out of API responses, refresh on 401, and tokens
dropped when the server's URL changes.
"""

import base64
import hashlib
import json
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from helpers import hdr, serve
from services import mcp_oauth

AS = {"codes": {}, "valid": set(), "registered": [], "refreshes": 0}
BASE = {}


def _challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


async def protected_mcp(request):
    token = request.headers.get("authorization", "").removeprefix("Bearer ")
    if token not in AS["valid"]:
        meta = f"{BASE['url']}/.well-known/oauth-protected-resource/mcp"
        return Response(status_code=401, headers={"WWW-Authenticate": f'Bearer resource_metadata="{meta}"'})
    if request.method == "DELETE":
        return Response(status_code=200)
    msg = await request.json()
    if "id" not in msg:
        return Response(status_code=202)
    if msg["method"] == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "p"}}
    elif msg["method"] == "tools/list":
        result = {"tools": [{"name": "whoami", "inputSchema": {"type": "object"}}]}
    else:
        result = {"content": [{"type": "text", "text": f"token {token}"}]}
    return JSONResponse({"jsonrpc": "2.0", "id": msg["id"], "result": result})


async def resource_metadata(request):
    return JSONResponse({"resource": f"{BASE['url']}/mcp", "authorization_servers": [f"{BASE['url']}/as"],
                         "scopes_supported": ["mcp:read", "mcp:write"]})


async def as_metadata(request):
    b = f"{BASE['url']}/as"
    return JSONResponse({"issuer": b, "authorization_endpoint": f"{b}/authorize", "token_endpoint": f"{b}/token",
                         "registration_endpoint": f"{b}/register", "code_challenge_methods_supported": ["S256"]})


async def register(request):
    body = await request.json()
    AS["registered"].append(body)
    return JSONResponse({"client_id": "cid-1", "redirect_uris": body["redirect_uris"]}, status_code=201)


async def token(request):
    form = dict(await request.form())
    assert form["resource"] == f"{BASE['url']}/mcp", "the resource indicator goes with every token request"
    if form["grant_type"] == "authorization_code":
        issued = AS["codes"].pop(form["code"], None)
        if not issued or _challenge(form["code_verifier"]) != issued["challenge"] or form["client_id"] != "cid-1":
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        AS["valid"].add("at-1")
        return JSONResponse({"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600, "token_type": "Bearer"})
    if form["grant_type"] == "refresh_token" and form["refresh_token"] == "rt-1":
        AS["refreshes"] += 1
        AS["valid"].add("at-2")
        return JSONResponse({"access_token": "at-2", "expires_in": 3600, "token_type": "Bearer"})
    return JSONResponse({"error": "invalid_grant"}, status_code=400)


fake = Starlette(routes=[
    Route("/mcp", protected_mcp, methods=["POST", "DELETE"]),
    Route("/.well-known/oauth-protected-resource/mcp", resource_metadata),
    Route("/.well-known/oauth-authorization-server/as", as_metadata),
    Route("/as/register", register, methods=["POST"]),
    Route("/as/token", token, methods=["POST"]),
])


@pytest.fixture(scope="module")
def base():
    for url in serve(fake):
        BASE["url"] = url
        yield url


@pytest.fixture(autouse=True)
def allow_local(env):
    env.setenv("EXTERNAL_AGENT_ALLOW_PRIVATE", "1")


def _authorize(auth_url):
    """What the authorization server does when the user approves: a code bound to the PKCE challenge."""
    q = {k: v[0] for k, v in parse_qs(urlparse(auth_url).query).items()}
    AS["codes"]["code-1"] = {"challenge": q["code_challenge"]}
    return q


@pytest.fixture(scope="module")
def server_id(client, base):
    r = client.post("/api/custom-mcp", headers=hdr(), json={"name": "prot", "transport": "http", "url": f"{base}/mcp"})
    assert r.json()["tools_cache"] == [] and r.json()["oauth_status"] == "none"
    return r.json()["id"]


def test_testing_a_protected_server_says_it_needs_auth(client, base):
    r = client.post("/api/custom-mcp/test", headers=hdr(), json={"transport": "http", "url": f"{base}/mcp"}).json()
    assert r["success"] is False and r["auth_required"] is True


def test_sign_in_registers_a_client_and_sends_pkce(client, base, server_id):
    r = client.post(f"/api/custom-mcp/{server_id}/oauth/start", headers=hdr(), json={})
    assert r.status_code == 200, r.text
    q = _authorize(r.json()["authorization_url"])
    assert r.json()["authorization_url"].startswith(f"{base}/as/authorize?")
    assert q["client_id"] == "cid-1" and q["code_challenge_method"] == "S256"
    assert q["resource"] == f"{base}/mcp" and q["scope"] == "mcp:read mcp:write"
    assert q["redirect_uri"].endswith("/api/custom-mcp/oauth/callback")
    assert q["state"].startswith(server_id + ".")
    assert AS["registered"][-1]["token_endpoint_auth_method"] == "none"
    assert AS["registered"][-1]["redirect_uris"] == [q["redirect_uri"]]

    bad = client.get("/api/custom-mcp/oauth/callback", params={"state": server_id + ".forged", "code": "code-1"})
    assert bad.status_code == 400 and "isn't valid" in bad.text

    ok = client.get("/api/custom-mcp/oauth/callback", params={"state": q["state"], "code": "code-1"})
    assert ok.status_code == 200 and "Connected" in ok.text
    replay = client.get("/api/custom-mcp/oauth/callback", params={"state": q["state"], "code": "code-1"})
    assert replay.status_code == 400, "a state works once"


def test_the_callback_needs_no_login_and_escapes_what_it_echoes(client):
    r = client.get("/api/custom-mcp/oauth/callback", params={"error": "access_denied",
                                                           "error_description": "</script><b>x</b>"})
    assert r.status_code == 400 and "<b>" not in r.text and "&lt;b&gt;" in r.text


def test_tokens_stay_on_the_server(client, server_id):
    listed = next(s for s in client.get("/api/custom-mcp", headers=hdr()).json() if s["id"] == server_id)
    assert listed["oauth_status"] == "connected"
    assert "at-1" not in json.dumps(listed) and "oauth" not in listed
    from db import get_db_connection
    conn = get_db_connection()
    raw = conn.execute("SELECT oauth FROM custom_mcp_servers WHERE id = ?", (server_id,)).fetchone()["oauth"]
    conn.close()
    assert raw.startswith("enc://") and "at-1" not in raw


def test_discovery_and_calls_use_the_token(client, server_id):
    r = client.post(f"/api/custom-mcp/{server_id}/discover", headers=hdr()).json()
    assert r["success"] and [t["name"] for t in r["tools"]] == ["whoami"]
    out = client.post(f"/api/custom-mcp/{server_id}/execute", headers=hdr(), json={"tool_name": "whoami"}).json()
    assert out["output"] == "token at-1"


def test_a_revoked_token_is_refreshed_once(client, server_id):
    AS["valid"].discard("at-1")
    out = client.post(f"/api/custom-mcp/{server_id}/execute", headers=hdr(), json={"tool_name": "whoami"}).json()
    assert out["output"] == "token at-2" and AS["refreshes"] == 1
    assert mcp_oauth.load(server_id)["refresh_token"] == "rt-1", "kept when the server doesn't rotate it"


def test_other_projects_cant_start_or_disconnect(client, server_id):
    other = hdr("user_admin", project="proj_support")
    assert client.post(f"/api/custom-mcp/{server_id}/oauth/start", headers=other, json={}).status_code == 404
    assert client.delete(f"/api/custom-mcp/{server_id}/oauth", headers=other).status_code == 404


def test_changing_the_url_drops_the_tokens(client, base, server_id):
    r = client.put(f"/api/custom-mcp/{server_id}", headers=hdr(), json={"url": f"{base}/elsewhere"})
    assert r.json()["oauth_status"] == "none" and mcp_oauth.load(server_id) == {}
