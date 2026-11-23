"""Single sign-on (services/sso.py, sso_oidc.py, sso_saml.py, routers/sso.py): provider admin, OIDC and SAML
sign-in end to end against fake IdPs (real RSA signatures), role mapping, session scoping, enforcement and the
attacks the design must stop (replay, wrong audience / nonce / issuer, tampering, assertion wrapping, open
redirects, cross-workspace reach)."""
import base64
import time
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree
from signxml import XMLSigner, methods

from db import get_db_connection as db_conn
from services import sso, sso_oidc

ISSUER = "https://idp.example.com"
CLIENT_ID = "pipesets-client"


@pytest.fixture(scope="module", autouse=True)
def _session_auth(env):
    env.setenv("AUTH_MODE", "session")


def h(token, tenant=None):
    headers = {"Authorization": f"Bearer {token}"}
    if tenant:
        headers["x-tenant-id"] = tenant
    return headers


def _signup(client, email, name):
    r = client.post("/api/auth/signup", json={"email": email, "password": "long-password", "display_name": name})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture(scope="module")
def owner(client):
    return _signup(client, "owner@acme.com", "Olive")


@pytest.fixture(scope="module")
def T(owner):
    return owner["tenants"][0]["id"]


@pytest.fixture(scope="module")
def O(owner, T):
    return h(owner["token"], T)


# ── Fake OIDC IdP ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def idp(env):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    jwk.update({"kid": "k1", "use": "sig", "alg": "RS256"})
    meta = {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize", "token_endpoint": f"{ISSUER}/token",
            "jwks_uri": f"{ISSUER}/jwks", "userinfo_endpoint": f"{ISSUER}/userinfo"}
    state = {"claims": {}, "header": {"kid": "k1"}, "key": key, "alg": "RS256", "userinfo": {}}

    async def cached(url, refresh=False):
        return meta if url.endswith("openid-configuration") else {"keys": [jwk]}

    async def exchange(p, m, code, verifier, base):
        assert code == "good-code"
        return {"id_token": jwt.encode(state["claims"], state["key"], algorithm=state["alg"], headers=state["header"]),
                "access_token": "at"}

    async def userinfo(m, access_token, sub):
        return state["userinfo"] if state["userinfo"].get("sub") == sub else {}

    env.setattr(sso_oidc, "_cached", cached)
    env.setattr(sso_oidc, "_exchange", exchange)
    env.setattr(sso_oidc, "_userinfo", userinfo)
    return state


def claims(nonce, **kw):
    now = int(time.time())
    c = {"iss": ISSUER, "sub": "u-1", "aud": CLIENT_ID, "exp": now + 300, "iat": now, "nonce": nonce,
         "email": "ed@acme.com", "name": "Ed", "email_verified": True, "groups": ["pipesets-editors"]}
    c.update(kw)
    return {k: v for k, v in c.items() if v is not None}


def _group(client, O, name):
    r = client.post("/api/iam/groups", json={"name": name}, headers=O)
    assert r.status_code in (200, 201), r.text
    return r.json().get("id") or r.json()["group"]["id"]


@pytest.fixture(scope="module")
def oidc(client, O):
    gid = _group(client, O, "Editors from IdP")
    r = client.post("/api/iam/sso", headers=O, json={
        "name": "Acme Okta", "protocol": "oidc",
        "config": {"issuer": ISSUER, "client_id": CLIENT_ID, "client_secret": "s3cret"},
        "email_domains": ["acme.com"], "role_claim": "groups",
        "role_mappings": [{"value": "pipesets-admins", "role": "owner"},
                          {"value": "pipesets-editors", "role": "editor", "group_id": gid}],
        "default_role": "viewer"})
    assert r.status_code == 201, r.text
    return {**r.json(), "group_id": gid}


def start(client, provider_id, return_to="http://localhost:5173"):
    r = client.get(f"/api/auth/sso/{provider_id}/start", params={"return_to": return_to}, follow_redirects=False)
    assert r.status_code in (302, 303), r.text
    return r


def oidc_login(client, idp, provider_id, return_to="http://localhost:5173", **kw):
    """Run the browser side of an OIDC sign-in → (redirect query back to the UI, nonce)."""
    loc = urlparse(start(client, provider_id, return_to).headers["location"])
    q = {k: v[0] for k, v in parse_qs(loc.query).items()}
    assert loc.netloc == "idp.example.com" and q["code_challenge_method"] == "S256" and q["client_id"] == CLIENT_ID
    idp["claims"] = claims(q["nonce"], **kw)
    r = client.get("/api/auth/sso/oidc/callback", params={"state": q["state"], "code": "good-code"},
                   follow_redirects=False)
    assert r.status_code == 303
    back = urlparse(r.headers["location"])
    return back, {k: v[0] for k, v in parse_qs(back.query).items()}, q


def sso_session(client, idp, provider_id, **kw):
    back, q, _ = oidc_login(client, idp, provider_id, **kw)
    assert "sso_code" in q, q
    r = client.post("/api/auth/sso/exchange", json={"code": q["sso_code"]})
    assert r.status_code == 200, r.text
    return r.json()


# ── Admin ─────────────────────────────────────────────────────────────────────

def test_admin_owner_only_and_secret_never_returned(client, owner, T, O, oidc):
    assert oidc["config"]["client_secret_set"] is True and "client_secret" not in oidc["config"]
    assert oidc["redirect_uri"].endswith("/api/auth/sso/oidc/callback")
    with db_conn() as conn:
        raw = conn.execute("SELECT config FROM sso_providers WHERE id = ?", (oidc["id"],)).fetchone()[0]
    assert "s3cret" not in raw and "enc://" in raw

    viewer = _signup(client, "vic@elsewhere.org", "Vic")
    client.post("/api/iam/users", headers=O, json={"email": "vic@elsewhere.org", "display_name": "Vic", "role": "editor"})
    assert client.get("/api/iam/sso", headers=h(viewer["token"], T)).status_code == 403

    # An empty secret on update keeps the saved one
    r = client.put(f"/api/iam/sso/{oidc['id']}", headers=O, json={"config": {"client_secret": ""}, "name": "Acme"})
    assert r.status_code == 200 and r.json()["config"]["client_secret_set"] and r.json()["name"] == "Acme"

    for bad, msg in [({"protocol": "ldap"}, "protocol"),
                     ({"protocol": "oidc", "name": "x", "config": {"issuer": "http://evil.com", "client_id": "a",
                                                                   "client_secret": "b"}}, "https"),
                     ({"protocol": "saml", "name": "x", "config": {"idp_entity_id": "e", "idp_sso_url": "https://i/x",
                                                                   "idp_certificate": "nope"}}, "certificate"),
                     ({**{k: oidc[k] for k in ("name",)}, "protocol": "oidc", "default_role": "owner",
                       "config": {"issuer": ISSUER, "client_id": "a", "client_secret": "b"}}, "owner")]:
        r = client.post("/api/iam/sso", headers=O, json=bad)
        assert r.status_code == 400 and msg in r.json()["detail"], (bad, r.text)

    actions = {e["action"] for e in client.get("/api/audit-log", headers=O).json()["entries"]}
    assert {"sso_provider.create", "sso_provider.update"} <= actions


def test_discover(client, oidc):
    assert [p["id"] for p in client.get("/api/auth/sso/discover", params={"email": "x@ACME.com"}).json()["providers"]] \
        == [oidc["id"]]
    assert client.get("/api/auth/sso/discover", params={"email": "x@other.com"}).json()["providers"] == []


# ── OIDC sign-in ──────────────────────────────────────────────────────────────

def test_oidc_provisions_maps_role_and_group(client, idp, T, O, oidc):
    s = sso_session(client, idp, oidc["id"])
    assert s["session"] == {"sso": True, "tenant_id": T}
    assert [t["id"] for t in s["tenants"]] == [T] and s["tenants"][0]["role"] == "editor"
    assert s["user"]["has_password"] is False and s["user"]["server_admin"] is False
    with db_conn() as conn:
        uid = s["user"]["id"]
        assert conn.execute("SELECT 1 FROM group_memberships WHERE group_id = ? AND user_id = ?",
                            (oidc["group_id"], uid)).fetchone()
    # The session works for the workspace's API
    assert client.get("/api/iam/context", headers=h(s["token"])).json()["tenant_id"] == T
    logins = [e for e in client.get("/api/audit-log", headers=O).json()["entries"] if e["action"] == "sso.login"]
    assert any(e["actor"] == uid and e["outcome"] == "success" and e["target_id"] == oidc["id"] for e in logins)


def test_oidc_resyncs_roles_and_groups(client, idp, T, oidc):
    s = sso_session(client, idp, oidc["id"], groups=["other"])          # unmapped → default viewer, group removed
    assert s["tenants"][0]["role"] == "viewer"
    with db_conn() as conn:
        assert not conn.execute("SELECT 1 FROM group_memberships WHERE group_id = ? AND user_id = ?",
                                (oidc["group_id"], s["user"]["id"])).fetchone()
    s = sso_session(client, idp, oidc["id"], groups="pipesets-admins")   # a single string claim
    assert s["tenants"][0]["role"] == "owner"


def test_last_owner_is_never_demoted(client, idp, owner, T, O, oidc):
    # Ed is an owner now; remove Olive's ownership so Ed is the last owner… then the IdP says viewer
    with db_conn() as conn:
        conn.execute("UPDATE tenant_memberships SET role = 'editor' WHERE tenant_id = ? AND user_id = ?",
                     (T, owner["user"]["id"]))
        conn.commit()
    s = sso_session(client, idp, oidc["id"], groups=[])
    assert s["tenants"][0]["role"] == "owner"
    with db_conn() as conn:
        conn.execute("UPDATE tenant_memberships SET role = 'owner' WHERE tenant_id = ? AND user_id = ?",
                     (T, owner["user"]["id"]))
        conn.commit()
    assert sso_session(client, idp, oidc["id"], groups=[])["tenants"][0]["role"] == "viewer"


def test_userinfo_fills_missing_claims(client, idp, oidc):
    idp["userinfo"] = {"sub": "u-ui", "groups": ["pipesets-editors"]}
    s = sso_session(client, idp, oidc["id"], sub="u-ui", email="ui@acme.com", groups=None)
    assert s["tenants"][0]["role"] == "editor"
    idp["userinfo"] = {}


@pytest.mark.parametrize("kw, msg", [
    ({"aud": "someone-else"}, "not valid"),
    ({"iss": "https://evil.example.com"}, "different identity provider"),
    ({"exp": int(time.time()) - 3600}, "expired"),
    ({"email_verified": False}, "isn't verified"),
    ({"email": "ed@evil.com"}, "can't sign in"),
    ({"email": None}, "valid email"),
])
def test_oidc_rejects_bad_tokens(client, idp, oidc, kw, msg):
    _, q, _ = oidc_login(client, idp, oidc["id"], **kw)
    assert "sso_code" not in q and msg in q["sso_error"], q


def test_oidc_rejects_nonce_and_algorithm_tricks(client, idp, oidc):
    loc = urlparse(start(client, oidc["id"]).headers["location"])
    q = {k: v[0] for k, v in parse_qs(loc.query).items()}
    idp["claims"] = claims("not-the-nonce")
    r = client.get("/api/auth/sso/oidc/callback", params={"state": q["state"], "code": "good-code"}, follow_redirects=False)
    assert "nonce" in parse_qs(urlparse(r.headers["location"]).query)["sso_error"][0]

    # HS256 signed with the public key as the secret (the classic key-confusion attack) and alg=none
    orig = idp["key"]
    for alg, key in (("HS256", "public-key-as-secret"), ("none", None)):
        loc = urlparse(start(client, oidc["id"]).headers["location"])
        q = {k: v[0] for k, v in parse_qs(loc.query).items()}
        idp.update(claims=claims(q["nonce"]), alg=alg, key=key)
        r = client.get("/api/auth/sso/oidc/callback", params={"state": q["state"], "code": "good-code"},
                       follow_redirects=False)
        assert "algorithm" in parse_qs(urlparse(r.headers["location"]).query)["sso_error"][0]
    idp.update(alg="RS256", key=orig)


def test_state_and_handoff_are_single_use(client, idp, oidc):
    _, q, auth_q = oidc_login(client, idp, oidc["id"])
    assert client.post("/api/auth/sso/exchange", json={"code": q["sso_code"]}).status_code == 200
    assert client.post("/api/auth/sso/exchange", json={"code": q["sso_code"]}).status_code == 401
    r = client.get("/api/auth/sso/oidc/callback", params={"state": auth_q["state"], "code": "good-code"},
                   follow_redirects=False)
    assert "already used" in parse_qs(urlparse(r.headers["location"]).query)["sso_error"][0]


def test_no_open_redirect(client, idp, oidc):
    back, q, _ = oidc_login(client, idp, oidc["id"], return_to="https://evil.example.net/steal")
    assert back.netloc == "testserver" and "sso_code" in q


# ── Scope, enforcement, provisioning rules ────────────────────────────────────

def test_sso_session_is_scoped_to_its_workspace(client, idp, oidc):
    s = sso_session(client, idp, oidc["id"], sub="u-dual", email="dual@acme.com")
    # The same person also owns another workspace (made with a password session)
    with db_conn() as conn:
        other = f"tenant_{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow().isoformat()
        conn.execute("INSERT INTO tenants (id, name, slug, status, created_at, updated_at) "
                     "VALUES (?, 'Other', ?, 'active', ?, ?)", (other, other, now, now))
        conn.execute("INSERT INTO tenant_memberships (tenant_id, user_id, role, created_at) VALUES (?, ?, 'owner', ?)",
                     (other, s["user"]["id"], now))
        conn.execute("UPDATE users SET server_admin = 1 WHERE id = ?", (s["user"]["id"],))
        conn.commit()
    tok = s["token"]
    assert client.get("/api/iam/context", headers=h(tok, other)).status_code == 403
    assert [t["id"] for t in client.get("/api/iam/tenants", headers=h(tok)).json()["tenants"]] == [oidc["tenant_id"]]
    assert client.put(f"/api/iam/tenants/{other}", headers=h(tok), json={"name": "pwned"}).status_code == 403
    assert client.delete(f"/api/iam/tenants/{other}", headers=h(tok)).status_code == 403
    assert client.post("/api/iam/tenants", headers=h(tok), json={"name": "New"}).status_code == 403
    me = client.get("/api/auth/me", headers=h(tok)).json()
    assert me["user"]["server_admin"] is False and [t["id"] for t in me["tenants"]] == [oidc["tenant_id"]]
    assert client.get("/api/admin/users", headers=h(tok)).status_code == 403


def test_existing_account_links_only_into_this_workspace(client, idp, oidc):
    outsider = _signup(client, "carol@acme.com", "Carol")
    s = sso_session(client, idp, oidc["id"], sub="u-carol", email="carol@acme.com")
    assert s["user"]["id"] == outsider["user"]["id"]
    assert [t["id"] for t in s["tenants"]] == [oidc["tenant_id"]]       # not Carol's own workspace


def test_auto_provision_off_and_unmapped_refusal(client, idp, O, oidc):
    client.put(f"/api/iam/sso/{oidc['id']}", headers=O, json={"auto_provision": False})
    _, q, _ = oidc_login(client, idp, oidc["id"], sub="u-new", email="newbie@acme.com")
    assert "no Pipesets account" in q["sso_error"]
    client.put(f"/api/iam/sso/{oidc['id']}", headers=O, json={"auto_provision": True, "default_role": ""})
    _, q, _ = oidc_login(client, idp, oidc["id"], sub="u-new", email="newbie@acme.com", groups=["nothing"])
    assert "isn't assigned" in q["sso_error"]
    client.put(f"/api/iam/sso/{oidc['id']}", headers=O, json={"default_role": "viewer"})


def test_enforce_blocks_member_password_sessions_not_owners(client, idp, owner, T, O, oidc):
    member = _signup(client, "pat@acme.com", "Pat")
    client.post("/api/iam/users", headers=O, json={"email": "pat@acme.com", "display_name": "Pat", "role": "editor"})
    assert client.get("/api/iam/context", headers=h(member["token"], T)).status_code == 200
    client.put(f"/api/iam/sso/{oidc['id']}", headers=O, json={"enforce": True})
    r = client.get("/api/iam/context", headers=h(member["token"], T))
    assert r.status_code == 403 and "single sign-on" in r.json()["detail"]
    assert T not in [t["id"] for t in client.get("/api/auth/me", headers=h(member["token"])).json()["tenants"]]
    assert client.get("/api/iam/context", headers=O).status_code == 200      # the owner keeps password access
    client.put(f"/api/iam/sso/{oidc['id']}", headers=O, json={"enforce": False})


def test_delete_provider_ends_its_sessions(client, idp, O, oidc):
    s = sso_session(client, idp, oidc["id"], sub="u-bye", email="bye@acme.com")
    assert client.get("/api/auth/me", headers=h(s["token"])).status_code == 200
    # A session opened by this provider can't delete it
    sso_owner = sso_session(client, idp, oidc["id"], sub="u-boss", email="boss@acme.com", groups=["pipesets-admins"])
    assert client.delete(f"/api/iam/sso/{oidc['id']}", headers=h(sso_owner["token"])).status_code == 409
    assert client.delete(f"/api/iam/sso/{oidc['id']}", headers=O).status_code == 200
    assert client.get("/api/auth/me", headers=h(s["token"])).status_code == 401
    assert client.get(f"/api/auth/sso/{oidc['id']}/start", follow_redirects=False).status_code == 404


# ── SAML ──────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def saml_idp():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "idp.example.com")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=365)).sign(key, hashes.SHA256()))
    return {"key": key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()),
            "cert": cert.public_bytes(serialization.Encoding.PEM).decode()}


@pytest.fixture(scope="module")
def saml(client, O, saml_idp):
    r = client.post("/api/iam/sso", headers=O, json={
        "name": "Acme ADFS", "protocol": "saml",
        "config": {"idp_entity_id": "https://idp.example.com/saml", "idp_sso_url": "https://idp.example.com/sso",
                   "idp_certificate": saml_idp["cert"], "email_attribute": "email"},
        "email_domains": ["acme.com"], "role_claim": "Role",
        "role_mappings": [{"value": "Editors", "role": "editor"}], "default_role": "viewer"})
    assert r.status_code == 201, r.text
    return r.json()


def _saml_start(client, saml):
    loc = urlparse(start(client, saml["id"]).headers["location"])
    q = {k: v[0] for k, v in parse_qs(loc.query).items()}
    req = etree.fromstring(zlib.decompress(base64.b64decode(q["SAMLRequest"]), -15))
    return q["RelayState"], req.get("ID")


def _assertion(saml, request_id, email="sam@acme.com", role="Editors", audience=None, aid=None, sign_key=None):
    now = datetime.now(timezone.utc)
    t = lambda d: (now + d).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    aid = aid or "_a" + uuid.uuid4().hex
    return etree.fromstring(f"""<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="{aid}" Version="2.0" IssueInstant="{t(timedelta())}">
<saml:Issuer>https://idp.example.com/saml</saml:Issuer>
<saml:Subject><saml:NameID Format="urn:oasis:names:tc:SAML:2.0:nameid-format:persistent">{email.split('@')[0]}-id</saml:NameID>
<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer"><saml:SubjectConfirmationData InResponseTo="{request_id}" Recipient="{saml['acs_url']}" NotOnOrAfter="{t(timedelta(minutes=5))}"/></saml:SubjectConfirmation></saml:Subject>
<saml:Conditions NotBefore="{t(-timedelta(minutes=1))}" NotOnOrAfter="{t(timedelta(minutes=5))}"><saml:AudienceRestriction><saml:Audience>{audience or saml['sp_entity_id']}</saml:Audience></saml:AudienceRestriction></saml:Conditions>
<saml:AttributeStatement><saml:Attribute Name="email"><saml:AttributeValue>{email}</saml:AttributeValue></saml:Attribute><saml:Attribute Name="Role"><saml:AttributeValue>{role}</saml:AttributeValue></saml:Attribute></saml:AttributeStatement>
</saml:Assertion>""".encode())


def _sign(el, idp):
    signed = XMLSigner(method=methods.enveloped, signature_algorithm="rsa-sha256", digest_algorithm="sha256",
                       c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#").sign(
        el, key=idp["key"], cert=idp["cert"], reference_uri=el.get("ID"))
    return signed


def _response(saml, request_id, assertions):
    resp = etree.fromstring(f"""<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_r{uuid.uuid4().hex}" Version="2.0" InResponseTo="{request_id}" Destination="{saml['acs_url']}" IssueInstant="2026-01-01T00:00:00Z"><saml:Issuer>https://idp.example.com/saml</saml:Issuer><samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status></samlp:Response>""".encode())
    for a in assertions:
        resp.append(a)
    return base64.b64encode(etree.tostring(resp)).decode()


def _post_acs(client, saml, relay, body):
    r = client.post(f"/api/auth/sso/saml/{saml['id']}/acs", data={"SAMLResponse": body, "RelayState": relay},
                    follow_redirects=False)
    assert r.status_code == 303
    return {k: v[0] for k, v in parse_qs(urlparse(r.headers["location"]).query).items()}


def test_saml_metadata(client, saml):
    r = client.get(f"/api/auth/sso/saml/{saml['id']}/metadata")
    assert r.status_code == 200 and saml["acs_url"] in r.text and f'entityID="{saml["sp_entity_id"]}"' in r.text


def test_saml_sign_in_with_role_mapping(client, saml, saml_idp, T):
    relay, rid = _saml_start(client, saml)
    q = _post_acs(client, saml, relay, _response(saml, rid, [_sign(_assertion(saml, rid), saml_idp)]))
    assert "sso_code" in q, q
    s = client.post("/api/auth/sso/exchange", json={"code": q["sso_code"]}).json()
    assert s["user"]["email"] == "sam@acme.com" and s["tenants"] == [s["tenants"][0]]
    assert s["tenants"][0]["id"] == T and s["tenants"][0]["role"] == "editor"
    # Replaying the same response: the RelayState was consumed
    q = _post_acs(client, saml, relay, _response(saml, rid, [_sign(_assertion(saml, rid), saml_idp)]))
    assert "IdP-initiated" in q["sso_error"]


def test_saml_rejects_tampering_audience_and_unsigned(client, saml, saml_idp):
    relay, rid = _saml_start(client, saml)
    signed = _sign(_assertion(saml, rid), saml_idp)
    signed.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}AttributeValue").text = "boss@acme.com"
    assert "signature" in _post_acs(client, saml, relay, _response(saml, rid, [signed]))["sso_error"]

    relay, rid = _saml_start(client, saml)
    q = _post_acs(client, saml, relay, _response(saml, rid, [_sign(_assertion(saml, rid, audience="urn:other"), saml_idp)]))
    assert "Audience" in q["sso_error"]

    relay, rid = _saml_start(client, saml)
    assert "signature" in _post_acs(client, saml, relay, _response(saml, rid, [_assertion(saml, rid)]))["sso_error"]

    # Signed by a different key
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    relay, rid = _saml_start(client, saml)
    q = _post_acs(client, saml, relay, _response(saml, rid, [_sign(_assertion(saml, rid), {**saml_idp, "key": other})]))
    assert "signature" in q["sso_error"]

    # A response for another sign-in (InResponseTo mismatch)
    relay, rid = _saml_start(client, saml)
    q = _post_acs(client, saml, relay, _response(saml, rid, [_sign(_assertion(saml, "_someone_else"), saml_idp)]))
    assert "InResponseTo" in q["sso_error"] or "belong" in q["sso_error"]


def test_saml_wrapping_attack_uses_only_the_signed_assertion(client, saml, saml_idp):
    relay, rid = _saml_start(client, saml)
    good = _sign(_assertion(saml, rid, email="low@acme.com", role="Viewers"), saml_idp)
    evil = _assertion(saml, rid, email="admin@acme.com", role="Editors")
    q = _post_acs(client, saml, relay, _response(saml, rid, [evil, good]))     # injected assertion first
    s = client.post("/api/auth/sso/exchange", json={"code": q["sso_code"]}).json()
    assert s["user"]["email"] == "low@acme.com" and s["tenants"][0]["role"] == "viewer"

    # A signed Response may hold only one assertion
    relay, rid = _saml_start(client, saml)
    body = _response(saml, rid, [_assertion(saml, rid), _assertion(saml, rid, email="x@acme.com")])
    resp = etree.fromstring(base64.b64decode(body))
    q = _post_acs(client, saml, relay, base64.b64encode(etree.tostring(_sign(resp, saml_idp))).decode())
    assert "exactly one assertion" in q["sso_error"]
