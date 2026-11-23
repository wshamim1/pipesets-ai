"""SCIM 2.0 provisioning (services/scim.py, routers/scim.py): tokens, Okta- and Entra-style user and group
calls, role mapping from groups, deactivation ending access and SSO sessions, the last-owner rule, the email
domain fence, isolation between workspaces, and SSO sign-in deferring to SCIM."""
import pytest

from db import get_db_connection as db_conn
from services import sso

MEDIA = "application/scim+json"


@pytest.fixture(scope="module", autouse=True)
def _session_auth(env):
    env.setenv("AUTH_MODE", "session")


def signup(client, email):
    r = client.post("/api/auth/signup", json={"email": email, "password": "long-password", "display_name": "O"})
    assert r.status_code == 201, r.text
    d = r.json()
    return {"Authorization": f"Bearer {d['token']}", "x-tenant-id": d["tenants"][0]["id"]}, d


@pytest.fixture(scope="module")
def owner(client):
    return signup(client, "owner@scim-acme.com")


@pytest.fixture(scope="module")
def O(owner):
    return owner[0]


@pytest.fixture(scope="module")
def T(owner):
    return owner[1]["tenants"][0]["id"]


@pytest.fixture(scope="module")
def provider(client, O):
    g = client.post("/api/iam/groups", json={"name": "Builders"}, headers=O).json()
    gid = g.get("id") or g["group"]["id"]
    r = client.post("/api/iam/sso", headers=O, json={
        "name": "Okta", "protocol": "oidc",
        "config": {"issuer": "https://idp.example.com", "client_id": "c", "client_secret": "s"},
        "email_domains": ["scim-acme.com"], "role_claim": "groups", "default_role": "",
        "role_mappings": [{"value": "Pipesets Admins", "role": "owner"},
                          {"value": "Pipesets Builders", "role": "editor", "group_id": gid},
                          {"value": "Pipesets Viewers", "role": "viewer"}]})
    assert r.status_code == 201, r.text
    return {**r.json(), "group_id": gid}


@pytest.fixture(scope="module")
def S(client, O, provider):
    r = client.post(f"/api/iam/sso/{provider['id']}/scim-token", headers=O)
    assert r.status_code == 200, r.text
    assert r.json()["base_url"].endswith("/scim/v2")
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": MEDIA}


def role_of(T, user_id):
    with db_conn() as c:
        row = c.execute("SELECT role FROM tenant_memberships WHERE tenant_id = ? AND user_id = ?", (T, user_id)).fetchone()
    return row[0] if row else None


def new_user(client, S, name, **extra):
    body = {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"], "userName": f"{name}@scim-acme.com",
            "name": {"givenName": name.title(), "familyName": "Test"}, "active": True,
            "emails": [{"value": f"{name}@scim-acme.com", "primary": True, "type": "work"}], "externalId": f"ext-{name}"}
    body.update(extra)
    r = client.post("/scim/v2/Users", headers=S, json=body)
    assert r.status_code == 201, r.text
    assert r.headers["content-type"].startswith(MEDIA)
    return r.json()


def new_group(client, S, name, members=()):
    r = client.post("/scim/v2/Groups", headers=S, json={"displayName": name, "members": [{"value": m} for m in members]})
    assert r.status_code == 201, r.text
    return r.json()


def test_token_needs_domains_owner_only_and_is_required(client, O, provider, S):
    assert client.get("/scim/v2/Users").status_code == 401
    assert client.get("/scim/v2/Users", headers={"Authorization": "Bearer scim_nope"}).status_code == 401
    assert client.get("/scim/v2/ServiceProviderConfig", headers=S).json()["patch"]["supported"] is True
    view = next(p for p in client.get("/api/iam/sso", headers=O).json()["providers"] if p["id"] == provider["id"])
    assert view["scim_enabled"] and view["scim_token_prefix"].startswith("scim_") and view["scim_base_url"].endswith("/scim/v2")
    # Without email domains SCIM can't be turned on
    bare = client.post("/api/iam/sso", headers=O, json={"name": "x", "protocol": "oidc", "config": {
        "issuer": "https://idp2.example.com", "client_id": "c", "client_secret": "s"}}).json()
    r = client.post(f"/api/iam/sso/{bare['id']}/scim-token", headers=O)
    assert r.status_code == 400 and "email domains" in r.json()["detail"]


def test_create_user_without_group_gets_no_access_then_group_grants_role(client, S, T, provider):
    u = new_user(client, S, "ann")
    assert u["active"] and u["userName"] == "ann@scim-acme.com" and u["emails"][0]["value"] == "ann@scim-acme.com"
    assert role_of(T, u["id"]) is None                       # default_role "" → no access until a mapped group
    g = new_group(client, S, "Pipesets Builders", [u["id"]])
    assert g["members"][0]["value"] == u["id"]
    assert role_of(T, u["id"]) == "editor"
    with db_conn() as c:
        assert c.execute("SELECT 1 FROM group_memberships WHERE group_id = ? AND user_id = ?",
                         (provider["group_id"], u["id"])).fetchone()
    # Filters IdPs use to find existing users and groups
    found = client.get("/scim/v2/Users", headers=S, params={"filter": 'userName eq "ANN@scim-acme.com"'}).json()
    assert found["totalResults"] == 1 and found["Resources"][0]["groups"][0]["display"] == "Pipesets Builders"
    assert client.get("/scim/v2/Groups", headers=S, params={"filter": 'displayName eq "Pipesets Builders"'}).json()[
        "totalResults"] == 1
    assert client.get("/scim/v2/Users", headers=S, params={"filter": 'nickName co "x"'}).status_code == 400


def test_okta_style_group_patch_and_rename_change_roles(client, S, T):
    u = new_user(client, S, "bob")
    g = new_group(client, S, "Pipesets Viewers")
    r = client.patch(f"/scim/v2/Groups/{g['id']}", headers=S, json={
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "add", "path": "members", "value": [{"value": u["id"]}]}]})
    assert r.status_code == 200 and role_of(T, u["id"]) == "viewer"
    client.patch(f"/scim/v2/Groups/{g['id']}", headers=S, json={"Operations": [
        {"op": "replace", "value": {"id": g["id"], "displayName": "Pipesets Admins"}}]})
    assert role_of(T, u["id"]) == "owner"                    # the group's name is what maps to a role
    client.patch(f"/scim/v2/Groups/{g['id']}", headers=S, json={"Operations": [
        {"op": "remove", "path": f'members[value eq "{u["id"]}"]'}]})
    assert role_of(T, u["id"]) is None


def test_entra_style_user_patch_deactivates_and_ends_sso_sessions(client, S, T, provider):
    u = new_user(client, S, "cat")
    new_group(client, S, "Pipesets Editors-ish")             # unmapped: no effect
    g = client.get("/scim/v2/Groups", headers=S, params={"filter": 'displayName eq "Pipesets Builders"'}).json()["Resources"][0]
    client.patch(f"/scim/v2/Groups/{g['id']}", headers=S, json={"Operations": [
        {"op": "Add", "path": "members", "value": [{"value": u["id"]}]}]})
    assert role_of(T, u["id"]) == "editor"
    from services import auth
    token, _ = auth.create_session(u["id"], "", T, provider["id"])
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    r = client.patch(f"/scim/v2/Users/{u['id']}", headers=S, json={"Operations": [
        {"op": "Replace", "path": "active", "value": "False"}]})
    assert r.status_code == 200 and r.json()["active"] is False
    assert role_of(T, u["id"]) is None
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    with db_conn() as c:
        assert c.execute("SELECT status FROM users WHERE id = ?", (u["id"],)).fetchone()[0] == "active", \
            "the global account isn't disabled: they may belong to other workspaces"
    # SSO sign-in refuses a deactivated SCIM user
    p = sso.get_provider(provider["id"])
    with pytest.raises(sso.SSOError, match="turned off your access"):
        sso.complete_login(p, subject="sub-cat", email="cat@scim-acme.com", claims=["Pipesets Admins"])
    # Reactivating restores the role from the groups
    client.patch(f"/scim/v2/Users/{u['id']}", headers=S, json={"Operations": [{"op": "replace", "value": {"active": True}}]})
    assert role_of(T, u["id"]) == "editor"
    # …and SSO doesn't override SCIM's role with the claims
    sso.complete_login(p, subject="sub-cat", email="cat@scim-acme.com", claims=["Pipesets Admins"])
    assert role_of(T, u["id"]) == "editor"


def test_put_delete_and_last_owner(client, S, T, owner):
    u = new_user(client, S, "dan")
    r = client.put(f"/scim/v2/Users/{u['id']}", headers=S, json={
        "userName": "dan@scim-acme.com", "displayName": "Daniel", "emails": [{"value": "dan@scim-acme.com"}]})
    assert r.status_code == 200 and r.json()["displayName"] == "Daniel"
    assert client.delete(f"/scim/v2/Users/{u['id']}", headers=S).status_code == 204
    assert client.get(f"/scim/v2/Users/{u['id']}", headers=S).status_code == 404
    # The workspace owner (signed up, then provisioned) can't be removed by SCIM
    o = new_user(client, S, "owner")
    assert o["id"] == owner[1]["user"]["id"] and role_of(T, o["id"]) == "owner"
    client.patch(f"/scim/v2/Users/{o['id']}", headers=S, json={"Operations": [{"op": "replace", "path": "active",
                                                                                 "value": False}]})
    assert role_of(T, o["id"]) == "owner"


def test_domain_fence_conflicts_and_bad_requests(client, S):
    r = client.post("/scim/v2/Users", headers=S, json={"userName": "eve@evil.com", "emails": [{"value": "eve@evil.com"}]})
    assert r.status_code == 400 and "email domains" in r.json()["detail"]
    assert client.post("/scim/v2/Users", headers=S, json={"userName": "ann@scim-acme.com"}).status_code == 409
    assert client.post("/scim/v2/Users", headers=S, content=b"not json").status_code == 400
    assert client.post("/scim/v2/Groups", headers=S, json={"displayName": "x", "members": [{"value": "user_nope"}]}
                       ).status_code == 400


def test_other_workspace_token_sees_nothing(client, S):
    O2, d2 = signup(client, "boss@other-scim.com")
    p2 = client.post("/api/iam/sso", headers=O2, json={"name": "Other", "protocol": "oidc", "email_domains": ["other-scim.com"],
                     "config": {"issuer": "https://idp3.example.com", "client_id": "c", "client_secret": "s"}}).json()
    S2 = {"Authorization": f"Bearer {client.post(f'/api/iam/sso/{p2['id']}/scim-token', headers=O2).json()['token']}"}
    assert client.get("/scim/v2/Users", headers=S2).json()["totalResults"] == 0
    ann = client.get("/scim/v2/Users", headers=S, params={"filter": 'userName eq "ann@scim-acme.com"'}).json()["Resources"][0]
    assert client.get(f"/scim/v2/Users/{ann['id']}", headers=S2).status_code == 404
    assert client.patch(f"/scim/v2/Users/{ann['id']}", headers=S2, json={"Operations": []}).status_code == 404


def test_audited_and_revocable(client, O, S, provider):
    actions = {e["action"] for e in client.get("/api/audit-log", headers=O, params={"limit": 500}).json()["entries"]}
    assert {"scim.token_issue", "scim.user_create", "scim.user_update", "scim.group_create", "scim.group_update",
            "scim.user_delete"} <= actions
    assert client.delete(f"/api/iam/sso/{provider['id']}/scim-token", headers=O).status_code == 200
    assert client.get("/scim/v2/Users", headers=S).status_code == 401
