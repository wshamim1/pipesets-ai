"""CSV Loader — document loader `csv`."""

import asyncio
import csv
import io
from typing import Any, Dict, List

from loaders._common import read_file, decode
from loaders.base import Document, LoaderError, LoaderSpec, document

LOADER = LoaderSpec(
    type="csv",
    label="CSV Loader",
    icon="📊",
    category="Files",
    desc="Load rows from a CSV file as documents",
    source_label="File Path",
    placeholder="/path/to/data.csv",
    file_based=True,
    aliases=("csvloader",),
    order=40,
)
EXTENSIONS = (".csv",)


def parse(name: str, data: bytes, cfg: Dict[str, Any]) -> List[Document]:
    """One document per row: "column: value" lines."""
    max_rows = int(cfg.get("max_rows", 5000))
    text = decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    docs = []
    for i, row in enumerate(reader, 1):
        if i > max_rows:
            break
        lines = [f"{k}: {v}" for k, v in row.items() if k is not None and str(v or "").strip()]
        if lines:
            docs.append(document("\n".join(lines), source=name, row=i))
    if not docs:
        raise LoaderError(f"{name} has no data rows.")
    return docs


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    name, data = read_file(source)
    return await asyncio.to_thread(parse, name, data, cfg)
