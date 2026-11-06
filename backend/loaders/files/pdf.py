"""PDF Loader — document loader `pdf`."""

import asyncio
import io
from typing import Any, Dict, List

from loaders import _ocr
from loaders._common import read_file
from loaders.base import Document, LoaderError, LoaderSpec, document

LOADER = LoaderSpec(
    type="pdf",
    label="PDF Loader",
    icon="📕",
    category="Files",
    desc="Load and extract text from PDF files",
    source_label="File Path",
    placeholder="/path/to/document.pdf",
    file_based=True,
    aliases=("pypdf", "pypdfloader", "pdfloader", "pymupdf", "unstructuredpdf"),
    order=10,
)
EXTENSIONS = (".pdf",)


def parse(name: str, data: bytes, cfg: Dict[str, Any]) -> List[Document]:
    """One document per page that has text. Pages without a text layer (scanned) are read by the
    ``ocr_engine`` setting (loaders/_ocr.py; default: the first local engine installed)."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted and not reader.decrypt(cfg.get("password", "")):
        raise LoaderError(f"{name} is password-protected.")
    title = getattr(reader.metadata, "title", None) if reader.metadata else None
    total = len(reader.pages)
    texts = {i: (page.extract_text() or "").strip() for i, page in enumerate(reader.pages, 1)}
    scanned = [i for i, t in texts.items() if not t]
    engine, ocr_error = None, None
    if scanned and not reader.is_encrypted:
        try:
            ocr, engine = _ocr.pdf_pages(name, data, scanned, cfg)
        except LoaderError as e:
            ocr, ocr_error = {}, str(e)
        texts.update({i: ocr.get(i, "").strip() for i in scanned})
    missing = ", ".join(str(i) for i in scanned if not texts[i]) or None
    docs = [document(t, source=name, page=i, pages=total, title=title,
                     parser=f"ocr:{engine}" if i in scanned else None,
                     pages_without_text=missing, ocr_error=ocr_error)
            for i, t in texts.items() if t]
    if not docs:
        raise LoaderError(f"No extractable text in {name} — it may be scanned images (needs OCR)."
                          + (f" {ocr_error}" if ocr_error else ""))
    return docs


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    name, data = read_file(source)
    return await asyncio.to_thread(parse, name, data, cfg)
