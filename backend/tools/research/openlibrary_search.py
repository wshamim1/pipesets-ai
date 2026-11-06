"""Open Library (books) — built-in tool `openlibrary_search`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import MAX_RESULTS, ToolSpec, params

TOOL = ToolSpec(
    id="openlibrary_search",
    name="Open Library Books",
    icon="📕",
    category="Research & Knowledge",
    description="Searches Open Library for books by title, author or subject (free, no key).",
    default_config={"max_results": 5},
    order=80,
    parameters=params(
        {"query": {"type": "string", "description": "Title, author or subject"}},
        {"max_results": MAX_RESULTS},
    ),
    input_param="query",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    if not inp:
        return "[Open Library] Please provide a title, author or subject."
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get("https://openlibrary.org/search.json", params={
                "q": inp, "limit": int(cfg.get("max_results", 5)),
                "fields": "key,title,author_name,first_publish_year,edition_count,subject,isbn",
            })
            resp.raise_for_status()
            docs = resp.json().get("docs", [])
        if not docs:
            return f"[Open Library] No books found for: {inp}"
        lines = [f"[Open Library: '{inp}']\n"]
        for i, b in enumerate(docs, 1):
            authors = ", ".join(b.get("author_name", [])[:3]) or "unknown author"
            subjects = ", ".join(b.get("subject", [])[:4])
            lines.append(
                f"{i}. {b.get('title', '')} — {authors} ({b.get('first_publish_year', '?')}), "
                f"{b.get('edition_count', 0)} editions\n   https://openlibrary.org{b.get('key', '')}"
                + (f"\n   subjects: {subjects}" if subjects else "")
            )
        return "\n".join(lines)
    except Exception as e:
        return f"[Open Library] Error: {e}"
