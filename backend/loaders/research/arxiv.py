"""arXiv — document loader `arxiv`."""

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

from loaders._common import http_client
from loaders.base import Document, LoaderError, LoaderSpec, document

LOADER = LoaderSpec(
    type="arxiv",
    label="arXiv",
    icon="🎓",
    category="Research & Media",
    desc="Load papers from arXiv by id or query",
    source_label="arXiv ID / Query",
    placeholder="2005.11401",
    aliases=("arxivloader",),
    order=30,
)


_ATOM = "{http://www.w3.org/2005/Atom}"
_ID = re.compile(r"(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7})")


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    """Papers by arXiv id(s) or search query: title, authors and abstract; full PDF text with full_text=true."""
    ids = _ID.findall(source)
    params = {"id_list": ",".join(ids)} if ids else {"search_query": f"all:{source}", "max_results": int(cfg.get("max_docs", 3))}
    full_text = str(cfg.get("full_text", False)).lower() == "true"
    async with http_client(timeout=30.0) as client:
        resp = await client.get("https://export.arxiv.org/api/query", params=params)
        resp.raise_for_status()
        entries = ET.fromstring(resp.content).findall(f"{_ATOM}entry")
        docs = []
        for e in entries:
            title = " ".join((e.findtext(f"{_ATOM}title") or "").split())
            if not title or title == "Error":
                continue
            authors = ", ".join(a.findtext(f"{_ATOM}name", "") for a in e.findall(f"{_ATOM}author"))
            abstract = " ".join((e.findtext(f"{_ATOM}summary") or "").split())
            link = e.findtext(f"{_ATOM}id", "")
            text = f"{title}\n\nAuthors: {authors}\n\nAbstract: {abstract}"
            if full_text:
                pdf_url = link.replace("/abs/", "/pdf/")
                r = await client.get(pdf_url)
                if r.status_code == 200:
                    from loaders.files import pdf
                    text += "\n\n" + "\n\n".join(d["text"] for d in pdf.parse(pdf_url, r.content, cfg))
            docs.append(document(text, source=link, title=title, authors=authors,
                                 published=(e.findtext(f"{_ATOM}published") or "")[:10]))
    if not docs:
        raise LoaderError(f"No arXiv papers found for: {source}")
    return docs
