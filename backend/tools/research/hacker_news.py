"""Hacker News — built-in tool `hacker_news`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import MAX_RESULTS, ToolSpec, params

TOOL = ToolSpec(
    id="hacker_news",
    name="Hacker News",
    icon="🟧",
    category="Research & Knowledge",
    description="Searches Hacker News stories, or returns the front page when input is empty or 'top'.",
    default_config={"max_results": 10},
    order=50,
    parameters=params({}, {"query": {"type": "string", "description": "Search terms; leave out for the front page"},
                           "max_results": MAX_RESULTS}),
    input_param="query",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    max_results = int(cfg.get("max_results", 10))
    front_page = inp.lower() in ("", "top", "front page", "frontpage", "front_page")
    params: Dict[str, Any] = {"hitsPerPage": max_results, "tags": "front_page" if front_page else "story"}
    if not front_page:
        params["query"] = inp
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://hn.algolia.com/api/v1/search", params=params)
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
        if not hits:
            return f"[Hacker News] No stories found for: {inp}"
        lines = [f"[Hacker News: {'front page' if front_page else repr(inp)}]\n"]
        for i, h in enumerate(hits, 1):
            link = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            lines.append(f"{i}. {h.get('title', '')} — {h.get('points', 0)} points, {h.get('num_comments', 0)} comments\n   {link}")
        return "\n".join(lines)
    except Exception as e:
        return f"[Hacker News] Error: {e}"
