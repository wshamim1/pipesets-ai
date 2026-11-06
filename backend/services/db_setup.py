"""
db_setup.py — choose the database from Settings → Database on a fresh install.

Before anyone builds pipelines, a server admin can point the server at PostgreSQL from the UI:
test the connection, then apply — the current (nearly empty) database is copied into the new
one (services/db_copy.py), so the admin's own account and workspace come along, and
``DATABASE_URL`` is written to the data directory's ``.env``. The backend uses it after a
restart. Once pipelines or runs exist, moving is ``manage.py db copy`` with the backend stopped:
a copy taken while the app keeps writing would lose whatever came after it.

Only possible where the app owns its configuration: when ``DATABASE_URL`` comes from the
environment (Docker Compose, Kubernetes), the page says what to set there instead.
"""

import os
from typing import Any, Dict, List, Optional

from dotenv import dotenv_values, set_key
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL

import db
from paths import data_path
from services.db_copy import CopyError, copy_database

ENV_FILE = data_path(".env")
# Rows that make an install "not fresh" any more — real work a live copy could lose
WORK_TABLES = ("apps", "app_versions", "agent_runs", "traces", "schedule_runs", "webhook_runs")
CONNECT_TIMEOUT_S = 5


class PostgresTarget(BaseModel):
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(..., min_length=1, max_length=63)
    user: str = Field(..., min_length=1, max_length=63)
    password: str = Field(default="", max_length=512)
    sslmode: str = Field(default="prefer", pattern="^(disable|allow|prefer|require|verify-ca|verify-full)$")

    def url(self, *, connect_timeout: bool = False) -> URL:
        query = {"sslmode": self.sslmode}
        if connect_timeout:
            query["connect_timeout"] = str(CONNECT_TIMEOUT_S)
        return URL.create("postgresql+psycopg2", username=self.user, password=self.password or None,
                          host=self.host.strip(), port=self.port, database=self.database.strip(), query=query)


def _file_value() -> Optional[str]:
    return dotenv_values(ENV_FILE).get("DATABASE_URL") if os.path.exists(ENV_FILE) else None


def config_source() -> str:
    """Where DATABASE_URL comes from: "default" (unset → SQLite), "env_file" (the data dir's .env,
    which the app can rewrite) or "environment" (set by the process — Compose, k8s — read-only)."""
    in_env = "DATABASE_URL" in os.environ
    from_file = _file_value()
    if not in_env and not from_file:
        return "default"
    if from_file is not None and os.environ.get("DATABASE_URL", from_file) == from_file:
        return "env_file"
    return "environment"


def _work_rows() -> Dict[str, int]:
    existing = set(inspect(db.get_engine()).get_table_names())
    conn = db.get_db_connection()
    try:
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in WORK_TABLES if t in existing}
    finally:
        conn.close()
    return {t: n for t, n in counts.items() if n}


def status() -> Dict[str, Any]:
    source = config_source()
    reasons: List[str] = []
    if source == "environment":
        reasons.append("DATABASE_URL is set by the server's environment (e.g. Docker Compose or Kubernetes), "
                       "so it has to be changed there.")
    work = _work_rows()
    if work:
        reasons.append("This server already has pipelines or runs (" + ", ".join(f"{n} {t}" for t, n in work.items())
                       + "). Move it with `python manage.py db copy` while the backend is stopped.")
    pending = None
    saved = _file_value()
    if source == "env_file" and saved and saved != db.DATABASE_URL:
        from sqlalchemy.engine import make_url
        pending = make_url(saved).render_as_string(hide_password=True)
    return {"can_configure": not reasons, "reasons": reasons, "source": source,
            "env_file": ENV_FILE, "pending_restart": pending}


def test_connection(target: PostgresTarget) -> Dict[str, Any]:
    """Connect, and report the server version and whether the database is empty. Never raises."""
    engine = create_engine(target.url(connect_timeout=True), pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SHOW server_version")).scalar()
            tables = [t for t in inspect(conn).get_table_names() if t != "alembic_version"]
        return {"ok": True, "server_version": version, "empty": not tables, "tables": len(tables),
                "message": f"Connected to PostgreSQL {version}"
                           + ("" if not tables else f" — it already has {len(tables)} tables")}
    except ModuleNotFoundError as e:
        return {"ok": False, "message": f"Database driver not installed: {e.name}"}
    except Exception as e:  # wrong host, password, database, SSL … — show the driver's reason
        reason = str(getattr(e, "orig", None) or e).strip().splitlines()[0][:300]
        return {"ok": False, "message": f"Couldn't connect: {reason}"}
    finally:
        engine.dispose()


def apply(target: PostgresTarget) -> Dict[str, Any]:
    """Copy this database into the target and save DATABASE_URL for the next start."""
    state = status()
    if not state["can_configure"]:
        raise CopyError(" ".join(state["reasons"]))
    check = test_connection(target)
    if not check["ok"]:
        raise CopyError(check["message"])
    # Rows pointing at deleted parents (left by SQLite before foreign keys were enforced) mean nothing
    report = copy_database(db.DATABASE_URL, target.url(connect_timeout=True).render_as_string(hide_password=False),
                           skip_orphans=True)
    url = target.url().render_as_string(hide_password=False)
    if not os.path.exists(ENV_FILE):
        open(ENV_FILE, "a").close()
    set_key(ENV_FILE, "DATABASE_URL", url, quote_mode="always")
    os.chmod(ENV_FILE, 0o600)   # it now holds the database password
    return {"ok": True, "copied_rows": report.total, "tables": len(report.rows), "env_file": ENV_FILE,
            "restart_required": True, "skipped_orphans": report.orphans}
