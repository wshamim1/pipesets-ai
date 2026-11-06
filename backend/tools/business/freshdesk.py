"""Freshdesk — built-in tool `freshdesk` (Freshdesk API v2 with an API key).

Actions: ``list`` (recently updated tickets, filtered by the input text; input with a ``:`` is sent
as a Freshdesk search query such as ``status:2 AND priority:3``), ``read`` (one ticket with its
conversation) and ``create`` (a ticket from ``requester_email``: the first line is the subject, the
rest the description). ``auto`` reads a ticket number (#123), creates on "create: …", and lists
otherwise.
"""

import re
from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[Freshdesk]"
STATUS = {2: "Open", 3: "Pending", 4: "Resolved", 5: "Closed"}
PRIORITY = {1: "Low", 2: "Medium", 3: "High", 4: "Urgent"}
_TICKET = re.compile(r"^#?(\d+)$")

TOOL = ToolSpec(
    id="freshdesk",
    name="Freshdesk",
    icon="🎧",
    category="Business Apps",
    description="Lists or searches Freshdesk tickets, reads one with its conversation, or creates a ticket. Input: filter text, a ticket number like #123, or 'create: Subject' + description.",
    default_config={"domain": "", "api_key": "", "action": "auto", "requester_email": "", "max_results": 20},
    order=108,
    required=("domain", "api_key"),
    selects={"action": Select("Action", (("auto", "Auto (#123 → read, 'create:' → create, else list)"),
                                         ("list", "List / search tickets"), ("read", "Read ticket"), ("create", "Create ticket")))},
    parameters=params(
        {"request": {"type": "string", "description": "Filter text or a Freshdesk query (status:2), a ticket number (#123), or 'create: Subject' + the description on the next lines"}},
        {"action": enum(["auto", "list", "read", "create"], "What to do (auto works it out from the request)")},
    ),
    input_param="request",
)


def _line(t: Dict[str, Any], base: str) -> str:
    return (f"- #{t.get('id')} {t.get('subject', '')} · {STATUS.get(t.get('status'), t.get('status'))}"
            f" · {PRIORITY.get(t.get('priority'), t.get('priority'))} · updated {(t.get('updated_at') or '')[:10]}\n"
            f"  {base}/a/tickets/{t.get('id')}")


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    domain = (cfg.get("domain") or "").strip().lower()
    key = (cfg.get("api_key") or "").strip()
    if not domain:
        return f"{LABEL} domain (e.g. acme for acme.freshdesk.com) is required in config."
    if not key:
        return f"{LABEL} api_key (Profile settings → View API key) is required in config."
    domain = re.sub(r"^https?://", "", domain).split("/")[0]
    if "." not in domain:
        domain = f"{domain}.freshdesk.com"
    base = f"https://{domain}"
    text = inp.strip()
    action = (cfg.get("action") or "auto").strip().lower()
    if action == "auto":
        if text.lower().startswith("create:"):
            action, text = "create", text[len("create:"):].strip()
        else:
            action = "read" if _TICKET.match(text) else "list"
    elif action == "create" and text.lower().startswith("create:"):
        text = text[len("create:"):].strip()
    if action not in ("list", "read", "create"):
        return f'{LABEL} Action is "auto", "list", "read" or "create" — got "{action}".'
    limit = max(1, min(int(cfg.get("max_results") or 20), 100))

    try:
        async with httpx.AsyncClient(timeout=20.0, auth=(key, "X")) as client:
            if action == "read":
                m = _TICKET.match(text)
                if not m:
                    return f"{LABEL} Give a ticket number like #123."
                resp = await client.get(f"{base}/api/v2/tickets/{m.group(1)}", params={"include": "conversations,requester"})
                if resp.status_code == 200:
                    t = resp.json()
                    out = [f"{LABEL} #{t['id']}: {t.get('subject', '')}", f"{base}/a/tickets/{t['id']}",
                           f"Status: {STATUS.get(t.get('status'), t.get('status'))} · Priority: {PRIORITY.get(t.get('priority'), t.get('priority'))}"
                           f" · Requester: {(t.get('requester') or {}).get('email', '?')} · Created {(t.get('created_at') or '')[:10]}",
                           "", (t.get("description_text") or "(no description)")[:6000]]
                    convo = (t.get("conversations") or [])[-10:]
                    if convo:
                        out += ["", f"Conversation ({len(convo)} latest):"]
                        out += [f"- {'note' if c.get('private') else 'reply'} {(c.get('created_at') or '')[:10]}: {(c.get('body_text') or '')[:800]}"
                                for c in convo]
                    return "\n".join(out)
            elif action == "create":
                email = (cfg.get("requester_email") or "").strip()
                if not email:
                    return f"{LABEL} Set requester_email to create tickets."
                subject, _, desc = text.partition("\n")
                if not subject.strip():
                    return f"{LABEL} Provide the ticket subject."
                resp = await client.post(f"{base}/api/v2/tickets", json={
                    "subject": subject.strip(), "description": desc.strip() or subject.strip(),
                    "email": email, "status": 2, "priority": 1})
                if resp.status_code == 201:
                    t = resp.json()
                    return f"{LABEL} Created #{t['id']}: {t.get('subject')}\n{base}/a/tickets/{t['id']}"
            elif ":" in text:
                resp = await client.get(f"{base}/api/v2/search/tickets", params={"query": f'"{text}"'})
                if resp.status_code == 200:
                    tickets = resp.json().get("results") or []
                    if not tickets:
                        return f"{LABEL} No tickets match {text}."
                    return f"{LABEL} {resp.json().get('total', len(tickets))} ticket(s) for {text}\n\n" + "\n".join(
                        _line(t, base) for t in tickets[:limit])
            else:
                resp = await client.get(f"{base}/api/v2/tickets", params={"order_by": "updated_at", "per_page": 100})
                if resp.status_code == 200:
                    tickets = resp.json()
                    if text:
                        tickets = [t for t in tickets if text.lower() in (t.get("subject") or "").lower()]
                    if not tickets:
                        return f"{LABEL} No recent tickets" + (f" with '{text}' in the subject." if text else ".")
                    return f"{LABEL} {len(tickets)} recent ticket(s)" + (f" matching '{text}'" if text else "") + "\n\n" + "\n".join(
                        _line(t, base) for t in tickets[:limit])
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach {domain}: {e}"
    if resp.status_code == 401:
        return f"{LABEL} The api_key is invalid."
    if resp.status_code == 404:
        return f"{LABEL} Not found — check the ticket number or domain."
    try:
        errors = resp.json().get("errors") or []
        detail = "; ".join(f"{e.get('field', '')}: {e.get('message', '')}".strip(": ") for e in errors) or resp.json().get("description")
    except (ValueError, AttributeError):
        detail = None
    return f"{LABEL} HTTP {resp.status_code}: {detail or resp.text[:200]}"
