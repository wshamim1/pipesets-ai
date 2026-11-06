"""Gmail Reader — built-in tool `gmail_reader` (Gmail REST API v1, read-only).

Actions: ``list`` (search messages, Gmail search syntax e.g. "from:boss newer_than:7d") and
``read`` (one message: headers, attachments, decoded text body). Auth is an OAuth access token
with the https://www.googleapis.com/auth/gmail.readonly scope (+ refresh token / client id /
secret when present) in the node config, resolved from a ``secret://`` ref like any other
credential.
"""

import base64
import html
import re
from typing import Any, Dict, List, Optional, Tuple

from tools.base import MAX_RESULTS, ToolSpec, enum, params
from tools.productivity._google_auth import call as google_call
from tools.productivity._google_auth import http_error

LABEL = "[Gmail]"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
_HEADERS = ["From", "To", "Cc", "Subject", "Date"]


def _headers(message: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for h in (message.get("payload") or {}).get("headers") or []:
        name, value = str(h.get("name") or ""), str(h.get("value") or "").strip()
        if name in _HEADERS and value:
            out[name] = value
    return out


def _parts(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        out.append(node)
        for part in node.get("parts") or []:
            walk(part)

    walk(payload)
    return out


def _decode_b64url(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def _body(payload: Dict[str, Any]) -> Tuple[str, str]:
    """(text, note) — the plain-text body, or HTML un-tagged when that's all there is."""
    parts = _parts(payload)
    for mime in ("text/plain", "text/html"):
        for p in parts:
            if p.get("mimeType") != mime:
                continue
            data = (p.get("body") or {}).get("data")
            if not data:
                continue
            text = _decode_b64url(data)
            if mime == "text/html":
                text = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))).strip()
                return text, "HTML body, tags stripped"
            return text.strip(), ""
    return "", "no body part"


TOOL = ToolSpec(
    id="gmail_reader",
    name="Gmail Reader",
    icon="📬",
    category="Productivity",
    description="Reads the user's Gmail via the Gmail API: search messages (Gmail search syntax) and read one in full.",
    default_config={"access_token": "", "query": "in:inbox", "max_results": 10, "max_chars": 5000},
    order=20,
    required=("access_token",),
    parameters=params(
        {"action": enum(["list", "read"], "list = search matching messages, read = one message in full")},
        {
            "query": {"type": "string", "description": "Gmail search string, e.g. 'from:boss newer_than:7d' (list)"},
            "max_results": MAX_RESULTS,
            "message_id": {"type": "string", "description": "The message id to read (from list) (read)"},
            "max_chars": {"type": "integer", "minimum": 200, "maximum": 20000,
                          "description": "Most body characters to return (read)"},
        },
    ),
    input_param="action",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("access_token") or "").strip()
    if not token:
        return (f"{LABEL} access_token is required in config — provide an OAuth access token (or a secret:// ref) "
                "with the gmail.readonly scope.")
    action = str(inp or "").strip().lower()
    if action not in ("list", "read"):
        return f'{LABEL} Action is "list" or "read" — got "{inp}".'

    if action == "read":
        message_id = str(cfg.get("message_id") or "").strip()
        if not message_id:
            return f"{LABEL} read needs a message_id — pass the id of a message from list."
        resp = await google_call(cfg, "GET", f"{GMAIL_API}/users/me/messages/{message_id}", query={"format": "full"})
        if resp.status_code != 200:
            return http_error(LABEL, resp)
        return _format_full(resp.json(), cfg)

    query = str(cfg.get("query") or "").strip()
    max_results = min(max(int(cfg.get("max_results", 10) or 10), 1), 20)
    listing = await google_call(cfg, "GET", f"{GMAIL_API}/users/me/messages",
                                query={"maxResults": max_results, **({"q": query} if query else {})})
    if listing.status_code != 200:
        return http_error(LABEL, listing)
    ids = [m.get("id") for m in (listing.json().get("messages") or [])]
    if not ids:
        return f'{LABEL} No messages match "{query}".'
    estimate = listing.json().get("resultSizeEstimate") or len(ids)

    lines = [f'{LABEL} {len(ids)} message(s) for "{query}" (about {estimate} match)', ""]
    for mid in ids:
        resp = await google_call(cfg, "GET", f"{GMAIL_API}/users/me/messages/{mid}", query={
            "format": "metadata", "metadataHeaders": _HEADERS})
        if resp.status_code != 200:
            lines.append(f"  #{mid}: {_http(resp)}")
            continue
        msg = resp.json()
        hs = _headers(msg)
        lines.append(f"  #{mid}")
        for name in ("From", "Date", "Subject"):
            if hs.get(name):
                lines.append(f"    {name}: {hs[name]}")
        snippet = str(msg.get("snippet") or "").strip()
        if snippet:
            lines.append(f"    {snippet[:200]}")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n\nTo read one in full: gmail_reader read with its message_id."


def _http(resp: Any) -> str:
    try:
        return resp.json().get("error", {}).get("message", "")[:200] or resp.text[:200]
    except Exception:
        return resp.text[:200]


def _format_full(msg: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    hs = _headers(msg)
    body, note = _body(msg.get("payload") or {})
    attachments = [p["filename"] for p in _parts(msg.get("payload") or {}) if p.get("filename")]
    max_chars = min(max(int(cfg.get("max_chars", 5000) or 5000), 200), 20000)

    out = [LABEL]
    for name in ("From", "To", "Cc", "Date", "Subject"):
        if hs.get(name):
            out.append(f"{name}: {hs[name]}")
    if attachments:
        out.append(f"Attachments: {', '.join(attachments)}")
    out.append(f"Id: {msg.get('id')}")
    if note:
        out.append(f"({note})")
    out.append("")
    if body:
        out.append(body[:max_chars])
        if len(body) > max_chars:
            out.append(f"\n… (body truncated at {max_chars} of {len(body)} characters)")
    else:
        out.append("[no readable body]")
    return "\n".join(out)
