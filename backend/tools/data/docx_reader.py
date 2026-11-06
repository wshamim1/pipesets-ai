"""Word (.docx) reader — built-in tool `docx_reader`."""

import os
from typing import Any, Dict, Optional

from tools.base import ToolSpec, markdown_table, params, tool_path

TOOL = ToolSpec(
    id="docx_reader",
    name="Word Reader",
    icon="📘",
    category="Data & Files",
    description="Extracts headings, paragraphs and tables from a local .docx file. Input is the file path.",
    default_config={"allowed_dir": "", "max_chars": 12000},
    order=90,
    parameters=params({"path": {"type": "string", "description": ".docx file path"}}),
    input_param="path",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    path, err = tool_path(inp, cfg, "Word Reader")
    if err:
        return err
    try:
        import docx
        doc = docx.Document(path)
        parts = []
        for p in doc.paragraphs:
            if not p.text.strip():
                continue
            style = (p.style.name or "").lower() if p.style is not None else ""
            level = style.replace("heading", "").strip() if style.startswith("heading") else ""
            parts.append(f"{'#' * int(level)} {p.text}" if level.isdigit() else p.text)
        for t in doc.tables:
            rows = [[c.text.strip() for c in r.cells] for r in t.rows]
            if rows:
                parts.append(markdown_table(rows[0], rows[1:]))
        text = "\n\n".join(parts)
        max_chars = int(cfg.get("max_chars", 12000))
        return f"[Word: {os.path.basename(path)}]\n\n" + text[:max_chars] + ("\n\n…(truncated)" if len(text) > max_chars else "")
    except FileNotFoundError:
        return f"[Word Reader] File not found: {path}"
    except Exception as e:
        return f"[Word Reader] Error: {e}"
