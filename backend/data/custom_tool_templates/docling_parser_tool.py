"""
Docling custom tool template for Pipesets AI.

Expected entrypoint:
    run(input_text: str, config: dict) -> str

Usage examples:
- input_text = "/absolute/path/to/file.pdf"
- input_text = "https://example.com/report.pdf"
- config = {
    "source": "",                 # optional override for input_text
    "output_format": "markdown",  # markdown | text | json
    "max_chars": 12000             # truncate long output
  }
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.parse
import urllib.request
from typing import Any, Dict, Tuple


def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _download_to_temp(url: str) -> Tuple[str, str]:
    parsed = urllib.parse.urlparse(url)
    ext = os.path.splitext(parsed.path)[1] or ".bin"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    tmp_path = tmp.name
    tmp.close()

    with urllib.request.urlopen(url, timeout=30) as resp:  # nosec B310
        data = resp.read()
    with open(tmp_path, "wb") as f:
        f.write(data)
    return tmp_path, ext


def _safe_export(document: Any, output_format: str) -> str:
    output_format = (output_format or "markdown").lower()

    if output_format == "json":
        if hasattr(document, "export_to_dict"):
            return json.dumps(document.export_to_dict(), ensure_ascii=True)
        if hasattr(document, "to_dict"):
            return json.dumps(document.to_dict(), ensure_ascii=True)
        return json.dumps({"error": "Docling JSON export method not found"}, ensure_ascii=True)

    if output_format == "text":
        if hasattr(document, "export_to_text"):
            return document.export_to_text()
        if hasattr(document, "export_to_markdown"):
            return document.export_to_markdown()
        return str(document)

    if hasattr(document, "export_to_markdown"):
        return document.export_to_markdown()
    if hasattr(document, "export_to_text"):
        return document.export_to_text()
    return str(document)


def run(input_text: str, config: Dict[str, Any]) -> str:
    source = str(config.get("source") or input_text or "").strip()
    output_format = str(config.get("output_format") or "markdown")
    max_chars = int(config.get("max_chars") or 12000)

    if not source:
        return "[Docling] Missing source. Provide a local file path or URL in input_text/config.source"

    temp_path = ""
    try:
        if _is_url(source):
            source_path, _ = _download_to_temp(source)
            temp_path = source_path
        else:
            source_path = source

        if not os.path.isfile(source_path):
            return f"[Docling] File not found: {source_path}"

        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        result = converter.convert(source_path)
        document = result.document
        rendered = _safe_export(document, output_format)

        if max_chars > 0 and len(rendered) > max_chars:
            rendered = rendered[:max_chars] + "\n\n[Truncated output]"

        payload = {
            "success": True,
            "source": source,
            "resolved_path": source_path,
            "output_format": output_format,
            "content": rendered,
        }
        return json.dumps(payload, ensure_ascii=True)

    except Exception as exc:
        return json.dumps(
            {
                "success": False,
                "source": source,
                "error": str(exc),
                "hint": "Ensure docling is installed and source format is supported.",
            },
            ensure_ascii=True,
        )
    finally:
        if temp_path and os.path.isfile(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
