"""SearXNG Search — built-in tool `searxng_search`."""

import os
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, query_params
from tools.search._format import format_search

TOOL = ToolSpec(
    id="searxng_search",
    name="SearXNG Search",
    icon="🛰️",
    category="Web Search",
    description="Private metasearch through your own SearXNG instance (JSON format enabled). No API key.",
    default_config={"base_url": "http://localhost:8080", "max_results": 5},
    order=70,
    required=("base_url",),
    parameters=query_params("What to search the web for"), input_param="query",
)


async def search(query: str, cfg: Dict[str, Any]) -> str:
    base_url = (cfg.get("base_url", "") or os.environ.get("SEARXNG_URL", "")).rstrip("/")
    if not base_url:
        return "[SearXNG] base_url of your SearXNG instance is required in config (JSON format must be enabled)."
    max_results = int(cfg.get("max_results", 5))
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{base_url}/search", params={"q": query, "format": "json"})
            resp.raise_for_status()
            results = resp.json().get("results", [])[:max_results]
        return format_search("SearXNG", query, [(r.get("title", ""), r.get("url", ""), r.get("content", "")) for r in results])
    except Exception as e:
        return f"[SearXNG] Error: {e}"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    if not inp:
        return "[Web Search] Please provide a search query."
    return await search(inp, cfg)
