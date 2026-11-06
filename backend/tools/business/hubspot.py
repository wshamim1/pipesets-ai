"""HubSpot — built-in tool `hubspot` (CRM API v3 with a private app access token).

Actions: ``search`` (contacts, companies or deals matching text) and ``create`` (one record from
a JSON object of properties; for contacts a bare email address also works). Private app scopes:
crm.objects.<object>.read, plus .write to create.
"""

import json
import re
from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[HubSpot]"
API = "https://api.hubapi.com/crm/v3/objects"
OBJECTS = ("contacts", "companies", "deals")
PROPERTIES = {
    "contacts": ["firstname", "lastname", "email", "phone", "company", "jobtitle", "lifecyclestage"],
    "companies": ["name", "domain", "industry", "city", "country", "numberofemployees"],
    "deals": ["dealname", "amount", "dealstage", "pipeline", "closedate"],
}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

TOOL = ToolSpec(
    id="hubspot",
    name="HubSpot",
    icon="🧲",
    category="Business Apps",
    description="Searches HubSpot CRM contacts, companies or deals, or creates one. Input: search text (search), or a JSON object of properties — or just an email for a contact (create).",
    default_config={"access_token": "", "object": "contacts", "action": "search", "max_results": 10},
    order=60,
    required=("access_token",),
    selects={
        "object": Select("Object", (("contacts", "Contacts"), ("companies", "Companies"), ("deals", "Deals"))),
        "action": Select("Action", (("search", "Search"), ("create", "Create"))),
    },
    parameters=params(
        {"request": {"type": "string", "description": "Search text (search), or a JSON object of properties to create, e.g. {\"email\": \"a@b.com\", \"firstname\": \"Ada\"}"}},
        {
            "action": enum(["search", "create"], "search = find records, create = add one"),
            "object": enum(list(OBJECTS), "Which CRM object"),
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Records to return (search)"},
        },
    ),
    input_param="request",
)


def _error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        body = {}
    msg = body.get("message") or resp.text[:200]
    if resp.status_code == 401:
        return f"{LABEL} The access_token is invalid or expired."
    if resp.status_code == 403:
        return f"{LABEL} The private app is missing a scope: {msg}"
    if resp.status_code == 409:
        return f"{LABEL} That record already exists: {msg}"
    return f"{LABEL} HTTP {resp.status_code}: {msg}"


def _line(obj: str, r: Dict[str, Any]) -> str:
    p = r.get("properties") or {}
    if obj == "contacts":
        name = " ".join(x for x in (p.get("firstname"), p.get("lastname")) if x) or "(no name)"
        extra = [p.get("email"), p.get("jobtitle"), p.get("company"), p.get("phone"), p.get("lifecyclestage")]
    elif obj == "companies":
        name = p.get("name") or "(no name)"
        extra = [p.get("domain"), p.get("industry"), p.get("city"), p.get("country")]
    else:
        name = p.get("dealname") or "(no name)"
        extra = [f"amount {p['amount']}" if p.get("amount") else None, p.get("dealstage"),
                 f"closes {p['closedate'][:10]}" if p.get("closedate") else None]
    return f"- {name} (id {r.get('id')})" + "".join(f" · {x}" for x in extra if x)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("access_token") or "").strip()
    if not token:
        return f"{LABEL} access_token (a private app token, pat-…) is required in config."
    obj = (cfg.get("object") or "contacts").strip().lower()
    if obj not in OBJECTS:
        return f"{LABEL} object is one of {', '.join(OBJECTS)} — got \"{obj}\"."
    action = (cfg.get("action") or "search").strip().lower()
    if action not in ("search", "create"):
        return f'{LABEL} Action is "search" or "create" — got "{action}".'
    text = inp.strip()

    async with httpx.AsyncClient(timeout=20.0, headers={"Authorization": f"Bearer {token}"}) as client:
        if action == "create":
            try:
                props = json.loads(text)
            except ValueError:
                props = {"email": text} if obj == "contacts" and _EMAIL.match(text) else None
            if not isinstance(props, dict) or not props:
                return f"{LABEL} To create, give a JSON object of properties (e.g. {{\"{PROPERTIES[obj][0]}\": \"…\"}})."
            resp = await client.post(f"{API}/{obj}", json={"properties": {k: str(v) for k, v in props.items()}})
            if resp.status_code not in (200, 201):
                return _error(resp)
            return f"{LABEL} Created {obj[:-1] if obj != 'companies' else 'company'}\n{_line(obj, resp.json())}"

        if not text:
            return f"{LABEL} Provide text to search for."
        limit = max(1, min(int(cfg.get("max_results") or 10), 100))
        resp = await client.post(f"{API}/{obj}/search", json={"query": text, "limit": limit,
                                                              "properties": PROPERTIES[obj]})
        if resp.status_code != 200:
            return _error(resp)
        body = resp.json()
        results = body.get("results", [])
        if not results:
            return f"{LABEL} No {obj} match '{text}'."
        return (f"{LABEL} {body.get('total', len(results))} {obj} match '{text}' (showing {len(results)})\n\n"
                + "\n".join(_line(obj, r) for r in results))
