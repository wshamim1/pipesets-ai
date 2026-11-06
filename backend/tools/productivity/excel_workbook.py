"""Excel workbook (OneDrive) — built-in tool `excel_workbook` (Microsoft Graph workbook, read-only).

Lists the sheets of an .xlsx stored in the user's OneDrive (input empty) and reads one sheet's
used range as a markdown table, values only. Auth is a delegated Microsoft OAuth access token
(+ refresh token / client id / secret when present) in the node config, resolved from a
``secret://`` ref. Delegate scopes: ``offline_access Files.Read.All``.
"""

from typing import Any, Dict, List, Optional
from urllib.parse import quote

from tools.base import ToolSpec, markdown_table, params
from tools.productivity._ms_auth import GRAPH, call as ms_call
from tools.productivity._ms_auth import ms_error

LABEL = "[Excel]"


def _trunc(cell: Any) -> Any:
    s = str(cell) if cell is not None else ""
    return s[:120] + "…" if len(s) > 120 else (s if s else "")


TOOL = ToolSpec(
    id="excel_workbook",
    name="Excel Workbook (OneDrive)",
    icon="📊",
    category="Productivity",
    description=("Reads an .xlsx workbook from the signed-in user's OneDrive via Microsoft Graph: "
                 "input empty = the workbook's sheet names in order, a sheet name = that sheet's "
                 "used range. Config holds the Graph drive item id (from onedrive) or the "
                 "workbook's OneDrive path. Delegated Graph scopes: Files.Read.All."),
    default_config={"access_token": "", "file_path": "", "file_id": "", "max_rows": 20},
    order=90,
    required=("access_token",),
    parameters=params(
        {"sheet": {"type": "string", "description": "Sheet name to read; empty lists the workbook's sheets"}},
        {
            "file_id": {"type": "string", "description": "The drive item id of the workbook (from onedrive)"},
            "path": {"type": "string", "description": "Or the workbook's OneDrive path, e.g. Documents/report.xlsx"},
            "max_rows": {"type": "integer", "minimum": 1, "maximum": 100,
                         "description": "Most rows to return"},
        },
    ),
    input_param="sheet",
)


async def _item_id(cfg: Dict[str, Any]) -> Any:
    """The drive item id of the workbook: file_id, or the id found at the given path."""
    file_id = str(cfg.get("file_id") or "").strip()
    if file_id:
        return file_id
    path = str(cfg.get("path") or cfg.get("file_path") or "").strip().strip("/")
    if not path:
        return ""
    resp = await ms_call(cfg, "GET", f"{GRAPH}/me/drive/root:/{path}", query={"$select": "id,name"})
    if resp.status_code != 200:
        return ms_error(LABEL, resp)
    return resp.json().get("id") or ""


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("access_token") or "").strip()
    if not token:
        return (f"{LABEL} access_token is required in config — provide a Microsoft OAuth access token "
                "(or a secret:// ref) with the Files.Read.All delegated scope.")
    item = await _item_id(cfg)
    if not item:
        return f"{LABEL} A file_id (from onedrive) or a path to the .xlsx is required."
    sheet = str(inp or "").strip()

    if not sheet or sheet.lower() in ("?", "sheets", "list"):
        sheets = await ms_call(cfg, "GET", f"{GRAPH}/me/drive/items/{item}/workbook/worksheets",
                               query={"$select": "id,name,position"})
        if sheets.status_code != 200:
            return ms_error(LABEL, sheets)
        named: List[Dict[str, Any]] = sheets.json().get("value") or []
        if not named:
            return f"{LABEL} The workbook has no sheets."
        return (f"{LABEL} {len(named)} sheet(s), in order: " +
                ", ".join(f"'{s.get('name')}'" for s in named) +
                "\nTo read one: pass its name again.")

    max_rows = min(max(int(cfg.get("max_rows", 20) or 20), 1), 100)
    used = await ms_call(cfg, "GET", f"{GRAPH}/me/drive/items/{item}/workbook/worksheets"
                                     f"/{quote(sheet, safe='')}/usedRange", query={"valuesOnly": "true"})
    if used.status_code != 200:
        return ms_error(LABEL, used)
    data = used.json() or {}
    text = data.get("text") or data.get("values") or []
    if not text:
        return f"{LABEL} Sheet '{sheet}' is empty."
    cols = len(text[0]) if text else 0
    if len(text) == 1:
        cells = ", ".join(str(c) if str(c) else "(empty)" for c in text[0])
        return f"{LABEL} Sheet '{sheet}': 1 row, {cols} column(s)\n{cells}"
    shown = text[:max_rows]
    table = markdown_table([_trunc(c) for c in shown[0]], [[_trunc(c) for c in row] for row in shown[1:]])
    note = ""
    if len(text) > max_rows:
        note = f"\n\nShowing {max_rows} of {len(text)} rows — pass max_rows for more."
    return f"{LABEL} Sheet '{sheet}': {len(text)} row(s), {cols} column(s)\n{table}{note}"
