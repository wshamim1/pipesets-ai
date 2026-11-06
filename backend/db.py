"""
Database access for the backend.

DATABASE_URL picks the database (any SQLAlchemy URL):
  sqlite:////data/pipesets.db                                   (default, via SQLITE_DB_PATH)
  postgresql+psycopg2://user:pass@host:5432/agentic
  mssql+pyodbc://user:pass@host/agentic?driver=ODBC+Driver+18+for+SQL+Server

The schema lives in Alembic migrations (backend/migrations); init_db() applies any that
are pending and seeds the demo tenant. get_db_connection() returns a sqlite3-style
connection (conn.execute with ? placeholders, rows readable as row["col"]) on every database.
"""

import os
import re
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Sequence, Union

from sqlalchemy import create_engine, event, make_url

from paths import CODE_DIR, data_path

BACKEND_DIR = CODE_DIR  # alembic.ini + migrations/
DB_PATH = os.getenv("SQLITE_DB_PATH", data_path("pipesets.db"))
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{DB_PATH}"

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        url = make_url(DATABASE_URL)
        if url.get_backend_name() == "sqlite":
            # FastAPI runs sync routes on a thread pool, so a pooled connection may change threads.
            _engine = create_engine(url, connect_args={"check_same_thread": False})
            # SQLite ignores foreign keys unless each connection asks; without this a delete leaves
            # its children behind (Postgres cascades). Migrations switch it off — see migrate().
            event.listen(_engine, "connect", _sqlite_foreign_keys_on)
        else:
            _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def _sqlite_foreign_keys_on(dbapi_connection, _record) -> None:
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    cur.close()


@contextmanager
def migration_connection(engine=None):
    """A connection for running migrations. On SQLite, foreign keys are off while it's out:
    a migration that rebuilds a table drops it first, and with cascades on, rebuilding ``users``
    would delete every membership. They're switched back on before the connection is pooled."""
    engine = engine or get_engine()
    with engine.connect() as conn:
        sqlite = engine.dialect.name == "sqlite"
        if sqlite:
            conn.exec_driver_sql("PRAGMA foreign_keys = OFF")
            conn.commit()   # a PRAGMA opens SQLAlchemy's transaction too; close it before begin()
        try:
            yield conn
        finally:
            if sqlite:
                conn.rollback()
                conn.exec_driver_sql("PRAGMA foreign_keys = ON")
                conn.commit()


def use_database(url: str) -> None:
    """Point every later connection at ``url`` (tests give each module a fresh database)."""
    global _engine, DATABASE_URL
    if _engine is not None:
        _engine.dispose()
    _engine, DATABASE_URL = None, url


def safe_database_url() -> str:
    """DATABASE_URL with the password masked, for logs and /health."""
    return make_url(DATABASE_URL).render_as_string(hide_password=True)


def backend_name() -> str:
    return get_engine().dialect.name  # sqlite | postgresql | mssql | mysql …


def _alembic_config():
    from alembic.config import Config

    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "migrations"))
    return cfg


def schema_status(engine=None) -> Dict[str, Any]:
    """The database's migration revision, the code's head revision, and what's still to apply."""
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config())
    head = script.get_current_head()
    with (engine or get_engine()).connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    pending = [] if current == head else [
        {"revision": r.revision, "description": (r.doc or "").strip().splitlines()[0] if r.doc else ""}
        for r in reversed(list(script.iterate_revisions(head, current)))
    ]
    return {"current": current, "head": head, "pending": pending}


def database_info() -> Dict[str, Any]:
    """What Settings → Database shows: which database, where, which version, schema state. No password."""
    engine = get_engine()
    url = engine.url
    kind = engine.dialect.name
    info: Dict[str, Any] = {
        "backend": kind, "driver": engine.dialect.driver, "url": safe_database_url(),
        "host": url.host or "", "port": url.port, "database": url.database or "",
        "server_version": "", "size_bytes": None,
    }
    with engine.connect() as conn:
        version = engine.dialect.server_version_info
        info["server_version"] = ".".join(str(v) for v in version) if version else ""
        try:
            if kind == "sqlite" and url.database and url.database != ":memory:":
                info["size_bytes"] = os.path.getsize(url.database)
            elif kind == "postgresql":
                from sqlalchemy import text
                info["size_bytes"] = conn.execute(text("SELECT pg_database_size(current_database())")).scalar()
        except Exception:  # size is a nice-to-have; a missing permission mustn't break the page
            pass
    info["schema"] = schema_status(engine)
    return info


# ── sqlite3-compatible connection wrapper ─────────────────────────────────────

class Row(tuple):
    """Like sqlite3.Row: index by position or column name; dict(row) works."""

    def __new__(cls, values, keys):
        row = super().__new__(cls, values)
        row._keys = keys
        return row

    def keys(self):
        return list(self._keys)

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return tuple.__getitem__(self, self._keys.index(key))
            except ValueError:
                raise IndexError(f"No item with that key: {key}") from None
        return tuple.__getitem__(self, key)


def _to_format_style(sql: str) -> str:
    """Rewrite ? placeholders as %s (and literal % as %%) outside quoted strings."""
    out = []
    for i, part in enumerate(re.split(r"('(?:[^']|'')*'|\"[^\"]*\")", sql)):
        if i % 2:  # quoted literal / identifier
            out.append(part.replace("%", "%%"))
        else:
            out.append(part.replace("%", "%%").replace("?", "%s"))
    return "".join(out)


class Cursor:
    def __init__(self, raw_cursor, paramstyle: str):
        self._cur = raw_cursor
        self._paramstyle = paramstyle

    def _sql(self, sql: str, has_params: bool) -> str:
        # Drivers only interpret % when parameters are passed.
        if self._paramstyle in ("format", "pyformat") and has_params:
            return _to_format_style(sql)
        return sql

    def execute(self, sql, params=()):
        params = tuple(params) if params else ()
        with _integrity_errors():
            if params:
                self._cur.execute(self._sql(sql, True), params)
            else:
                self._cur.execute(sql)
        return self

    def executemany(self, sql, seq_of_params):
        seq = [tuple(p) for p in seq_of_params]
        if seq:
            with _integrity_errors():
                self._cur.executemany(self._sql(sql, True), seq)
        return self

    def _wrap(self, values):
        if values is None:
            return None
        keys = [d[0] for d in self._cur.description]
        return Row(values, keys)

    def fetchone(self):
        return self._wrap(self._cur.fetchone())

    def fetchmany(self, size=None):
        rows = self._cur.fetchmany(size) if size is not None else self._cur.fetchmany()
        return [self._wrap(r) for r in rows]

    def fetchall(self):
        return [self._wrap(r) for r in self._cur.fetchall()]

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def lastrowid(self):
        return getattr(self._cur, "lastrowid", None)

    @property
    def description(self):
        return self._cur.description

    def close(self):
        self._cur.close()


class Connection:
    """A pooled DB-API connection with the sqlite3.Connection surface the routers use."""

    def __init__(self, raw_connection, paramstyle: str):
        self._raw = raw_connection
        self._paramstyle = paramstyle

    def cursor(self) -> Cursor:
        return Cursor(self._raw.cursor(), self._paramstyle)

    def execute(self, sql, params=()) -> Cursor:
        return self.cursor().execute(sql, params)

    def executemany(self, sql, seq_of_params) -> Cursor:
        return self.cursor().executemany(sql, seq_of_params)

    def commit(self):
        with _integrity_errors():   # Postgres may report a constraint only at commit
            self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()  # returns it to the pool (uncommitted work is rolled back)

    # Same as sqlite3: `with conn:` commits or rolls back, but does not close.
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


def get_db_connection() -> Connection:
    engine = get_engine()
    return Connection(engine.raw_connection(), engine.dialect.paramstyle)


def _dbapi_error(name: str):
    return getattr(get_engine().dialect.dbapi, name)


class _DBAPIErrorMeta(type):
    # isinstance(e, db.IntegrityError) also matches the driver's own exception
    def __instancecheck__(cls, obj):
        return type.__instancecheck__(cls, obj) or isinstance(obj, _dbapi_error(cls.__name__))


class IntegrityError(Exception, metaclass=_DBAPIErrorMeta):
    """A constraint failed (duplicate key, missing parent row), on any database. The connection
    wrapper raises it in place of the driver's error: ``except`` matches on the real class
    hierarchy, so a metaclass alone can't make ``except db.IntegrityError:`` catch sqlite3's."""


@contextmanager
def _integrity_errors():
    try:
        yield
    except Exception as e:
        if not issubclass(type(e), IntegrityError) and isinstance(e, _dbapi_error("IntegrityError")):
            raise IntegrityError(str(e)) from e
        raise


# ── Schema + seed ─────────────────────────────────────────────────────────────

def migrate() -> None:
    """Apply pending Alembic migrations (creates every table on a fresh database)."""
    from alembic import command

    cfg = _alembic_config()
    with migration_connection() as connection, connection.begin():
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")


# ── Portable upserts ──────────────────────────────────────────────────────────
# SQLite's INSERT OR IGNORE / INSERT OR REPLACE don't exist on other databases. SQLite (3.24+)
# and PostgreSQL share INSERT … ON CONFLICT; elsewhere a lookup decides between INSERT and UPDATE.
# ``key`` must be the table's primary key (or a unique index) for ON CONFLICT to apply.

def _rows(rows: Union[Dict[str, Any], Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    return [rows] if isinstance(rows, dict) else list(rows)


def _write(conn: "Connection", table: str, rows, key: Sequence[str], update: bool) -> None:
    rows = _rows(rows)
    if not rows:
        return
    cols = list(rows[0])
    insert = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
    if backend_name() in ("sqlite", "postgresql"):
        rest = [c for c in cols if c not in key]
        action = (f"DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in rest)}"
                  if update and rest else "DO NOTHING")
        conn.executemany(f"{insert} ON CONFLICT ({', '.join(key)}) {action}",
                         [tuple(r[c] for c in cols) for r in rows])
        return
    where = " AND ".join(f"{c} = ?" for c in key)
    for r in rows:
        exists = conn.execute(f"SELECT 1 FROM {table} WHERE {where}", tuple(r[c] for c in key)).fetchone()
        if not exists:
            conn.execute(insert, tuple(r[c] for c in cols))
        elif update and len(cols) > len(key):
            rest = [c for c in cols if c not in key]
            conn.execute(f"UPDATE {table} SET {', '.join(f'{c} = ?' for c in rest)} WHERE {where}",
                         tuple(r[c] for c in rest) + tuple(r[c] for c in key))


def insert_ignore(conn: "Connection", table: str, rows, key: Sequence[str]) -> None:
    """Insert each row (a dict, or a list of dicts) unless one with the same ``key`` exists."""
    _write(conn, table, rows, key, update=False)


def upsert(conn: "Connection", table: str, rows, key: Sequence[str]) -> None:
    """Insert each row, or overwrite the given columns of the row with the same ``key``."""
    _write(conn, table, rows, key, update=True)


def _insert_missing(cursor: Cursor, table: str, key: dict, values: dict) -> None:
    """Insert a row unless one with the same key columns exists (portable INSERT OR IGNORE)."""
    where = " AND ".join(f"{c} = ?" for c in key)
    if cursor.execute(f"SELECT 1 FROM {table} WHERE {where}", tuple(key.values())).fetchone():
        return
    row = {**key, **values}
    cursor.execute(
        f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
        tuple(row.values()),
    )


def seed_demo_data() -> None:
    # Seeded users have no password; set one with `python manage.py set-password`.
    now = datetime.utcnow().isoformat()
    conn = get_db_connection()
    cur = conn.cursor()

    _insert_missing(cur, "tenants", {"id": "tenant_demo"},
                    {"name": "Demo Tenant", "slug": "demo-tenant", "status": "active",
                     "created_at": now, "updated_at": now})

    for user_id, email, name in (
        ("user_admin", "admin@demo.local", "Demo Admin"),
        ("user_analyst", "analyst@demo.local", "Demo Analyst"),
        ("user_viewer", "viewer@demo.local", "Demo Viewer"),
    ):
        _insert_missing(cur, "users", {"id": user_id},
                        {"email": email, "display_name": name, "status": "active",
                         "server_admin": 1 if user_id == "user_admin" else 0,
                         "created_at": now, "updated_at": now})

    for user_id, role in (("user_admin", "owner"), ("user_analyst", "editor"), ("user_viewer", "viewer")):
        _insert_missing(cur, "tenant_memberships", {"tenant_id": "tenant_demo", "user_id": user_id},
                        {"role": role, "created_at": now})

    for group_id, name, description in (
        ("group_engineering", "Engineering", "Pipeline builders and tool authors"),
        ("group_ops", "Operations", "Runtime and support operators"),
    ):
        _insert_missing(cur, "groups", {"id": group_id},
                        {"tenant_id": "tenant_demo", "name": name, "description": description,
                         "created_at": now, "updated_at": now})

    for group_id, user_id in (("group_engineering", "user_admin"), ("group_engineering", "user_analyst"),
                              ("group_ops", "user_viewer")):
        _insert_missing(cur, "group_memberships", {"group_id": group_id, "user_id": user_id},
                        {"tenant_id": "tenant_demo", "created_at": now})

    for project_id, name, description in (
        ("proj_research", "Research Pipelines", "Experimental research and analysis pipelines"),
        ("proj_support", "Support Automation", "Customer support and operations workflows"),
    ):
        _insert_missing(cur, "projects", {"id": project_id},
                        {"tenant_id": "tenant_demo", "name": name, "description": description,
                         "status": "active", "created_by": "user_admin", "created_at": now, "updated_at": now})

    for acl_id, project_id, principal_type, principal_id, resource, action in (
        ("acl_admin_all", None, "user", "user_admin", "*", "*"),
        ("acl_eng_apps_rw", "proj_research", "group", "group_engineering", "apps", "*"),
        ("acl_eng_tools_rw", "proj_research", "group", "group_engineering", "tools", "*"),
        ("acl_eng_mcp_rw", "proj_research", "group", "group_engineering", "mcp", "*"),
        ("acl_eng_secrets_rw", "proj_research", "group", "group_engineering", "secrets", "*"),
        ("acl_ops_read", "proj_support", "group", "group_ops", "apps", "read"),
    ):
        _insert_missing(cur, "acl_entries", {"id": acl_id},
                        {"tenant_id": "tenant_demo", "project_id": project_id,
                         "principal_type": principal_type, "principal_id": principal_id,
                         "resource": resource, "action": action, "effect": "allow", "created_at": now})

    conn.commit()
    conn.close()


def init_db() -> None:
    migrate()
    seed_demo_data()
