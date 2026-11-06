"""DuckDuckGo Search — built-in tool `duckduckgo_search`."""

import asyncio
from typing import Any, Dict, Optional

from tools.base import Select, ToolSpec, query_params
from tools.search._format import format_search

TOOL = ToolSpec(
    id="duckduckgo_search",
    name="DuckDuckGo Search",
    icon="🦆",
    category="Web Search",
    description="Free web search with no API key. Input is the search query.",
    default_config={"max_results": 5, "region": "", "safesearch": "moderate"},
    order=10,
    selects={
        "safesearch": Select("Safe search", (("strict", "Strict"), ("moderate", "Moderate"), ("off", "Off"))),
    },
    parameters=query_params("What to search the web for"), input_param="query",
)


async def search(query: str, cfg: Dict[str, Any]) -> str:
    max_results = int(cfg.get("max_results", 5))
    try:
        from ddgs import DDGS  # successor of the deprecated duckduckgo-search package
    except ImportError:
        return "[DuckDuckGo] Install 'ddgs' on the backend for live results."
    kwargs: Dict[str, Any] = {"max_results": max_results, "safesearch": cfg.get("safesearch", "moderate")}
    if cfg.get("region"):
        kwargs["region"] = cfg["region"]
    try:
        results = await asyncio.to_thread(lambda: list(DDGS().text(query, **kwargs)))
        return format_search("DuckDuckGo", query, [(r.get("title", ""), r.get("href", ""), r.get("body", "")) for r in results])
    except Exception as e:
        return f"[DuckDuckGo] Error: {e}"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    if not inp:
        return "[Web Search] Please provide a search query."
    return await search(inp, cfg)
