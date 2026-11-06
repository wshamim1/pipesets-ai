"""RSS / Atom feed reader — built-in tool `rss_reader`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="rss_reader",
    name="RSS / Atom Reader",
    icon="📰",
    category="Research & Knowledge",
    description="Reads the latest items from an RSS or Atom feed. Input is the feed URL.",
    default_config={"feed_url": "", "max_items": 10},
    order=60,
    parameters=params(
        {"feed_url": {"type": "string", "description": "RSS or Atom feed URL"}},
        {"max_items": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Most items"}},
    ),
    input_param="feed_url",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import xml.etree.ElementTree as ET
    feed_url = inp if inp.startswith(("http://", "https://")) else cfg.get("feed_url", "")
    max_items = int(cfg.get("max_items", 10))
    if not feed_url:
        return "[RSS] Provide a feed URL as input or set feed_url in config."
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(feed_url, headers={"User-Agent": "PipesetsAI/1.0 (https://github.com/pipesets-ai; tool: rss_reader)"})
            resp.raise_for_status()
        root = ET.fromstring(resp.content)
        atom = "{http://www.w3.org/2005/Atom}"
        items = []
        for item in root.iter("item"):  # RSS 2.0
            items.append((item.findtext("title", ""), item.findtext("link", ""), item.findtext("pubDate", "")))
        for entry in root.iter(f"{atom}entry"):  # Atom
            link = entry.find(f"{atom}link")
            items.append((
                entry.findtext(f"{atom}title", ""),
                link.get("href", "") if link is not None else "",
                entry.findtext(f"{atom}updated", "") or entry.findtext(f"{atom}published", ""),
            ))
        if not items:
            return f"[RSS] No items found in {feed_url}"
        lines = [f"[RSS Feed: {feed_url}]\n"]
        for i, (title, link, date) in enumerate(items[:max_items], 1):
            lines.append(f"{i}. {' '.join(title.split())}" + (f" ({date})" if date else "") + f"\n   {link}")
        return "\n".join(lines)
    except ET.ParseError as e:
        return f"[RSS] Not a valid RSS/Atom feed: {e}"
    except Exception as e:
        return f"[RSS] Error: {e}"
