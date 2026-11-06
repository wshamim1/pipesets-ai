"""DNS / WHOIS lookup — built-in tool `dns_whois`."""

import asyncio
import re
from typing import Any, Dict, List, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

TOOL = ToolSpec(
    id="dns_whois",
    name="DNS / WHOIS Lookup",
    icon="🧭",
    category="APIs & Integrations",
    description="DNS records (A, AAAA, MX, TXT, NS, CNAME) via DNS-over-HTTPS and domain registration details (registrar, created/expiry dates, status) via RDAP. Input is a domain.",
    default_config={"mode": "both", "record_types": "A,AAAA,MX,TXT,NS,CNAME"},
    order=90,
    selects={
        "mode": Select("Lookup", (("both", "DNS + WHOIS"), ("dns", "DNS only"), ("whois", "WHOIS only"))),
    },
    parameters=params(
        {"domain": {"type": "string", "description": "Domain, e.g. example.com"}},
        {"mode": enum(["both", "dns", "whois"], "DNS records, registration details, or both")},
    ),
    input_param="domain",
)

_TYPE_NAMES = {1: "A", 2: "NS", 5: "CNAME", 6: "SOA", 15: "MX", 16: "TXT", 28: "AAAA"}


async def _dns(client: httpx.AsyncClient, domain: str, types: List[str]) -> List[str]:
    async def one(rtype: str):
        r = await client.get("https://cloudflare-dns.com/dns-query", params={"name": domain, "type": rtype},
                             headers={"accept": "application/dns-json"})
        r.raise_for_status()
        return rtype, [a for a in r.json().get("Answer", []) if _TYPE_NAMES.get(a.get("type")) == rtype]

    lines = ["DNS records:"]
    for rtype, answers in await asyncio.gather(*(one(t) for t in types)):
        for a in answers:
            lines.append(f"  {rtype:5} {a.get('data', '')}  (TTL {a.get('TTL', '?')})")
    return lines if len(lines) > 1 else ["DNS records: none found"]


async def _whois(client: httpx.AsyncClient, domain: str) -> List[str]:
    r = await client.get(f"https://rdap.org/domain/{domain}", follow_redirects=True)
    if r.status_code in (400, 404):  # some registries answer 400 for subdomains
        return ["WHOIS: domain not found (or not registered)"]
    r.raise_for_status()
    d = r.json()
    events = {e.get("eventAction"): (e.get("eventDate") or "")[:10] for e in d.get("events", [])}
    registrar = ""
    for ent in d.get("entities", []):
        if "registrar" in ent.get("roles", []):
            for field in (ent.get("vcardArray") or [None, []])[1]:
                if field[0] == "fn":
                    registrar = field[3]
    nameservers = [ns.get("ldhName", "").lower() for ns in d.get("nameservers", [])]
    return ["WHOIS (RDAP):",
            f"  registrar : {registrar or 'unknown'}",
            f"  created   : {events.get('registration', '?')}",
            f"  expires   : {events.get('expiration', '?')}",
            f"  updated   : {events.get('last changed', '?')}",
            f"  status    : {', '.join(d.get('status', [])) or '?'}",
            f"  nameservers: {', '.join(nameservers) or '?'}"]


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    m = re.search(r"([a-z0-9-]+(?:\.[a-z0-9-]+)+)", inp.lower().replace("https://", "").replace("http://", ""))
    if not m:
        return "[DNS/WHOIS] Provide a domain, e.g. 'example.com'."
    domain = m.group(1).strip(".")
    mode = cfg.get("mode", "both")
    types = [t.strip().upper() for t in str(cfg.get("record_types", "A,AAAA,MX,TXT,NS,CNAME")).split(",")
             if t.strip().upper() in _TYPE_NAMES.values()]
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            sections = []
            if mode in ("both", "dns"):
                sections.append(await _dns(client, domain, types or ["A"]))
            if mode in ("both", "whois"):
                # RDAP only knows registered domains: strip subdomains until one is found
                # (works for multi-part suffixes like example.co.uk too)
                labels = domain.split(".")
                for i in range(len(labels) - 1):
                    found = await _whois(client, ".".join(labels[i:]))
                    if not found[0].startswith("WHOIS: domain not found") or i == len(labels) - 2:
                        break
                sections.append(found)
        return f"[DNS/WHOIS: {domain}]\n" + "\n\n".join("\n".join(s) for s in sections)
    except Exception as e:
        return f"[DNS/WHOIS] Error: {e}"
