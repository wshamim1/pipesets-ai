"""Adzuna — built-in tool `adzuna_jobs` (Adzuna job search API, free app id + key).

Aggregated job ads in many countries, including India, the UK, the US, Germany, Australia and Canada.
Input is the keywords; ``where`` narrows the location, ``country`` picks the market, ``max_days_old`` keeps
it fresh. Returns title, company, location, salary range when given, contract and the ad link.
"""

from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, params

LABEL = "[Adzuna]"
COUNTRIES = (("in", "India"), ("gb", "United Kingdom"), ("us", "United States"), ("ca", "Canada"), ("au", "Australia"),
             ("de", "Germany"), ("fr", "France"), ("nl", "Netherlands"), ("sg", "Singapore"), ("za", "South Africa"),
             ("nz", "New Zealand"), ("es", "Spain"), ("it", "Italy"), ("pl", "Poland"), ("br", "Brazil"), ("mx", "Mexico"),
             ("at", "Austria"), ("be", "Belgium"), ("ch", "Switzerland"))

TOOL = ToolSpec(
    id="adzuna_jobs",
    name="Adzuna Jobs",
    icon="🧭",
    category="Jobs & Careers",
    description="Searches job ads in India, the UK, US, Europe and more via the Adzuna API: title, company, location, salary range and link. Input: keywords.",
    default_config={"app_id": "", "app_key": "", "country": "in", "where": "", "max_days_old": 30, "max_results": 10},
    order=20,
    required=("app_id", "app_key"),
    selects={"country": Select("Country", COUNTRIES)},
    parameters=params({"what": {"type": "string", "description": "Keywords, e.g. 'python developer'"}},
                      {"where": {"type": "string", "description": "City or region"},
                       "country": {"type": "string", "enum": [c for c, _ in COUNTRIES], "description": "Market"},
                       "max_days_old": {"type": "integer", "minimum": 1, "maximum": 90, "description": "Only ads this recent"}}),
    input_param="what",
    is_new=True,
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    app_id, app_key = str(cfg.get("app_id") or "").strip(), str(cfg.get("app_key") or "").strip()
    if not app_id or not app_key:
        return f"{LABEL} app_id and app_key are required in config (free at developer.adzuna.com)."
    country = str(cfg.get("country") or "in").lower()
    if country not in dict(COUNTRIES):
        return f"{LABEL} country is one of {', '.join(c for c, _ in COUNTRIES)} — got '{country}'."
    q: Dict[str, Any] = {"app_id": app_id, "app_key": app_key, "what": inp.strip(), "sort_by": "date",
                         "results_per_page": max(1, min(int(cfg.get("max_results") or 10), 50)),
                         "max_days_old": int(cfg.get("max_days_old") or 30), "content-type": "application/json"}
    if str(cfg.get("where") or "").strip():
        q["where"] = cfg["where"].strip()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1", params=q)
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach Adzuna: {e}"
    if resp.status_code in (401, 403):
        return f"{LABEL} HTTP {resp.status_code} — check app_id and app_key."
    if resp.status_code >= 400:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    results = data.get("results") or []
    if not results:
        return f"{LABEL} No jobs for '{inp.strip()}' in {dict(COUNTRIES)[country]}" + (f" ({q['where']})." if "where" in q else ".")
    lines = [f"{LABEL} {len(results)} of {data.get('count', len(results))} job(s) in {dict(COUNTRIES)[country]}, newest first"]
    for r in results:
        lo, hi = r.get("salary_min"), r.get("salary_max")
        salary = f"{lo:,.0f}–{hi:,.0f}" if lo and hi and lo != hi else (f"{lo:,.0f}" if lo else "")
        lines.append(f"- {r.get('title')} · {(r.get('company') or {}).get('display_name', '')} · "
                     f"{(r.get('location') or {}).get('display_name', '')}"
                     + (f" · {salary}{' (estimated)' if str(r.get('salary_is_predicted')) == '1' else ''}" if salary else "")
                     + (f" · {r.get('contract_time')}" if r.get("contract_time") else "")
                     + f" · {(r.get('created') or '')[:10]}\n    {r.get('redirect_url')}")
    return "\n".join(lines)
