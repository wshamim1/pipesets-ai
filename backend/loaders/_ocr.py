"""OCR engines for scanned PDF pages and images (the PDF loader's fallback and the Image loader).

``ocr_engine`` picks one:

    auto       the first local engine installed: ocrmypdf → tesseract → docling (default)
    ocrmypdf   OCRmyPDF adds a text layer to the scanned pages (fixes rotation first); needs the
               ocrmypdf, tesseract and ghostscript programs
    tesseract  Tesseract on each page image; needs the tesseract program
    docling    Docling's OCR (loaders/_docling.py); best on tables, needs docling + torch
    vision     a vision model through the LLM gateway transcribes each page; costs per page, sends
               the page images to that provider. Never picked by ``auto``
    off        no OCR

Settings: ``ocr_language`` (Tesseract codes, ``eng+spa``; default ``eng``), ``ocr_dpi`` (300),
``ocr_max_pages`` (200, vision: 50). Vision also takes ``ocr_provider`` / ``ocr_model`` /
``ocr_api_key`` / ``ocr_base_url``; without a key the project's default key for the provider is used.
"""

import asyncio
import base64
import contextvars
import io
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from loaders import _docling
from loaders.base import LoaderError

ENGINES = ("auto", "ocrmypdf", "tesseract", "docling", "vision", "off")
LOCAL = ("ocrmypdf", "tesseract", "docling")
PAGE_TIMEOUT_S = 120
VISION_PROMPT = (
    "Transcribe all text on this scanned page exactly as written, in reading order. Keep tables as Markdown "
    "tables. Don't summarise, correct or add anything; write [illegible] for text you can't read. "
    "Answer with the page text only."
)
INSTALL = {
    "ocrmypdf": "OCRmyPDF isn't installed (pip install ocrmypdf, plus the tesseract and ghostscript programs).",
    "tesseract": "Tesseract isn't installed (brew install tesseract / apt install tesseract-ocr).",
    "docling": _docling.INSTALL_HINT,
}


def available(engine: str) -> bool:
    if engine == "ocrmypdf":
        return bool(shutil.which("ocrmypdf") and shutil.which("tesseract") and shutil.which("gs"))
    if engine == "tesseract":
        return bool(shutil.which("tesseract"))
    if engine == "docling":
        return _docling.available()
    return engine == "vision"


def engine_for(cfg: Dict[str, Any]) -> str:
    """The engine the settings ask for; "off" also when the old ``ocr_fallback: false`` is set."""
    if cfg.get("ocr_fallback") is False or str(cfg.get("ocr_fallback")).lower() == "false":
        return "off"
    engine = str(cfg.get("ocr_engine") or "auto").lower()
    if engine not in ENGINES:
        raise LoaderError(f"Unknown OCR engine '{engine}' (choose {', '.join(ENGINES)}).")
    return engine


def _pick(engine: str) -> str:
    if engine != "auto":
        if engine in INSTALL and not available(engine):
            raise LoaderError(INSTALL[engine])
        return engine
    for e in LOCAL:
        if available(e):
            return e
    raise LoaderError("No OCR engine is installed on this server. Install Tesseract (brew install tesseract / "
                      "apt install tesseract-ocr) or set the OCR engine to vision.")


# ── Page images ───────────────────────────────────────────────────────────────

def _pdf_images(data: bytes, pages: List[int], dpi: int) -> Dict[int, bytes]:
    """PNG bytes of the given (1-based) PDF pages."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        out = {}
        for no in pages:
            if 1 <= no <= len(pdf):
                image = pdf[no - 1].render(scale=dpi / 72).to_pil()
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                out[no] = buf.getvalue()
        return out
    finally:
        pdf.close()


def _png(data: bytes) -> bytes:
    """An image file (PNG, JPG, TIFF, …) as PNG bytes, first frame only."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()


# ── Engines ───────────────────────────────────────────────────────────────────

def _tesseract(png: bytes, lang: str) -> str:
    try:
        r = subprocess.run(["tesseract", "stdin", "stdout", "-l", lang], input=png, capture_output=True,
                           timeout=PAGE_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        raise LoaderError("Tesseract took too long on a page.")
    if r.returncode != 0:
        raise LoaderError(f"Tesseract failed: {r.stderr.decode(errors='replace').strip()[-300:]}")
    return r.stdout.decode("utf-8", errors="replace").strip()


def _ocrmypdf(data: bytes, pages: List[int], lang: str) -> Dict[int, str]:
    from pypdf import PdfReader

    with tempfile.TemporaryDirectory(prefix="pipesets-ocr-") as tmp:
        src, dst = os.path.join(tmp, "in.pdf"), os.path.join(tmp, "out.pdf")
        with open(src, "wb") as f:
            f.write(data)
        try:
            r = subprocess.run(["ocrmypdf", "--skip-text", "--rotate-pages", "-l", lang,
                                "--pages", ",".join(map(str, pages)), src, dst],
                               capture_output=True, timeout=PAGE_TIMEOUT_S * max(1, len(pages)), check=False)
        except subprocess.TimeoutExpired:
            raise LoaderError("OCRmyPDF took too long.")
        if r.returncode != 0 or not os.path.isfile(dst):
            raise LoaderError(f"OCRmyPDF failed: {r.stderr.decode(errors='replace').strip()[-300:]}")
        reader = PdfReader(dst)
        return {no: (reader.pages[no - 1].extract_text() or "").strip() for no in pages if no <= len(reader.pages)}


def _run(coro_fn):
    """Run an async call from sync loader code, whether or not an event loop is running here
    (Directory and S3 call ``parse`` from inside their async ``load``)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_fn())
    ctx = contextvars.copy_context()   # keeps the project scope the gateway resolves default keys from
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(ctx.run, asyncio.run, coro_fn()).result()


def _vision(images: Dict[int, bytes], cfg: Dict[str, Any]) -> Dict[int, str]:
    import llm

    provider = str(cfg.get("ocr_provider") or "").strip()
    model = str(cfg.get("ocr_model") or "").strip()
    if not provider or not model:
        raise LoaderError("Vision OCR needs a model: set ocr_provider and ocr_model (e.g. openai / gpt-4o-mini).")

    async def page(sem: asyncio.Semaphore, png: bytes) -> str:
        url = "data:image/png;base64," + base64.b64encode(png).decode()
        req = llm.LLMRequest(provider=provider, model=model, api_key=str(cfg.get("ocr_api_key") or ""),
                             base_url=cfg.get("ocr_base_url") or None, temperature=0.0, max_tokens=4096,
                             timeout_s=PAGE_TIMEOUT_S, messages=[{"role": "user", "content": [
                                 {"type": "text", "text": VISION_PROMPT},
                                 {"type": "image_url", "image_url": {"url": url}}]}])
        async with sem:
            return (await llm.complete(req)).text.strip()

    async def all_pages() -> List[str]:
        sem = asyncio.Semaphore(4)
        return await asyncio.gather(*(page(sem, png) for png in images.values()))

    try:
        texts = _run(all_pages)
    except LoaderError:
        raise
    except Exception as e:  # noqa: BLE001
        raise LoaderError(f"Vision OCR with {provider}/{model} failed: {e}") from e
    return dict(zip(images, texts))


# ── Entry points ──────────────────────────────────────────────────────────────

def _limits(cfg: Dict[str, Any], engine: str) -> Tuple[str, int, int]:
    lang = str(cfg.get("ocr_language") or "eng").strip() or "eng"
    dpi = max(72, min(600, int(cfg.get("ocr_dpi") or 300)))
    cap = int(cfg.get("ocr_max_pages") or (50 if engine == "vision" else 200))
    return lang, dpi, cap


def pdf_pages(name: str, data: bytes, pages: List[int], cfg: Dict[str, Any]) -> Tuple[Dict[int, str], Optional[str]]:
    """OCR the given (1-based) pages of a PDF → ({page: text}, engine used). ({}, None) when OCR is off."""
    engine = engine_for(cfg)
    if engine == "off" or not pages:
        return {}, None
    engine = _pick(engine)
    lang, dpi, cap = _limits(cfg, engine)
    if len(pages) > cap:
        raise LoaderError(f"{os.path.basename(name)} has {len(pages)} scanned pages; OCR is limited to {cap} "
                          "(raise ocr_max_pages).")
    if engine == "ocrmypdf":
        return _ocrmypdf(data, pages, lang), engine
    if engine == "docling":
        return {no: t for no, t in _docling.convert_pages(name, data, {**cfg, "ocr": True}) if no in pages}, engine
    images = _pdf_images(data, pages, dpi)
    if engine == "vision":
        return _vision(images, cfg), engine
    return {no: _tesseract(png, lang) for no, png in images.items()}, engine


def image_text(name: str, data: bytes, cfg: Dict[str, Any]) -> Tuple[str, str]:
    """OCR one image file → (text, engine used). OCRmyPDF works on PDFs, so ``auto`` skips it here."""
    engine = engine_for(cfg)
    if engine == "off":
        raise LoaderError("OCR is off, and an image has no text without it.")
    if engine == "auto":
        engine = next((e for e in ("tesseract", "docling") if available(e)), "auto")
        if engine == "auto":
            _pick("auto")   # raises the "no OCR engine" message
    elif engine == "ocrmypdf":
        raise LoaderError("OCRmyPDF reads PDFs only; choose tesseract, docling or vision for images.")
    else:
        _pick(engine)
    lang = _limits(cfg, engine)[0]
    if engine == "docling":
        pages = _docling.convert_pages(name, data, {**cfg, "ocr": True})
        return "\n\n".join(t for _, t in pages), engine
    png = _png(data)
    if engine == "vision":
        return _vision({1: png}, cfg)[1], engine
    return _tesseract(png, lang), engine
