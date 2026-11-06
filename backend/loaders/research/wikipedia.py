"""Wikipedia — document loader `wikipedia`."""

import asyncio
from typing import Any, Dict, List

from loaders.base import Document, LoaderError, LoaderSpec, document

LOADER = LoaderSpec(
    type="wikipedia",
    label="Wikipedia",
    icon="📖",
    category="Research & Media",
    desc="Load Wikipedia articles for a query",
    source_label="Search Query / Page Title",
    placeholder="Retrieval-augmented generation",
    aliases=("wikipedialoader",),
    order=20,
)



async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    """Full plain-text articles: the best match for the query (cross-language aware), plus more hits."""
    import httpx

    from tools.research.wikipedia import HEADERS, find_article

    lang = (cfg.get("language") or "en").strip().lower()
    max_docs = int(cfg.get("max_docs", 1))
    api = f"https://{lang}.wikipedia.org/w/api.php"
    async with httpx.AsyncClient(timeout=20.0, headers=HEADERS, follow_redirects=True) as client:
        best = await find_article(client, source, lang)
        titles = [best.replace("_", " ")] if best else []
        if max_docs > len(titles):
            search = await client.get(api, params={"action": "query", "list": "search", "srsearch": source,
                                                   "srlimit": max_docs, "format": "json", "formatversion": 2})
            search.raise_for_status()
            titles += [h["title"] for h in search.json().get("query", {}).get("search", []) if h["title"] not in titles]
        titles = titles[:max_docs]
        if not titles:
            raise LoaderError(f"No Wikipedia ({lang}) article found for: {source}")
        async def article(title: str):
            # full-text extracts come back for one page per request, so fetch each separately
            r = await client.get(api, params={"action": "query", "prop": "extracts|info", "explaintext": 1, "inprop": "url",
                                              "titles": title, "format": "json", "formatversion": 2, "redirects": 1})
            r.raise_for_status()
            page = (r.json().get("query", {}).get("pages") or [{}])[0]
            if page.get("extract"):
                return document(f"{page['title']}\n\n{page['extract']}", source=page.get("fullurl", ""),
                                title=page["title"], language=lang)
            return None

        docs = [d for d in await asyncio.gather(*(article(t) for t in titles)) if d]
    if not docs:
        raise LoaderError(f"Couldn't read the Wikipedia article for: {source}")
    return docs
