"""Google Search (Serper) — built-in tool `serper_search`."""

import os
from typing import Any, Dict, Optional

import httpx

from tools._choices import COUNTRIES
from tools.base import Select, ToolSpec, query_params
from tools.search._format import format_search

TOOL = ToolSpec(
    id="serper_search",
    name="Google Search (Serper)",
    icon="🌐",
    category="Web Search",
    description="Google results (organic + answer box) via Serper.dev. Requires a Serper API key.",
    default_config={"api_key": "", "max_results": 5, "country": "us"},
    order=40,
    required=("api_key",),
    selects={
        "country": Select("Country", COUNTRIES),
    },
    parameters=query_params("What to search the web for"), input_param="query",
)


async def search(query: str, cfg: Dict[str, Any]) -> str:
    api_key = cfg.get("api_key", "") or os.environ.get("SERPER_API_KEY", "")
    if not api_key:
        return "[Google/Serper] api_key is required in config (or set SERPER_API_KEY)."
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                json={"q": query, "num": int(cfg.get("max_results", 5)), "gl": cfg.get("country", "us")},
                headers={"X-API-KEY": api_key},
            )
            resp.raise_for_status()
            d = resp.json()
        box = d.get("answerBox", {})
        answer = box.get("answer") or box.get("snippet") or ""
        items = [(r.get("title", ""), r.get("link", ""), r.get("snippet", "")) for r in d.get("organic", [])]
        return format_search("Google (Serper)", query, items, answer)
    except Exception as e:
        return f"[Google/Serper] Error: {e}"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    if not inp:
        return "[Web Search] Please provide a search query."
    return await search(inp, cfg)
