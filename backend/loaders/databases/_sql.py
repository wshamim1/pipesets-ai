"""Row extraction for the SQL loaders and POST /api/retrieval/ingest/database.

Each fetcher takes an object with the DatabaseIngestRequest fields (connection_string,
host, port, database, user, password, table, query, max_rows) and returns
(tables_queried, record_texts) — one text per row.
"""


def _fetch_postgres_records(req):
    import psycopg2
    import psycopg2.extras

    conn = None
    try:
        if req.connection_string:
            conn = psycopg2.connect(req.connection_string, connect_timeout=10)
        else:
            conn = psycopg2.connect(
                host=req.host or "localhost",
                port=int(req.port or 5432),
                database=req.database or "postgres",
                user=req.user or "postgres",
                password=req.password or "",
                connect_timeout=10,
            )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        tables_queried = []
        doc_texts = []

        if req.query and req.query.strip():
            cur.execute(req.query.strip())
            rows = cur.fetchall()
            tables_queried.append("custom_query")
            for idx, r in enumerate(rows):
                row_dict = dict(r)
                text_lines = [f"Source: Custom SQL Query | Row #{idx + 1}"]
                for k, v in row_dict.items():
                    text_lines.append(f"{k}: {v}")
                doc_texts.append("\n".join(text_lines))
        else:
            if req.table and req.table.strip():
                tables = [req.table.strip()]
            else:
                cur.execute("""
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                """)
                tables = [r["table_name"] for r in cur.fetchall()]

            for t in tables:
                tables_queried.append(t)
                cur.execute(f'SELECT * FROM "{t}" LIMIT %s', (req.max_rows,))
                rows = cur.fetchall()
                for idx, r in enumerate(rows):
                    row_dict = dict(r)
                    text_lines = [f"Table: {t} | Record #{idx + 1}"]
                    for k, v in row_dict.items():
                        text_lines.append(f"{k}: {v}")
                    doc_texts.append("\n".join(text_lines))

        return tables_queried, doc_texts
    finally:
        if conn:
            conn.close()


def _fetch_mysql_records(req):
    import pymysql
    import pymysql.cursors

    conn = None
    try:
        conn = pymysql.connect(
            host=req.host or "localhost",
            port=int(req.port or 3306),
            database=req.database or "",
            user=req.user or "root",
            password=req.password or "",
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10,
        )
        cur = conn.cursor()
        tables_queried = []
        doc_texts = []

        if req.query and req.query.strip():
            cur.execute(req.query.strip())
            rows = cur.fetchall()
            tables_queried.append("custom_query")
            for idx, r in enumerate(rows):
                text_lines = [f"Source: Custom SQL Query | Row #{idx + 1}"]
                for k, v in dict(r).items():
                    text_lines.append(f"{k}: {v}")
                doc_texts.append("\n".join(text_lines))
        else:
            if req.table and req.table.strip():
                tables = [req.table.strip()]
            else:
                cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()")
                tables = [r["TABLE_NAME"] or r["table_name"] for r in cur.fetchall()]

            for t in tables:
                tables_queried.append(t)
                cur.execute(f"SELECT * FROM `{t}` LIMIT %s", (req.max_rows,))
                rows = cur.fetchall()
                for idx, r in enumerate(rows):
                    text_lines = [f"Table: {t} | Record #{idx + 1}"]
                    for k, v in dict(r).items():
                        text_lines.append(f"{k}: {v}")
                    doc_texts.append("\n".join(text_lines))

        return tables_queried, doc_texts
    finally:
        if conn:
            conn.close()


def _fetch_sqlite_records(req):
    import sqlite3

    db_path = req.database or (req.connection_string.replace("sqlite:///", "").replace("sqlite://", "") if req.connection_string else ":memory:")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        tables_queried = []
        doc_texts = []

        if req.query and req.query.strip():
            cur.execute(req.query.strip())
            rows = cur.fetchall()
            tables_queried.append("custom_query")
            for idx, r in enumerate(rows):
                text_lines = [f"Source: Custom SQL Query | Row #{idx + 1}"]
                for k in r.keys():
                    text_lines.append(f"{k}: {r[k]}")
                doc_texts.append("\n".join(text_lines))
        else:
            if req.table and req.table.strip():
                tables = [req.table.strip()]
            else:
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                tables = [r["name"] for r in cur.fetchall()]

            for t in tables:
                tables_queried.append(t)
                cur.execute(f'SELECT * FROM "{t}" LIMIT ?', (req.max_rows,))
                rows = cur.fetchall()
                for idx, r in enumerate(rows):
                    text_lines = [f"Table: {t} | Record #{idx + 1}"]
                    for k in r.keys():
                        text_lines.append(f"{k}: {r[k]}")
                    doc_texts.append("\n".join(text_lines))

        return tables_queried, doc_texts
    finally:
        conn.close()
