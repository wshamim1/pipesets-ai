"""Bluesky — built-in tool `bluesky_post` (AT Protocol with an app password).

Signs in (``com.atproto.server.createSession``) and posts the input with ``createRecord``. Links in
the text become clickable link facets, whose positions are UTF-8 byte offsets as the protocol needs.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from tools.base import ToolSpec, params

LABEL = "[Bluesky]"
MAX_CHARS = 300
_URL = re.compile(r"https?://[^\s<>\"']+[^\s<>\"'.,;:!?)\]]")

TOOL = ToolSpec(
    id="bluesky_post",
    name="Bluesky Post",
    icon="🦋",
    category="Communication",
    description="Posts to Bluesky (up to 300 characters; links become clickable). Uses an app password, not the account password.",
    default_config={"handle": "", "app_password": "", "service": "https://bsky.social"},
    order=120,
    required=("handle", "app_password"),
    parameters=params({"text": {"type": "string", "description": "The post text, up to 300 characters"}}),
    input_param="text",
)


def _link_facets(text: str) -> List[Dict[str, Any]]:
    facets = []
    for m in _URL.finditer(text):
        start = len(text[:m.start()].encode("utf-8"))
        facets.append({"index": {"byteStart": start, "byteEnd": start + len(m.group(0).encode("utf-8"))},
                       "features": [{"$type": "app.bsky.richtext.facet#link", "uri": m.group(0)}]})
    return facets


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    handle = (cfg.get("handle") or "").strip().lstrip("@")
    password = (cfg.get("app_password") or "").strip()
    if not handle:
        return f"{LABEL} handle (e.g. you.bsky.social) is required in config."
    if not password:
        return f"{LABEL} app_password (Settings → Privacy and security → App passwords) is required in config."
    if not inp:
        return f"{LABEL} Provide the text to post."
    if len(inp) > MAX_CHARS:
        return f"{LABEL} Posts are limited to {MAX_CHARS} characters; this one has {len(inp)}."
    service = (cfg.get("service") or "https://bsky.social").strip().rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{service}/xrpc/com.atproto.server.createSession",
                                     json={"identifier": handle, "password": password})
            if resp.status_code == 401:
                return f"{LABEL} Sign-in failed — check handle and app_password."
            if resp.status_code != 200:
                return f"{LABEL} Sign-in failed: HTTP {resp.status_code}: {resp.text[:200]}"
            session = resp.json()
            record: Dict[str, Any] = {"$type": "app.bsky.feed.post", "text": inp,
                                      "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
            facets = _link_facets(inp)
            if facets:
                record["facets"] = facets
            resp = await client.post(f"{service}/xrpc/com.atproto.repo.createRecord",
                                     headers={"Authorization": f"Bearer {session['accessJwt']}"},
                                     json={"repo": session["did"], "collection": "app.bsky.feed.post", "record": record})
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach {service}: {e}"
    if resp.status_code != 200:
        return f"{LABEL} Not posted: HTTP {resp.status_code}: {resp.text[:200]}"
    rkey = resp.json().get("uri", "").rsplit("/", 1)[-1]
    return f"{LABEL} Posted.\nhttps://bsky.app/profile/{session.get('handle', handle)}/post/{rkey}"
