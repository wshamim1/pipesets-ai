"""SQL the app runs must work on every DATABASE_URL, not only SQLite: no SQLite-only statements in
the app's own code, and the portable upsert helpers (db.insert_ignore / db.upsert) behave like
the INSERT OR IGNORE / INSERT OR REPLACE they replace. CI runs this on SQLite and Postgres."""

import re
from pathlib import Path

import db

BACKEND = Path(__file__).resolve().parents[2]
# A user's own SQLite database (a tool target), csv_sql's private in-memory SQLite, and db.py's
# SQLite-only foreign-key switch
ALLOWED = {"tools/mcp/databases/database.py", "tools/data/csv_sql.py", "db.py"}
SQLITE_ONLY = re.compile(r"\bINSERT\s+OR\s+(IGNORE|REPLACE)\b|\bPRAGMA\b|\bAUTOINCREMENT\b", re.IGNORECASE)


def test_no_sqlite_only_sql_in_app_code():
    offenders = []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).as_posix()
        if rel.split("/")[0] in ("tests", "migrations", ".venv", "build", "dist") or rel in ALLOWED:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            code = line.split("#", 1)[0]
            if SQLITE_ONLY.search(code) and '"""' not in line:
                offenders.append(f"{rel}:{n}: {line.strip()}")
    assert not offenders, "SQLite-only SQL (use db.insert_ignore / db.upsert):\n" + "\n".join(offenders)


def _table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS portability_t (k1 VARCHAR(20), k2 INTEGER, v VARCHAR(20), "
                 "n INTEGER, PRIMARY KEY (k1, k2))")
    conn.execute("DELETE FROM portability_t")


def test_insert_ignore_keeps_the_existing_row():
    conn = db.get_db_connection()
    try:
        _table(conn)
        db.insert_ignore(conn, "portability_t", {"k1": "a", "k2": 1, "v": "first", "n": 1}, key=("k1", "k2"))
        db.insert_ignore(conn, "portability_t", [{"k1": "a", "k2": 1, "v": "second", "n": 2},
                                                 {"k1": "a", "k2": 2, "v": "other", "n": 3}], key=("k1", "k2"))
        conn.commit()
        rows = [tuple(r) for r in conn.execute("SELECT k1, k2, v FROM portability_t ORDER BY k2").fetchall()]
        assert rows == [("a", 1, "first"), ("a", 2, "other")]
    finally:
        conn.execute("DROP TABLE portability_t")
        conn.commit()
        conn.close()


def test_upsert_overwrites_the_row_with_the_same_key():
    conn = db.get_db_connection()
    try:
        _table(conn)
        db.upsert(conn, "portability_t", {"k1": "a", "k2": 1, "v": "first", "n": 1}, key=("k1", "k2"))
        db.upsert(conn, "portability_t", [{"k1": "a", "k2": 1, "v": "second", "n": 0},
                                          {"k1": "b", "k2": 1, "v": "new", "n": 5}], key=("k1", "k2"))
        db.upsert(conn, "portability_t", [], key=("k1", "k2"))
        conn.commit()
        rows = [tuple(r) for r in conn.execute("SELECT k1, v, n FROM portability_t ORDER BY k1").fetchall()]
        assert rows == [("a", "second", 0), ("b", "new", 5)]
    finally:
        conn.execute("DROP TABLE portability_t")
        conn.commit()
        conn.close()


def test_except_integrity_error_catches_the_drivers_error():
    """`except db.IntegrityError:` must work on every database (it used to never match)."""
    conn = db.get_db_connection()
    try:
        _table(conn)
        conn.execute("INSERT INTO portability_t (k1, k2, v, n) VALUES ('a', 1, 'x', 1)")
        conn.commit()
        try:
            conn.execute("INSERT INTO portability_t (k1, k2, v, n) VALUES ('a', 1, 'dup', 2)")
            conn.commit()
            raise AssertionError("duplicate key accepted")
        except db.IntegrityError:
            conn.rollback()
    finally:
        conn.execute("DROP TABLE portability_t")
        conn.commit()
        conn.close()


def test_duplicate_agent_run_id_is_a_409(client):
    from helpers import hdr
    body = {"goal": "Say hi", "run_id": "run-portability-dup"}
    first = client.post("/api/agents/run", json=body, headers=hdr())
    assert first.status_code == 200, first.text
    again = client.post("/api/agents/run", json=body, headers=hdr())
    assert again.status_code == 409 and "already exists" in again.json()["detail"]
