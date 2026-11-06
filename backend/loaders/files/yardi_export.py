"""Yardi Report Export — document loader `yardi_export`.

Reads a report exported from Yardi Voyager (rent roll, lease expiration, tenancy schedule) as CSV
or Excel and turns each tenant row into a document. Report exports aren't clean tables, so the loader:

* finds the header row below the report's title lines (the first row naming at least three known
  columns; ``header_row`` overrides it, 1-based);
* remembers the property from group heading rows (a row with only its first cell filled) for the
  rows under it;
* skips blank, "Total" / "Grand Total" and repeated header rows.

Known columns are also copied into the document's metadata under standard names (``property``,
``unit``, ``tenant``, ``lease_from``, ``lease_to``, ``sqft``, ``monthly_rent``, …) so later steps can
match Yardi rows to leases and licenses without guessing column names.
"""

import asyncio
import csv
import datetime
import io
import os
import re
from typing import Any, Dict, List, Optional, Sequence

from loaders._common import read_file, decode
from loaders.base import Document, LoaderError, LoaderSpec, document

LOADER = LoaderSpec(
    type="yardi_export",
    label="Yardi Report Export",
    icon="🏢",
    category="Files",
    desc="Rent roll / lease expiration reports exported from Yardi (CSV or Excel), one document per tenant row",
    source_label="File Path",
    placeholder="/path/to/rent_roll.xlsx",
    file_based=True,
    aliases=("yardi", "yardivoyager", "rentroll", "yardirentroll"),
    order=200,
)
# No EXTENSIONS: plain .csv / .xlsx stay with the CSV and Excel loaders.

# Standard field → header spellings seen in Yardi exports (compared lower-case, punctuation removed)
COLUMNS: Dict[str, Sequence[str]] = {
    "property": ("property", "property code", "property name", "prop", "building"),
    "unit": ("unit", "unit no", "unit number", "suite", "space"),
    "tenant": ("tenant", "tenant name", "lease", "lease name", "name", "resident", "occupant"),
    "tenant_code": ("tenant code", "lease code", "tenant id", "lease id", "resident code"),
    "lease_type": ("lease type", "type"),
    "status": ("status", "lease status", "unit status"),
    "lease_from": ("lease from", "lease start", "start date", "from", "commencement", "move in"),
    "lease_to": ("lease to", "lease end", "end date", "to", "expiration", "expiration date", "move out"),
    "term_months": ("term", "term months", "lease term"),
    "sqft": ("sq ft", "sqft", "area", "unit sqft", "gla", "rentable sf", "rsf"),
    "beds": ("beds", "licensed beds", "bed count"),
    "monthly_rent": ("monthly rent", "rent", "current rent", "monthly charge", "base rent", "market rent"),
    "annual_rent": ("annual rent", "annual base rent", "yearly rent"),
    "rent_per_sqft": ("rent sq ft", "rent per sqft", "annual rent sq ft", "rent psf"),
    "security_deposit": ("security deposit", "deposit", "sec dep"),
    "balance": ("balance", "amount due", "past due"),
}
_LOOKUP = {spelling: field for field, spellings in COLUMNS.items() for spelling in spellings}
_TOTAL = re.compile(r"^\s*(grand\s+)?total\b|^\s*totals?\s*:", re.IGNORECASE)
MAX_TITLE_ROWS = 30


def _key(cell: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", cell.lower())).strip()


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime.datetime):
        return v.date().isoformat() if v.time() == datetime.time() else v.isoformat()
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _rows(name: str, data: bytes) -> List[List[str]]:
    ext = os.path.splitext(name)[1].lower()
    if ext in (".xlsx", ".xlsm") or data[:2] == b"PK":
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            ws = wb.worksheets[0]
            return [[_cell(v) for v in r] for r in ws.iter_rows(values_only=True)]
        finally:
            wb.close()
    if ext == ".xls":
        raise LoaderError(f"{os.path.basename(name)} is an old .xls workbook — export the report as .xlsx or CSV.")
    text = decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect=dialect)]


def _header_index(rows: List[List[str]], cfg: Dict[str, Any]) -> int:
    if cfg.get("header_row"):
        idx = int(cfg["header_row"]) - 1
        if not 0 <= idx < len(rows):
            raise LoaderError(f"header_row {cfg['header_row']} is outside the report ({len(rows)} rows).")
        return idx
    for i, row in enumerate(rows[:MAX_TITLE_ROWS]):
        if sum(1 for c in row if _key(c) in _LOOKUP) >= 3:
            return i
    raise LoaderError("Couldn't find the header row (no row in the first 30 names three known columns such as "
                      "Property, Unit, Tenant, Lease From, Lease To, Rent). Set header_row on the node.")


def _fields(header: List[str]) -> Dict[int, str]:
    """Column index → standard field, first match wins (so "Lease" doesn't override "Tenant")."""
    out: Dict[int, str] = {}
    taken = set()
    for i, h in enumerate(header):
        field = _LOOKUP.get(_key(h))
        if field and field not in taken:
            out[i] = field
            taken.add(field)
    return out


def parse(name: str, data: bytes, cfg: Dict[str, Any]) -> List[Document]:
    rows = _rows(name, data)
    h = _header_index(rows, cfg)
    header = [c or f"Column {i + 1}" for i, c in enumerate(rows[h])]
    fields = _fields(header)
    title = " · ".join(" ".join(c for c in r if c) for r in rows[:h] if any(r)) or None
    max_rows = int(cfg.get("max_rows", 10000))
    header_keys = [_key(c) for c in rows[h]]
    group: Optional[str] = None
    docs: List[Document] = []
    for n, row in enumerate(rows[h + 1:], start=h + 2):
        filled = [c for c in row if c]
        if not filled:
            continue
        if _TOTAL.match(filled[0]) or [_key(c) for c in row[:len(header_keys)]] == header_keys:
            continue
        if len(filled) == 1 and row and row[0]:
            group = row[0]          # a property heading above its rows
            continue
        values = {header[i]: row[i] for i in range(min(len(header), len(row))) if row[i]}
        std = {fields[i]: row[i] for i in fields if i < len(row) and row[i]}
        if group and "property" not in std:
            std["property"] = group
        if not ({"unit", "tenant", "tenant_code"} & std.keys()):
            continue
        lines = [f"{k}: {v}" for k, v in values.items()]
        if group and "property" not in {fields.get(i) for i in fields}:
            lines.insert(0, f"Property: {group}")
        docs.append(document("\n".join(lines), source=name, row=n, report=title, **std))
        if len(docs) >= max_rows:
            break
    if not docs:
        raise LoaderError(f"{name} has no tenant rows under its header (row {h + 1}).")
    return docs


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    name, data = read_file(source)
    return await asyncio.to_thread(parse, name, data, cfg)
