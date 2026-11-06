"""Jooble — built-in tool `jooble_jobs` (Jooble REST API; a free key from jooble.org/api/about).

A job-search aggregator covering 60+ countries, including India. Input is the keywords, ``location``
narrows it. Returns title, company, location, salary when given, the source site and the link.
"""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

LABEL = "[Jooble]"

TOOL = ToolSpec(
    id="jooble_jobs",
    name="Jooble Jobs",
    icon="🔎",
    category="Jobs & Careers",
    description="Searches jobs in 60+ countries (India included) via the Jooble API: title, company, location, salary, source and link. Input: keywords.",
    default_config={"api_key": "", "location": "", "max_results": 10},
    order=30,
    required=("api_key",),
    parameters=params({"keywords": {"type": "string", "description": "Keywords, e.g. 'react developer'"}},
                      {"location": {"type": "string", "description": "City, region or country"}}),
    input_param="keywords",
    is_new=True,
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    key = str(cfg.get("api_key") or "").strip()
    if not key:
        return f"{LABEL} api_key is required in config (request one at jooble.org/api/about)."
    body = {"keywords": inp.strip(), "location": str(cfg.get("location") or "").strip(), "page": "1"}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(f"https://jooble.org/api/{key}", json=body)
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach Jooble: {e}"
    if resp.status_code in (401, 403):
        return f"{LABEL} HTTP {resp.status_code} — check api_key."
    if resp.status_code >= 400:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    jobs = (data.get("jobs") or [])[:max(1, min(int(cfg.get("max_results") or 10), 50))]
    if not jobs:
        return f"{LABEL} No jobs for '{body['keywords']}'" + (f" in {body['location']}." if body["location"] else ".")
    lines = [f"{LABEL} {len(jobs)} of {data.get('totalCount', len(jobs))} job(s)"]
    for j in jobs:
        lines.append(f"- {j.get('title')} · {j.get('company') or ''} · {j.get('location') or ''}"
                     + (f" · {j['salary']}" if j.get("salary") else "") + (f" · {j['type']}" if j.get("type") else "")
                     + f" · via {j.get('source') or 'Jooble'} · {(j.get('updated') or '')[:10]}\n    {j.get('link')}")
    return "\n".join(lines)
