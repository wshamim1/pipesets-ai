"""Moving the app database (services/db_copy.py, `manage.py db copy`) and the read-only database
info in Settings (GET /api/system/database). The source is this module's test database — SQLite,
or Postgres on that CI leg — and each target is a fresh SQLite file. Steps of one scenario."""

import pytest
from sqlalchemy import create_engine, text

import db
import manage
from helpers import hdr, mock_flow
from services import secret_store
from services.db_copy import CopyError, copy_database
from services.vector_store import LocalStore

ADMIN = hdr()
ANALYST = hdr("user_analyst")
SECRET = "sk-live-copied-0123456789"
state = {}


def _count(url, table):
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
    finally:
        engine.dispose()


@pytest.fixture
def target(tmp_path):
    return f"sqlite:///{tmp_path / 'target.db'}"


def test_database_info_is_read_only_and_never_shows_the_password(client):
    r = client.get("/api/system/database", headers=ADMIN)
    assert r.status_code == 200
    info = r.json()
    assert info["backend"] == db.backend_name()
    assert info["schema"]["current"] == info["schema"]["head"] and info["schema"]["pending"] == []
    assert info["size_bytes"] is None or info["size_bytes"] > 0
    password = db.get_engine().url.password
    assert not password or f":{password}@" not in r.text
    assert client.get("/api/system/database", headers=ANALYST).status_code == 403
    assert client.put("/api/system/database", headers=ADMIN).status_code == 405, "nothing to change here"


def test_pending_migrations_are_listed(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    from alembic import command
    cfg = db._alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0010_audit_log")
    status = db.schema_status(engine)
    engine.dispose()
    assert status["current"] == "0010_audit_log"
    pending = [p["revision"] for p in status["pending"]]
    assert pending[0] == "0011_custom_tool_requirements" and pending[-1] == status["head"]
    assert pending == sorted(pending), "oldest first"


def test_copy_moves_every_row_and_secrets_still_decrypt(client, target):
    app = client.post("/api/apps", json={"name": "To move", "flow_data": mock_flow()}, headers=ADMIN).json()
    assert client.post(f"/api/apps/{app['id']}/publish", headers=ADMIN).status_code == 200
    state["secret"] = client.post("/api/secrets", json={"name": "Moved key", "value": SECRET}, headers=ADMIN).json()
    LocalStore().upsert("moved_docs", [{"chunk_id": "c1", "content": "hello", "embedding": [0.1, 0.2]}])

    lines = []
    report = copy_database(db.DATABASE_URL, target, progress=lines.append)
    assert report.rows["apps"] >= 1 and report.rows["app_versions"] >= 1 and report.rows["secrets"] >= 1
    assert "rag_chunks" in report.created, "tables made at run time come along too"
    for table, n in report.rows.items():
        assert _count(target, table) == n == _count(db.DATABASE_URL, table), table
    assert any("Creating the schema" in line for line in lines)

    # Same master key, other database: the copied secret still decrypts
    engine = create_engine(target)
    with engine.connect() as conn:
        ciphertext = conn.execute(text("SELECT ciphertext FROM secrets WHERE id = :id"),
                                  {"id": state["secret"]["id"]}).scalar()
    assert db.schema_status(engine)["pending"] == []
    engine.dispose()
    assert secret_store.decrypt(ciphertext) == SECRET


def test_copy_refuses_a_target_with_data_unless_overwrite(target):
    copy_database(db.DATABASE_URL, target)
    with pytest.raises(CopyError, match="already has data"):
        copy_database(db.DATABASE_URL, target)
    report = copy_database(db.DATABASE_URL, target, overwrite=True)
    assert _count(target, "apps") == report.rows["apps"], "overwrite replaces, doesn't duplicate"


def test_copy_refuses_the_same_database():
    with pytest.raises(CopyError, match="same database"):
        copy_database(db.DATABASE_URL, db.DATABASE_URL)


def test_copy_refuses_a_source_behind_on_migrations(tmp_path, target):
    old = f"sqlite:///{tmp_path / 'old.db'}"
    engine = create_engine(old)
    from alembic import command
    cfg = db._alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0010_audit_log")
    engine.dispose()
    with pytest.raises(CopyError, match="db setup"):
        copy_database(old, target)


def test_orphans_stop_the_copy_or_are_left_out(tmp_path):
    # A membership whose tenant is gone — what older installs have, from before SQLite's foreign
    # keys were switched on (db.py); written here with them off, as those installs did
    import sqlite3
    src = f"sqlite:///{tmp_path / 'orphans.db'}"
    source = db.DATABASE_URL
    db.use_database(src)
    try:
        db.init_db()
    finally:
        db.use_database(source)
    raw = sqlite3.connect(tmp_path / "orphans.db")
    raw.execute("INSERT INTO tenant_memberships (tenant_id, user_id, role, created_at) "
                "VALUES ('tenant_gone', 'user_admin', 'owner', '2026-01-01')")
    raw.commit()
    raw.close()

    with pytest.raises(CopyError, match="skip-orphans"):
        copy_database(src, f"sqlite:///{tmp_path / 'a.db'}")
    report = copy_database(src, f"sqlite:///{tmp_path / 'b.db'}", skip_orphans=True)
    assert report.orphans == {"tenant_memberships": 1}
    assert _count(f"sqlite:///{tmp_path / 'b.db'}", "tenant_memberships") == _count(src, "tenant_memberships") - 1


def test_cli(capsys, target):
    assert manage.main(["db", "copy", "--to", target]) == 0
    out = capsys.readouterr().out
    assert "row counts match" in out and "PIPESETS_MASTER_KEY" in out
    assert manage.main(["db", "copy", "--to", target]) == 1
    assert "already has data" in capsys.readouterr().err
    assert manage.main(["db", "copy"]) == 2
