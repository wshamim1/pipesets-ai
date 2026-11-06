"""
mcp_oauth.py — OAuth 2.1 sign-in for remote custom MCP servers (MCP authorization spec 2025-06-18).

Flow
----
1. ``start()`` probes the server: its 401 ``WWW-Authenticate`` names the protected-resource
   metadata (RFC 9728), else ``/.well-known/oauth-protected-resource`` is tried. That lists the
   authorization server, whose metadata (RFC 8414 / OIDC discovery) gives the endpoints. A
   server without resource metadata (spec 2025-03-26) is its own authorization server, with
   ``/authorize``, ``/token`` and ``/register`` as the fallbacks.
2. The client is registered dynamically (RFC 7591) unless the user supplies a client id (e.g.
   GitHub, which has no registration endpoint). The authorization URL carries PKCE S256, a
   random ``state`` and the ``resource`` indicator (RFC 8707).
3. The browser comes back to the public callback with ``code`` and ``state``. ``finish()``
   matches the single-use, 10-minute ``state`` and exchanges the code for tokens.
4. ``bearer()`` returns a live access token for each call, refreshing it when it's about to
   expire (or on a 401, with ``force=True``).

Everything — endpoints, client, tokens, the pending sign-in — is one JSON document stored sealed
(``enc://``) in ``custom_mcp_servers.oauth``. It never leaves the backend.

Every URL the backend fetches passes the outbound SSRF guard; redirects are not followed.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlparse, urlunparse

import httpx

from db import get_db_connection
from services import secret_store
from services.external_agent import validate_endpoint

PENDING_TTL_S = 600
REFRESH_MARGIN_S = 60
TIMEOUT_S = 15.0
CALLBACK_PATH = "/api/custom-mcp/oauth/callback"


class OAuthError(RuntimeError):
    """Sign-in or token refresh failed; the message says why."""


# ── Storage ───────────────────────────────────────────────────────────────────

def load(server_id: str) -> Dict[str, Any]:
    conn = get_db_connection()
    row = conn.execute("SELECT oauth FROM custom_mcp_servers WHERE id = ?", (server_id,)).fetchone()
    conn.close()
    return from_column((row["oauth"] if row else "") or "")


def from_column(raw: str) -> Dict[str, Any]:
    """The OAuth document in a custom_mcp_servers.oauth value ({} when empty or unreadable)."""
    try:
        return json.loads(secret_store.unseal(raw)) if secret_store.is_sealed(raw) else {}
    except Exception:
        return {}


def save(server_id: str, state: Dict[str, Any]) -> None:
    conn = get_db_connection()
    conn.execute("UPDATE custom_mcp_servers SET oauth = ? WHERE id = ?",
                 (secret_store.seal(json.dumps(state)) if state else "", server_id))
    conn.commit()
    conn.close()


def status(state: Dict[str, Any]) -> str:
    """"connected", "expired" (no usable token or refresh token) or "none"."""
    if not state.get("access_token"):
        return "none"
    if state.get("refresh_token") or not state.get("expires_at") or state["expires_at"] > time.time():
        return "connected"
    return "expired"


def redirect_uri(base_url: str) -> str:
    """The callback URL: PIPESETS_PUBLIC_URL when set (behind a proxy), else the request's own base."""
    return (os.getenv("PIPESETS_PUBLIC_URL", "").strip() or base_url).rstrip("/") + CALLBACK_PATH


# ── Discovery ─────────────────────────────────────────────────────────────────

async def _get_json(client: httpx.AsyncClient, url: str) -> Optional[Dict[str, Any]]:
    try:
        await validate_endpoint(url)
        r = await client.get(url, headers={"Accept": "application/json"})
    except (ValueError, httpx.HTTPError):
        return None
    if r.status_code != 200:
        return None
    try:
        doc = r.json()
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def _well_known(base: str, name: str) -> List[str]:
    """RFC 8414 path insertion first, then the root (and OIDC's path-appended form)."""
    p = urlparse(base)
    path = p.path.rstrip("/")
    root = urlunparse((p.scheme, p.netloc, "", "", "", ""))
    urls = [f"{root}/.well-known/{name}{path}"] if path else []
    urls.append(f"{root}/.well-known/{name}")
    if path and name == "openid-configuration":
        urls.append(f"{root}{path}/.well-known/{name}")
    return urls


def _challenge_param(header: str, name: str) -> str:
    m = re.search(rf'{name}="([^"]*)"', header or "") or re.search(rf"{name}=([^\s,]+)", header or "")
    return m.group(1) if m else ""


async def _probe(client: httpx.AsyncClient, server_url: str) -> str:
    """The server's WWW-Authenticate challenge for an unauthenticated initialize ('' if none)."""
    try:
        r = await client.post(server_url, headers={"Accept": "application/json, text/event-stream"},
                              json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                                  "protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "pipesets-ai", "version": "1.0.0"}}})
    except httpx.HTTPError:
        return ""
    return r.headers.get("www-authenticate", "") if r.status_code == 401 else ""


async def discover(client: httpx.AsyncClient, server_url: str) -> Dict[str, Any]:
    """Endpoints for signing in to ``server_url``: authorization / token / registration
    endpoints, the resource indicator and the scopes to ask for."""
    challenge = await _probe(client, server_url)
    prm = None
    hinted = _challenge_param(challenge, "resource_metadata")
    for url in ([hinted] if hinted else []) + _well_known(server_url, "oauth-protected-resource"):
        prm = await _get_json(client, url)
        if prm and prm.get("authorization_servers"):
            break
        prm = None

    p = urlparse(server_url)
    origin = urlunparse((p.scheme, p.netloc, "", "", "", ""))
    issuer = prm["authorization_servers"][0] if prm else origin
    meta = None
    for url in _well_known(issuer, "oauth-authorization-server") + _well_known(issuer, "openid-configuration"):
        meta = await _get_json(client, url)
        if meta and meta.get("authorization_endpoint") and meta.get("token_endpoint"):
            break
        meta = None
    if meta is None:
        if prm:
            raise OAuthError(f"Couldn't read the metadata of authorization server {issuer}")
        meta = {"authorization_endpoint": f"{origin}/authorize", "token_endpoint": f"{origin}/token",
                "registration_endpoint": f"{origin}/register"}
    for key in ("authorization_endpoint", "token_endpoint"):
        if urlparse(meta[key]).scheme not in ("http", "https"):   # it's opened in the user's browser
            raise OAuthError(f"The authorization server's {key} isn't an http(s) URL")
    methods = meta.get("code_challenge_methods_supported")
    if methods and "S256" not in methods:
        raise OAuthError("The authorization server doesn't support PKCE S256")

    scope = _challenge_param(challenge, "scope") or " ".join((prm or {}).get("scopes_supported") or [])
    return {"issuer": issuer,
            "authorization_endpoint": meta["authorization_endpoint"],
            "token_endpoint": meta["token_endpoint"],
            "registration_endpoint": meta.get("registration_endpoint", ""),
            "resource": (prm or {}).get("resource") or server_url,
            "scope": scope}


async def _register(client: httpx.AsyncClient, endpoint: str, redirect: str) -> Dict[str, Any]:
    await validate_endpoint(endpoint)
    r = await client.post(endpoint, json={
        "client_name": "Pipesets AI", "redirect_uris": [redirect],
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
        "token_endpoint_auth_method": "none"})
    if r.status_code not in (200, 201):
        raise OAuthError(f"Client registration failed (HTTP {r.status_code}): {r.text[:200]}")
    doc = r.json()
    if not doc.get("client_id"):
        raise OAuthError("Client registration returned no client_id")
    return {"client_id": doc["client_id"], "client_secret": doc.get("client_secret", ""),
            "token_auth": doc.get("token_endpoint_auth_method") or ("client_secret_post" if doc.get("client_secret")
                                                                     else "none")}


# ── Sign-in ───────────────────────────────────────────────────────────────────

def _pkce() -> Tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def start(server: Dict[str, Any], redirect: str, client_id: str = "", client_secret: str = "",
                scope: Optional[str] = None) -> str:
    """Begin signing in; returns the authorization URL to open in the browser."""
    old = load(server["id"])
    async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False) as client:
        try:
            await validate_endpoint(server["url"])
            endpoints = await discover(client, server["url"])
        except ValueError as e:
            raise OAuthError(str(e))
        if client_id:
            reg = {"client_id": client_id, "client_secret": client_secret,
                   "token_auth": "client_secret_post" if client_secret else "none"}
        elif old.get("client_id") and old.get("redirect_uri") == redirect and old.get("issuer") == endpoints["issuer"]:
            reg = {k: old.get(k, "") for k in ("client_id", "client_secret", "token_auth")}
        elif endpoints["registration_endpoint"]:
            try:
                reg = await _register(client, endpoints["registration_endpoint"], redirect)
            except (ValueError, httpx.HTTPError) as e:
                raise OAuthError(f"Client registration failed: {e}")
        else:
            raise OAuthError("This server doesn't support automatic client registration. "
                             "Create an OAuth app with the provider and enter its client id.")

    verifier, challenge = _pkce()
    state = f"{server['id']}.{secrets.token_urlsafe(24)}"
    scope = endpoints["scope"] if scope is None else scope
    keep = {k: old[k] for k in ("access_token", "refresh_token", "expires_at") if k in old}
    save(server["id"], {**keep, **endpoints, **reg, "scope": scope, "redirect_uri": redirect,
                        "pending": {"state": state, "verifier": verifier, "expires_at": time.time() + PENDING_TTL_S}})
    params = {"response_type": "code", "client_id": reg["client_id"], "redirect_uri": redirect,
              "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
              "resource": endpoints["resource"]}
    if scope:
        params["scope"] = scope
    sep = "&" if "?" in endpoints["authorization_endpoint"] else "?"
    return endpoints["authorization_endpoint"] + sep + urlencode(params)


def server_for_state(state: str) -> str:
    """The server id a callback's ``state`` names (checked against the stored one in finish())."""
    return state.split(".", 1)[0] if "." in (state or "") else ""


def _token_auth(st: Dict[str, Any], form: Dict[str, str]) -> Optional[Tuple[str, str]]:
    """Adds client credentials to the token request; returns HTTP basic auth when that's the method."""
    form["client_id"] = st["client_id"]
    if st.get("client_secret"):
        if st.get("token_auth") == "client_secret_basic":
            return st["client_id"], st["client_secret"]
        form["client_secret"] = st["client_secret"]
    return None


async def _token_request(st: Dict[str, Any], form: Dict[str, str]) -> Dict[str, Any]:
    basic = _token_auth(st, form)
    if st.get("resource"):
        form["resource"] = st["resource"]
    try:
        await validate_endpoint(st["token_endpoint"])
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False) as client:
            r = await client.post(st["token_endpoint"], data=form, auth=basic, headers={"Accept": "application/json"})
    except (ValueError, httpx.HTTPError) as e:
        raise OAuthError(f"Token request failed: {e}")
    try:
        doc = r.json()
    except ValueError:
        doc = {}
    if r.status_code != 200 or not doc.get("access_token"):
        raise OAuthError(f"Token request failed: {doc.get('error_description') or doc.get('error') or r.status_code}")
    return {"access_token": doc["access_token"],
            "refresh_token": doc.get("refresh_token") or st.get("refresh_token", ""),
            "expires_at": time.time() + float(doc["expires_in"]) if doc.get("expires_in") else 0}


async def finish(state: str, code: str) -> str:
    """Exchange the callback's code for tokens; returns the server id. Raises OAuthError."""
    server_id = server_for_state(state)
    st = load(server_id) if server_id else {}
    pending = st.get("pending") or {}
    if not pending or not hmac.compare_digest(pending.get("state", ""), state or ""):
        raise OAuthError("This sign-in link isn't valid. Start again from the MCP server settings.")
    st.pop("pending")
    save(server_id, st)   # single use, whatever happens next
    if pending["expires_at"] < time.time():
        raise OAuthError("The sign-in took too long. Start again.")
    tokens = await _token_request(st, {"grant_type": "authorization_code", "code": code,
                                       "redirect_uri": st["redirect_uri"], "code_verifier": pending["verifier"]})
    save(server_id, {**st, **tokens})
    return server_id


async def bearer(server_id: str, force: bool = False) -> Optional[str]:
    """A live access token for the server, refreshed when needed; None when it isn't signed in."""
    st = load(server_id)
    if not st.get("access_token"):
        return None
    fresh = not st.get("expires_at") or st["expires_at"] - REFRESH_MARGIN_S > time.time()
    if fresh and not force:
        return st["access_token"]
    if not st.get("refresh_token"):
        return None if not fresh else st["access_token"]
    tokens = await _token_request(st, {"grant_type": "refresh_token", "refresh_token": st["refresh_token"]})
    save(server_id, {**st, **tokens})
    return tokens["access_token"]


def disconnect(server_id: str) -> None:
    save(server_id, {})
