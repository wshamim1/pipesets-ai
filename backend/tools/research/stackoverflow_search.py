"""Stack Overflow — built-in tool `stackoverflow_search`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, query_params

TOOL = ToolSpec(
    id="stackoverflow_search",
    name="Stack Overflow",
    icon="💡",
    category="Research & Knowledge",
    description="Searches Stack Overflow (or any Stack Exchange site) for questions with accepted answers.",
    default_config={"site": "stackoverflow", "max_results": 5, "answered_only": True},
    order=30,
    parameters=query_params("A programming question or error message", answered_only={"type": "boolean",
        "description": "Only questions with an accepted answer"}),
    input_param="query",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import html
    if not inp:
        return "[Stack Overflow] Please provide a search query."
    params = {
        "order": "desc", "sort": "relevance", "q": inp, "site": cfg.get("site", "stackoverflow"),
        "pagesize": int(cfg.get("max_results", 5)),
    }
    if cfg.get("answered_only", True):
        params["accepted"] = "True"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get("https://api.stackexchange.com/2.3/search/advanced", params=params)
            resp.raise_for_status()
            items = resp.json().get("items", [])
        if not items:
            return f"[Stack Overflow] No questions found for: {inp}"
        lines = [f"[Stack Overflow: '{inp}']\n"]
        for i, q in enumerate(items, 1):
            tags = ", ".join(q.get("tags", [])[:4])
            lines.append(
                f"{i}. {html.unescape(q.get('title', ''))} — score {q.get('score', 0)}, "
                f"{q.get('answer_count', 0)} answers{' ✓' if q.get('is_answered') else ''}\n   [{tags}] {q.get('link', '')}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"[Stack Overflow] Error: {e}"
