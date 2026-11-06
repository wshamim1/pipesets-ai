"""Outlook Mail — built-in tool `outlook_mail` (Microsoft Graph mail).

Actions: ``list`` (search or the newest messages), ``read`` (one message in full) and ``send``
(plain text to one or more addresses). Auth is a delegated Microsoft OAuth access token (+ refresh
token / client id / secret when present) in the node config, resolved from a ``secret://`` ref like
any other credential. Delegate scopes: ``offline_access Mail.Read Mail.Send``.
"""

import html
import re
from typing import Any, Dict, List, Optional

from tools.base import MAX_RESULTS, ToolSpec, enum, params
from tools.productivity._ms_auth import GRAPH, call as ms_call
from tools.productivity._ms_auth import ms_error

LABEL = "[Outlook Mail]"
_MSG_FIELDS = "id,subject,from,receivedDateTime,bodyPreview"
_READ_FIELDS = "id,subject,from,toRecipients,ccRecipients,receivedDateTime,body"
_HEAD_COUNT = 5
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


def _addr(entry: Any) -> str:
    """One Graph recipient entry as ``Name <email>`` or ``''``."""
    if not isinstance(entry, dict):
        return ""
    ea = entry.get("emailAddress") or {}
    email, name = str(ea.get("address") or ""), str(ea.get("name") or "")
    if not email:
        return ""
    return f"{name} <{email}>" if name and name.lower() != email else email


def _as_text(entry: Any) -> str:
    """A single ``to`` argument value: an address as given."""
    s = str(entry or "").strip()
    bracket = re.search(r"<([^>]+)>", s)
    return bracket.group(1).strip() if bracket else s


def _recipients(raw: str) -> List[str]:
    """The typed ``to`` argument (comma/semicolon separated) as plain addresses."""
    return [a for a in (_as_text(p) for p in re.split(r"[;,]", str(raw or ""))) if a]


def _format_full(msg: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    body = str((msg.get("body") or {}).get("content") or "")
    if (msg.get("body") or {}).get("contentType") == "html":
        body = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))).strip()
    max_chars = min(max(int(cfg.get("max_chars", 5000) or 5000), 200), 20000)

    out = [LABEL, f"From: {_addr(msg.get('from')) or '(no sender)'}"]
    for key, name in (("toRecipients", "To"), ("ccRecipients", "Cc")):
        addrs = [_addr(e) for e in msg.get(key) or [] if _addr(e)]
        if addrs:
            out.append(f"{name}: {', '.join(addrs[:_HEAD_COUNT])}"
                       + (f" … (+{len(addrs) - _HEAD_COUNT})" if len(addrs) > _HEAD_COUNT else ""))
    if msg.get("receivedDateTime"):
        out.append(f"Date: {msg['receivedDateTime']}")
    if msg.get("subject"):
        out.append(f"Subject: {msg['subject']}")
    out.append(f"Id: {msg.get('id')}")
    out.append("")
    out.append(body[:max_chars] or "[no body]")
    if len(body) > max_chars:
        out.append(f"\n… (body truncated at {max_chars} of {len(body)} characters)")
    return "\n".join(out)


TOOL = ToolSpec(
    id="outlook_mail",
    name="Outlook Mail",
    icon="✉️",
    category="Productivity",
    description=("Reads and sends the signed-in user's Outlook mail via Microsoft Graph: search or "
                 "list the newest messages, read one in full, send a plain-text message. "
                 "Delegated Graph scopes: Mail.Read, Mail.Send."),
    default_config={"access_token": "", "action": "list", "query": "", "max_results": 10},
    order=100,
    required=("access_token",),
    parameters=params(
        {"action": enum(["list", "read", "send"], "list = search or newest messages, read = one in full, send = a plain-text message")},
        {
            "query": {"type": "string", "description": "Search text (subject, sender, body); empty = newest first (list)"},
            "max_results": MAX_RESULTS,
            "message_id": {"type": "string", "description": "The message id to read (from list) (read)"},
            "max_chars": {"type": "integer", "minimum": 200, "maximum": 20000,
                          "description": "Most body characters to return (read)"},
            "to": {"type": "string", "description": "Recipient addresses, comma or semicolon separated (send)"},
            "subject": {"type": "string", "description": "Message subject (send)"},
            "message_text": {"type": "string", "description": "Plain-text message body (send)"},
        },
    ),
    input_param="action",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("access_token") or "").strip()
    if not token:
        return (f"{LABEL} access_token is required in config — provide a Microsoft OAuth access token "
                "(or a secret:// ref) with the Mail.Read / Mail.Send delegated scopes.")
    action = str(inp or cfg.get("action") or "").strip().lower()
    if action not in ("list", "read", "send"):
        return f'{LABEL} Action is "list", "read" or "send" — got "{inp}".'

    if action == "read":
        message_id = str(cfg.get("message_id") or "").strip()
        if not message_id:
            return f"{LABEL} read needs a message_id — pass the id of a message from list."
        resp = await ms_call(cfg, "GET", f"{GRAPH}/me/messages/{message_id}", query={
            "$select": _READ_FIELDS})
        if resp.status_code != 200:
            return ms_error(LABEL, resp)
        return _format_full(resp.json(), cfg)

    if action == "send":
        recipients = _recipients(cfg.get("to"))
        subject = str(cfg.get("subject") or "").strip()
        body = str(cfg.get("message_text") or "")
        if not (recipients and subject and body):
            return (f"{LABEL} send needs a to (comma-separated addresses), subject and message_text "
                    "— pass all three.")
        bad = [r for r in recipients if not _EMAIL_RE.fullmatch(r)]
        if bad:
            return f"{LABEL} These don't look like email addresses: {', '.join(bad)}"
        payload = {"message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": r}} for r in recipients],
        }, "saveToSentItems": True}
        resp = await ms_call(cfg, "POST", f"{GRAPH}/me/sendMail", json_body=payload)
        if resp.status_code != 202:
            return ms_error(LABEL, resp)
        return f"{LABEL} Sent '{subject}' to {', '.join(recipients)}."

    # list
    query = str(cfg.get("query") or "").strip()
    top = min(max(int(cfg.get("max_results", 10) or 10), 1), 20)
    q: Dict[str, Any] = {"$select": _MSG_FIELDS, "$top": top}
    if query:
        q["$search"] = f'"{query}"'
    else:
        q["$orderby"] = "receivedDateTime desc"
    resp = await ms_call(cfg, "GET", f"{GRAPH}/me/messages", query=q)
    if resp.status_code != 200:
        return ms_error(LABEL, resp)
    found: List[Dict[str, Any]] = resp.json().get("value") or []
    if not found:
        return f'{LABEL} No messages match "{query}".' if query else f"{LABEL} The inbox is empty."
    scope = f' matching "{query}"' if query else " (newest first)"
    lines = [f"{LABEL} {len(found)} message(s){scope}", ""]
    for m in found:
        sender = _addr(m.get("from")) or "(no sender)"
        lines.append(f"  #{m.get('id')} · {str(m.get('receivedDateTime') or '').replace('T', ' ')} · {sender}")
        subject = str(m.get("subject") or "").strip()
        if subject:
            lines.append(f"    Subject: {subject}")
        preview = str(m.get("bodyPreview") or "").strip()
        if preview:
            lines.append(f"    {preview[:200]}")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n\nTo read one in full: outlook_mail read with its message_id."
