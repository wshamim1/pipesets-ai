"""Google Search (SerpApi) — built-in tool `serpapi_search`."""

import os
from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, query_params
from tools.search._format import format_search

TOOL = ToolSpec(
    id="serpapi_search",
    name="Google Search (SerpApi)",
    icon="🌍",
    category="Web Search",
    description="Google (or Bing, DuckDuckGo, etc.) results via SerpApi. Requires a SerpApi key.",
    default_config={"api_key": "", "max_results": 5, "engine": "google"},
    order=50,
    required=("api_key",),
    selects={
        "engine": Select("Engine", (("google", "Google"), ("bing", "Bing"), ("duckduckgo", "DuckDuckGo"), ("yahoo", "Yahoo"), ("baidu", "Baidu"), ("yandex", "Yandex"), ("google_news", "Google News"), ("google_scholar", "Google Scholar"))),
    },
    parameters=query_params("What to search the web for"), input_param="query",
)


async def search(query: str, cfg: Dict[str, Any]) -> str:
    api_key = cfg.get("api_key", "") or os.environ.get("SERPAPI_API_KEY", "")
    if not api_key:
        return "[Google/SerpApi] api_key is required in config (or set SERPAPI_API_KEY)."
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get("https://serpapi.com/search.json", params={
                "q": query, "api_key": api_key, "engine": cfg.get("engine", "google"),
                "num": int(cfg.get("max_results", 5)),
            })
            resp.raise_for_status()
            d = resp.json()
        box = d.get("answer_box", {})
        answer = box.get("answer") or box.get("snippet") or ""
        items = [(r.get("title", ""), r.get("link", ""), r.get("snippet", "")) for r in d.get("organic_results", [])]
        return format_search("Google (SerpApi)", query, items, answer)
    except Exception as e:
        return f"[Google/SerpApi] Error: {e}"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    if not inp:
        return "[Web Search] Please provide a search query."
    return await search(inp, cfg)
