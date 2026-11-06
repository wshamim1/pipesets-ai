"""Sign-up, login sessions and how they tie into tenants / groups / ACLs."""
import pytest

from db import get_db_connection as db_conn
from services import auth as auth_service


@pytest.fixture(scope="module", autouse=True)
def _session_auth(env):
    env.setenv("AUTH_MODE", "session")


def h(token, tenant=None, project=None):
    headers = {"Authorization": f"Bearer {token}"}
    if tenant:
        headers["x-tenant-id"] = tenant
    if project:
        headers["x-project-id"] = project
    return headers


@pytest.fixture(scope="module")
def alice(client):
    r = client.post("/api/auth/signup", json={"email": "Alice@Example.com", "password": "correct-horse",
                                              "display_name": "Alice"})
    assert r.status_code == 201
    return r.json()


@pytest.fixture(scope="module")
def bob(client):
    return client.post("/api/auth/signup", json={"email": "bob@example.com", "password": "bob-password",
                                                 "display_name": "Bob"}).json()


@pytest.fixture(scope="module")
def A(alice):
    """Alice (owner) acting in her own tenant."""
    return h(alice["token"], alice["tenants"][0]["id"])


@pytest.fixture(scope="module")
def B(bob, alice):
    """Bob acting in Alice's tenant."""
    return h(bob["token"], alice["tenants"][0]["id"])


def test_unauthenticated_access(client):
    assert client.get("/api/iam/users").status_code == 401
    assert client.get("/api/iam/users", headers={"x-user-id": "user_admin"}).status_code == 401, \
        "x-user-id alone is not a session"
    assert client.get("/health").status_code == 200
    assert client.get("/api/auth/config").json()["signup_enabled"] is True
    assert client.get("/api/iam/users", headers=h("uas_nope")).status_code == 401


def test_signup(client, alice):
    tenant = alice["tenants"][0]
    assert tenant["role"] == "owner" and len(tenant["projects"]) == 1, "signup creates an owned tenant + project"
    assert alice["user"]["email"] == "alice@example.com", "email normalised"
    assert client.post("/api/auth/signup", json={"email": "alice@example.com", "password": "another-pass"}).status_code == 409
    assert client.post("/api/auth/signup", json={"email": "x@example.com", "password": "short"}).status_code == 400
    assert client.post("/api/auth/signup", json={"email": "not-an-email", "password": "long-enough"}).status_code == 400
    assert client.post("/api/auth/signup", json={"email": "admin@demo.local", "password": "takeover-attempt"}
                       ).status_code == 409, "seeded email can't be claimed"

    assert client.get("/api/auth/me", headers=h(alice["token"])).json()["user"]["id"] == alice["user"]["id"]
    ctx = client.get("/api/iam/context", headers=h(alice["token"])).json()
    assert ctx["tenant_id"] == tenant["id"] and ctx["project_id"] == tenant["projects"][0]["id"] and ctx["can_admin"]


def test_login(client, alice):
    assert client.post("/api/auth/login", json={"email": "alice@example.com", "password": "nope-nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "whatever1"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "admin@demo.local", "password": ""}).status_code == 401, \
        "seeded user without a password can't log in"
    r = client.post("/api/auth/login", json={"email": "ALICE@example.com", "password": "correct-horse"})
    assert r.status_code == 200 and r.json()["token"].startswith("uas_")


def test_tenant_isolation(client, alice, bob):
    a_tenant, b_tok = alice["tenants"][0], bob["token"]
    assert client.get("/api/iam/users", headers=h(b_tok, a_tenant["id"])).status_code == 403
    assert client.get("/api/iam/users", headers=h(b_tok, "tenant_demo")).status_code == 403
    assert client.get("/api/iam/users", headers=h(b_tok, project=a_tenant["projects"][0]["id"])).status_code == 403
    assert [t["id"] for t in client.get("/api/iam/tenants", headers=h(b_tok)).json()["tenants"]] == [bob["tenants"][0]["id"]]
    assert client.put(f"/api/iam/tenants/{a_tenant['id']}", json={"name": "pwned"}, headers=h(b_tok)).status_code == 403
    ctx = client.get("/api/iam/context", headers={**h(b_tok), "x-user-id": alice["user"]["id"]}).json()
    assert ctx["user_id"] == bob["user"]["id"], "x-user-id is ignored once signed in"


def test_admin_links_existing_account(client, bob, A, B):
    r = client.post("/api/iam/users", json={"email": "bob@example.com", "display_name": "ignored"}, headers=A)
    assert r.status_code == 200 and r.json()["existing_account"] and r.json()["id"] == bob["user"]["id"]
    assert client.get("/api/iam/users", headers=B).status_code == 200, "bob enters alice's tenant as viewer"
    assert client.post("/api/iam/groups", json={"name": "x"}, headers=B).status_code == 403
    assert client.post("/api/iam/acls", json={"principal_type": "user", "principal_id": bob["user"]["id"],
                                              "resource": "*", "action": "*"}, headers=B).status_code == 403
    assert client.put(f"/api/iam/users/{bob['user']['id']}", json={"role": "owner"}, headers=B).status_code == 403
    assert client.put(f"/api/iam/users/{bob['user']['id']}", json={"display_name": "Robert"}, headers=B).status_code == 200
    assert client.get("/api/api-keys", headers=B).status_code == 403
    assert all("password_hash" not in u for u in client.get("/api/iam/users", headers=A).json()["users"])


def test_groups_and_acls(client, alice, bob, A, B):
    group = client.post("/api/iam/groups", json={"name": "Integrators"}, headers=A).json()
    assert client.post(f"/api/iam/groups/{group['id']}/members", json={"user_id": bob["user"]["id"]},
                       headers=A).status_code == 200
    assert client.post(f"/api/iam/groups/{group['id']}/members", json={"user_id": "user_admin"},
                       headers=A).status_code == 404, "can't add a non-member"
    assert client.post("/api/iam/acls", json={"principal_type": "group", "principal_id": "group_ops",
                                              "resource": "*", "action": "*"}, headers=A).status_code == 404, \
        "ACL can't target another tenant's group"
    allow = client.post("/api/iam/acls", json={"principal_type": "group", "principal_id": group["id"],
                                               "resource": "api_keys", "action": "admin"}, headers=A)
    assert allow.status_code == 200
    assert client.get("/api/api-keys", headers=B).status_code == 200, "access through the group"

    deny = client.post("/api/iam/acls", json={"principal_type": "user", "principal_id": bob["user"]["id"],
                                              "resource": "api_keys", "action": "*", "effect": "deny"}, headers=A).json()
    assert client.get("/api/api-keys", headers=B).status_code == 403, "a user deny overrides the group allow"
    client.delete(f"/api/iam/acls/{deny['id']}", headers=A)
    assert client.get("/api/api-keys", headers=B).status_code == 200
    assert client.post("/api/iam/access-check", json={"user_id": alice["user"]["id"], "project_id": "",
                                                      "resource": "x", "action": "y"}, headers=B).status_code == 403


def test_admin_created_account_and_disabling(client, bob, A):
    r = client.post("/api/iam/users", json={"email": "carol@example.com", "display_name": "Carol",
                                            "password": "carol-secret"}, headers=A)
    assert r.status_code == 200 and r.json()["has_password"]
    login = {"email": "carol@example.com", "password": "carol-secret"}
    assert client.post("/api/auth/login", json=login).status_code == 200
    assert client.put(f"/api/iam/users/{bob['user']['id']}", json={"password": "hijacked-pw"},
                      headers=A).status_code == 403, "can't reset the password of another tenant's owner"

    carol_tok = client.post("/api/auth/login", json=login).json()["token"]
    client.put(f"/api/iam/users/{r.json()['id']}", json={"status": "disabled"}, headers=A)
    assert client.get("/api/auth/me", headers=h(carol_tok)).status_code == 401, "disabling kills sessions"
    assert client.post("/api/auth/login", json=login).status_code == 403


def test_logout_and_password_change(client, alice, bob):
    assert client.post("/api/auth/logout", headers=h(bob["token"])).status_code == 200
    assert client.get("/api/auth/me", headers=h(bob["token"])).status_code == 401

    r = client.post("/api/auth/change-password", json={"current_password": "correct-horse",
                                                       "new_password": "battery-staple"}, headers=h(alice["token"]))
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=h(alice["token"])).status_code == 401, "old sessions die"
    assert client.post("/api/auth/login", json={"email": "alice@example.com", "password": "battery-staple"}).status_code == 200

    fake_request = type("R", (), {"headers": {"authorization": "Bearer ps_abc"}})()
    assert auth_service.extract_token(fake_request) is None, "API keys are not sessions"


def test_brute_force_throttle(client):
    codes = [client.post("/api/auth/login", json={"email": "dave@example.com", "password": "wrong-pass"}).status_code
             for _ in range(11)]
    assert codes[-1] == 429


# ── Server admins ─────────────────────────────────────────────────────────────

def test_server_admin_role(client, env):
    import manage

    # The seeded demo admin can't sign in (no password), so the first sign-up owns the server ...
    conn = db_conn()
    conn.execute("UPDATE users SET server_admin = 0 WHERE id <> 'user_admin'")
    conn.execute("UPDATE users SET password_hash = NULL WHERE id = 'user_admin'")
    conn.commit()
    has_admin = conn.execute("SELECT 1 FROM users WHERE server_admin = 1 AND password_hash IS NOT NULL").fetchone()
    conn.close()
    assert not has_admin
    first = client.post("/api/auth/signup", json={"email": "owner@server.test", "password": "correct horse battery"}).json()
    assert first["user"]["server_admin"] is True
    # ... and the next one doesn't, though they own their own workspace
    second = client.post("/api/auth/signup", json={"email": "guest@server.test", "password": "correct horse battery"}).json()
    assert second["user"]["server_admin"] is False
    guest = {"Authorization": f"Bearer {second['token']}"}
    owner = {"Authorization": f"Bearer {first['token']}"}
    assert client.get("/api/iam/context", headers=guest).json()["can_admin"] is True, "owns their workspace"
    assert client.get("/api/iam/context", headers=guest).json()["server_admin"] is False
    assert client.get("/api/system/database", headers=guest).status_code == 403
    assert client.get("/api/system/database", headers=owner).status_code == 200

    # PIPESETS_SERVER_ADMINS and the CLI grant it too; disabled accounts never have it
    env.setenv("PIPESETS_SERVER_ADMINS", " Guest@Server.test ")
    assert client.get("/api/system/database", headers=guest).status_code == 200
    env.delenv("PIPESETS_SERVER_ADMINS")
    assert manage.main(["server-admin", "guest@server.test"]) == 0
    assert auth_service.is_server_admin(second["user"]["id"])
    assert manage.main(["server-admin", "guest@server.test", "--revoke"]) == 0
    assert not auth_service.is_server_admin(second["user"]["id"])
    assert manage.main(["server-admin", "nobody@server.test"]) == 1
    assert manage.main(["server-admin", "--list"]) == 0
