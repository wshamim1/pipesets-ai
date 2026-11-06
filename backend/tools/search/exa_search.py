"""Exa Search — built-in tool `exa_search`."""

import os
from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, query_params
from tools.search._format import format_search

TOOL = ToolSpec(
    id="exa_search",
    name="Exa Search",
    icon="🧠",
    category="Web Search",
    description="Neural web search built for LLMs, returning page text with each result. Requires an Exa API key.",
    default_config={"api_key": "", "max_results": 5, "search_type": "auto"},
    order=60,
    required=("api_key",),
    selects={
        "search_type": Select("Search type", (("auto", "Auto"), ("neural", "Neural"), ("keyword", "Keyword"))),
    },
    parameters=query_params("What to search the web for"), input_param="query",
)


async def search(query: str, cfg: Dict[str, Any]) -> str:
    api_key = cfg.get("api_key", "") or os.environ.get("EXA_API_KEY", "")
    if not api_key:
        return "[Exa] api_key is required in config (or set EXA_API_KEY)."
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://api.exa.ai/search",
                json={
                    "query": query, "numResults": int(cfg.get("max_results", 5)),
                    "type": cfg.get("search_type", "auto"),
                    "contents": {"text": {"maxCharacters": 400}},
                },
                headers={"x-api-key": api_key},
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
        return format_search("Exa", query, [(r.get("title", ""), r.get("url", ""), r.get("text", "")) for r in results])
    except Exception as e:
        return f"[Exa] Error: {e}"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    if not inp:
        return "[Web Search] Please provide a search query."
    return await search(inp, cfg)
