"""Excel / CSV import and export for eval datasets and run results."""

import csv
import io
from typing import Any, Dict, List, Optional, Sequence, Tuple

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

MAX_IMPORT_ROWS = 5000

# Header aliases (lower-cased, "_" → " ") so sheets from other tools import without renaming columns.
PROMPT_KEYS = {"prompt", "input", "question", "query", "user input", "test input", "message", "utterance", "test case"}
EXPECTED_KEYS = {"expected", "expected output", "expected answer", "answer", "output", "reference",
                 "ground truth", "expected result", "expected response"}
TAG_KEYS = {"tags", "tag", "category", "categories", "type", "labels", "label"}

CASE_HEADERS = ["prompt", "expected_output", "tags", "source"]


def _norm_header(v: Any) -> str:
    return " ".join(str(v or "").strip().lower().replace("_", " ").split())


def _rows_from_file(filename: str, content: bytes) -> List[List[Any]]:
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [list(r) for _, r in zip(range(MAX_IMPORT_ROWS + 10), ws.iter_rows(values_only=True))]
        wb.close()
        return rows
    if name.endswith((".csv", ".tsv", ".txt")):
        text = content.decode("utf-8-sig", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel_tab if name.endswith(".tsv") else csv.excel
        return [r for _, r in zip(range(MAX_IMPORT_ROWS + 10), csv.reader(io.StringIO(text), dialect))]
    raise ValueError("Unsupported file type — upload .xlsx or .csv (old .xls: save as .xlsx first)")


def parse_cases(filename: str, content: bytes) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Read test cases from the first sheet. Columns are matched by header name (prompt/input/
    question…, expected/answer…, tags/category…); without a recognised header, column A is the
    prompt, B the expected output and C the tags. Returns (cases, info)."""
    rows = [r for r in _rows_from_file(filename, content) if any(str(c or "").strip() for c in r)]
    if not rows:
        return [], {"columns": {}, "header_row": None, "rows": 0}

    cols: Dict[str, Optional[int]] = {"prompt": None, "expected": None, "tags": None}
    header_idx: Optional[int] = None
    for i, row in enumerate(rows[:5]):
        names = [_norm_header(c) for c in row]
        if any(n in PROMPT_KEYS for n in names):
            header_idx = i
            for j, n in enumerate(names):
                if n in PROMPT_KEYS and cols["prompt"] is None:
                    cols["prompt"] = j
                elif n in EXPECTED_KEYS and cols["expected"] is None:
                    cols["expected"] = j
                elif n in TAG_KEYS and cols["tags"] is None:
                    cols["tags"] = j
            break
    if header_idx is None:
        cols = {"prompt": 0, "expected": 1, "tags": 2}

    def cell(row: Sequence[Any], key: str) -> str:
        j = cols[key]
        return str(row[j]).strip() if j is not None and j < len(row) and row[j] is not None else ""

    cases = []
    for row in rows[(header_idx + 1) if header_idx is not None else 0:][:MAX_IMPORT_ROWS]:
        prompt = cell(row, "prompt")
        if not prompt:
            continue
        raw_tags = cell(row, "tags").replace(";", ",")
        cases.append({
            "prompt": prompt,
            "expected_output": cell(row, "expected"),
            "tags": [t.strip().lower().replace(" ", "_") for t in raw_tags.split(",") if t.strip()],
        })
    header = rows[header_idx] if header_idx is not None else []
    info = {
        "header_row": header_idx + 1 if header_idx is not None else None,
        "columns": {k: (str(header[v]) if header_idx is not None else f"column {chr(65 + v)}")
                    for k, v in cols.items() if v is not None},
        "rows": len(rows) - (1 if header_idx is not None else 0),
    }
    return cases, info


def build_xlsx(sheets: List[Dict[str, Any]]) -> bytes:
    """sheets: [{title, headers, rows, widths?}] → workbook bytes with a styled, frozen header row."""
    wb = Workbook()
    wb.remove(wb.active)
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="4338CA")
    for sh in sheets:
        ws = wb.create_sheet(sh["title"][:31])
        ws.append(sh["headers"])
        for c in ws[1]:
            c.font, c.fill = head_font, head_fill
        for r in sh["rows"]:
            ws.append(list(r))
        ws.freeze_panes = "A2"
        for i, w in enumerate(sh.get("widths") or [], start=1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
        wrap = Alignment(wrap_text=True, vertical="top")
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.alignment = wrap
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_csv(headers: List[str], rows: List[Sequence[Any]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")   # BOM so Excel opens UTF-8 correctly
