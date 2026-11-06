"""Brave Search — built-in tool `brave_search`."""

import os
from typing import Any, Dict, Optional

import httpx

from tools._choices import COUNTRIES
from tools.base import Select, ToolSpec, query_params
from tools.search._format import format_search

TOOL = ToolSpec(
    id="brave_search",
    name="Brave Search",
    icon="🦁",
    category="Web Search",
    description="Independent-index web search via the Brave Search API. Requires a Brave API key.",
    default_config={"api_key": "", "max_results": 5, "country": "us"},
    order=30,
    required=("api_key",),
    selects={
        "country": Select("Country", COUNTRIES),
    },
    parameters=query_params("What to search the web for"), input_param="query",
)


async def search(query: str, cfg: Dict[str, Any]) -> str:
    api_key = cfg.get("api_key", "") or os.environ.get("BRAVE_API_KEY", "")
    if not api_key:
        return "[Brave] api_key is required in config (or set BRAVE_API_KEY)."
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": int(cfg.get("max_results", 5)), "country": cfg.get("country", "us")},
                headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            )
            resp.raise_for_status()
            results = resp.json().get("web", {}).get("results", [])
        return format_search("Brave", query, [(r.get("title", ""), r.get("url", ""), r.get("description", "")) for r in results])
    except Exception as e:
        return f"[Brave] Error: {e}"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    if not inp:
        return "[Web Search] Please provide a search query."
    return await search(inp, cfg)
