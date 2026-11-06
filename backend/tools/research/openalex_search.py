"""OpenAlex scholarly search — built-in tool `openalex_search`."""

import os
from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, query_params

TOOL = ToolSpec(
    id="openalex_search",
    name="OpenAlex Scholarly Search",
    icon="🏛️",
    category="Research & Knowledge",
    description="Searches 250M+ scholarly works across all fields: titles, authors, venue, year, citation counts and open-access links (free; API key optional for higher limits).",
    default_config={"max_results": 5, "sort": "relevance", "open_access_only": False, "from_year": "", "api_key": ""},
    order=110,
    selects={
        "sort": Select("Sort by", (("relevance", "Relevance"), ("cited_by_count", "Most cited"), ("publication_date", "Newest"))),
    },
    parameters=query_params("Search terms for scholarly works",
                            from_year={"type": "integer", "description": "Only works published from this year"},
                            open_access_only={"type": "boolean", "description": "Only open-access works"}),
    input_param="query",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    if not inp:
        return "[OpenAlex] Please provide a search query."
    filters = []
    if str(cfg.get("open_access_only", False)).lower() == "true":
        filters.append("is_oa:true")
    if str(cfg.get("from_year", "")).strip().isdigit():
        filters.append(f"from_publication_date:{str(cfg['from_year']).strip()}-01-01")
    params: Dict[str, Any] = {"search": inp, "per-page": int(cfg.get("max_results", 5)), "mailto": "tools@pipesets.ai"}
    sort = cfg.get("sort", "relevance")
    if sort in ("cited_by_count", "publication_date"):
        params["sort"] = f"{sort}:desc"
    if filters:
        params["filter"] = ",".join(filters)
    api_key = cfg.get("api_key") or os.environ.get("OPENALEX_API_KEY", "")
    if api_key:
        params["api_key"] = api_key
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get("https://api.openalex.org/works", params=params)
        if resp.status_code == 429:
            return "[OpenAlex] Daily free quota reached for this server — add an OpenAlex API key in config."
        resp.raise_for_status()
        works = resp.json().get("results", [])
        if not works:
            return f"[OpenAlex] No works found for: {inp}"
        lines = [f"[OpenAlex: '{inp}']\n"]
        for i, w in enumerate(works, 1):
            authors = [a.get("author", {}).get("display_name", "") for a in w.get("authorships", [])[:3]]
            more = " et al." if len(w.get("authorships", [])) > 3 else ""
            venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name", "")
            oa = (w.get("open_access") or {}).get("oa_url")
            link = w.get("doi") or w.get("id", "")
            lines.append(f"{i}. {w.get('display_name', '')} ({w.get('publication_year', '?')})\n"
                         f"   {', '.join(authors)}{more}" + (f" — {venue}" if venue else "")
                         + f"\n   cited by {w.get('cited_by_count', 0):,} · {link}" + (f"\n   open access: {oa}" if oa else ""))
        return "\n".join(lines)
    except Exception as e:
        return f"[OpenAlex] Error: {e}"
