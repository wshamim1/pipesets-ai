"""PDF reader — built-in tool `pdf_reader`."""

import io
import re
from typing import Any, Dict, List, Optional

import httpx

from tools.base import ToolSpec, params, tool_path

TOOL = ToolSpec(
    id="pdf_reader",
    name="PDF Reader",
    icon="📃",
    category="Data & Files",
    description="Extracts the text of a PDF, page by page. Input is a local file path or an https:// URL.",
    default_config={"allowed_dir": "", "pages": "", "max_chars": 20000},
    order=120,
    parameters=params(
        {"source": {"type": "string", "description": "A PDF file path or https:// URL"}},
        {
            "pages": {"type": "string", "description": "Pages to read, e.g. 1-3,5; default all"},
            "max_chars": {"type": "integer", "minimum": 200, "maximum": 100000, "description": "Longest text to return"},
        },
    ),
    input_param="source",
)

MAX_DOWNLOAD = 25 * 1024 * 1024


def _page_numbers(spec: str, total: int) -> List[int]:
    """'1-3,7' → [0, 1, 2, 6] (1-based in, 0-based out); '' → every page."""
    if not spec.strip():
        return list(range(total))
    pages: List[int] = []
    for part in spec.split(","):
        m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", part)
        if m:
            start, end = int(m.group(1)), int(m.group(2) or m.group(1))
            pages += [p - 1 for p in range(start, end + 1) if 1 <= p <= total]
    return sorted(set(pages))


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    from pypdf import PdfReader

    source = inp.strip().strip("'\"")
    try:
        if source.startswith(("http://", "https://")):
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(source)
                resp.raise_for_status()
            if len(resp.content) > MAX_DOWNLOAD:
                return f"[PDF Reader] File is larger than {MAX_DOWNLOAD // (1024 * 1024)} MB."
            reader, name = PdfReader(io.BytesIO(resp.content)), source.rsplit("/", 1)[-1] or source
        else:
            path, err = tool_path(source, cfg, "PDF Reader")
            if err:
                return err
            reader, name = PdfReader(path), path.rsplit("/", 1)[-1]
        if reader.is_encrypted and not reader.decrypt(cfg.get("password", "")):
            return "[PDF Reader] The PDF is password-protected (set `password` in config)."
        total = len(reader.pages)
        wanted = _page_numbers(str(cfg.get("pages", "")), total)
        max_chars = int(cfg.get("max_chars", 20000))
        parts, used = [], 0
        for i in wanted:
            text = (reader.pages[i].extract_text() or "").strip()
            chunk = f"--- Page {i + 1} ---\n{text}"
            if used + len(chunk) > max_chars:
                parts.append(f"…(truncated at {max_chars} characters; use `pages` to read further)")
                break
            parts.append(chunk)
            used += len(chunk)
        if not any(p.strip() for p in parts):
            return f"[PDF Reader] No extractable text in {name} — it may be scanned images (try Docling with OCR)."
        meta = reader.metadata or {}
        title = getattr(meta, "title", None) or ""
        return f"[PDF: {name}{' — ' + title if title else ''}] {total} pages\n\n" + "\n\n".join(parts)
    except FileNotFoundError:
        return f"[PDF Reader] File not found: {source}"
    except Exception as e:
        return f"[PDF Reader] Error: {e}"
