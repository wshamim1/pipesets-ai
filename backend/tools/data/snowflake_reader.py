"""Snowflake — built-in tool `snowflake_reader` (snowflake-connector-python).

Runs one SELECT / SHOW / DESCRIBE / WITH statement and returns the rows as a markdown table. The
connector is optional — install ``snowflake-connector-python`` (it is commented in
``backend/requirements.txt``). Auth is account / user / password (+ warehouse / database / schema)
in the node config, resolved from ``secret://`` refs like any other credential.
"""

import asyncio
import re
from typing import Any, Dict, List, Optional

from tools.base import ToolSpec, markdown_table, params

LABEL = "[Snowflake]"
READONLY = ("select", "show", "describe", "desc", "explain", "with")


def _trunc(v: Any) -> str:
    s = "NULL" if v is None else str(v)
    return s[:120] + "…" if len(s) > 120 else s


def _first_keyword(sql: str) -> str:
    return (re.split(r"\(|\s", sql.strip(), 1)[0] or "").lower()


TOOL = ToolSpec(
    id="snowflake_reader",
    name="Snowflake",
    icon="❄️",
    category="Data & Files",
    description=("Runs one read statement (SELECT / SHOW / DESCRIBE / WITH, or EXPLAIN) on a "
                 "Snowflake account and returns the rows as a markdown table. Needs the "
                 "snowflake-connector-python package."),
    default_config={"account": "", "user": "", "password": "", "warehouse": "", "database": "",
                    "schema": "", "role": "", "max_results": 50},
    order=220,
    required=("account", "user", "password"),
    parameters=params(
        {"sql": {"type": "string", "description": "One Snowflake statement — SELECT, SHOW, DESCRIBE, EXPLAIN or WITH"}},
        {"max_results": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Most rows to return"}},
    ),
    input_param="sql",
)


def _connect(conn_cfg: Dict[str, Any]):
    import snowflake.connector as connector
    kwargs = {k: v for k, v in conn_cfg.items() if v}
    return connector.connect(**kwargs)


def _execute(conn_cfg: Dict[str, Any], sql: str, limit: int) -> tuple:
    """(header, rows, total) — sync, run in a thread; the connector fetch() is blocking."""
    conn = _connect(conn_cfg)
    try:
        cur = conn.cursor()
        try:
            cur.execute(sql)
            header = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchmany(limit)
            total = len(rows)
            many = cur.fetchone() is not None
            return header, rows, total + (1 if many else 0)
        finally:
            cur.close()
    finally:
        conn.close()


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    conn_cfg = {"account": (cfg.get("account") or "").strip(),
                "user": (cfg.get("user") or "").strip(),
                "password": (cfg.get("password") or "").strip(),
                "warehouse": (cfg.get("warehouse") or "").strip(),
                "database": (cfg.get("database") or "").strip(),
                "schema": (cfg.get("schema") or "").strip(),
                "role": (cfg.get("role") or "").strip()}
    if not (conn_cfg["account"] and conn_cfg["user"] and conn_cfg["password"]):
        return f"{LABEL} account, user and password are required in config."
    sql = str(inp or "").strip()
    if not sql:
        return f"{LABEL} Pass the SQL statement to run."
    keyword = _first_keyword(sql)
    if keyword not in READONLY and cfg.get("allow_write") is not True:
        return (f"{LABEL} Only {', '.join(READONLY)} statements are allowed (read-only) — got "
                f"{keyword.upper()}.")
    limit = min(max(int(cfg.get("max_results", 50) or 50), 1), 100)

    try:
        header, rows, total = await asyncio.to_thread(_execute, conn_cfg, sql, limit)
    except ModuleNotFoundError:
        return f"{LABEL} snowflake-connector-python is not installed — pip install snowflake-connector-python"
    except Exception as e:
        msg = str(e)
        if "password" in msg.lower() or "authentication" in msg.lower():
            return f"{LABEL} Authentication failed — check account / user / password."
        return f"{LABEL} {_trunc(msg)}"
    if not rows:
        return f"{LABEL} The query returned 0 rows."
    out = [f"{LABEL} {total} row(s)", "",
           markdown_table(header, [[_trunc(c) for c in row] for row in rows])]
    if total > limit:
        out.append(f"Showing {limit} of {total} rows — narrow the query for more.")
    return "\n".join(out).rstrip()
