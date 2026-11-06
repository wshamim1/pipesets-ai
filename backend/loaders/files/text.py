"""Plain Text — document loader `text`."""

import asyncio
from typing import Any, Dict, List

from loaders._common import read_file, decode
from loaders.base import Document, LoaderError, LoaderSpec, document

LOADER = LoaderSpec(
    type="text",
    label="Plain Text",
    icon="📝",
    category="Files",
    desc="Load raw .txt files",
    source_label="File Path",
    placeholder="/path/to/file.txt",
    file_based=True,
    aliases=("txt", "textloader", "file"),
    order=20,
)
EXTENSIONS = (".txt", ".text", ".log")


def parse(name: str, data: bytes, cfg: Dict[str, Any]) -> List[Document]:
    text = decode(data).strip()
    if not text:
        raise LoaderError(f"{name} is empty.")
    return [document(text, source=name)]


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    name, data = read_file(source)
    return await asyncio.to_thread(parse, name, data, cfg)
