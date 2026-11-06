"""Tavily Search — built-in tool `tavily_search`."""

import os
from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, query_params
from tools.search._format import format_search

TOOL = ToolSpec(
    id="tavily_search",
    name="Tavily Search",
    icon="🔎",
    category="Web Search",
    description="AI-optimised web search that returns a direct answer plus sources. Requires a Tavily API key.",
    default_config={"api_key": "", "max_results": 5, "search_depth": "basic", "include_answer": True},
    order=20,
    required=("api_key",),
    selects={
        "search_depth": Select("Search depth", (("basic", "Basic (faster)"), ("advanced", "Advanced (more thorough)"))),
    },
    parameters=query_params("What to search the web for"), input_param="query",
)


async def search(query: str, cfg: Dict[str, Any]) -> str:
    api_key = cfg.get("api_key", "") or os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return "[Tavily] api_key is required in config (or set TAVILY_API_KEY)."
    max_results = int(cfg.get("max_results", 5))
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post("https://api.tavily.com/search", json={
                "api_key": api_key, "query": query, "max_results": max_results,
                "search_depth": cfg.get("search_depth", "basic"),
                "include_answer": bool(cfg.get("include_answer", True)),
            })
            resp.raise_for_status()
            d = resp.json()
        items = [(r.get("title", ""), r.get("url", ""), r.get("content", "")) for r in d.get("results", [])[:max_results]]
        return format_search("Tavily", query, items, d.get("answer") or "")
    except Exception as e:
        return f"[Tavily] Error: {e}"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    if not inp:
        return "[Web Search] Please provide a search query."
    return await search(inp, cfg)
