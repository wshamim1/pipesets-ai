"""Company Jobs — built-in tool `company_jobs` (public Greenhouse, Lever and Ashby job-board APIs, no key).

Many companies host their careers page on one of these, and each publishes its open roles as a public
API meant for exactly this. Input is the company's board name — usually its name, e.g. ``stripe`` or
``netflix`` — optionally prefixed with the platform (``greenhouse:stripe``, ``lever:netflix``,
``ashby:linear``); without a prefix the three are tried in turn. ``filter`` keeps roles whose title,
team or location contains the text.
"""

from typing import Any, Dict, List, Optional, Tuple

import httpx

from tools.base import Select, ToolSpec, params

LABEL = "[Company Jobs]"
PLATFORMS = ("greenhouse", "lever", "ashby")

TOOL = ToolSpec(
    id="company_jobs",
    name="Company Jobs",
    icon="🏢",
    category="Jobs & Careers",
    description="Lists a company's open roles from its Greenhouse, Lever or Ashby careers board (public APIs, no key). Input: the company's board name, e.g. stripe, or greenhouse:stripe.",
    default_config={"filter": "", "lever_region": "global", "max_results": 30},
    order=40,
    selects={"lever_region": Select("Lever region", (("global", "Global (api.lever.co)"), ("eu", "EU (api.eu.lever.co)")))},
    parameters=params({"company": {"type": "string", "description": "Board name, e.g. stripe, or platform:name (greenhouse:, lever:, ashby:)"}},
                      {"filter": {"type": "string", "description": "Only roles whose title, team or location contains this, e.g. 'engineer' or 'Bengaluru'"}}),
    input_param="company",
    is_new=True,
)

Job = Tuple[str, str, str, str, str]   # title, team, location, kind, url


async def _greenhouse(client: httpx.AsyncClient, board: str, cfg: Dict[str, Any]) -> Optional[List[Job]]:
    r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", params={"content": "true"})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return [(j.get("title", ""), ", ".join(d.get("name", "") for d in j.get("departments") or []),
             (j.get("location") or {}).get("name", ""), "", j.get("absolute_url", "")) for j in r.json().get("jobs") or []]


async def _lever(client: httpx.AsyncClient, board: str, cfg: Dict[str, Any]) -> Optional[List[Job]]:
    host = "api.eu.lever.co" if cfg.get("lever_region") == "eu" else "api.lever.co"
    r = await client.get(f"https://{host}/v0/postings/{board}", params={"mode": "json"})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    out = []
    for p in r.json() or []:
        c = p.get("categories") or {}
        out.append((p.get("text", ""), c.get("team") or c.get("department") or "", c.get("location", ""),
                    " · ".join(x for x in (c.get("commitment"), p.get("workplaceType") if p.get("workplaceType") != "unspecified" else "") if x),
                    p.get("hostedUrl", "")))
    return out


async def _ashby(client: httpx.AsyncClient, board: str, cfg: Dict[str, Any]) -> Optional[List[Job]]:
    r = await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{board}", params={"includeCompensation": "true"})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs") or []:
        if j.get("isListed") is False:
            continue
        pay = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        out.append((j.get("title", ""), j.get("team") or j.get("department") or "", j.get("location", ""),
                    " · ".join(x for x in (j.get("employmentType"), j.get("workplaceType"), pay) if x), j.get("jobUrl", "")))
    return out


FETCH = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    ref = inp.strip().strip("'\"").lower()
    platform, _, board = ref.partition(":") if ":" in ref else ("", "", ref)
    board = board.strip().strip("/")
    if not board or not all(ch.isalnum() or ch in "-_." for ch in board):
        return f"{LABEL} Input is a company board name, e.g. stripe, or greenhouse:stripe / lever:netflix / ashby:linear."
    if platform and platform not in PLATFORMS:
        return f"{LABEL} Platform is one of {', '.join(PLATFORMS)} — got '{platform}'."
    tried = [platform] if platform else list(PLATFORMS)
    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"Accept": "application/json"}) as client:
            for name in tried:
                jobs = await FETCH[name](client, board, cfg)
                if jobs is not None:
                    break
            else:
                return f"{LABEL} No {' / '.join(p.capitalize() for p in tried)} job board named '{board}'. Check the name in the company's careers URL."
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't read the {name} board '{board}': {e}"
    text = str(cfg.get("filter") or "").strip().lower()
    total = len(jobs)
    if text:
        jobs = [j for j in jobs if any(text in field.lower() for field in j[:3])]
    if not jobs:
        return f"{LABEL} {board} ({name}) has {total} open role(s), none matching '{text}'." if text else f"{LABEL} {board} ({name}) has no open roles."
    limit = max(1, min(int(cfg.get("max_results") or 30), 200))
    lines = [f"{LABEL} {len(jobs)} open role(s) at {board} on {name.capitalize()}" + (f" matching '{text}'" if text else "")
             + (f" (showing {limit})" if len(jobs) > limit else "")]
    lines += [f"- {t.strip()}" + (f" · {team}" if team else "") + (f" · {loc}" if loc else "") + (f" · {kind}" if kind else "") + f"\n    {url}"
              for t, team, loc, kind, url in jobs[:limit]]
    return "\n".join(lines)
