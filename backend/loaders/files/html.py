"""HTML File — document loader `html`."""

import asyncio
from typing import Any, Dict, List

from loaders._common import read_file, decode
from loaders.base import Document, LoaderError, LoaderSpec, document

LOADER = LoaderSpec(
    type="html",
    label="HTML File",
    icon="🧩",
    category="Files",
    desc="Parse a local .html file",
    source_label="File Path",
    placeholder="/path/to/page.html",
    aliases=("htm", "bshtml", "bshtmlloader", "unstructuredhtml"),
    order=70,
)
EXTENSIONS = (".html", ".htm")


def parse(name: str, data: bytes, cfg: Dict[str, Any]) -> List[Document]:
    from tools.data.html_to_markdown import html_to_markdown

    title, md = html_to_markdown(decode(data), include_links=False, main_content_only=False)
    if not md:
        raise LoaderError(f"{name} has no readable text.")
    return [document(md, source=name, title=title)]


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    name, data = read_file(source)
    return await asyncio.to_thread(parse, name, data, cfg)
