"""Shared helpers for the Google API tools (Calendar, Gmail): OAuth calls and error text.

Auth is an OAuth access token (+ refresh token / client id / secret when present) in the
node config, resolved from a ``secret://`` ref like any other credential. The env vars
GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET fill in the client credentials.
"""

import json
import os
from typing import Any, Dict, Optional

import httpx

GOOGLE_AUTH_URL = "https://oauth2.googleapis.com/token"


async def call(cfg: Dict[str, Any], method: str, url: str, *, query: Optional[Dict[str, Any]] = None,
               json_body: Optional[Dict[str, Any]] = None) -> httpx.Response:
    """Authorized request with the Bearer token; on 401, retries once with a refreshed token."""
    token = (cfg.get("access_token") or "").strip()
    refresh_token = (cfg.get("refresh_token") or "").strip()
    client_id = (cfg.get("client_id") or os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
    client_secret = (cfg.get("client_secret") or os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()

    async def _do(tok: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=20.0) as client:
            return await client.request(method, url, params=query, json=json_body,
                                        headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"})

    resp = await _do(token)
    if resp.status_code == 401 and refresh_token and client_id and client_secret:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(GOOGLE_AUTH_URL, data={
                "grant_type": "refresh_token", "refresh_token": refresh_token,
                "client_id": client_id, "client_secret": client_secret})
            if r.status_code == 200:
                tok = r.json().get("access_token") or ""
                if tok:
                    resp = await _do(tok)
    return resp


def http_error(label: str, resp: httpx.Response) -> str:
    label = label.strip("[]")
    if resp.status_code == 401:
        return f"[{label}] Authentication failed — check the access_token (or refresh_token)."
    if resp.status_code == 403:
        return f"[{label}] The account doesn't have permission for this — check the OAuth scope."
    if resp.status_code == 404:
        return f"[{label}] Not found (or not visible to this account)."
    try:
        detail = json.dumps(resp.json())[:300]
    except Exception:
        detail = resp.text[:300]
    return f"[{label}] HTTP {resp.status_code}: {detail}"
