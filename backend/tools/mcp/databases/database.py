"""Generic DB tool + mcp_postgres (both routed through shared engine) — `mcp_database` and `mcp_postgres`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

SQL_PARAMETERS = params({}, {"query": {"type": "string",
                                       "description": "A SELECT / WITH / EXPLAIN statement; leave out to list tables and columns"}})

TOOLS = [
    ToolSpec(
        id="mcp_database",
        name="Database Query (SQL)",
        type="mcp",
        icon="🗃️",
        group="mcp_servers",
        category="Databases & Data",
        description="Query any SQL database via a Connection node. Supports PostgreSQL, MySQL, and SQLite.",
        default_config={"transport": "native", "read_only": True},
        order=30,
        parameters=SQL_PARAMETERS,
        input_param="query",
    ),
    ToolSpec(
        id="mcp_postgres",
        name="MCP Postgres",
        type="mcp",
        icon="🐘",
        group="mcp_servers",
        category="Databases & Data",
        description="Query and inspect a Postgres database via the MCP protocol.",
        default_config={"transport": "native", "read_only": True},
        order=40,
        parameters=SQL_PARAMETERS,
        input_param="query",
    ),
]


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:

    # ── Resolve credentials from config ──────────────────────────────────
    host     = cfg.get("host") or ""
    port_raw = cfg.get("port") or ""
    database = cfg.get("database") or ""
    user     = cfg.get("user") or ""
    password = cfg.get("password") or ""
    db_type  = (cfg.get("db_type") or cfg.get("connection_type") or "").lower()
    conn_str = cfg.get("connection_string") or ""

    # Reject placeholder DSNs
    _BAD = {"postgresql://user:pass@localhost:5432/db", "postgresql://", "mysql://user:pass@localhost:3306/db", ""}
    if conn_str.strip() in _BAD or "user:pass@" in conn_str:
        conn_str = ""

    # Auto-detect db_type from conn_str prefix if not explicit
    if not db_type:
        if conn_str.startswith(("postgresql://", "postgres://")):
            db_type = "postgres"
        elif conn_str.startswith(("mysql://", "mysql+pymysql://")):
            db_type = "mysql"
        elif conn_str.startswith("sqlite://") or (database or "").endswith(".db"):
            db_type = "sqlite"
        else:
            db_type = "postgres"  # default

    # Build connection string from individual fields when present
    if not conn_str and host and database and user:
        default_port = {"postgres": 5432, "mysql": 3306}.get(db_type, 5432)
        port_val = int(port_raw) if port_raw else default_port
        from urllib.parse import quote
        u, pw = quote(user, safe=""), quote(password, safe="")
        if db_type == "mysql":
            conn_str = f"mysql+pymysql://{u}:{pw}@{host}:{port_val}/{database}"
        else:
            conn_str = f"postgresql://{u}:{pw}@{host}:{port_val}/{database}"

    if not conn_str and db_type == "sqlite" and database:
        conn_str = database  # SQLite uses the file path directly

    if not conn_str and not (host and database):
        return (
            f"[{tool_type}] No database credentials found.\n\n"
            "Draw an edge from a Connection node (Postgres, MySQL, or SQLite) to this tool — "
            "credentials are resolved at runtime and never stored in the tool config."
        )

    tag = f"[{tool_type}:{db_type}]"

    # ── DB-specific helpers ───────────────────────────────────────────────

    def _pg_connect():
        try:
            import psycopg2
            return psycopg2.connect(conn_str), "pg"
        except ImportError:
            raise RuntimeError("psycopg2 not installed — run: pip install psycopg2-binary")

    def _mysql_connect():
        try:
            import pymysql
            import pymysql.cursors
            # Parse conn_str or use individual fields
            if host and database and user:
                pv = int(port_raw) if port_raw else 3306
                return pymysql.connect(
                    host=host, port=pv, user=user, password=password,
                    database=database, cursorclass=pymysql.cursors.DictCursor,
                    autocommit=True,
                ), "mysql"
            raise RuntimeError("Missing MySQL connection fields")
        except ImportError:
            raise RuntimeError("pymysql not installed — run: pip install pymysql")

    def _sqlite_connect():
        import sqlite3 as _sqlite3
        db_path = database or conn_str.replace("sqlite:///", "").replace("sqlite://", "") or ":memory:"
        return _sqlite3.connect(db_path), "sqlite"

    def _get_schema_pg(cur) -> str:
        import psycopg2
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' ORDER BY table_name
        """)
        tables = [r[0] for r in cur.fetchall()]
        lines = ["Database schema (public schema):"]
        for t in tables:
            cur.execute("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
            """, (t,))
            cols = cur.fetchall()
            col_defs = ", ".join(f"{c[0]} {c[1]}{'?' if c[2] == 'YES' else ''}" for c in cols)
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            row_count = cur.fetchone()[0]
            lines.append(f"  • {t} ({row_count} rows): {col_defs}")
        return "\n".join(lines)

    def _get_schema_mysql(cur) -> str:
        cur.execute("SHOW TABLES")
        rows = cur.fetchall()
        tables = [list(r.values())[0] if isinstance(r, dict) else r[0] for r in rows]
        lines = [f"Database schema ({database}):"]
        for t in tables:
            cur.execute(f"DESCRIBE `{t}`")
            cols = cur.fetchall()
            if cols and isinstance(cols[0], dict):
                col_defs = ", ".join(f"{c['Field']} {c['Type']}{'?' if c['Null'] == 'YES' else ''}" for c in cols)
            else:
                col_defs = ", ".join(f"{c[0]} {c[1]}" for c in cols)
            cur.execute(f"SELECT COUNT(*) as cnt FROM `{t}`")
            cnt_row = cur.fetchone()
            row_count = cnt_row['cnt'] if isinstance(cnt_row, dict) else cnt_row[0]
            lines.append(f"  • {t} ({row_count} rows): {col_defs}")
        return "\n".join(lines)

    def _get_schema_sqlite(conn_obj) -> str:
        cur = conn_obj.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cur.fetchall()]
        lines = [f"Database schema ({database or ':memory:'}):"]
        for t in tables:
            cur.execute(f"PRAGMA table_info(`{t}`)")
            cols = cur.fetchall()
            col_defs = ", ".join(f"{c[1]} {c[2]}" for c in cols)
            cur.execute(f"SELECT COUNT(*) FROM `{t}`")
            row_count = cur.fetchone()[0]
            lines.append(f"  • {t} ({row_count} rows): {col_defs}")
        return "\n".join(lines)

    def _fmt_results(rows, cols, sql_str, tag_str) -> str:
        if not rows:
            return f"{tag_str} Query returned 0 rows.\nSQL: {sql_str}"
        header = " | ".join(str(c) for c in cols)
        sep = "-" * len(header)
        body = [" | ".join(str(v) for v in (r.values() if isinstance(r, dict) else r)) for r in rows[:100]]
        note = f"\n(showing {len(body)} of {len(rows)} rows)" if len(rows) > 100 else ""
        return f"{tag_str} query results ({len(rows)} rows)\nSQL: {sql_str}\n\n{header}\n{sep}\n" + "\n".join(body) + note

    # ── Detect intent ─────────────────────────────────────────────────────
    import re as _re
    inp_s = inp.strip()
    inp_l = inp_s.lower()
    schema_kw = ("schema", "tables", "list tables", "describe", "what tables", "show tables", "columns")
    is_schema_req = not inp_s or any(kw in inp_l for kw in schema_kw)

    sql_match = _re.search(r"```sql\s*(.*?)```", inp_s, _re.DOTALL | _re.IGNORECASE)
    if sql_match:
        sql = sql_match.group(1).strip()
        is_schema_req = False
    elif inp_l.startswith(("select", "with ", "explain", "show ", "describe ")):
        sql = inp_s
        is_schema_req = False
    else:
        sql = None

    # ── Execute ───────────────────────────────────────────────────────────
    try:
        if db_type == "mysql":
            db_conn, _ = _mysql_connect()
            cur = db_conn.cursor()
            if is_schema_req:
                schema = _get_schema_mysql(cur)
                db_conn.close()
                return f"{tag} schema\n{schema}"
            if sql is None:
                schema = _get_schema_mysql(cur)
                db_conn.close()
                return f"{tag} schema context for query planning\n{schema}\n\nUse the schema above to answer: {inp_s}"
            cur.execute(sql)
            rows = cur.fetchall()
            cols = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else [d[0] for d in (cur.description or [])]
            db_conn.close()
            return _fmt_results(rows, cols, sql, tag)

        elif db_type == "sqlite":
            import sqlite3 as _sqlite3
            db_conn, _ = _sqlite_connect()
            if is_schema_req:
                schema = _get_schema_sqlite(db_conn)
                db_conn.close()
                return f"{tag} schema\n{schema}"
            if sql is None:
                schema = _get_schema_sqlite(db_conn)
                db_conn.close()
                return f"{tag} schema context for query planning\n{schema}\n\nUse the schema above to answer: {inp_s}"
            cur = db_conn.cursor()
            cur.execute(sql)
            rows = cur.fetchall()
            cols = [d[0] for d in (cur.description or [])]
            db_conn.close()
            return _fmt_results(rows, cols, sql, tag)

        else:
            # PostgreSQL (default)
            import psycopg2
            db_conn, _ = _pg_connect()
            cur = db_conn.cursor()
            if is_schema_req:
                schema = _get_schema_pg(cur)
                db_conn.close()
                return f"{tag} schema\n{schema}"
            if sql is None:
                schema = _get_schema_pg(cur)
                db_conn.close()
                return f"{tag} schema context for query planning\n{schema}\n\nUse the schema above to answer: {inp_s}"
            cur.execute(sql)
            rows = cur.fetchall()
            cols = [d[0] for d in (cur.description or [])]
            db_conn.close()
            return _fmt_results(rows, cols, sql, tag)

    except Exception as e:
        return f"{tag} Error: {e}"
