"""Google Jobs — built-in tool `google_jobs` (SerpApi's Google Jobs engine).

Google Jobs indexes postings from LinkedIn, Indeed, Naukri, Glassdoor, company career sites and many
others, so this is the permitted way to search them: each result says where it was posted ("via
LinkedIn") and lists its apply links. Input is the search, e.g. "data engineer"; ``location`` (city
level works best) and ``gl`` (country) narrow it. ``next_page_token`` from a result gets the next page.
"""

import os
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

LABEL = "[Google Jobs]"

TOOL = ToolSpec(
    id="google_jobs",
    name="Google Jobs",
    icon="💼",
    category="Jobs & Careers",
    description="Searches job listings across LinkedIn, Indeed, Naukri, Glassdoor and company sites via Google Jobs (SerpApi): title, company, location, salary, where it was posted and apply links. Input: the job search.",
    default_config={"api_key": "", "location": "", "gl": "", "hl": "en", "max_results": 10},
    order=10,
    required=("api_key",),
    parameters=params({"query": {"type": "string", "description": "Job search, e.g. 'senior data engineer'"}},
                      {"location": {"type": "string", "description": "City or region, e.g. 'Bengaluru, Karnataka, India'"},
                       "gl": {"type": "string", "description": "Two-letter country code, e.g. in, us, gb"},
                       "next_page_token": {"type": "string", "description": "From a previous result, for the next page"}}),
    input_param="query",
    is_new=True,
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    key = (cfg.get("api_key") or os.environ.get("SERPAPI_API_KEY", "")).strip()
    if not key:
        return f"{LABEL} api_key (a SerpApi key) is required in config."
    query = inp.strip()
    if not query:
        return f"{LABEL} Provide a job search, e.g. 'data engineer'."
    q: Dict[str, Any] = {"engine": "google_jobs", "q": query, "api_key": key, "hl": cfg.get("hl") or "en"}
    for k in ("location", "gl", "next_page_token"):
        if str(cfg.get(k) or "").strip():
            q[k] = str(cfg[k]).strip()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get("https://serpapi.com/search.json", params=q)
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach SerpApi: {e}"
    if resp.status_code == 401:
        return f"{LABEL} HTTP 401 — check the SerpApi api_key."
    data = resp.json() if "json" in resp.headers.get("content-type", "") else {}
    if resp.status_code >= 400 or data.get("error"):
        if "hasn't returned any results" in str(data.get("error", "")):
            return f"{LABEL} No jobs found for '{query}'" + (f" in {q['location']}." if "location" in q else ".")
        return f"{LABEL} {data.get('error') or f'HTTP {resp.status_code}'}"
    jobs = (data.get("jobs_results") or [])[:max(1, min(int(cfg.get("max_results") or 10), 10))]
    if not jobs:
        return f"{LABEL} No jobs found for '{query}'."
    lines = [f"{LABEL} {len(jobs)} job(s) for '{query}'" + (f" in {q['location']}" if "location" in q else "")]
    for j in jobs:
        ext = j.get("detected_extensions") or {}
        bits = [b for b in (ext.get("posted_at"), ext.get("schedule_type"), ext.get("salary")) if b]
        lines.append(f"- {j.get('title')} · {j.get('company_name')} · {j.get('location')} · {j.get('via', '')}"
                     + (f" · {' · '.join(bits)}" if bits else ""))
        for a in (j.get("apply_options") or [])[:3]:
            lines.append(f"    apply on {a.get('title')}: {a.get('link')}")
    token = (data.get("serpapi_pagination") or {}).get("next_page_token")
    if token:
        lines.append(f"More: next_page_token={token}")
    return "\n".join(lines)
