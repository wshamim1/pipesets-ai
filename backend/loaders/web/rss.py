"""RSS Feed — document loader `rss`."""

import xml.etree.ElementTree as ET
from typing import Any, Dict, List

from loaders._common import http_client
from loaders.base import Document, LoaderError, LoaderSpec, document

LOADER = LoaderSpec(
    type="rss",
    label="RSS Feed",
    icon="📡",
    category="Web & Feeds",
    desc="Load entries from an RSS / Atom feed",
    source_label="Feed URL",
    placeholder="https://example.com/feed.xml",
    aliases=("atom", "rssloader", "rssfeed"),
    order=30,
)


_ATOM = "{http://www.w3.org/2005/Atom}"
_CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    """One document per feed item: title, summary/content (as text), link and date."""
    from tools.data.html_to_markdown import html_to_markdown

    max_items = int(cfg.get("max_items", 50))
    async with http_client() as client:
        resp = await client.get(source)
    if resp.status_code >= 400:
        raise LoaderError(f"{source} returned HTTP {resp.status_code}.")
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        raise LoaderError(f"{source} isn't a valid RSS/Atom feed: {e}")
    items = []
    for it in root.iter("item"):
        items.append((it.findtext("title", ""), it.findtext("link", ""), it.findtext("pubDate", ""),
                      it.findtext(_CONTENT) or it.findtext("description", "")))
    for e in root.iter(f"{_ATOM}entry"):
        link = e.find(f"{_ATOM}link")
        items.append((e.findtext(f"{_ATOM}title", ""), link.get("href", "") if link is not None else "",
                      e.findtext(f"{_ATOM}updated", "") or e.findtext(f"{_ATOM}published", ""),
                      e.findtext(f"{_ATOM}content", "") or e.findtext(f"{_ATOM}summary", "")))
    docs = []
    for title, link, date, body in items[:max_items]:
        text = html_to_markdown(body, link, include_links=False, main_content_only=False)[1] if "<" in (body or "") else (body or "").strip()
        docs.append(document(f"{title.strip()}\n\n{text}".strip(), source=link, title=title.strip(), published=date))
    if not docs:
        raise LoaderError(f"No items in {source}.")
    return docs
