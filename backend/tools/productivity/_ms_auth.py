"""Shared helpers for the Microsoft Graph tools (Outlook, OneDrive, Teams, Excel workbooks).

Auth is a Microsoft identity platform delegated OAuth access token (+ refresh token / client id /
secret when present) in the node config, resolved from a ``secret://`` ref like any other
credential. The env vars MICROSOFT_OAUTH_CLIENT_ID / MICROSOFT_OAUTH_CLIENT_SECRET fill in the
client credentials. Scopes needed per tool are named in the tool's description.
"""

import json
import os
from typing import Any, Dict, Optional

import httpx

MS_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH = "https://graph.microsoft.com/v1.0"


async def call(cfg: Dict[str, Any], method: str, url: str, *, query: Optional[Dict[str, Any]] = None,
               json_body: Optional[Dict[str, Any]] = None,
               headers: Optional[Dict[str, str]] = None) -> httpx.Response:
    """Authorized request with the Bearer token; on 401, retries once with a refreshed token.

    Redirects are followed (content downloads behind /content redirect to the CDN).
    """
    token = (cfg.get("access_token") or "").strip()
    refresh_token = (cfg.get("refresh_token") or "").strip()
    client_id = (cfg.get("client_id") or os.environ.get("MICROSOFT_OAUTH_CLIENT_ID") or "").strip()
    client_secret = (cfg.get("client_secret") or os.environ.get("MICROSOFT_OAUTH_CLIENT_SECRET") or "").strip()

    async def _do(tok: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            return await client.request(method, url, params=query, json=json_body,
                                        headers={"Authorization": f"Bearer {tok}",
                                                 "Accept": "application/json", **(headers or {})})

    resp = await _do(token)
    if resp.status_code == 401 and refresh_token and client_id and client_secret:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(MS_AUTH_URL, data={
                "grant_type": "refresh_token", "refresh_token": refresh_token,
                "client_id": client_id, "client_secret": client_secret,
                "scope": cfg.get("scope", "") or "offline_access"})
            if r.status_code == 200:
                tok = r.json().get("access_token") or ""
                if tok:
                    resp = await _do(tok)
    return resp


def ms_error(label: str, resp: httpx.Response) -> str:
    """A Graph HTTP response as friendly text (message from the error body when there is one)."""
    label = label.strip("[]")
    detail = ""
    try:
        detail = str((resp.json().get("error") or {}).get("message") or "")[:300]
    except Exception:
        detail = resp.text[:300]
    if resp.status_code == 401:
        return f"[{label}] Authentication failed — check the access_token (or refresh_token)."
    if resp.status_code == 403:
        return (f"[{label}] The account doesn't have permission for this — check the OAuth scope "
                f"(and admin consent for application permissions). {detail}")
    if resp.status_code == 404:
        return f"[{label}] Not found (or not visible to this account)."
    return f"[{label}] HTTP {resp.status_code}: {detail}"


def api_detail(resp: httpx.Response) -> str:
    try:
        return json.dumps(resp.json())[:300]
    except Exception:
        return resp.text[:300]
