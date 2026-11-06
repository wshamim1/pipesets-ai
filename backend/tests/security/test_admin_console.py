"""Settings → Admin console (routers/admin.py): server admins see and manage every user, workspace
and pipeline; everyone else gets 403. The guards keep the server administrable."""
import pytest

from db import get_db_connection
from helpers import mock_flow
from services import auth


@pytest.fixture(scope="module", autouse=True)
def _setup(env):
    env.setenv("AUTH_MODE", "session")


def signup(client, email):
    data = client.post("/api/auth/signup", json={"email": email, "password": "password123",
                                                 "display_name": email.split("@")[0]}).json()
    t = data["tenants"][0]
    return {"Authorization": f"Bearer {data['token']}", "x-tenant-id": t["id"], "x-project-id": t["projects"][0]["id"],
            "_user": data["user"]["id"]}


def h(user):
    return {k: v for k, v in user.items() if not k.startswith("_")}


@pytest.fixture(scope="module")
def admin(client):
    user = signup(client, "console-admin@example.com")
    auth.set_server_admin("console-admin@example.com")
    return user


@pytest.fixture(scope="module")
def member(client, admin):   # after admin: the first sign-up on a server with no admin becomes one
    user = signup(client, "console-member@example.com")
    client.post("/api/apps", json={"name": "Member pipeline", "flow_data": mock_flow()}, headers=h(user))
    return user


def test_non_admins_are_refused(client, member):
    for path in ("/api/admin/overview", "/api/admin/users", "/api/admin/workspaces", "/api/admin/apps",
                 "/api/admin/audit"):
        assert client.get(path, headers=h(member)).status_code == 403, path
    assert client.patch(f"/api/admin/users/{member['_user']}", json={"server_admin": True},
                        headers=h(member)).status_code == 403


def test_admin_sees_every_user_workspace_and_pipeline(client, admin, member):
    users = {u["id"]: u for u in client.get("/api/admin/users", headers=h(admin)).json()["users"]}
    assert users[admin["_user"]]["server_admin"] and not users[member["_user"]]["server_admin"]
    assert users[member["_user"]]["workspaces"][0]["role"] == "owner"
    workspaces = {w["id"]: w for w in client.get("/api/admin/workspaces", headers=h(admin)).json()["workspaces"]}
    assert workspaces[member["x-tenant-id"]]["owners"] == ["console-member@example.com"]
    assert not workspaces[member["x-tenant-id"]]["is_member"]
    apps = client.get("/api/admin/apps", params={"q": "Member pipeline"}, headers=h(admin)).json()["apps"]
    assert [a["workspace"] for a in apps] == [workspaces[member["x-tenant-id"]]["name"]]
    flow = client.get(f"/api/admin/apps/{apps[0]['id']}", headers=h(admin)).json()["flow_data"]
    assert len(flow["nodes"]) == 1
    assert client.get("/api/admin/overview", headers=h(admin)).json()["pipelines"] >= 1


def test_viewing_another_workspace_does_not_grant_edit_until_joining(client, admin, member):
    app_id = client.get("/api/admin/apps", params={"q": "Member pipeline"}, headers=h(admin)).json()["apps"][0]["id"]
    in_member_ws = {**h(admin), "x-tenant-id": member["x-tenant-id"], "x-project-id": member["x-project-id"]}
    assert client.get(f"/api/apps/{app_id}", headers=in_member_ws).status_code == 403
    assert client.post(f"/api/admin/workspaces/{member['x-tenant-id']}/join", headers=h(admin)).status_code == 200
    assert client.get(f"/api/apps/{app_id}", headers=in_member_ws).status_code == 200


def test_disable_signs_the_user_out_and_enable_restores(client, admin):
    other = signup(client, "console-disable@example.com")
    res = client.patch(f"/api/admin/users/{other['_user']}", json={"status": "disabled"}, headers=h(admin))
    assert res.status_code == 200 and res.json()["active_sessions"] == 0
    assert client.get("/api/auth/me", headers=h(other)).status_code == 401
    assert client.patch(f"/api/admin/users/{other['_user']}", json={"status": "active"},
                        headers=h(admin)).json()["status"] == "active"


def test_admin_can_grant_and_revoke_server_admin(client, admin, member):
    assert client.patch(f"/api/admin/users/{member['_user']}", json={"server_admin": True},
                        headers=h(admin)).json()["server_admin"]
    assert client.get("/api/admin/overview", headers=h(member)).status_code == 200
    assert not client.patch(f"/api/admin/users/{member['_user']}", json={"server_admin": False},
                            headers=h(admin)).json()["server_admin"]
    assert client.get("/api/admin/overview", headers=h(member)).status_code == 403


def test_admin_cannot_lock_themselves_out(client, admin):
    for body in ({"status": "disabled"}, {"server_admin": False}):
        assert client.patch(f"/api/admin/users/{admin['_user']}", json=body, headers=h(admin)).status_code == 400
    assert client.delete(f"/api/admin/users/{admin['_user']}", headers=h(admin)).status_code == 400


def test_password_reset_signs_out_and_the_new_password_works(client, admin):
    other = signup(client, "console-reset@example.com")
    res = client.post(f"/api/admin/users/{other['_user']}/password", json={"password": "brand-new-pass-1"},
                      headers=h(admin))
    assert res.status_code == 200 and res.json()["sessions_revoked"] >= 1
    assert client.get("/api/auth/me", headers=h(other)).status_code == 401
    assert client.post("/api/auth/login", json={"email": "console-reset@example.com",
                                                "password": "brand-new-pass-1"}).status_code == 200


def test_deleting_a_sole_owner_is_refused_until_their_workspace_goes(client, admin):
    other = signup(client, "console-delete@example.com")
    res = client.delete(f"/api/admin/users/{other['_user']}", headers=h(admin))
    assert res.status_code == 409 and "only owner" in res.json()["detail"]
    assert client.delete(f"/api/admin/workspaces/{other['x-tenant-id']}", headers=h(admin)).status_code == 200
    assert client.delete(f"/api/admin/users/{other['_user']}", headers=h(admin)).status_code == 200
    assert other["_user"] not in [u["id"] for u in client.get("/api/admin/users", headers=h(admin)).json()["users"]]


def test_admin_actions_are_audited_and_listed_server_wide(client, admin, member):
    client.post(f"/api/admin/users/{member['_user']}/sign-out", headers=h(admin))
    entries = client.get("/api/admin/audit", params={"action": "admin."}, headers=h(admin)).json()["entries"]
    actions = {e["action"] for e in entries}
    assert {"admin.user_sign_out", "admin.workspace_join", "admin.user_update"} <= actions
    assert all(e["actor_email"] == "console-admin@example.com" for e in entries if e["outcome"] == "success")
    # the member's refused attempt to make themselves an admin is on record too
    assert any(e["actor"] == member["_user"] and e["outcome"] == "denied" for e in entries)
    conn = get_db_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'admin.user_sign_out' AND target_id = ?",
                            (member["_user"],)).fetchone()[0] == 1
    finally:
        conn.close()
