"""Image (OCR) — document loader `image` (OCR engines in loaders/_ocr.py)."""

import asyncio
from typing import Any, Dict, List

from loaders import _ocr
from loaders._common import read_file
from loaders.base import Document, LoaderError, LoaderSpec, document

LOADER = LoaderSpec(
    type="image",
    label="Image (OCR)",
    icon="🖼️",
    category="Files",
    desc="Read text from scanned images (PNG, JPG, TIFF) with Tesseract, Docling or a vision model",
    source_label="File Path",
    placeholder="/path/to/scan.png",
    file_based=True,
    aliases=("png", "jpg", "jpeg", "tiff", "ocr", "unstructuredimage", "imagecaption"),
    order=240,
)
EXTENSIONS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")


def parse(name: str, data: bytes, cfg: Dict[str, Any]) -> List[Document]:
    text, engine = _ocr.image_text(name, data, cfg)
    if not text.strip():
        raise LoaderError(f"No text found in {name}.")
    return [document(text.strip(), source=name, page=1, pages=1, parser=f"ocr:{engine}")]


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    name, data = read_file(source)
    return await asyncio.to_thread(parse, name, data, cfg)
