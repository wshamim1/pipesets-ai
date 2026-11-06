"""Word (DOCX) — document loader `docx`."""

import asyncio
import io
from typing import Any, Dict, List

from loaders._common import read_file
from loaders.base import Document, LoaderError, LoaderSpec, document

LOADER = LoaderSpec(
    type="docx",
    label="Word (DOCX)",
    icon="📘",
    category="Files",
    desc="Extract text from Word documents",
    source_label="File Path",
    placeholder="/path/to/document.docx",
    file_based=True,
    aliases=("word", "doc", "docx2txt", "docx2txtloader", "unstructuredword"),
    order=60,
)
EXTENSIONS = (".docx",)


def parse(name: str, data: bytes, cfg: Dict[str, Any]) -> List[Document]:
    """Headings, paragraphs and tables (as markdown) in document order."""
    import docx

    doc = docx.Document(io.BytesIO(data))
    parts = []
    for p in doc.paragraphs:
        if p.text.strip():
            style = (p.style.name or "").lower() if p.style is not None else ""
            level = style.replace("heading", "").strip() if style.startswith("heading") else ""
            parts.append(f"{'#' * int(level)} {p.text}" if level.isdigit() else p.text)
    for table in doc.tables:
        rows = [[c.text.strip().replace("|", "\\|") for c in r.cells] for r in table.rows]
        if rows:
            parts.append("\n".join(["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
                                   + ["| " + " | ".join(r) + " |" for r in rows[1:]]))
    text = "\n\n".join(parts).strip()
    if not text:
        raise LoaderError(f"{name} has no text.")
    return [document(text, source=name, title=doc.core_properties.title or None)]


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    name, data = read_file(source)
    return await asyncio.to_thread(parse, name, data, cfg)
