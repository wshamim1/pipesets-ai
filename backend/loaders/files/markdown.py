"""Markdown — document loader `markdown`."""

import asyncio
from typing import Any, Dict, List

from loaders._common import read_file, decode
from loaders.base import Document, LoaderError, LoaderSpec, document

LOADER = LoaderSpec(
    type="markdown",
    label="Markdown",
    icon="🗒️",
    category="Files",
    desc="Load .md files",
    source_label="File Path",
    placeholder="/path/to/README.md",
    file_based=True,
    aliases=("md", "unstructuredmarkdown", "markdownloader"),
    order=30,
)
EXTENSIONS = (".md", ".markdown", ".mdx")


def parse(name: str, data: bytes, cfg: Dict[str, Any]) -> List[Document]:
    text = decode(data).strip()
    if not text:
        raise LoaderError(f"{name} is empty.")
    return [document(text, source=name)]


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    name, data = read_file(source)
    return await asyncio.to_thread(parse, name, data, cfg)
