"""PDF Generator — built-in tool `pdf_generator`."""

import os
import tempfile
from typing import Any, Dict, Optional

from tools.base import Select, ToolSpec, params

TOOL = ToolSpec(
    id="pdf_generator",
    name="PDF Generator",
    icon="🧾",
    category="Data & Files",
    description="Generates a PDF document from input text (article, report, notes).",
    default_config={"output_dir": "", "file_name": "", "title": "", "page_size": "A4"},
    order=70,
    selects={
        "page_size": Select("Page size", (("A4", "A4"), ("letter", "Letter"))),
    },
    parameters=params(
        {"text": {"type": "string", "description": "The document text"}},
        {"title": {"type": "string", "description": "Document title"}},
    ),
    input_param="text",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    text = inp.strip()
    if not text:
        return "[PDF Generator] No content provided. Pass article/report text as input."

    output_dir = (cfg.get("output_dir", "") or "").strip()
    file_name = (cfg.get("file_name", "") or "").strip()
    title = (cfg.get("title", "") or "").strip()
    page_size = (cfg.get("page_size", "A4") or "A4").strip().upper()

    try:
        from reportlab.lib.pagesizes import A4, LETTER
        from reportlab.pdfgen import canvas
    except ImportError:
        return "[PDF Generator] reportlab is not installed. Run: pip install reportlab"

    safe_stem = "generated_article"
    if file_name:
        safe_stem = "".join(ch for ch in file_name if ch.isalnum() or ch in ("-", "_", ".", " ")).strip() or safe_stem
    if not safe_stem.lower().endswith(".pdf"):
        safe_stem += ".pdf"

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.abspath(os.path.join(output_dir, safe_stem))
    else:
        fd, tmp_path = tempfile.mkstemp(prefix="agentic_", suffix=".pdf")
        os.close(fd)
        output_path = tmp_path

    page_w, page_h = LETTER if page_size == "LETTER" else A4
    left_margin = 50
    right_margin = 50
    top_margin = 50
    bottom_margin = 50
    line_height = 16

    try:
        c = canvas.Canvas(output_path, pagesize=(page_w, page_h))

        y = page_h - top_margin
        if title:
            c.setFont("Helvetica-Bold", 16)
            c.drawString(left_margin, y, title)
            y -= line_height * 2

        c.setFont("Helvetica", 11)
        usable_w = page_w - left_margin - right_margin
        max_chars_per_line = max(40, int(usable_w / 6))

        paragraphs = text.split("\n")
        for para in paragraphs:
            words = para.split()
            if not words:
                y -= line_height
                if y < bottom_margin:
                    c.showPage()
                    c.setFont("Helvetica", 11)
                    y = page_h - top_margin
                continue

            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if len(candidate) <= max_chars_per_line:
                    current = candidate
                    continue

                c.drawString(left_margin, y, current)
                y -= line_height
                if y < bottom_margin:
                    c.showPage()
                    c.setFont("Helvetica", 11)
                    y = page_h - top_margin
                current = word

            if current:
                c.drawString(left_margin, y, current)
                y -= line_height
                if y < bottom_margin:
                    c.showPage()
                    c.setFont("Helvetica", 11)
                    y = page_h - top_margin

            y -= 4
            if y < bottom_margin:
                c.showPage()
                c.setFont("Helvetica", 11)
                y = page_h - top_margin

        c.save()
        size = os.path.getsize(output_path)
        return (
            f"[PDF Generator] PDF created successfully.\n"
            f"Path: {output_path}\n"
            f"Size: {size} bytes"
        )
    except Exception as e:
        return f"[PDF Generator] Error: {e}"
