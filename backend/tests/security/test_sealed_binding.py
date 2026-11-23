"""Sealed values are bound to their tenant (services/secret_store.py, migration 0039): resolve_refs opens a
value only in the tenant it was sealed for, refuses unbound (pre-binding) values and works only inside a
request or run; a credential copied from one workspace's connection is useless in another."""
import pytest

from services import secret_store
from services.pipeline_runner import RunScope, current_scope


@pytest.fixture(scope="module", autouse=True)
def _setup(env):
    env.setenv("AUTH_MODE", "session")


def in_tenant(tenant, fn):
    token = current_scope.set(RunScope(tenant_id=tenant, project_id="p", user_id="u"))
    try:
        return fn()
    finally:
        current_scope.reset(token)


def test_seal_binds_to_the_current_or_given_tenant():
    v = in_tenant("tA", lambda: secret_store.seal("pw"))
    assert secret_store.sealed_tenant(v) == "tA" and secret_store.unseal(v) == "pw"
    assert secret_store.sealed_tenant(secret_store.seal("pw", "tB")) == "tB"
    assert secret_store.sealed_tenant(secret_store.seal("pw")) is None          # outside any scope
    assert secret_store.sealed_tenant(secret_store.seal("pw", "")) is None


def test_resolve_refs_opens_only_in_the_bound_tenant():
    cfg = {"password": secret_store.seal("pw", "tA"), "host": "db"}
    assert in_tenant("tA", lambda: secret_store.resolve_refs(cfg)) == {"password": "pw", "host": "db"}
    with pytest.raises(secret_store.WrongTenantError, match="another workspace"):
        in_tenant("tB", lambda: secret_store.resolve_refs(cfg))
    with pytest.raises(secret_store.WrongTenantError, match="predates"):
        in_tenant("tA", lambda: secret_store.resolve_refs({"password": secret_store.seal("pw", "")}))
    with pytest.raises(secret_store.SecretError, match="signed-in request or pipeline run"):
        secret_store.resolve_refs(cfg)
    assert secret_store.reveal_value("plain-key") == "plain-key"


def test_tampering_with_the_ciphertext_is_detected():
    v = secret_store.seal("pw", "tA")
    with pytest.raises(secret_store.SecretError):
        secret_store.unseal(v[:-6] + ("A" if v[-6] != "A" else "B") + v[-5:])


def test_rebind_and_rotation_keep_the_binding():
    doc = {"a": secret_store.seal("x", "tA"), "b": [secret_store.seal("y", "")], "c": "plain"}
    out, n = secret_store.rebind(doc, "tB")
    assert n == 2 and {secret_store.sealed_tenant(out["a"]), secret_store.sealed_tenant(out["b"][0])} == {"tB"}
    assert secret_store.rebind(out, "tB")[1] == 0 and out["c"] == "plain"
    rotated, _ = secret_store._rotate_sealed_tree(out)
    assert secret_store.sealed_tenant(rotated["a"]) == "tB" and secret_store.unseal(rotated["a"]) == "x"


def signup(client, email):
    data = client.post("/api/auth/signup", json={"email": email, "password": "password123",
                                                 "display_name": email.split("@")[0]}).json()
    t = data["tenants"][0]
    return {"Authorization": f"Bearer {data['token']}", "x-tenant-id": t["id"], "x-project-id": t["projects"][0]["id"]}


def test_a_credential_copied_from_another_workspace_is_useless(client):
    A, B = signup(client, "bind-a@example.com"), signup(client, "bind-b@example.com")
    conn = client.post("/api/connections", headers=A, json={
        "name": "A's API", "type": "custom_api", "config": {"base_url": "https://a.invalid", "api_key": "A-SECRET"}}).json()
    stolen = conn["config"]["api_key"]
    assert secret_store.sealed_tenant(stolen) == A["x-tenant-id"]
    # B pastes A's sealed value into its own connection: it is kept as is, but never opens in B
    r = client.post("/api/connections", headers=B, json={
        "name": "copy", "type": "custom_api", "config": {"base_url": "https://evil.invalid", "api_key": stolen}})
    assert r.status_code == 200 and r.json()["status"] == "error" and "another workspace" in r.json()["status_msg"]
    r = client.post("/api/connections/test", headers=B, json={
        "type": "custom_api", "config": {"base_url": "https://evil.invalid", "api_key": stolen}})
    assert r.json()["success"] is False and "another workspace" in r.json()["message"]
    # …and still works in A
    assert client.post(f"/api/connections/{conn['id']}/test", headers=A).json().get("message", "") \
        and "another workspace" not in client.post(f"/api/connections/{conn['id']}/test", headers=A).json()["message"]
