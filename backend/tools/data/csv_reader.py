"""CSV Reader — built-in tool `csv_reader`."""

import os
from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="csv_reader",
    name="CSV Reader",
    icon="📊",
    category="Data & Files",
    description="Reads a local CSV file and returns its contents as a markdown table. Input is the file path.",
    default_config={"allowed_dir": "", "max_rows": 50},
    order=20,
    parameters=params(
        {"path": {"type": "string", "description": "CSV file path"}},
        {"max_rows": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "Most rows to return"}},
    ),
    input_param="path",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import csv as _csv
    allowed_dir = cfg.get("allowed_dir", "").strip()
    max_rows = int(cfg.get("max_rows", 50))
    path = inp.strip().strip("'\"")
    if allowed_dir and not os.path.isabs(path):
        path = os.path.join(allowed_dir, path)
    if allowed_dir and not os.path.abspath(path).startswith(os.path.abspath(allowed_dir)):
        return f"[CSV Reader] Access denied: path is outside allowed directory '{allowed_dir}'"
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            reader = _csv.reader(fh)
            rows = list(reader)
        if not rows:
            return f"[CSV Reader] File is empty: {path}"
        header = rows[0]
        data_rows = rows[1:max_rows + 1]
        col_widths = [max(len(str(v)) for v in [header[i]] + [r[i] for r in data_rows if i < len(r)]) for i in range(len(header))]
        def fmt_row(row: list) -> str:
            return "| " + " | ".join(str(v).ljust(col_widths[i]) if i < len(col_widths) else str(v) for i, v in enumerate(row)) + " |"
        sep = "| " + " | ".join("-" * w for w in col_widths) + " |"
        lines = [fmt_row(header), sep] + [fmt_row(r) for r in data_rows]
        total = len(rows) - 1
        suffix = f"\n\n(showing {len(data_rows)} of {total} rows)" if total > max_rows else f"\n\n({total} rows total)"
        return f"[CSV: {path}]\n\n" + "\n".join(lines) + suffix
    except FileNotFoundError:
        return f"[CSV Reader] File not found: {path}"
    except Exception as e:
        return f"[CSV Reader] Error: {e}"
