"""Dropbox — built-in tool `dropbox` (Dropbox API v2; read-only).

Input: a path starting with ``/`` lists that folder, or reads the file's text when it is a file
(``/`` alone is the root); anything else searches file and folder names and contents.

Auth: Dropbox access tokens expire after four hours, so set ``refresh_token`` with the app's
``app_key`` and ``app_secret`` (a fresh access token is fetched for each call); a bare
``access_token`` works until it expires.
"""

import json
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

LABEL = "[Dropbox]"
API = "https://api.dropboxapi.com/2"
CONTENT = "https://content.dropboxapi.com/2"
TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
MAX_READ = 1_000_000

TOOL = ToolSpec(
    id="dropbox",
    name="Dropbox",
    icon="📦",
    category="Productivity",
    description="Dropbox (read-only): lists a folder, reads a text file, or searches files by name and content. Input: a path like /Reports (or /notes.txt), or search text.",
    default_config={"refresh_token": "", "app_key": "", "app_secret": "", "access_token": "", "max_chars": 20000, "max_results": 25},
    order=120,
    parameters=params({"request": {"type": "string", "description": "A folder or file path starting with / (/ is the root), or search text"}}),
    input_param="request",
    is_new=True,
)


def _entry(m: Dict[str, Any]) -> str:
    if m.get(".tag") == "folder":
        return f"- 📁 {m.get('path_display')}/"
    size = m.get("size")
    return (f"- {m.get('path_display')} · {f'{size:,} bytes' if isinstance(size, int) else ''}"
            f" · modified {(m.get('server_modified') or '')[:10]}")


def _error(resp: httpx.Response) -> str:
    try:
        summary = resp.json().get("error_summary") or ""
    except ValueError:
        summary = resp.text[:200]
    if resp.status_code == 401:
        return f"{LABEL} HTTP 401 — the token is invalid or expired (set refresh_token, app_key and app_secret)."
    if "not_found" in summary:
        return f"{LABEL} Not found: {summary.split('/')[0]} path."
    if "missing_scope" in summary:
        return f"{LABEL} The app is missing a scope ({summary}) — it needs files.metadata.read and files.content.read."
    return f"{LABEL} HTTP {resp.status_code}: {summary}"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    refresh = str(cfg.get("refresh_token") or "").strip()
    token = str(cfg.get("access_token") or "").strip()
    if not refresh and not token:
        return f"{LABEL} Set refresh_token with app_key and app_secret (or a short-lived access_token) in config."
    text = inp.strip().strip("'\"")
    limit = max(1, min(int(cfg.get("max_results") or 25), 100))
    max_chars = max(100, int(cfg.get("max_chars") or 20000))
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if refresh:
                key, secret = str(cfg.get("app_key") or "").strip(), str(cfg.get("app_secret") or "").strip()
                if not key or not secret:
                    return f"{LABEL} refresh_token needs app_key and app_secret too."
                tr = await client.post(TOKEN_URL, data={"grant_type": "refresh_token", "refresh_token": refresh},
                                       auth=(key, secret))
                if tr.status_code >= 400:
                    return f"{LABEL} Couldn't refresh the access token (HTTP {tr.status_code}): {tr.text[:200]}"
                token = tr.json().get("access_token", "")
            auth = {"Authorization": f"Bearer {token}"}
            if not text.startswith("/"):
                if not text:
                    return f"{LABEL} Give a path starting with / or text to search for."
                resp = await client.post(f"{API}/files/search_v2", headers=auth,
                                         json={"query": text[:1000], "options": {"max_results": limit}})
                if resp.status_code >= 400:
                    return _error(resp)
                matches = [((m.get("metadata") or {}).get("metadata") or {}) for m in resp.json().get("matches") or []]
                if not matches:
                    return f"{LABEL} Nothing matches '{text}'."
                return f"{LABEL} {len(matches)} match(es) for '{text}'\n" + "\n".join(_entry(m) for m in matches)
            path = "" if text == "/" else text.rstrip("/")
            resp = await client.post(f"{API}/files/list_folder", headers=auth, json={"path": path, "limit": limit})
            if resp.status_code == 409 and "not_folder" in resp.text:
                resp = await client.post(f"{CONTENT}/files/download", headers={
                    **auth, "Dropbox-API-Arg": json.dumps({"path": path}, ensure_ascii=True)})
                if resp.status_code >= 400:
                    return _error(resp)
                meta = json.loads(resp.headers.get("dropbox-api-result") or "{}")
                raw = resp.content[:MAX_READ]
                try:
                    body = raw.decode("utf-8")
                except UnicodeDecodeError:
                    return f"{LABEL} {path} is a binary file ({meta.get('size', len(resp.content)):,} bytes); only text files can be read."
                cut = len(body) > max_chars
                return (f"{LABEL} {meta.get('path_display', path)} · modified {(meta.get('server_modified') or '')[:10]}\n\n"
                        + body[:max_chars] + (f"\n\n… (truncated at {max_chars:,} characters)" if cut else ""))
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach Dropbox: {e}"
    if resp.status_code >= 400:
        return _error(resp)
    data = resp.json()
    entries = data.get("entries") or []
    if not entries:
        return f"{LABEL} {text} is empty."
    entries.sort(key=lambda m: (m.get(".tag") != "folder", (m.get("name") or "").lower()))
    more = " (more not shown)" if data.get("has_more") else ""
    return f"{LABEL} {len(entries)} item(s) in {text}{more}\n" + "\n".join(_entry(m) for m in entries)
