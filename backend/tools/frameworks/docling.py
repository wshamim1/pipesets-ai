"""Docling — document parsing framework — built-in tool `docling`."""

import os
from typing import Any, Dict, Optional

from tools.base import ToolSpec

TOOL = ToolSpec(
    id="docling",
    name="Docling",
    icon="📑",
    group="frameworks",
    description="Parse PDFs, DOCX, PPTX, images, HTML, and more into clean Markdown or JSON using IBM's Docling library. Supports OCR, table extraction, and layout analysis.",
    default_config={
        "input_path": "",
        "output_path": "",
        "output_format": "markdown",
        "ocr": False,
        "export_tables": True,
        "max_chars": 80000,
    },
    order=10,
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import pathlib as _pathlib

    input_path = (cfg.get("input_path") or "").strip() or inp.strip()
    output_path = (cfg.get("output_path") or "").strip()
    output_format = cfg.get("output_format", "markdown").lower()
    use_ocr = bool(cfg.get("ocr", False))
    export_tables = bool(cfg.get("export_tables", True))

    # Supported file extensions Docling can handle
    SUPPORTED_EXTS = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm",
                      ".txt", ".md", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}

    if not input_path:
        return "[Docling] No input path provided. Set 'input_path' in config or pass the file path as input."

    resolved = os.path.abspath(input_path)

    # Validate output_path: if it looks like a directory (no extension), auto-append a filename
    if output_path:
        op = _pathlib.Path(os.path.abspath(output_path))
        ext = ".json" if output_format == "json" else ".md"
        if op.suffix == "":
            # User gave a directory — treat it as the output folder, auto-name the file
            output_path = str(op / f"docling_output{ext}")
        else:
            output_path = str(op)

    def _convert_one(file_path: str) -> tuple[str, str]:
        """Convert a single file, return (content, label)."""
        from docling.document_converter import DocumentConverter
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import PdfFormatOption

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = use_ocr
        pipeline_options.do_table_structure = export_tables

        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )
        result = converter.convert(file_path)
        doc = result.document

        if output_format == "json":
            import json as _json
            return _json.dumps(doc.export_to_dict(), indent=2), "JSON"
        else:
            return doc.export_to_markdown(), "Markdown"

    def _save(content: str, out_file: str) -> str:
        """Write content to out_file, creating parent dirs. Returns saved path."""
        os.makedirs(os.path.dirname(out_file) if os.path.dirname(out_file) else ".", exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as fh:
            fh.write(content)
        return os.path.abspath(out_file)

    try:
        # ── Directory mode: parse every supported file in the folder ──────
        if os.path.isdir(resolved):
            files = sorted(
                f for f in _pathlib.Path(resolved).iterdir()
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS
            )
            if not files:
                return (
                    f"[Docling] No supported files found in: {resolved}\n"
                    f"Supported formats: {', '.join(sorted(SUPPORTED_EXTS))}"
                )

            parts = [f"[Docling — Directory]\nFolder: {resolved}\nFiles found: {len(files)}\n"]
            saved_files: list[str] = []

            for fp in files:
                try:
                    content, label = _convert_one(str(fp))
                    parts.append(f"\n{'─'*60}\n📄 {fp.name}  [{label}]\n{'─'*60}\n{content}")

                    if output_path:
                        # For directory input, save each file alongside the others
                        # using the stem name inside the output folder/path parent
                        out_dir = os.path.dirname(output_path)
                        ext = ".json" if output_format == "json" else ".md"
                        out_file = os.path.join(out_dir, fp.stem + ext)
                        saved_files.append(_save(content, out_file))
                except Exception as fe:
                    parts.append(f"\n📄 {fp.name}  — ⚠ Skipped: {fe}")

            summary = ""
            if saved_files:
                summary = "\n\n✅ Saved files:\n" + "\n".join(f"  • {s}" for s in saved_files)
            return "".join(parts) + summary

        # ── Single file mode ──────────────────────────────────────────────
        elif os.path.isfile(resolved):
            suffix = _pathlib.Path(resolved).suffix.lower()
            if suffix not in SUPPORTED_EXTS:
                return (
                    f"[Docling] Unsupported file type: '{suffix}'\n"
                    f"Supported formats: {', '.join(sorted(SUPPORTED_EXTS))}"
                )
            content, label = _convert_one(resolved)

            saved_note = ""
            if output_path:
                saved = _save(content, output_path)
                saved_note = f"\n✅ Saved to: {saved}"

            return f"[Docling — {label}]\nSource: {resolved}{saved_note}\n\n{content}"

        else:
            return f"[Docling] Path not found: {resolved}"

    except ImportError:
        return (
            "[Docling] Package not found. Install it with:\n"
            "  pip install docling\n\n"
            "Then restart the backend server."
        )
    except Exception as e:
        return f"[Docling] Error: {e}"
