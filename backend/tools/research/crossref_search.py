"""Crossref — built-in tool `crossref_search` (Crossref REST API; free, no key).

A DOI input (10.xxxx/…, or a doi.org link) returns that work's metadata; anything else searches
works by bibliographic text. ``mailto`` puts requests in Crossref's faster "polite" pool.
"""

import re
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from tools.base import ToolSpec, query_params

LABEL = "[Crossref]"
API = "https://api.crossref.org/works"
_DOI = re.compile(r"(10\.\d{4,9}/\S+)")

TOOL = ToolSpec(
    id="crossref_search",
    name="Crossref DOI Lookup",
    icon="🔗",
    category="Research & Knowledge",
    description="Looks up a DOI, or searches 150M+ scholarly works by title, author or citation text: journal, date, authors, citation count. Free, no key.",
    default_config={"mailto": "", "max_results": 5},
    order=145,
    parameters=query_params("A DOI, or title / author / citation text to search for"),
    input_param="query",
)


def _work(w: Dict[str, Any]) -> str:
    title = (w.get("title") or ["(untitled)"])[0]
    authors = [" ".join(filter(None, (a.get("given"), a.get("family")))) or a.get("name", "")
               for a in w.get("author") or []]
    byline = ", ".join(authors[:4]) + (" et al." if len(authors) > 4 else "")
    parts = ((w.get("issued") or {}).get("date-parts") or [[None]])[0]
    date = "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(parts) if p)
    venue = (w.get("container-title") or [""])[0]
    meta = " · ".join(b for b in (w.get("type"), venue, date, f"{w.get('is-referenced-by-count', 0)} citations") if b)
    return f"{title}\n   {byline}\n   {meta}\n   https://doi.org/{w.get('DOI', '')}"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    if not inp:
        return f"{LABEL} Provide a DOI or text to search for."
    mailto = (cfg.get("mailto") or "").strip()
    headers = {"User-Agent": f"pipesets-ai (mailto:{mailto})" if mailto else "pipesets-ai"}
    doi = _DOI.search(inp)
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            if doi:
                resp = await client.get(f"{API}/{quote(doi.group(1).rstrip('.,;'), safe='/')}")
            else:
                limit = max(1, min(int(cfg.get("max_results") or 5), 20))
                resp = await client.get(API, params={"query.bibliographic": inp, "rows": limit,
                                                     **({"mailto": mailto} if mailto else {})})
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach Crossref: {e}"
    if resp.status_code == 404:
        return f"{LABEL} No work with DOI {doi.group(1) if doi else inp}."
    if resp.status_code != 200:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:200]}"
    message = resp.json().get("message") or {}
    if doi:
        out = [f"{LABEL} {_work(message)}"]
        if message.get("publisher"):
            out.append(f"   Publisher: {message['publisher']}")
        if message.get("abstract"):
            out.append("   " + re.sub(r"<[^>]+>", "", message["abstract"]).strip()[:800])
        return "\n".join(out)
    items = message.get("items") or []
    if not items:
        return f"{LABEL} No works found for '{inp}'."
    return f"{LABEL} {len(items)} work(s) for '{inp}'\n\n" + "\n\n".join(f"{i}. {_work(w)}" for i, w in enumerate(items, 1))
