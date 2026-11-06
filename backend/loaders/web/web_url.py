"""Web URL — document loader `web_url`."""

from typing import Any, Dict, List

from loaders._common import http_client
from loaders.base import Document, LoaderError, LoaderSpec, document

LOADER = LoaderSpec(
    type="web_url",
    label="Web URL",
    icon="🌐",
    category="Web & Feeds",
    desc="Crawl a web page and extract its content",
    source_label="URL",
    placeholder="https://example.com/page",
    aliases=("web", "url", "webbase", "webbaseloader", "http", "https", "recursiveurl", "recursiveurlloader"),
    order=10,
)


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    from tools.data.html_to_markdown import html_to_markdown

    url = source if source.startswith(("http://", "https://")) else f"https://{source}"
    async with http_client() as client:
        resp = await client.get(url)
    if resp.status_code >= 400:
        raise LoaderError(f"{url} returned HTTP {resp.status_code}.")
    ctype = resp.headers.get("content-type", "")
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        from loaders.files import pdf
        return pdf.parse(url, resp.content, cfg)
    if "html" not in ctype and "xml" not in ctype:
        return [document(resp.text, source=str(resp.url))]
    title, md = html_to_markdown(resp.text, str(resp.url), include_links=bool(cfg.get("include_links", False)))
    if not md:
        raise LoaderError(f"No readable text at {url} (the page may need JavaScript).")
    return [document(md, source=str(resp.url), title=title)]

