"""Semantic Scholar — built-in tool `semantic_scholar_search` (Academic Graph API; free, key optional)."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, query_params

LABEL = "[Semantic Scholar]"
API = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,year,authors,venue,citationCount,url,abstract,externalIds,openAccessPdf"

TOOL = ToolSpec(
    id="semantic_scholar_search",
    name="Semantic Scholar",
    icon="🎓",
    category="Research & Knowledge",
    description="Searches 200M+ academic papers on Semantic Scholar: titles, authors, venues, citation counts, abstracts and open-access PDFs. Free; an API key raises the rate limit.",
    default_config={"api_key": "", "max_results": 5, "year": ""},
    order=140,
    parameters=query_params("Paper topic, title or keywords",
                            year={"type": "string", "description": "Publication year or range, e.g. 2023 or 2019-2024"}),
    input_param="query",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    if not inp:
        return f"{LABEL} Provide a search query."
    limit = max(1, min(int(cfg.get("max_results") or 5), 20))
    q: Dict[str, Any] = {"query": inp, "limit": limit, "fields": FIELDS}
    year = str(cfg.get("year") or "").strip()
    if year:
        q["year"] = year
    headers = {"x-api-key": cfg["api_key"].strip()} if (cfg.get("api_key") or "").strip() else {}
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            resp = await client.get(API, params=q)
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach Semantic Scholar: {e}"
    if resp.status_code == 429:
        return f"{LABEL} Rate limited — wait a moment, or set an api_key."
    if resp.status_code == 403:
        return f"{LABEL} The api_key was refused."
    if resp.status_code != 200:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:200]}"
    papers = resp.json().get("data") or []
    if not papers:
        return f"{LABEL} No papers found for '{inp}'."
    lines = [f"{LABEL} {len(papers)} paper(s) for '{inp}'\n"]
    for i, p in enumerate(papers, 1):
        authors = [a.get("name", "") for a in p.get("authors") or []]
        byline = ", ".join(authors[:4]) + (" et al." if len(authors) > 4 else "")
        meta = " · ".join(str(b) for b in (p.get("year"), p.get("venue"), f"{p.get('citationCount', 0)} citations") if b)
        lines.append(f"{i}. {p.get('title', '')}\n   {byline}\n   {meta}")
        doi = (p.get("externalIds") or {}).get("DOI")
        if doi:
            lines.append(f"   DOI: {doi}")
        pdf = (p.get("openAccessPdf") or {}).get("url")
        lines.append(f"   {pdf or p.get('url', '')}")
        if p.get("abstract"):
            lines.append(f"   {p['abstract'][:400]}{'…' if len(p['abstract']) > 400 else ''}")
        lines.append("")
    return "\n".join(lines).rstrip()
