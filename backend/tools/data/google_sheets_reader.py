"""Google Sheets (public / published) — built-in tool `google_sheets_reader`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, markdown_table, params

TOOL = ToolSpec(
    id="google_sheets_reader",
    name="Google Sheets Reader",
    icon="🟩",
    category="Data & Files",
    description="Reads a Google Sheet shared as 'Anyone with the link' as a markdown table. Input is the sheet URL.",
    default_config={"sheet_url": "", "max_rows": 50},
    order=100,
    parameters=params(
        {"url": {"type": "string", "description": "The sheet URL (shared as anyone with the link)"}},
        {"max_rows": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "Most rows to return"}},
    ),
    input_param="url",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import csv as _csv
    import io
    import re
    source = inp if "docs.google.com" in inp else cfg.get("sheet_url", "")
    m = re.search(r"/spreadsheets/d/(?:e/)?([A-Za-z0-9_-]+)", source)
    if not m:
        return "[Google Sheets] Provide a Google Sheets URL (shared as 'Anyone with the link') as input or sheet_url."
    gid = re.search(r"[#&?]gid=(\d+)", source)
    url = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv" + (f"&gid={gid.group(1)}" if gid else "")
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
        if resp.status_code in (401, 403) or "text/html" in resp.headers.get("content-type", ""):
            return "[Google Sheets] This sheet isn't public. Share it as 'Anyone with the link can view'."
        resp.raise_for_status()
        rows = list(_csv.reader(io.StringIO(resp.text)))
        if not rows:
            return "[Google Sheets] The sheet is empty."
        max_rows = int(cfg.get("max_rows", 50))
        return (f"[Google Sheet {m.group(1)[:10]}…]\n\n" + markdown_table(rows[0], rows[1:max_rows + 1])
                + f"\n\n(showing {min(max_rows, len(rows) - 1)} of {len(rows) - 1} rows)")
    except Exception as e:
        return f"[Google Sheets] Error: {e}"
