"""Excel reader — built-in tool `excel_reader`."""

import os
from typing import Any, Dict, Optional

from tools.base import ToolSpec, markdown_table, params, tool_path

TOOL = ToolSpec(
    id="excel_reader",
    name="Excel Reader",
    icon="📗",
    category="Data & Files",
    description="Reads a sheet of a local .xlsx file as a markdown table. Input is the file path.",
    default_config={"allowed_dir": "", "sheet": "", "max_rows": 50},
    order=80,
    parameters=params(
        {"path": {"type": "string", "description": ".xlsx file path"}},
        {
            "sheet": {"type": "string", "description": "Sheet name; default the first"},
            "max_rows": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "Most rows to return"},
        },
    ),
    input_param="path",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    path, err = tool_path(inp, cfg, "Excel Reader")
    if err:
        return err
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheet_name = cfg.get("sheet") or wb.sheetnames[0]
        if sheet_name not in wb.sheetnames:
            return f"[Excel Reader] No sheet '{sheet_name}'. Sheets: {', '.join(wb.sheetnames)}"
        rows = [["" if v is None else str(v) for v in r] for r in wb[sheet_name].iter_rows(values_only=True)]
        wb.close()
        if not rows:
            return f"[Excel Reader] Sheet '{sheet_name}' is empty."
        max_rows = int(cfg.get("max_rows", 50))
        return (f"[Excel: {os.path.basename(path)} › {sheet_name}] (sheets: {', '.join(wb.sheetnames)})\n\n"
                + markdown_table(rows[0], rows[1:max_rows + 1])
                + f"\n\n(showing {min(max_rows, len(rows) - 1)} of {len(rows) - 1} rows)")
    except FileNotFoundError:
        return f"[Excel Reader] File not found: {path}"
    except Exception as e:
        return f"[Excel Reader] Error: {e}"
