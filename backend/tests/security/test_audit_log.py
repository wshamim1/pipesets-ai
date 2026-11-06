"""The admin audit log (services/audit.py, GET /api/audit-log): which requests are recorded,
what an entry holds (never request bodies), denied attempts, tenant scoping and access —
and a guard that every mutating admin route is either audited or explicitly exempt.
The tests are steps of one scenario, in order."""

import json

import main
from helpers import hdr, mock_flow
from services import audit

ADMIN = hdr()
ANALYST = hdr("user_analyst")
SECRET_VALUE = "sk-live-do-not-log-1234567890"
state = {}


def entries(client, **params):
    r = client.get("/api/audit-log", params=params, headers=ADMIN)
    assert r.status_code == 200
    return r.json()["entries"]


def test_every_mutating_admin_route_is_audited_or_exempt():
    # The OpenAPI schema lists every route template (app.routes nests included routers)
    routes = {(m.upper(), path) for path, ops in main.app.openapi()["paths"].items()
              for m in ops if m.upper() not in ("GET", "HEAD", "OPTIONS")}
    assert len(routes) > 100
    admin = {rt for rt in routes if rt[1].startswith(audit.AUDITED_PREFIXES)}
    missing = admin - set(audit.AUDITED) - audit.NOT_AUDITED
    assert not missing, f"add these to services/audit.py AUDITED or NOT_AUDITED: {sorted(missing)}"
    stale = (set(audit.AUDITED) | audit.NOT_AUDITED) - routes
    assert not stale, f"no such routes: {sorted(stale)}"


def test_secret_lifecycle_is_recorded_without_the_value(client):
    r = client.post("/api/secrets", json={"name": "Serper", "value": SECRET_VALUE}, headers=ADMIN)
    assert r.status_code == 201
    state["secret"] = secret_id = r.json()["id"]
    assert client.put(f"/api/secrets/{secret_id}", json={"name": "Serper 2"}, headers=ADMIN).status_code == 200
    assert client.delete(f"/api/secrets/{secret_id}", headers=ADMIN).status_code == 200

    got = entries(client, action="secret.")
    assert [e["action"] for e in got] == ["secret.delete", "secret.update", "secret.create"], "newest first"
    create = got[-1]
    assert create["target_id"] == secret_id, "a create's target comes from the response"
    assert (create["actor"], create["tenant_id"], create["project_id"]) == ("user_admin", "tenant_demo", "proj_research")
    assert (create["outcome"], create["status"], create["method"], create["path"]) == \
        ("success", 201, "POST", "/api/secrets")
    assert all(SECRET_VALUE not in str(e) for e in entries(client)), "request bodies are never stored"


def test_api_key_create_and_revoke(client):
    r = client.post("/api/api-keys", json={"name": "ci"}, headers=ADMIN)
    key_id = r.json()["id"]
    client.delete(f"/api/api-keys/{key_id}", headers=ADMIN)
    got = entries(client, action="api_key.")
    assert [(e["action"], e["target_id"]) for e in got] == [("api_key.revoke", key_id), ("api_key.create", key_id)]
    assert r.json()["key"] not in str(entries(client)), "the issued key never reaches the log"


def test_denied_attempt_is_recorded(client):
    assert client.post("/api/api-keys", json={"name": "sneaky"}, headers=ANALYST).status_code == 403
    denied = entries(client, actor="user_analyst")
    assert [(e["action"], e["outcome"], e["status"]) for e in denied] == [("api_key.create", "denied", 403)]


def test_publish_and_iam_changes(client):
    app_id = client.post("/api/apps", json={"name": "Audited", "flow_data": mock_flow()}, headers=ADMIN).json()["id"]
    assert client.post(f"/api/apps/{app_id}/publish", headers=ADMIN).status_code == 200
    r = client.post("/api/iam/groups", json={"name": "Auditors"}, headers=ADMIN)
    group_id = r.json()["id"]
    client.post(f"/api/iam/groups/{group_id}/members", json={"user_id": "user_viewer"}, headers=ADMIN)
    client.delete(f"/api/iam/groups/{group_id}/members/user_viewer", headers=ADMIN)

    actions = [(e["action"], e["target_id"]) for e in entries(client)]
    assert ("app.publish", app_id) in actions
    assert ("group.create", group_id) in actions
    assert ("group.member_remove", f"{group_id}/user_viewer") in actions
    assert not any(a.startswith("app.create") for a, _ in actions), "pipeline edits aren't admin actions"


def test_not_recorded(client):
    before = len(entries(client, limit=500))
    client.post("/api/secrets", json={"name": ""}, headers=ADMIN)                      # 422
    client.delete("/api/secrets/sec_nope", headers=ADMIN)                              # 404
    client.post("/api/iam/access-check", json={"resource": "apps", "action": "read"}, headers=ADMIN)
    client.get("/api/secrets", headers=ADMIN)
    assert len(entries(client, limit=500)) == before


def test_reading_needs_audit_access_and_is_tenant_scoped(client):
    assert client.get("/api/audit-log", headers=ANALYST).status_code == 403
    audit.record(tenant_id="tenant_other", project_id="", actor="someone", action="secret.create", target_id="x",
                 outcome="success", status=201, method="POST", path="/api/secrets", ip="")
    assert all(e["tenant_id"] == "tenant_demo" for e in entries(client, limit=500))


def test_paging(client):
    page = client.get("/api/audit-log", params={"limit": 2}, headers=ADMIN).json()
    assert len(page["entries"]) == 2 and page["next_before"]
    rest = client.get("/api/audit-log", params={"limit": 500, "before": page["next_before"]}, headers=ADMIN).json()
    assert {e["id"] for e in page["entries"]}.isdisjoint(e["id"] for e in rest["entries"])
    assert rest["next_before"] is None


def test_filters_by_outcome_and_time(client):
    denied = entries(client, outcome="denied")
    assert denied and all(e["outcome"] == "denied" for e in denied)
    newest = entries(client, limit=1)[0]["created_at"]
    assert entries(client, since=newest) == entries(client, limit=1)
    assert newest not in {e["created_at"] for e in entries(client, until=newest, limit=500)}
    assert client.get("/api/audit-log", params={"outcome": "maybe"}, headers=ADMIN).status_code == 422


def test_policy_lists_retention_and_actions(client, env):
    env.setenv("AUDIT_RETENTION_DAYS", "90")
    policy = client.get("/api/audit-log/policy", headers=ADMIN).json()
    assert policy["retention_days"] == 90
    assert {"secret.create", "audit.export", "audit.purge"} <= set(policy["actions"])
    assert client.get("/api/audit-log/policy", headers=ANALYST).status_code == 403


def test_export_csv_and_jsonl_and_is_itself_logged(client):
    r = client.get("/api/audit-log/export", params={"action": "secret."}, headers=ADMIN)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="audit-log-tenant_demo-' in r.headers["content-disposition"]
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("created_at,actor,action")
    assert [line.split(",")[2] for line in lines[1:]] == ["secret.delete", "secret.update", "secret.create"]

    r = client.get("/api/audit-log/export", params={"format": "jsonl", "outcome": "denied"}, headers=ADMIN)
    rows = [json.loads(line) for line in r.text.splitlines()]
    assert rows and all(row["outcome"] == "denied" for row in rows)

    exports = entries(client, action="audit.export")
    assert [e["target_id"] for e in exports] == ["jsonl", "csv"]
    assert exports[0]["actor"] == "user_admin" and "outcome=denied" in exports[0]["path"]
    assert client.get("/api/audit-log/export", headers=ANALYST).status_code == 403
    assert not entries(client, action="audit.export", actor="user_analyst"), "a refused export isn't an export"


def test_export_pages_through_entries_sharing_a_timestamp(env):
    env.setattr(audit, "_now", lambda: "2026-01-01T00:00:00")
    for i in range(7):
        audit.record(tenant_id="tenant_ties", project_id="", actor="a", action="secret.create", target_id=str(i),
                     outcome="success", status=201, method="POST", path="/api/secrets", ip="")
    env.undo()
    got = [e["target_id"] for e in audit.iter_entries("tenant_ties", batch=3)]
    assert sorted(got) == [str(i) for i in range(7)]


def test_export_neutralises_spreadsheet_formulas(client):
    audit.record(tenant_id="tenant_demo", project_id="", actor="=HYPERLINK(\"http://x\")", action="secret.create",
                 target_id="+1", outcome="success", status=201, method="POST", path="/api/secrets", ip="")
    text = client.get("/api/audit-log/export", params={"action": "secret.create"}, headers=ADMIN).text
    assert "'=HYPERLINK" in text and ",'+1," in text


def test_retention_purges_old_entries_and_leaves_a_marker(env):
    from datetime import datetime, timedelta
    old = (datetime.utcnow() - timedelta(days=40)).isoformat()
    env.setattr(audit, "_now", lambda: old)
    audit.record(tenant_id="tenant_retention", project_id="", actor="a", action="secret.create", target_id="old",
                 outcome="success", status=201, method="POST", path="/api/secrets", ip="")
    env.undo()
    audit.record(tenant_id="tenant_retention", project_id="", actor="a", action="secret.create", target_id="new",
                 outcome="success", status=201, method="POST", path="/api/secrets", ip="")

    env.setenv("AUDIT_RETENTION_DAYS", "0")
    assert audit.purge_expired() == {}, "0 keeps everything"
    env.setenv("AUDIT_RETENTION_DAYS", "30")
    assert audit.purge_expired()["tenant_retention"] == 1

    left = audit.list_entries("tenant_retention", limit=10)
    assert [e["target_id"] for e in left if e["action"] == "secret.create"] == ["new"]
    marker = next(e for e in left if e["action"] == "audit.purge")
    assert marker["actor"] == "system" and marker["target_id"].startswith("1 entries before")
    env.setenv("AUDIT_RETENTION_DAYS", "soon")
    assert audit.retention_days() == audit.DEFAULT_RETENTION_DAYS
