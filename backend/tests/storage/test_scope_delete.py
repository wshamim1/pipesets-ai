"""Deleting a workspace or a project removes everything in it — on SQLite as on Postgres — except
its audit log. Before, SQLite (foreign keys off) kept memberships, groups, projects and ACLs, and
both databases kept apps, secrets, API keys and the rest, which have no foreign key at all."""

from db import get_db_connection
from helpers import hdr, mock_flow
from routers import iam
from services import audit

ADMIN = hdr()


def _rows(table, tenant_id, project_id=None):
    conn = get_db_connection()
    try:
        sql, args = f"SELECT COUNT(*) FROM {table} WHERE tenant_id = ?", [tenant_id]
        if project_id:
            sql, args = sql + " AND project_id = ?", args + [project_id]
        return conn.execute(sql, tuple(args)).fetchone()[0]
    finally:
        conn.close()


def _fill(client, tenant_id, project_id):
    """A pipeline (published), a secret, an API key, a group with a member and an ACL in a scope."""
    h = hdr(tenant=tenant_id, project=project_id)
    app = client.post("/api/apps", json={"name": "Doomed", "flow_data": mock_flow()}, headers=h).json()
    assert client.post(f"/api/apps/{app['id']}/publish", headers=h).status_code == 200
    assert client.post("/api/secrets", json={"name": "Doomed key", "value": "sk-doomed-0123456789"},
                       headers=h).status_code == 201
    assert client.post("/api/api-keys", json={"name": "doomed"}, headers=h).status_code in (200, 201)
    return app["id"]


def test_scoped_tables_are_found_from_the_schema():
    tables = iam._scoped_tables("tenant_id")
    assert {"apps", "app_versions", "secrets", "api_keys", "schedules", "webhooks"} <= set(tables)
    assert "audit_log" not in tables, "kept until retention removes it"
    assert "tenant_memberships" not in tables, "cascaded by its foreign key instead"


def test_deleting_a_workspace_removes_everything_in_it(client):
    tenant = client.post("/api/iam/tenants", json={"name": "Short lived"}, headers=ADMIN).json()
    tid = tenant["id"]
    project = client.post("/api/iam/projects", json={"name": "P"},
                          headers=hdr(tenant=tid)).json()
    pid = project["id"]
    _fill(client, tid, pid)
    group = client.post("/api/iam/groups", json={"name": "G"}, headers=hdr(tenant=tid, project=pid)).json()
    client.post(f"/api/iam/groups/{group['id']}/members", json={"user_id": "user_admin"},
                headers=hdr(tenant=tid, project=pid))
    audit_before = _rows("audit_log", tid)
    assert audit_before > 0

    r = client.delete(f"/api/iam/tenants/{tid}", headers=ADMIN)
    assert r.status_code == 200
    removed = r.json()["removed"]
    assert removed["apps"] == 1 and removed["secrets"] == 1 and removed["api_keys"] == 1

    for table in iam._scoped_tables("tenant_id") + ["tenant_memberships", "groups", "group_memberships",
                                                     "projects", "acl_entries"]:
        assert _rows(table, tid) == 0, f"{table} still has rows of the deleted workspace"
    assert _rows("audit_log", tid) >= audit_before, "the audit log survives"


def test_deleting_a_project_removes_its_data_only(client):
    keep = _fill(client, "tenant_demo", "proj_support")
    project = client.post("/api/iam/projects", json={"name": "Temporary"}, headers=ADMIN).json()
    pid = project["id"]
    _fill(client, "tenant_demo", pid)

    r = client.delete(f"/api/iam/projects/{pid}", headers=ADMIN)
    assert r.status_code == 200 and r.json()["removed"]["apps"] == 1
    for table in iam._scoped_tables("project_id"):
        assert _rows(table, "tenant_demo", pid) == 0, table
    assert client.get(f"/api/apps/{keep}", headers=hdr(project="proj_support")).status_code == 200, \
        "other projects are untouched"


def test_foreign_keys_are_enforced():
    """SQLite now refuses rows that point nowhere, like Postgres always did."""
    from db import IntegrityError
    conn = get_db_connection()
    try:
        try:
            conn.execute("INSERT INTO tenant_memberships (tenant_id, user_id, role, created_at) "
                         "VALUES ('tenant_missing', 'user_admin', 'owner', '2026-01-01')")
            conn.commit()
            raise AssertionError("an orphan membership was accepted")
        except IntegrityError:
            conn.rollback()
    finally:
        conn.close()
    assert audit.retention_days() >= 0
