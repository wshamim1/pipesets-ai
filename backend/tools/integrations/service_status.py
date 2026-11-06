"""Service Status — built-in tool `service_status` (public Atlassian Statuspage pages, no key).

Input: a provider name from ``KNOWN`` (github, openai, cloudflare, …) or any Statuspage URL. Returns
the overall status, the components that aren't operational and the open incidents, from the page's
``/api/v2/summary.json``. Several inputs separated by commas are checked together — "is it us or
them?" during an incident.
"""

from typing import Any, Dict, List, Optional

import httpx

from tools.base import ToolSpec, params

LABEL = "[Service Status]"
# Providers whose status pages run on Statuspage (and so serve /api/v2/summary.json)
KNOWN = {
    "github": "https://www.githubstatus.com", "openai": "https://status.openai.com",
    "anthropic": "https://status.anthropic.com", "cloudflare": "https://www.cloudflarestatus.com",
    "atlassian": "https://status.atlassian.com", "jira": "https://jira-software.status.atlassian.com",
    "vercel": "https://www.vercel-status.com",
    "netlify": "https://www.netlifystatus.com", "twilio": "https://status.twilio.com",
    "discord": "https://discordstatus.com", "dropbox": "https://status.dropbox.com",
    "zoom": "https://status.zoom.us", "npm": "https://status.npmjs.org", "reddit": "https://www.redditstatus.com",
    "digitalocean": "https://status.digitalocean.com", "snowflake": "https://status.snowflake.com",
    "mongodb": "https://status.mongodb.com",
    "confluent": "https://status.confluent.cloud", "sendgrid": "https://status.sendgrid.com",
    "hubspot": "https://status.hubspot.com", "linear": "https://linearstatus.com",
}

TOOL = ToolSpec(
    id="service_status",
    name="Service Status",
    icon="🟢",
    category="APIs & Integrations",
    description="Checks the public status pages of SaaS providers (GitHub, OpenAI, Cloudflare, Snowflake, … or any Statuspage URL): overall status, degraded components and open incidents. Free, no key.",
    default_config={},
    order=104,
    parameters=params({"services": {"type": "string", "description": "Provider names or Statuspage URLs, comma-separated (e.g. 'github, openai')"}}),
    input_param="services",
    is_new=True,
)


def _url(name: str) -> Optional[str]:
    key = name.strip().lower()
    if key in KNOWN:
        return KNOWN[key]
    if key.startswith(("http://", "https://")):
        return key.rstrip("/").removesuffix("/api/v2/summary.json")
    if "." in key:
        return f"https://{key.rstrip('/')}"
    return None


async def _check(client: httpx.AsyncClient, name: str) -> str:
    url = _url(name)
    if not url:
        return f"- {name}: unknown provider — give its status page URL (known: {', '.join(sorted(KNOWN))})"
    try:
        resp = await client.get(f"{url}/api/v2/summary.json")
    except httpx.HTTPError as e:
        return f"- {name}: couldn't reach {url} ({e})"
    if resp.status_code >= 400 or "json" not in resp.headers.get("content-type", ""):
        return f"- {name}: {url} isn't a Statuspage status page (HTTP {resp.status_code})"
    data = resp.json()
    overall = (data.get("status") or {}).get("description") or "unknown"
    lines = [f"- {(data.get('page') or {}).get('name') or name}: {overall}"]
    broken: List[Dict[str, Any]] = [c for c in data.get("components") or []
                                    if c.get("status") not in ("operational", None) and not c.get("group")]
    lines += [f"    ⚠ {c.get('name')}: {c.get('status', '').replace('_', ' ')}" for c in broken[:10]]
    for inc in data.get("incidents") or []:
        latest = (inc.get("incident_updates") or [{}])[0]
        lines.append(f"    🔴 {inc.get('name')} ({inc.get('status')}, {inc.get('impact')}) since "
                     f"{(inc.get('started_at') or inc.get('created_at') or '')[:16].replace('T', ' ')}"
                     + (f": {' '.join(latest['body'].split())[:200]}" if latest.get("body") else "") + f"\n      {inc.get('shortlink') or ''}")
    for m in [m for m in data.get("scheduled_maintenances") or [] if m.get("status") == "in_progress"]:
        lines.append(f"    🛠 Maintenance in progress: {m.get('name')}")
    return "\n".join(lines)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    names = [n for n in (p.strip().strip("'\"") for p in inp.split(",")) if n]
    if not names:
        return f"{LABEL} Name the services to check, e.g. 'github, openai' (known: {', '.join(sorted(KNOWN))})."
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        results = [await _check(client, n) for n in names[:10]]
    return f"{LABEL}\n" + "\n".join(results)
