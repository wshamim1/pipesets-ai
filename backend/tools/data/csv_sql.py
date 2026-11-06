"""CSV SQL — built-in tool `csv_sql` (SQLite in memory; offline).

Loads CSV (pasted text, or a file confined to ``allowed_dir``) into a table named ``data`` and runs
one SQL query on it. Numbers become numbers so SUM / AVG / ORDER BY work. Only reads are allowed:
an authorizer refuses anything but SELECT, ATTACH / PRAGMA / writes included, and a progress
handler stops runaway queries.
"""

import asyncio
import csv
import io
import re
import sqlite3
from typing import Any, Dict, List, Optional

from tools.base import ToolSpec, json_input, markdown_table, params, tool_path

LABEL = "[CSV SQL]"
MAX_INPUT_BYTES = 20_000_000
MAX_STEPS = 50_000_000   # SQLite VM steps (progress handler is called every 1000)
_ALLOWED = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
            getattr(sqlite3, "SQLITE_RECURSIVE", 33)}

TOOL = ToolSpec(
    id="csv_sql",
    name="CSV SQL Query",
    icon="🧮",
    category="Data & Files",
    description="Runs a SQL query over CSV data (pasted, or a file in allowed_dir) as a table named data — filter, group, join with itself, aggregate. Read-only.",
    default_config={"allowed_dir": "", "max_rows": 100},
    order=435,
    parameters=params(
        {"sql": {"type": "string", "description": "One SELECT query over the table `data`, e.g. SELECT region, SUM(amount) FROM data GROUP BY region"}},
        {"csv": {"type": "string", "description": "The CSV text, header row first"},
         "path": {"type": "string", "description": "A CSV file to read instead of csv"}},
    ),
    to_input=json_input,
)


def _columns(header: List[str]) -> List[str]:
    cols, seen = [], set()
    for i, raw in enumerate(header):
        name = re.sub(r"\W+", "_", raw.strip()).strip("_").lower() or f"col{i + 1}"
        base, n = name, 2
        while name in seen:
            name, n = f"{base}_{n}", n + 1
        seen.add(name)
        cols.append(name)
    return cols


def _value(v: str):
    s = v.strip()
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", s):
        return float(s)
    return v


def _query(text: str, sql: str, max_rows: int) -> str:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return f"{LABEL} The CSV is empty."
    cols = _columns(rows[0])
    conn = sqlite3.connect(":memory:")
    try:
        quoted = ", ".join('"' + c + '"' for c in cols)   # names are word characters only
        conn.execute(f"CREATE TABLE data ({quoted})")
        width = len(cols)
        conn.executemany(f"INSERT INTO data VALUES ({', '.join('?' * width)})",
                         ([_value(r[i]) if i < len(r) else None for i in range(width)] for r in rows[1:] if r))
        conn.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in _ALLOWED else sqlite3.SQLITE_DENY)
        steps = [0]

        def progress():
            steps[0] += 1000
            return 1 if steps[0] > MAX_STEPS else 0
        conn.set_progress_handler(progress, 1000)
        try:
            cur = conn.execute(sql)
            result = cur.fetchmany(max_rows + 1)
        except sqlite3.DatabaseError as e:
            msg = str(e)
            if "not authorized" in msg:
                msg = "only SELECT queries over `data` are allowed"
            elif "interrupted" in msg:
                msg = "the query ran too long and was stopped"
            return f"{LABEL} Query failed: {msg}. Columns: {', '.join(cols)}"
        header = [d[0] for d in cur.description or []]
    finally:
        conn.close()
    if not result:
        return f"{LABEL} No rows. Columns: {', '.join(cols)}"
    more = len(result) > max_rows
    return (f"{LABEL} {min(len(result), max_rows)}{'+' if more else ''} row(s) from {len(rows) - 1} CSV row(s)\n\n"
            + markdown_table(header, [list(r) for r in result[:max_rows]])
            + (f"\n\n(More rows not shown — add a LIMIT or raise max_rows.)" if more else ""))


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import json
    try:
        args = json.loads(inp) if inp else {}
    except json.JSONDecodeError:
        args = {}
    if not isinstance(args, dict) or not str(args.get("sql") or "").strip():
        return f'{LABEL} Input is JSON: {{"sql": "SELECT … FROM data", "csv": "a,b\\n1,2"}} or {{"sql": …, "path": "file.csv"}}.'
    text = args.get("csv")
    if not text and args.get("path"):
        path, err = tool_path(str(args["path"]), cfg, "CSV SQL")
        if err:
            return err
        try:
            with open(path, "rb") as f:
                raw = f.read(MAX_INPUT_BYTES + 1)
        except OSError as e:
            return f"{LABEL} Couldn't read {args['path']}: {e.strerror or e}"
        text = raw.decode("utf-8-sig", errors="replace")
    if not text:
        return f"{LABEL} Provide the CSV text (csv) or a file (path)."
    if len(text) > MAX_INPUT_BYTES:
        return f"{LABEL} The CSV is too large (limit {MAX_INPUT_BYTES // 1_000_000} MB)."
    max_rows = max(1, min(int(cfg.get("max_rows") or 100), 1000))
    return await asyncio.to_thread(_query, str(text), str(args["sql"]), max_rows)
