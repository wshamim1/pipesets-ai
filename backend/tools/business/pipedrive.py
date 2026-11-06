"""Pipedrive — built-in tool `pipedrive` (Pipedrive API v2 with a personal API token; read-only).

Input: empty lists open deals, most recently updated first; ``#123`` reads that deal with its person
and organization; anything else searches deals, people and organizations.
"""

import re
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

LABEL = "[Pipedrive]"
_DEAL = re.compile(r"^#?(\d+)$")
_DOMAIN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

TOOL = ToolSpec(
    id="pipedrive",
    name="Pipedrive",
    icon="🤝",
    category="Business Apps",
    description="Pipedrive CRM (read-only): open deals, one deal with its contact and organization, or a search across deals, people and organizations. Input: empty, a deal number like #123, or search text.",
    default_config={"company_domain": "", "api_token": "", "max_results": 20},
    order=109,
    required=("company_domain", "api_token"),
    parameters=params({}, {"request": {"type": "string", "description": "A deal number (#123), search text, or empty for open deals"}}),
    input_param="request",
    is_new=True,
)


def _money(d: Dict[str, Any]) -> str:
    return f"{d['value']:,} {d.get('currency') or ''}".strip() if isinstance(d.get("value"), (int, float)) else ""


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    domain = re.sub(r"^https?://", "", str(cfg.get("company_domain") or "").strip().lower()).split(".")[0]
    token = str(cfg.get("api_token") or "").strip()
    if not domain:
        return f"{LABEL} company_domain (acme for acme.pipedrive.com) is required in config."
    if not token:
        return f"{LABEL} api_token (Personal preferences → API) is required in config."
    if not _DOMAIN.match(domain):
        return f"{LABEL} company_domain is the acme in acme.pipedrive.com — got '{domain}'."
    base = f"https://{domain}.pipedrive.com/api/v2"
    app = f"https://{domain}.pipedrive.com"
    text = inp.strip()
    limit = max(1, min(int(cfg.get("max_results") or 20), 100))
    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"x-api-token": token, "Accept": "application/json"}) as client:
            m = _DEAL.match(text)
            if m:
                resp = await client.get(f"{base}/deals/{m.group(1)}")
                person = org = None
                if resp.status_code == 200:
                    d = resp.json().get("data") or {}
                    if d.get("person_id"):
                        person = await client.get(f"{base}/persons/{d['person_id']}")
                    if d.get("org_id"):
                        org = await client.get(f"{base}/organizations/{d['org_id']}")
            elif text:
                resp = await client.get(f"{base}/itemSearch", params={
                    "term": text, "item_types": "deal,person,organization", "limit": limit})
            else:
                resp = await client.get(f"{base}/deals", params={
                    "status": "open", "sort_by": "update_time", "sort_direction": "desc", "limit": limit})
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach {domain}.pipedrive.com: {e}"
    if resp.status_code == 401:
        return f"{LABEL} HTTP 401 — check api_token."
    if resp.status_code == 404:
        return f"{LABEL} Not found: {text or 'deals'} (check the deal number and company_domain)."
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("error")
        except ValueError:
            detail = None
        return f"{LABEL} HTTP {resp.status_code}: {detail or resp.text[:200]}"
    data = resp.json().get("data")

    if m:
        d = data or {}
        p = (person.json().get("data") or {}) if person is not None and person.status_code == 200 else {}
        o = (org.json().get("data") or {}) if org is not None and org.status_code == 200 else {}
        emails = ", ".join(e.get("value", "") for e in p.get("emails") or [] if e.get("value"))
        return "\n".join(x for x in [
            f"{LABEL} Deal #{d.get('id')}: {d.get('title')}",
            f"  {app}/deal/{d.get('id')}",
            f"  Status: {d.get('status')} · Value: {_money(d) or '—'} · Stage {d.get('stage_id')} · Probability: {d.get('probability') if d.get('probability') is not None else '—'}",
            f"  Expected close: {d.get('expected_close_date') or '—'} · Updated {(d.get('update_time') or '')[:10]}"
            + (f" · Lost reason: {d['lost_reason']}" if d.get("lost_reason") else ""),
            f"  Contact: {p.get('name')}{' · ' + emails if emails else ''}" if p else "",
            f"  Organization: {o.get('name')}" if o else "",
        ] if x)
    if text:
        items = (data or {}).get("items") or []
        if not items:
            return f"{LABEL} Nothing matches '{text}'."
        lines = [f"{LABEL} {len(items)} result(s) for '{text}'"]
        for it in items:
            i = it.get("item") or {}
            kind = i.get("type")
            if kind == "deal":
                lines.append(f"- deal #{i.get('id')} {i.get('title')} · {i.get('status')} · {_money(i) or '—'}"
                             f"{' · ' + (i.get('organization') or {}).get('name', '') if i.get('organization') else ''}")
            else:
                extra = ", ".join(x for x in (i.get("emails") or [])[:2] if isinstance(x, str))
                lines.append(f"- {kind} #{i.get('id')} {i.get('name')}{' · ' + extra if extra else ''}"
                             f"{' · ' + (i.get('organization') or {}).get('name', '') if kind == 'person' and i.get('organization') else ''}")
        return "\n".join(lines)
    deals = data or []
    if not deals:
        return f"{LABEL} No open deals."
    return f"{LABEL} {len(deals)} open deal(s), most recently updated first\n" + "\n".join(
        f"- #{d.get('id')} {d.get('title')} · {_money(d) or '—'} · stage {d.get('stage_id')}"
        f" · close {d.get('expected_close_date') or '—'} · updated {(d.get('update_time') or '')[:10]}" for d in deals)
