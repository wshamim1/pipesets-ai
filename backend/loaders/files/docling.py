"""Docling — document loader `docling` (OCR, layout and tables; loaders/_docling.py)."""

import asyncio
from typing import Any, Dict, List

from loaders import _docling
from loaders._common import read_file
from loaders.base import Document, LoaderError, LoaderSpec, document

LOADER = LoaderSpec(
    type="docling",
    label="Docling (OCR + tables)",
    icon="📑",
    category="Files",
    desc="Scanned PDFs, images, DOCX and PPTX with OCR, layout and tables kept — one document per page",
    source_label="File Path",
    placeholder="/path/to/scanned-lease.pdf",
    file_based=True,
    aliases=("doclingloader", "ocrpdf", "scannedpdf"),
    order=15,
)
# No EXTENSIONS: the PDF / DOCX loaders stay the defaults for Directory and S3 (the PDF loader
# OCRs scanned pages on its own, with Docling as one of its engines — loaders/_ocr.py).


def parse(name: str, data: bytes, cfg: Dict[str, Any]) -> List[Document]:
    pages = _docling.convert_pages(name, data, cfg)
    if not pages:
        raise LoaderError(f"Docling found no text in {name}.")
    total = max(no for no, _ in pages)
    return [document(text, source=name, page=no, pages=total, parser="docling") for no, text in pages]


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    name, data = read_file(source)
    return await asyncio.to_thread(parse, name, data, cfg)
