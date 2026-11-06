"""Docling conversion shared by the Docling loader and the PDF loader's OCR fallback.

Docling (and its ML stack) is optional: the desktop build leaves it out, so every caller checks
``available()`` or handles ``LoaderError`` from ``convert_pages``.
"""

import io
import os
import platform
import sys
from typing import Any, Dict, List, Tuple

from loaders.base import LoaderError

SUPPORTED_EXTS = (".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".md",
                  ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")

INSTALL_HINT = "Docling isn't installed on this server (pip install docling); the desktop app leaves it out."

# docling-parse's macOS x86_64 build segfaults on image-only (scanned) PDFs, taking the whole
# process down (7.22–7.24; the Linux build reads them fine). pypdfium2 reads them on every platform.
_PDFIUM_BACKEND = sys.platform == "darwin" and platform.machine() == "x86_64"


def available() -> bool:
    try:
        import docling.document_converter  # noqa: F401
    except Exception:  # noqa: BLE001 — a broken ML stack fails with more than ImportError
        return False
    return True


def convert_pages(name: str, data: bytes, cfg: Dict[str, Any]) -> List[Tuple[int, str]]:
    """→ [(page number, markdown)] for pages with text. Formats without pages come back as page 1.

    ``cfg``: ``ocr`` (default True) reads text from scanned pages and images; ``tables``
    (default True) keeps table structure.
    """
    if os.path.splitext(name)[1].lower() not in SUPPORTED_EXTS:
        raise LoaderError(f"Docling can't read {os.path.basename(name)} (supported: {', '.join(SUPPORTED_EXTS)}).")
    try:
        from docling.datamodel.base_models import DocumentStream, InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except Exception as e:  # noqa: BLE001
        raise LoaderError(f"{INSTALL_HINT} ({e.__class__.__name__})") from e

    options = PdfPipelineOptions()
    options.do_ocr = bool(cfg.get("ocr", True))
    options.do_table_structure = bool(cfg.get("tables", True))
    pdf_format = PdfFormatOption(pipeline_options=options)
    if _PDFIUM_BACKEND:
        from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
        pdf_format = PdfFormatOption(pipeline_options=options, backend=PyPdfiumDocumentBackend)
    converter = DocumentConverter(format_options={InputFormat.PDF: pdf_format})
    try:
        doc = converter.convert(DocumentStream(name=os.path.basename(name), stream=io.BytesIO(data))).document
    except Exception as e:  # noqa: BLE001
        raise LoaderError(f"Docling couldn't read {os.path.basename(name)}: {e}") from e

    page_numbers = sorted(doc.pages) if getattr(doc, "pages", None) else []
    if not page_numbers:
        text = doc.export_to_markdown().strip()
        return [(1, text)] if text else []
    pages = []
    for no in page_numbers:
        text = doc.export_to_markdown(page_no=no).strip()
        if text:
            pages.append((no, text))
    return pages
