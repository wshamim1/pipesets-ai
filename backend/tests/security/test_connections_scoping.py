"""Saved connections are scoped to their tenant + project (routers/connections.py, migration 0038): another
workspace can't list, read, edit, test or delete them, can't borrow their sealed password for a test against a
host of its choosing, and members need the ``secrets`` permission. Also the migration's backfill."""
import json
import uuid
from datetime import datetime

import pytest

from db import get_db_connection as db_conn


@pytest.fixture(scope="module", autouse=True)
def _setup(env):
    env.setenv("AUTH_MODE", "session")


def signup(client, email):
    data = client.post("/api/auth/signup", json={"email": email, "password": "password123",
                                                 "display_name": email.split("@")[0]}).json()
    t = data["tenants"][0]
    return {"Authorization": f"Bearer {data['token']}", "x-tenant-id": t["id"], "x-project-id": t["projects"][0]["id"]}


@pytest.fixture(scope="module")
def A(client):
    return signup(client, "conn-owner@example.com")


@pytest.fixture(scope="module")
def B(client):
    return signup(client, "conn-other@example.com")


@pytest.fixture(scope="module")
def conn(client, A):
    r = client.post("/api/connections", headers=A, json={
        "name": "Prod DB", "type": "custom_api",
        "config": {"base_url": "https://api.example.invalid", "api_key": "SUPER-SECRET"}})
    assert r.status_code == 200, r.text
    return r.json()


def test_owner_sees_own_connection(client, A, conn):
    assert [c["id"] for c in client.get("/api/connections", headers=A).json()] == [conn["id"]]
    assert client.get(f"/api/connections/{conn['id']}", headers=A).status_code == 200
    with db_conn() as c:
        row = c.execute("SELECT tenant_id, project_id FROM connections WHERE id = ?", (conn["id"],)).fetchone()
    assert (row[0], row[1]) == (A["x-tenant-id"], A["x-project-id"])


def test_other_workspace_sees_and_touches_nothing(client, A, B, conn):
    cid = conn["id"]
    assert client.get("/api/connections", headers=B).json() == []
    assert client.get(f"/api/connections/{cid}", headers=B).status_code == 404
    assert client.put(f"/api/connections/{cid}", headers=B, json={"name": "pwned"}).status_code == 404
    assert client.post(f"/api/connections/{cid}/test", headers=B).status_code == 404
    assert client.delete(f"/api/connections/{cid}", headers=B).status_code == 404
    assert client.get(f"/api/connections/{cid}", headers=A).json()["name"] == "Prod DB"


def test_cannot_borrow_a_saved_password_for_an_adhoc_test(client, B, conn):
    # Empty secret fields would reuse the saved connection's — pointed at the attacker's host
    r = client.post("/api/connections/test", headers=B, json={
        "type": "custom_api", "connection_id": conn["id"],
        "config": {"base_url": "https://attacker.example.invalid", "api_key": ""}})
    assert r.status_code == 404


def test_other_project_of_same_workspace_is_separate(client, A, conn):
    p = client.post("/api/iam/projects", headers=A, json={"name": "Second"})
    assert p.status_code in (200, 201), p.text
    other = {**A, "x-project-id": p.json().get("id") or p.json()["project"]["id"]}
    assert client.get("/api/connections", headers=other).json() == []


def test_members_need_the_secrets_permission(client, A, conn):
    member = signup(client, "conn-member@example.com")
    client.post("/api/iam/users", headers=A, json={"email": "conn-member@example.com", "display_name": "M",
                                                   "role": "editor"})
    M = {**member, "x-tenant-id": A["x-tenant-id"], "x-project-id": A["x-project-id"]}
    assert client.get("/api/connections", headers=M).status_code == 403
    me = client.get("/api/iam/users", headers=A).json()
    users = me.get("users", me) if isinstance(me, dict) else me
    uid = next(u["id"] for u in users if u["email"] == "conn-member@example.com")
    r = client.post("/api/iam/acls", headers=A, json={"principal_type": "user", "principal_id": uid,
                                                      "resource": "secrets", "action": "read", "effect": "allow"})
    assert r.status_code in (200, 201), r.text
    assert [c["id"] for c in client.get("/api/connections", headers=M).json()] == [conn["id"]]
    assert client.put(f"/api/connections/{conn['id']}", headers=M, json={"name": "x"}).status_code == 403


def test_migration_backfill(tmp_path):
    """0038 assigns connections from the apps that use them, falls back on a one-workspace server, and
    leaves connections shared across workspaces unscoped."""
    from alembic import command
    from alembic.config import Config
    import os
    import sqlalchemy as sa

    eng = sa.create_engine(f"sqlite:///{tmp_path}/m.db")
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "..", "migrations"))

    def upgrade(rev):          # migrations/env.py runs on the connection it is handed
        with eng.begin() as connection:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, rev)

    upgrade("0037_sso")
    now = datetime.utcnow().isoformat()
    node = lambda cid: {"id": uuid.uuid4().hex, "type": "connection", "data": {"connection_id": cid}}  # noqa: E731
    with eng.begin() as c:
        c.execute(sa.text("DELETE FROM tenants"))
        for t, p in (("tA", "pA"), ("tA", "pA2"), ("tB", "pB")):
            c.execute(sa.text("INSERT INTO tenants (id, name, slug, status, created_at, updated_at) "
                              "SELECT :t, :t, :t, 'active', :n, :n WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE id = :t)"),
                      {"t": t, "n": now})
            c.execute(sa.text("INSERT INTO projects (id, tenant_id, name, status, created_by, created_at, updated_at) "
                              "VALUES (:p, :t, :p, 'active', 'u', :n, :n)"), {"p": p, "t": t, "n": now})
        for cid in ("c_one", "c_two_projects", "c_shared", "c_unused"):
            c.execute(sa.text("INSERT INTO connections (id, name, type, config, created_at, updated_at) "
                              "VALUES (:i, :i, 'custom_api', '{}', :n, :n)"), {"i": cid, "n": now})
        for app, t, p, cids in (("a1", "tA", "pA", ["c_one", "c_two_projects", "c_shared"]),
                                ("a2", "tA", "pA2", ["c_two_projects"]), ("a3", "tB", "pB", ["c_shared"])):
            c.execute(sa.text("INSERT INTO apps (id, name, tenant_id, project_id, flow_data, created_at, updated_at) "
                              "VALUES (:a, :a, :t, :p, :f, :n, :n)"),
                      {"a": app, "t": t, "p": p, "f": json.dumps({"nodes": [node(x) for x in cids]}), "n": now})
    upgrade("0038_scope_connections")
    with eng.connect() as c:
        got = {r[0]: (r[1], r[2]) for r in c.execute(sa.text("SELECT id, tenant_id, project_id FROM connections"))}
    eng.dispose()
    assert got["c_one"] == ("tA", "pA")
    assert got["c_two_projects"] == ("tA", "pA")
    assert got["c_shared"] == (None, None)
    assert got["c_unused"] == (None, None)        # two workspaces: no fallback


def test_manage_lists_and_assigns_unscoped(client, A, capsys):
    import manage
    with db_conn() as c:
        from services import secret_store
        c.execute("INSERT INTO connections (id, name, type, config, created_at, updated_at) "
                  "VALUES ('conn_orphan', 'Orphan DB', 'custom_api', ?, 'x', 'x')",
                  (json.dumps({"api_key": secret_store.seal("orphan-key", "")}),))
        c.commit()
    assert manage.main(["connections"]) == 0 and "conn_orphan" in capsys.readouterr().out
    assert manage.main(["connections", "--assign", "conn_orphan"]) == 1          # --project required
    assert manage.main(["connections", "--assign", "conn_orphan", "--project", A["x-project-id"]]) == 0
    moved = next(c for c in client.get("/api/connections", headers=A).json() if c["id"] == "conn_orphan")
    from services import secret_store
    assert secret_store.sealed_tenant(moved["config"]["api_key"]) == A["x-tenant-id"], "credentials re-bound"
    assert manage.main(["connections", "--assign", "conn_orphan", "--project", A["x-project-id"]]) == 1  # now scoped
