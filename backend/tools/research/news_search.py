"""News search (Google News RSS) — built-in tool `news_search`."""

from typing import Any, Dict, Optional

import httpx

from tools._choices import COUNTRIES_UPPER
from tools.base import Select, ToolSpec, enum, query_params

TOOL = ToolSpec(
    id="news_search",
    name="News Search",
    icon="🗞️",
    category="Research & Knowledge",
    description="Latest news articles on a topic from Google News (free, no key).",
    default_config={"max_results": 8, "language": "en", "country": "US", "time_range": ""},
    order=100,
    selects={
        "language": Select("Language", (("en", "English"), ("fr", "French"), ("de", "German"), ("es", "Spanish"), ("it", "Italian"), ("pt", "Portuguese"), ("nl", "Dutch"), ("hi", "Hindi"), ("ja", "Japanese"), ("zh", "Chinese"), ("ar", "Arabic"))),
        "country": Select("Edition", COUNTRIES_UPPER),
        "time_range": Select("Published within", (("", "Any time"), ("1h", "Past hour"), ("1d", "Past day"), ("7d", "Past week"), ("30d", "Past month"))),
    },
    parameters=query_params("News topic", time_range=enum(["", "1h", "1d", "7d", "30d"],
        "Published within: '' any time, 1h, 1d, 7d or 30d")),
    input_param="query",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import xml.etree.ElementTree as ET
    if not inp:
        return "[News] Please provide a topic."
    lang, country = cfg.get("language", "en"), (cfg.get("country", "US") or "US").upper()
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get("https://news.google.com/rss/search", params={
                "q": inp + (f" when:{cfg['time_range']}" if cfg.get("time_range") else ""),
                "hl": f"{lang}-{country}", "gl": country, "ceid": f"{country}:{lang}",
            }, headers={"User-Agent": "Mozilla/5.0 (compatible; PipesetsAI/1.0)"})
            resp.raise_for_status()
        items = ET.fromstring(resp.content).findall("./channel/item")[: int(cfg.get("max_results", 8))]
        if not items:
            return f"[News] No articles found for: {inp}"
        lines = [f"[News: '{inp}']\n"]
        for i, it in enumerate(items, 1):
            lines.append(f"{i}. {it.findtext('title', '')} — {it.findtext('source', '')} ({it.findtext('pubDate', '')})"
                         f"\n   {it.findtext('link', '')}")
        return "\n".join(lines)
    except Exception as e:
        return f"[News] Error: {e}"
