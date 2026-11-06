"""Sitemap — document loader `sitemap`."""

import asyncio
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

from loaders._common import http_client
from loaders.base import Document, LoaderError, LoaderSpec, document

LOADER = LoaderSpec(
    type="sitemap",
    label="Sitemap",
    icon="🗺️",
    category="Web & Feeds",
    desc="Load every page listed in a sitemap.xml",
    source_label="Sitemap URL",
    placeholder="https://example.com/sitemap.xml",
    aliases=("sitemaploader",),
    order=20,
)


_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def _locs(xml: bytes) -> tuple:
    root = ET.fromstring(xml)
    is_index = root.tag.endswith("sitemapindex")
    return is_index, [el.text.strip() for el in root.iter(f"{_NS}loc") if el.text]


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    """Fetch every page listed in a sitemap (or sitemap index), up to max_pages."""
    from tools.data.html_to_markdown import html_to_markdown

    max_pages = int(cfg.get("max_pages", 25))
    url_filter = (cfg.get("url_filter") or "").strip()
    async with http_client() as client:
        resp = await client.get(source)
        if resp.status_code >= 400:
            raise LoaderError(f"{source} returned HTTP {resp.status_code}.")
        try:
            is_index, urls = _locs(resp.content)
            if is_index:   # follow up to 5 child sitemaps
                children, urls = urls[:5], []
                for child in children:
                    r = await client.get(child)
                    if r.status_code < 400:
                        urls += _locs(r.content)[1]
        except ET.ParseError as e:
            raise LoaderError(f"{source} isn't a valid sitemap: {e}")
        if url_filter:
            urls = [u for u in urls if re.search(url_filter, u)]
        urls = urls[:max_pages]
        if not urls:
            raise LoaderError("The sitemap lists no pages" + (f" matching '{url_filter}'." if url_filter else "."))
        sem = asyncio.Semaphore(5)

        async def fetch(url: str):
            async with sem:
                try:
                    r = await client.get(url)
                    if r.status_code >= 400 or "html" not in r.headers.get("content-type", ""):
                        return None
                    title, md = html_to_markdown(r.text, url, include_links=False)
                    return document(md, source=url, title=title) if md else None
                except Exception:
                    return None

        docs = [d for d in await asyncio.gather(*(fetch(u) for u in urls)) if d]
    if not docs:
        raise LoaderError("None of the sitemap pages could be read.")
    return docs
