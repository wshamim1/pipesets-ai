"""Excel (XLSX) — document loader `excel`."""

import asyncio
import io
from typing import Any, Dict, List

from loaders._common import read_file
from loaders.base import Document, LoaderError, LoaderSpec, document

LOADER = LoaderSpec(
    type="excel",
    label="Excel (XLSX)",
    icon="📗",
    category="Files",
    desc="Load sheets from Excel workbooks",
    source_label="File Path",
    placeholder="/path/to/book.xlsx",
    file_based=True,
    aliases=("xlsx", "xls", "unstructuredexcel", "unstructuredexcelloader"),
    order=90,
)
EXTENSIONS = (".xlsx", ".xlsm")


def parse(name: str, data: bytes, cfg: Dict[str, Any]) -> List[Document]:
    """One document per sheet, as a markdown table (header row first)."""
    import openpyxl

    max_rows = int(cfg.get("max_rows", 2000))
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    docs = []
    try:
        for ws in wb.worksheets:
            rows = []
            for r in ws.iter_rows(values_only=True):
                if any(v is not None for v in r):
                    rows.append(["" if v is None else str(v).replace("|", "\\|").replace("\n", " ") for v in r])
                if len(rows) > max_rows:
                    break
            if not rows:
                continue
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            table = "\n".join(["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width] + ["| " + " | ".join(r) + " |" for r in rows[1:]])
            docs.append(document(f"Sheet: {ws.title}\n\n{table}", source=name, sheet=ws.title, rows=len(rows) - 1))
    finally:
        wb.close()
    if not docs:
        raise LoaderError(f"{name} has no data.")
    return docs


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    name, data = read_file(source)
    return await asyncio.to_thread(parse, name, data, cfg)
