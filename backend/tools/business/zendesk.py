"""Zendesk Support — built-in tool `zendesk`."""

import re
from typing import Any, Dict, Optional

import httpx

from tools.base import MAX_RESULTS, Select, ToolSpec, params

TOOL = ToolSpec(
    id="zendesk",
    name="Zendesk",
    icon="🎧",
    category="Business Apps",
    description="Searches Zendesk tickets, reads a ticket with its latest comments, or creates a ticket. Input: a ticket number, search text (Zendesk search syntax works), or 'create: Subject' + description.",
    default_config={"subdomain": "", "email": "", "api_token": "", "action": "auto", "priority": "normal", "max_results": 10},
    order=40,
    required=("subdomain", "email", "api_token"),
    selects={
        "action": Select("Action", (("auto", "Auto (number → read, 'create:' → create, else search)"),
                                    ("search", "Search"), ("get", "Read ticket"), ("create", "Create ticket"))),
        "priority": Select("Priority for new tickets", (("low", "Low"), ("normal", "Normal"), ("high", "High"), ("urgent", "Urgent"))),
    },
    parameters=params(
        {
            "request": {"type": "string", "description": "A ticket number, search text (Zendesk syntax), or 'create: Subject' + a description on the next lines"},
        },
        {"max_results": MAX_RESULTS},
    ),
    input_param="request",
)


def _error(resp: httpx.Response) -> str:
    if resp.status_code == 401:
        return "[Zendesk] Authentication failed — check the email, API token and that token access is enabled."
    if resp.status_code == 404:
        return "[Zendesk] Not found."
    try:
        body = resp.json()
        detail = body.get("description") or body.get("error") or str(body.get("details", ""))
    except ValueError:
        detail = resp.text[:300]
    return f"[Zendesk] HTTP {resp.status_code}: {detail}"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    sub = re.sub(r"^https?://", "", (cfg.get("subdomain") or "").strip()).split(".")[0]
    email, token = (cfg.get("email") or "").strip(), (cfg.get("api_token") or "").strip()
    if not (sub and email and token):
        return "[Zendesk] subdomain, email and api_token are required in config."
    base, agent = f"https://{sub}.zendesk.com/api/v2", f"https://{sub}.zendesk.com/agent/tickets"
    text = inp.strip()
    action = cfg.get("action", "auto")
    if action == "auto":
        if text.lower().startswith("create:"):
            action, text = "create", text[len("create:"):].strip()
        elif re.fullmatch(r"#?\d+", text):
            action = "get"
        else:
            action = "search"
    if not text:
        return "[Zendesk] Provide a ticket number, search text or the ticket to create."

    async with httpx.AsyncClient(timeout=20.0, auth=(f"{email}/token", token)) as client:
        if action == "get":
            tid = text.lstrip("#")
            resp = await client.get(f"{base}/tickets/{tid}.json")
            if resp.status_code != 200:
                return _error(resp)
            t = resp.json().get("ticket", {})
            comments = await client.get(f"{base}/tickets/{tid}/comments.json", params={"sort_order": "desc", "per_page": 4})
            out = [f"[Zendesk #{t.get('id')}] {t.get('subject', '')}",
                   f"   status {t.get('status', '?')} · priority {t.get('priority') or 'none'} · "
                   f"created {(t.get('created_at') or '')[:10]} · updated {(t.get('updated_at') or '')[:10]}",
                   f"   tags: {', '.join(t.get('tags', [])) or 'none'}", f"   {agent}/{t.get('id')}", "",
                   (t.get("description") or "")[:3000]]
            if comments.status_code == 200:
                latest = comments.json().get("comments", [])[:3]
                if latest:
                    out.append("\nLatest comments:")
                    for c in latest:
                        out.append(f"- {'public' if c.get('public') else 'internal'} ({(c.get('created_at') or '')[:10]}): "
                                   f"{(c.get('plain_body') or c.get('body') or '').strip()[:500]}")
            return "\n".join(out)

        if action == "create":
            subject, _, description = text.partition("\n")
            resp = await client.post(f"{base}/tickets.json", json={"ticket": {
                "subject": subject.strip()[:255], "comment": {"body": description.strip() or subject.strip()},
                "priority": cfg.get("priority") or "normal"}})
            if resp.status_code not in (200, 201):
                return _error(resp)
            t = resp.json().get("ticket", {})
            return f"[Zendesk] Created ticket #{t.get('id')}: {subject.strip()}\n   {agent}/{t.get('id')}"

        resp = await client.get(f"{base}/search.json", params={
            "query": f"type:ticket {text}", "sort_by": "updated_at", "sort_order": "desc",
            "per_page": int(cfg.get("max_results", 10))})
        if resp.status_code != 200:
            return _error(resp)
        tickets = resp.json().get("results", [])
        if not tickets:
            return f"[Zendesk] No tickets match: {text}"
        lines = [f"[Zendesk: '{text}']\n"]
        for t in tickets:
            lines.append(f"#{t.get('id')} [{t.get('status', '?')}] {t.get('subject', '')} — priority {t.get('priority') or 'none'}, "
                         f"updated {(t.get('updated_at') or '')[:10]}\n   {agent}/{t.get('id')}")
        return "\n".join(lines)
