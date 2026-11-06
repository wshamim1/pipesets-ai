"""PubMed — built-in tool `pubmed_search`."""

import os
from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, query_params

TOOL = ToolSpec(
    id="pubmed_search",
    name="PubMed",
    icon="🧬",
    category="Research & Knowledge",
    description="Searches PubMed for biomedical papers: titles, authors, journals and links (free; NCBI key optional).",
    default_config={"max_results": 5, "sort": "relevance", "api_key": ""},
    order=90,
    selects={
        "sort": Select("Sort by", (("relevance", "Best match"), ("pub_date", "Newest"))),
    },
    parameters=query_params("Biomedical search terms, e.g. 'GLP-1 obesity trials'"), input_param="query",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    if not inp:
        return "[PubMed] Please provide a search query."
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    params: Dict[str, Any] = {"db": "pubmed", "retmode": "json"}
    if cfg.get("api_key") or os.environ.get("NCBI_API_KEY"):
        params["api_key"] = cfg.get("api_key") or os.environ.get("NCBI_API_KEY")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            search = await client.get(f"{base}/esearch.fcgi", params={
                **params, "term": inp, "retmax": int(cfg.get("max_results", 5)), "sort": cfg.get("sort", "relevance"),
            })
            search.raise_for_status()
            ids = search.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                return f"[PubMed] No articles found for: {inp}"
            summary = await client.get(f"{base}/esummary.fcgi", params={**params, "id": ",".join(ids)})
            summary.raise_for_status()
            result = summary.json().get("result", {})
        lines = [f"[PubMed: '{inp}']\n"]
        for i, pmid in enumerate(ids, 1):
            a = result.get(pmid, {})
            authors = ", ".join(x.get("name", "") for x in a.get("authors", [])[:3])
            lines.append(f"{i}. {a.get('title', '')}\n   {authors} — {a.get('fulljournalname', a.get('source', ''))}, "
                         f"{a.get('pubdate', '')}\n   https://pubmed.ncbi.nlm.nih.gov/{pmid}/")
        return "\n".join(lines)
    except Exception as e:
        return f"[PubMed] Error: {e}"
