"""arXiv search — built-in tool `arxiv_search`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, query_params

TOOL = ToolSpec(
    id="arxiv_search",
    name="arXiv Search",
    icon="🎓",
    category="Research & Knowledge",
    description="Searches arXiv for research papers and returns titles, authors, links and abstracts.",
    default_config={"max_results": 5, "sort_by": "relevance"},
    order=20,
    selects={
        "sort_by": Select("Sort by", (("relevance", "Relevance"), ("submittedDate", "Newest submitted"), ("lastUpdatedDate", "Recently updated"))),
    },
    parameters=query_params("Search terms for papers, e.g. 'diffusion models for audio'", sort_by=enum(
        ["relevance", "submittedDate", "lastUpdatedDate"], "Order: relevance, newest submitted or recently updated")),
    input_param="query",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import xml.etree.ElementTree as ET
    max_results = int(cfg.get("max_results", 5))
    if not inp:
        return "[arXiv] Please provide a search query."
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                "https://export.arxiv.org/api/query",
                params={"search_query": f"all:{inp}", "max_results": max_results, "sortBy": cfg.get("sort_by", "relevance")},
            )
            resp.raise_for_status()
        ns = {"a": "http://www.w3.org/2005/Atom"}
        entries = ET.fromstring(resp.text).findall("a:entry", ns)
        if not entries:
            return f"[arXiv] No papers found for: {inp}"
        lines = [f"[arXiv Search: '{inp}']\n"]
        for i, e in enumerate(entries, 1):
            title = " ".join((e.findtext("a:title", "", ns) or "").split())
            authors = ", ".join(a.findtext("a:name", "", ns) for a in e.findall("a:author", ns)[:3])
            published = (e.findtext("a:published", "", ns) or "")[:10]
            abstract = " ".join((e.findtext("a:summary", "", ns) or "").split())[:300]
            lines.append(f"{i}. {title} ({published})\n   {authors}\n   {e.findtext('a:id', '', ns)}\n   {abstract}")
        return "\n".join(lines)
    except Exception as e:
        return f"[arXiv] Error: {e}"
