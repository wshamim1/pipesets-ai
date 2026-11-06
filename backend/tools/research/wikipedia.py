"""Wikipedia — built-in tool `wikipedia`."""

from typing import Any, Dict, Optional

import httpx

from tools._choices import WIKIPEDIA_LANGUAGES
from tools.base import Select, ToolSpec, params

TOOL = ToolSpec(
    id="wikipedia",
    name="Wikipedia",
    icon="📚",
    category="Research & Knowledge",
    description="Looks up a topic on Wikipedia and returns the article summary. Input is the topic.",
    default_config={"language": "en"},
    order=10,
    selects={
        "language": Select("Wikipedia language", WIKIPEDIA_LANGUAGES, hint="Which Wikipedia to read. The model still answers in the language of the question unless its system prompt says otherwise."),
    },
    parameters=params({"query": {"type": "string", "description": "Article title or topic"}},
                      {"language": {"type": "string", "description": "Wikipedia language code, e.g. en, de, fr"}}),
    input_param="query",
)


# Wikimedia rejects requests whose User-Agent lacks a contact URL
HEADERS = {"User-Agent": "PipesetsAI/1.0 (https://github.com/pipesets-ai; tool: wikipedia)"}


async def find_article(client: httpx.AsyncClient, query: str, lang: str) -> Optional[str]:
    """Page key of the best article for ``query`` on ``lang`` Wikipedia (also used by the loader).

    Agents usually query in English, which matches poorly on other wikis (an English query on
    fr.wikipedia found "spice trade" for "Silk Road"). When the native search's top title doesn't
    match the query, find the article on English Wikipedia and follow its interlanguage link.
    """
    async def search(wiki: str) -> Optional[str]:
        r = await client.get(f"https://{wiki}.wikipedia.org/w/rest.php/v1/search/page", params={"q": query, "limit": 1})
        r.raise_for_status()
        pages = r.json().get("pages", [])
        return pages[0]["key"] if pages else None

    def title_matches(key: Optional[str]) -> bool:
        """Most of the title's words appear in the query (so the query was in this language)."""
        import re
        words = lambda t: set(re.findall(r"\w+", t.lower().replace("_", " ")))  # noqa: E731
        title = words(key or "")
        return bool(title) and len(title & words(query)) / len(title) >= 0.6

    key = await search(lang)
    if lang != "en" and not title_matches(key):
        en_key = await search("en")
        if en_key:
            ll = await client.get("https://en.wikipedia.org/w/api.php", params={
                "action": "query", "prop": "langlinks", "titles": en_key, "lllang": lang,
                "redirects": 1, "format": "json", "formatversion": 2,
            })
            ll.raise_for_status()
            links = (ll.json().get("query", {}).get("pages") or [{}])[0].get("langlinks", [])
            if links:
                key = links[0]["title"].replace(" ", "_")
    return key


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    from urllib.parse import quote
    lang = (cfg.get("language", "en") or "en").strip().lower()
    if not inp:
        return "[Wikipedia] Please provide a topic to look up."
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=HEADERS) as client:
            key = await find_article(client, inp, lang)
            if not key:
                return f"[Wikipedia ({lang})] No article found for: {inp}"
            summary = await client.get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(key, safe='')}")
            summary.raise_for_status()
            d = summary.json()
            url = d.get("content_urls", {}).get("desktop", {}).get("page", "")
            return f"[Wikipedia ({lang}): {d.get('title', key)}]\n{d.get('extract', '')}\n\nSource: {url}"
    except Exception as e:
        return f"[Wikipedia] Error: {e}"
